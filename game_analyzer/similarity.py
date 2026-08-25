"""Card-fingerprint similarity: exact-first, near matches secondary."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from game_analyzer.confidence import ConfidenceLevel, ConfidenceResult, level_at_least
from game_analyzer.race_values import CARDS_PER_DRAW_ROUND, suits_match

# Near = stronger overlap for browsing (not a bet signal).
# With 12 handicap cards, 9 shared → Jaccard 9/15 = 0.60.
# Exact (12/12) stays primary for live twin notify.
NEAR_JACCARD_MIN = 0.60
NEAR_SHARED_MIN = 9  # implied by Jaccard on 12-card handicaps; used in UI copy
LIVE_MIN_MATCHES = 2
LIVE_AGREE_MIN = 0.80
CLOSEST_PAIR_LIMIT = 40


class MatchStage(str, Enum):
    HANDICAP = "handicap"
    HANDICAP_R1 = "handicap+R1"
    HANDICAP_R2 = "handicap+R2"


@dataclass(frozen=True)
class GameFingerprint:
    game_id: str
    winner_suit: str | None
    handicap_cards: tuple[tuple[str, ...], ...]
    draw_cards: tuple[str, ...]
    handicap_key: str
    draw_r1_key: str | None
    draw_r2_key: str | None
    handicap_set: frozenset[str]
    draw_r1_set: frozenset[str]
    draw_r2_set: frozenset[str]

    @property
    def has_r1(self) -> bool:
        return self.draw_r1_key is not None

    @property
    def has_r2(self) -> bool:
        return self.draw_r2_key is not None


@dataclass(frozen=True)
class SimilarityHit:
    other: GameFingerprint
    stage: MatchStage
    exact: bool
    match_pct: float
    same_winner: bool | None

    @property
    def label(self) -> str:
        kind = "exact" if self.exact else "near"
        return f"{self.stage.value} {kind} {self.match_pct:.0f}%"


@dataclass(frozen=True)
class SimilarityCluster:
    stage: MatchStage
    exact: bool
    match_pct: float
    key: str
    games: tuple[GameFingerprint, ...]
    winners_same: bool | None
    winner_counts: tuple[tuple[str, int], ...]
    agreement_pct: float | None

    @property
    def size(self) -> int:
        return len(self.games)

    @property
    def majority_winner(self) -> str | None:
        if not self.winner_counts:
            return None
        return self.winner_counts[0][0]


@dataclass(frozen=True)
class TwinLiveSignal:
    """Live twin match suggestion (notification payload)."""

    stage: MatchStage
    exact: bool
    match_pct: float
    suggested_winner: str
    match_count: int
    agreement_pct: float
    confidence_level: str | None
    confidence_pick: str | None
    confidence_agrees: bool | None
    message: str
    matched_game_ids: tuple[str, ...]


def _normalize_handicap(handicap: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...] | None:
    if len(handicap) != 4:
        return None
    rows: list[tuple[str, ...]] = []
    for row in handicap:
        cards = tuple(
            sorted(
                c
                for c in row
                if c and not str(c).startswith("?")
            )
        )
        if len(cards) != 3:
            return None
        rows.append(cards)
    return tuple(rows)


def _draw_slice(draws: tuple[str, ...], rounds: int) -> tuple[str, ...] | None:
    need = rounds * CARDS_PER_DRAW_ROUND
    clean = tuple(c for c in draws if c and not str(c).startswith("?"))
    if len(clean) < need:
        return None
    return clean[:need]


def _card_key(cards: tuple[str, ...]) -> str:
    return ",".join(sorted(cards))


def _handicap_key(rows: tuple[tuple[str, ...], ...]) -> str:
    # Keep suit order Spades,Hearts,Clubs,Diamonds as stored.
    return "|".join(_card_key(row) for row in rows)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def build_fingerprint(
    game_id: str,
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
    winner_suit: str | None = None,
) -> GameFingerprint | None:
    rows = _normalize_handicap(handicap_cards)
    if rows is None:
        return None
    r1 = _draw_slice(draw_cards, 1)
    r2 = _draw_slice(draw_cards, 2)
    hc_set = frozenset(c for row in rows for c in row)
    return GameFingerprint(
        game_id=game_id,
        winner_suit=winner_suit.title() if winner_suit else None,
        handicap_cards=rows,
        draw_cards=tuple(c for c in draw_cards if c and not str(c).startswith("?")),
        handicap_key=_handicap_key(rows),
        draw_r1_key=_card_key(r1) if r1 else None,
        draw_r2_key=_card_key(r2) if r2 else None,
        handicap_set=hc_set,
        draw_r1_set=frozenset(r1) if r1 else frozenset(),
        draw_r2_set=frozenset(r2) if r2 else frozenset(),
    )


def _stage_score(
    a: GameFingerprint,
    b: GameFingerprint,
    stage: MatchStage,
) -> tuple[bool, float] | None:
    """Return (exact, pct) for stage, or None if stage not comparable."""
    if stage is MatchStage.HANDICAP:
        if a.handicap_key == b.handicap_key:
            return True, 100.0
        jac = jaccard(a.handicap_set, b.handicap_set)
        if jac >= NEAR_JACCARD_MIN:
            return False, round(jac * 100.0, 1)
        return None

    if stage is MatchStage.HANDICAP_R1:
        if not a.has_r1 or not b.has_r1:
            return None
        exact_h = a.handicap_key == b.handicap_key
        exact_d = a.draw_r1_key == b.draw_r1_key
        if exact_h and exact_d:
            return True, 100.0
        jac_h = jaccard(a.handicap_set, b.handicap_set)
        jac_d = jaccard(a.draw_r1_set, b.draw_r1_set)
        # Weighted: handicap heavier.
        combined = 0.65 * jac_h + 0.35 * jac_d
        if exact_h and jac_d >= NEAR_JACCARD_MIN:
            return False, round(max(combined, 0.90) * 100.0, 1)
        if combined >= NEAR_JACCARD_MIN:
            return False, round(combined * 100.0, 1)
        return None

    if stage is MatchStage.HANDICAP_R2:
        if not a.has_r2 or not b.has_r2:
            return None
        exact_h = a.handicap_key == b.handicap_key
        exact_d = a.draw_r2_key == b.draw_r2_key
        if exact_h and exact_d:
            return True, 100.0
        jac_h = jaccard(a.handicap_set, b.handicap_set)
        jac_d = jaccard(a.draw_r2_set, b.draw_r2_set)
        combined = 0.55 * jac_h + 0.45 * jac_d
        if exact_h and jac_d >= NEAR_JACCARD_MIN:
            return False, round(max(combined, 0.90) * 100.0, 1)
        if combined >= NEAR_JACCARD_MIN:
            return False, round(combined * 100.0, 1)
        return None
    return None


def compare_fingerprints(
    query: GameFingerprint,
    other: GameFingerprint,
    *,
    prefer_deepest: bool = True,
) -> SimilarityHit | None:
    if query.game_id == other.game_id:
        return None
    stages = (
        (MatchStage.HANDICAP_R2, MatchStage.HANDICAP_R1, MatchStage.HANDICAP)
        if prefer_deepest
        else (MatchStage.HANDICAP, MatchStage.HANDICAP_R1, MatchStage.HANDICAP_R2)
    )
    best: SimilarityHit | None = None
    for stage in stages:
        scored = _stage_score(query, other, stage)
        if scored is None:
            continue
        exact, pct = scored
        same: bool | None = None
        if query.winner_suit and other.winner_suit:
            same = suits_match(query.winner_suit, other.winner_suit)
        hit = SimilarityHit(
            other=other,
            stage=stage,
            exact=exact,
            match_pct=pct,
            same_winner=same,
        )
        if best is None:
            best = hit
            continue
        # Prefer exact over near; then higher pct; then deeper stage.
        stage_rank = {
            MatchStage.HANDICAP_R2: 3,
            MatchStage.HANDICAP_R1: 2,
            MatchStage.HANDICAP: 1,
        }
        better = (
            (exact and not best.exact)
            or (exact == best.exact and pct > best.match_pct)
            or (
                exact == best.exact
                and pct == best.match_pct
                and stage_rank[stage] > stage_rank[best.stage]
            )
        )
        if better:
            best = hit
    return best


def find_matches(
    query: GameFingerprint,
    corpus: list[GameFingerprint],
    *,
    exact_only: bool = False,
) -> list[SimilarityHit]:
    hits: list[SimilarityHit] = []
    for other in corpus:
        hit = compare_fingerprints(query, other)
        if hit is None:
            continue
        if exact_only and not hit.exact:
            continue
        hits.append(hit)
    hits.sort(key=lambda h: (not h.exact, -h.match_pct, h.stage.value, h.other.game_id))
    return hits


def _winner_stats(games: list[GameFingerprint]) -> tuple[tuple[tuple[str, int], ...], float | None, bool | None]:
    counts: Counter[str] = Counter()
    for g in games:
        if g.winner_suit:
            counts[g.winner_suit.title()] += 1
    if not counts:
        return (), None, None
    ranked = tuple(counts.most_common())
    total = sum(counts.values())
    agreement = round(100.0 * ranked[0][1] / total, 1) if total else None
    same = len(counts) == 1
    return ranked, agreement, same


def build_clusters(
    corpus: list[GameFingerprint],
    *,
    exact_only: bool = False,
) -> list[SimilarityCluster]:
    """Group finished games by strongest shared fingerprint key per stage."""
    clusters: list[SimilarityCluster] = []

    def add_groups(
        stage: MatchStage,
        key_fn,
        *,
        exact: bool,
        pct: float,
    ) -> None:
        buckets: dict[str, list[GameFingerprint]] = {}
        for fp in corpus:
            key = key_fn(fp)
            if not key:
                continue
            buckets.setdefault(key, []).append(fp)
        for key, games in buckets.items():
            if len(games) < 2:
                continue
            winners, agreement, same = _winner_stats(games)
            clusters.append(
                SimilarityCluster(
                    stage=stage,
                    exact=exact,
                    match_pct=pct,
                    key=key,
                    games=tuple(games),
                    winners_same=same,
                    winner_counts=winners,
                    agreement_pct=agreement,
                )
            )

    # Exact clusters first (focused).
    add_groups(MatchStage.HANDICAP, lambda f: f.handicap_key, exact=True, pct=100.0)
    add_groups(
        MatchStage.HANDICAP_R1,
        lambda f: f"{f.handicap_key}||{f.draw_r1_key}" if f.draw_r1_key else None,
        exact=True,
        pct=100.0,
    )
    add_groups(
        MatchStage.HANDICAP_R2,
        lambda f: f"{f.handicap_key}||{f.draw_r2_key}" if f.draw_r2_key else None,
        exact=True,
        pct=100.0,
    )

    if not exact_only:
        # Near clusters: handicap pairs at/above near threshold (not already exact).
        used_pairs: set[tuple[str, str]] = set()
        near_pairs: list[tuple[float, GameFingerprint, GameFingerprint]] = []
        for i, a in enumerate(corpus):
            for b in corpus[i + 1 :]:
                scored = _stage_score(a, b, MatchStage.HANDICAP)
                if scored is None:
                    continue
                exact, pct = scored
                if exact:
                    continue
                pair = tuple(sorted((a.game_id, b.game_id)))
                if pair in used_pairs:
                    continue
                used_pairs.add(pair)
                near_pairs.append((pct, a, b))
        near_pairs.sort(key=lambda row: (-row[0], row[1].game_id, row[2].game_id))
        for pct, a, b in near_pairs[:CLOSEST_PAIR_LIMIT]:
            games = (a, b)
            winners, agreement, same = _winner_stats(list(games))
            shared = len(a.handicap_set & b.handicap_set)
            clusters.append(
                SimilarityCluster(
                    stage=MatchStage.HANDICAP,
                    exact=False,
                    match_pct=pct,
                    key=f"near:{a.game_id}:{b.game_id}:shared={shared}",
                    games=games,
                    winners_same=same,
                    winner_counts=winners,
                    agreement_pct=agreement,
                )
            )

    stage_order = {
        MatchStage.HANDICAP_R2: 0,
        MatchStage.HANDICAP_R1: 1,
        MatchStage.HANDICAP: 2,
    }
    clusters.sort(
        key=lambda c: (
            not c.exact,
            # Among near sets: same-winner first (still browse-only, clearer signal).
            0 if c.exact else (0 if c.winners_same else 1),
            stage_order.get(c.stage, 9),
            -c.match_pct,
            -c.size,
            c.key,
        )
    )
    return clusters


def evaluate_live_twin(
    query: GameFingerprint,
    corpus: list[GameFingerprint],
    *,
    confidence: ConfidenceResult | None = None,
) -> TwinLiveSignal | None:
    """Suggest a winner from exact historical twins when agreement + confidence align."""
    # Prefer deepest exact stage available.
    for stage in (MatchStage.HANDICAP_R2, MatchStage.HANDICAP_R1, MatchStage.HANDICAP):
        exact_hits = [
            h
            for h in find_matches(query, corpus, exact_only=True)
            if h.stage is stage and h.exact
        ]
        if len(exact_hits) < LIVE_MIN_MATCHES:
            continue
        winners = [h.other.winner_suit for h in exact_hits if h.other.winner_suit]
        if len(winners) < LIVE_MIN_MATCHES:
            continue
        counts = Counter(w.title() for w in winners)
        top, top_n = counts.most_common(1)[0]
        agreement = top_n / len(winners)
        if agreement < LIVE_AGREE_MIN:
            continue

        conf_level = confidence.level.value if confidence and confidence.ready else None
        conf_pick = confidence.pick.title() if confidence and confidence.pick else None
        conf_agrees: bool | None = None
        if conf_pick:
            conf_agrees = suits_match(conf_pick, top)

        # Gate with confidence system when a lock exists.
        if confidence is not None and confidence.ready and conf_pick:
            if level_at_least(confidence.level, ConfidenceLevel.HIGH):
                if not conf_agrees:
                    # Strong confidence conflicts with twins — do not notify a winner.
                    continue
            elif confidence.level is ConfidenceLevel.MEDIUM:
                if not conf_agrees:
                    continue
            else:
                # LOW / weak confidence: only allow unanimous exact twins.
                if agreement < 0.999:
                    continue

        ids = tuple(h.other.game_id for h in exact_hits)
        conf_note = ""
        if conf_level and conf_pick:
            if conf_agrees:
                conf_note = f" · confidence {conf_level} also picks {conf_pick}"
            else:
                conf_note = f" · confidence {conf_level} picks {conf_pick}"
        message = (
            f"Twin match ({stage.value} exact): possible winner {top} "
            f"({top_n}/{len(winners)} = {agreement:.0%} agree, {len(exact_hits)} games)"
            f"{conf_note}"
        )
        return TwinLiveSignal(
            stage=stage,
            exact=True,
            match_pct=100.0,
            suggested_winner=top,
            match_count=len(exact_hits),
            agreement_pct=round(agreement * 100.0, 1),
            confidence_level=conf_level,
            confidence_pick=conf_pick,
            confidence_agrees=conf_agrees,
            message=message,
            matched_game_ids=ids,
        )
    return None


def cluster_kind_badge(cluster: SimilarityCluster) -> str:
    """Short client-facing badge: exact vs near (same / mixed winners)."""
    if cluster.exact:
        return "EXACT"
    if cluster.winners_same:
        return "NEAR · same winners"
    if cluster.winners_same is False:
        return "NEAR · mixed winners · browse only"
    return "NEAR · browse only"


def cluster_badge_kind(cluster: SimilarityCluster) -> str:
    """CSS/UI class key for a cluster badge."""
    if cluster.exact:
        return "exact"
    if cluster.winners_same:
        return "near-same"
    if cluster.winners_same is False:
        return "near-mixed"
    return "near"


def format_cluster_headline(cluster: SimilarityCluster) -> str:
    badge = cluster_kind_badge(cluster)
    winner_note = "winners mixed"
    if cluster.winners_same and cluster.majority_winner:
        winner_note = f"all won {cluster.majority_winner}"
    elif cluster.majority_winner and cluster.agreement_pct is not None:
        winner_note = (
            f"majority {cluster.majority_winner} ({cluster.agreement_pct:.0f}%)"
        )
    shared_note = ""
    if not cluster.exact and cluster.key.startswith("near:") and "shared=" in cluster.key:
        shared_note = f" · {cluster.key.rsplit('shared=', 1)[-1]}/12 cards shared"
    return (
        f"{badge} · {cluster.stage.value} · {cluster.match_pct:.0f}% · "
        f"{cluster.size} games · {winner_note}{shared_note}"
    )
