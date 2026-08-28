"""Card-fingerprint similarity: exact-first, near matches secondary."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

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
    # Provenance for late-round twin trust (Similar page / alerts).
    draw_source: str = "unknown"
    frame_draws: tuple[str, ...] = ()

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
    """Multiset key (order ignored) — handicap rows only."""
    return ",".join(sorted(cards))


def _round_key(cards: tuple[str, ...]) -> str:
    """Positional key — draw rounds must match exact card sequence."""
    return ",".join(cards)


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
    *,
    draw_source: str = "unknown",
    frame_draws: tuple[str, ...] | list[str] = (),
) -> GameFingerprint | None:
    rows = _normalize_handicap(handicap_cards)
    if rows is None:
        return None
    r1 = _draw_slice(draw_cards, 1)
    r2 = _draw_slice(draw_cards, 2)
    hc_set = frozenset(c for row in rows for c in row)
    clean_frames = tuple(c for c in frame_draws if c and not str(c).startswith("?"))
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
        draw_source=draw_source,
        frame_draws=clean_frames,
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
) -> TwinLiveSignal | None:
    """Suggest a winner from exact historical twins when agreement is strong."""
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

        ids = tuple(h.other.game_id for h in exact_hits)
        message = (
            f"Twin match ({stage.value} exact): possible winner {top} "
            f"({top_n}/{len(winners)} = {agreement:.0%} agree, {len(exact_hits)} games)"
        )
        return TwinLiveSignal(
            stage=stage,
            exact=True,
            match_pct=100.0,
            suggested_winner=top,
            match_count=len(exact_hits),
            agreement_pct=round(agreement * 100.0, 1),
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


# --- Late-round (R3 / R4 / R5) cascade: independent of handicap twin logic ---

LATE_ROUND_MIN = 3
LATE_ROUND_MAX = 5

# Twin-set trust levels (Similar page / production gating).
TRUST_VERIFIED = "verified"  # IN_PLAY frames agree with chosen draws for matched rounds
TRUST_FALLBACK = "fallback"  # no frames to cross-check; json/guess only
TRUST_WEAK = "weak"  # table source, frame mismatch, or key disagreement — excluded


@dataclass(frozen=True)
class LateRoundHit:
    game_id: str
    winner_suit: str | None
    draw_cards: tuple[str, ...]
    handicap_cards: tuple[tuple[str, ...], ...]
    round_n: int
    round_cards: tuple[str, ...]


@dataclass(frozen=True)
class LateRoundSignal:
    """Live or query alert for an exact late-round draw match."""

    round_n: int
    live_game_id: str | None
    live_round_cards: tuple[str, ...]
    matches: tuple[LateRoundHit, ...]
    winner_counts: tuple[tuple[str, int], ...]
    agreement_pct: float | None
    majority_winner: str | None
    message: str
    similar_path: str

    @property
    def kind(self) -> str:
        return f"twin-r{self.round_n}"

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def matched_game_ids(self) -> tuple[str, ...]:
        return tuple(m.game_id for m in self.matches)


@dataclass(frozen=True)
class LateRoundStageStats:
    """Corpus winner agreement for a late-round cascade stage."""

    stage: str  # "R3", "R3→R4", "R3→R4→R5"
    round_n: int
    twin_sets: int
    games_in_sets: int
    same_winner_sets: int
    same_winner_pct: float | None
    mean_agreement_pct: float | None


def draw_round_cards(
    draw_cards: tuple[str, ...] | list[str],
    round_n: int,
) -> tuple[str, ...] | None:
    """1-based draw round slice (R3 = cards 7–9)."""
    if round_n < 1:
        return None
    start = (round_n - 1) * CARDS_PER_DRAW_ROUND
    end = start + CARDS_PER_DRAW_ROUND
    clean = tuple(c for c in draw_cards if c and not str(c).startswith("?"))
    if len(clean) < end:
        return None
    return clean[start:end]


def draw_round_key(
    draw_cards: tuple[str, ...] | list[str],
    round_n: int,
) -> str | None:
    cards = draw_round_cards(draw_cards, round_n)
    return _round_key(cards) if cards else None


def full_draw_rounds(draw_cards: tuple[str, ...] | list[str]) -> int:
    clean = tuple(c for c in draw_cards if c and not str(c).startswith("?"))
    return len(clean) // CARDS_PER_DRAW_ROUND


def is_production_safe_late_round(fp: GameFingerprint, round_n: int) -> bool:
    """Whether corpus game ``fp`` is trusted for live/production matching at ``round_n``."""
    level, _ = _game_round_trust(fp, round_n)
    return level != TRUST_WEAK


def find_late_round_matches(
    live_draws: tuple[str, ...] | list[str],
    corpus: list[GameFingerprint],
    round_n: int,
    *,
    pool_ids: set[str] | frozenset[str] | tuple[str, ...] | list[str] | None = None,
    exclude_game_id: str | None = None,
    production_only: bool = False,
) -> list[LateRoundHit]:
    """Exact match of one draw round against corpus (optionally restricted to a pool)."""
    if round_n < LATE_ROUND_MIN or round_n > LATE_ROUND_MAX:
        return []
    live_key = draw_round_key(live_draws, round_n)
    live_cards = draw_round_cards(live_draws, round_n)
    if live_key is None or live_cards is None:
        return []
    allow = set(pool_ids) if pool_ids is not None else None
    hits: list[LateRoundHit] = []
    for fp in corpus:
        if exclude_game_id and fp.game_id == exclude_game_id:
            continue
        if allow is not None and fp.game_id not in allow:
            continue
        if production_only and not is_production_safe_late_round(fp, round_n):
            continue
        other_key = draw_round_key(fp.draw_cards, round_n)
        if other_key is None or other_key != live_key:
            continue
        other_cards = draw_round_cards(fp.draw_cards, round_n)
        if other_cards is None:
            continue
        hits.append(
            LateRoundHit(
                game_id=fp.game_id,
                winner_suit=fp.winner_suit,
                draw_cards=fp.draw_cards,
                handicap_cards=fp.handicap_cards,
                round_n=round_n,
                round_cards=other_cards,
            )
        )
    hits.sort(key=lambda h: h.game_id)
    return hits


def _late_winner_summary(
    hits: list[LateRoundHit],
) -> tuple[tuple[tuple[str, int], ...], float | None, str | None]:
    counts: Counter[str] = Counter()
    for hit in hits:
        if hit.winner_suit:
            counts[hit.winner_suit.title()] += 1
    if not counts:
        return (), None, None
    ranked = tuple(counts.most_common())
    total = sum(counts.values())
    agreement = round(100.0 * ranked[0][1] / total, 1) if total else None
    return ranked, agreement, ranked[0][0]


def build_late_round_signal(
    live_draws: tuple[str, ...] | list[str],
    hits: list[LateRoundHit],
    round_n: int,
    *,
    live_game_id: str | None = None,
) -> LateRoundSignal | None:
    if not hits:
        return None
    live_cards = draw_round_cards(live_draws, round_n)
    if live_cards is None:
        return None
    winners, agreement, majority = _late_winner_summary(hits)
    winner_bits = " · ".join(f"{name}×{n}" for name, n in winners) if winners else "no winners"
    ids = ",".join(h.game_id for h in hits)
    live_q = f"&live={live_game_id}" if live_game_id else ""
    path = f"/similar?stage=r{round_n}&ids={ids}{live_q}"
    agree_note = f", {agreement:.0f}% agree on {majority}" if agreement is not None and majority else ""
    message = (
        f"[TWIN-R{round_n}] Game {live_game_id or '-'} — "
        f"{len(hits)} past game(s) match R{round_n} draws [{', '.join(live_cards)}] "
        f"· winners: {winner_bits}{agree_note} · link={path}"
    )
    return LateRoundSignal(
        round_n=round_n,
        live_game_id=live_game_id,
        live_round_cards=live_cards,
        matches=tuple(hits),
        winner_counts=winners,
        agreement_pct=agreement,
        majority_winner=majority,
        message=message,
        similar_path=path,
    )


def evaluate_late_round_cascade(
    live_draws: tuple[str, ...] | list[str],
    corpus: list[GameFingerprint],
    *,
    live_game_id: str | None = None,
    max_round: int = LATE_ROUND_MAX,
    production_only: bool = False,
) -> dict[int, LateRoundSignal]:
    """Run R3→R4→R5 cascade; return a signal for each stage that still has matches."""
    rounds_seen = full_draw_rounds(live_draws)
    end = min(max_round, LATE_ROUND_MAX, rounds_seen)
    out: dict[int, LateRoundSignal] = {}
    pool: set[str] | None = None
    for round_n in range(LATE_ROUND_MIN, end + 1):
        hits = find_late_round_matches(
            live_draws,
            corpus,
            round_n,
            pool_ids=pool,
            exclude_game_id=live_game_id,
            production_only=production_only,
        )
        signal = build_late_round_signal(
            live_draws, hits, round_n, live_game_id=live_game_id
        )
        if signal is None:
            break
        out[round_n] = signal
        pool = set(signal.matched_game_ids)
        if not pool:
            break
    return out


def late_round_corpus_stats(
    corpus: list[GameFingerprint],
    *,
    max_round: int = LATE_ROUND_MAX,
) -> list[LateRoundStageStats]:
    """Winner-agreement stats for R3, R3→R4, and R3→R4→R5 exact twin sets."""
    end = min(max_round, LATE_ROUND_MAX)
    stages: list[LateRoundStageStats] = []

    def _bucket_key(fp: GameFingerprint, through_round: int) -> str | None:
        parts: list[str] = []
        for rn in range(LATE_ROUND_MIN, through_round + 1):
            key = draw_round_key(fp.draw_cards, rn)
            if key is None:
                return None
            parts.append(key)
        return "||".join(parts)

    for through in range(LATE_ROUND_MIN, end + 1):
        buckets: dict[str, list[GameFingerprint]] = {}
        for fp in corpus:
            if not fp.winner_suit:
                continue
            key = _bucket_key(fp, through)
            if key is None:
                continue
            buckets.setdefault(key, []).append(fp)

        twin_sets = 0
        games_in = 0
        same_sets = 0
        agreements: list[float] = []
        for games in buckets.values():
            if len(games) < 2:
                continue
            twin_sets += 1
            games_in += len(games)
            _winners, agreement, same = _winner_stats(games)
            if same:
                same_sets += 1
            if agreement is not None:
                agreements.append(agreement)

        label = "→".join(f"R{n}" for n in range(LATE_ROUND_MIN, through + 1))
        stages.append(
            LateRoundStageStats(
                stage=label,
                round_n=through,
                twin_sets=twin_sets,
                games_in_sets=games_in,
                same_winner_sets=same_sets,
                same_winner_pct=(
                    round(100.0 * same_sets / twin_sets, 1) if twin_sets else None
                ),
                mean_agreement_pct=(
                    round(sum(agreements) / len(agreements), 1) if agreements else None
                ),
            )
        )
    return stages


@dataclass(frozen=True)
class LateRoundTwinSet:
    """Browseable twin set: games sharing exact R3 (and optionally R4/R5)."""

    stage: str
    round_n: int
    matched_rounds: tuple[int, ...]
    key: str
    games: tuple[GameFingerprint, ...]
    winner_counts: tuple[tuple[str, int], ...]
    agreement_pct: float | None
    winners_same: bool | None
    # Shared cards for each matched round (same across the set).
    round_cards: tuple[tuple[int, tuple[str, ...]], ...]
    trust: str = TRUST_VERIFIED
    trust_notes: tuple[str, ...] = ()

    @property
    def size(self) -> int:
        return len(self.games)

    @property
    def majority_winner(self) -> str | None:
        if not self.winner_counts:
            return None
        return self.winner_counts[0][0]

    @property
    def is_production_safe(self) -> bool:
        return self.trust in {TRUST_VERIFIED, TRUST_FALLBACK}


def _game_round_trust(fp: GameFingerprint, round_n: int) -> tuple[str, tuple[str, ...]]:
    """Trust for one game at one late draw round."""
    if fp.draw_source == "table":
        return TRUST_WEAK, (f"#{fp.game_id}: suit-table draws (not round-ordered)",)
    chosen = draw_round_key(fp.draw_cards, round_n)
    if fp.frame_draws:
        frame = draw_round_key(fp.frame_draws, round_n)
        if frame is None:
            note = f"#{fp.game_id}: IN_PLAY frames missing R{round_n}"
            if fp.draw_source == "frames":
                return TRUST_FALLBACK, (note,)
            return TRUST_FALLBACK, (note,)
        if chosen != frame:
            return (
                TRUST_WEAK,
                (f"#{fp.game_id}: R{round_n} stored draws ≠ IN_PLAY frames",),
            )
        return TRUST_VERIFIED, ()
    if fp.draw_source in {"json", "guess"}:
        return TRUST_FALLBACK, (f"#{fp.game_id}: draw source {fp.draw_source} (no frames)",)
    return TRUST_WEAK, (f"#{fp.game_id}: no verified round-ordered draws",)


def assess_late_round_twin_set(twin_set: LateRoundTwinSet) -> tuple[str, tuple[str, ...]]:
    """Return (trust_level, notes). Weak sets must not ship to production UI."""
    notes: list[str] = []
    levels: list[str] = []
    for rn in twin_set.matched_rounds:
        keys = {draw_round_key(g.draw_cards, rn) for g in twin_set.games}
        keys.discard(None)
        if len(keys) > 1:
            return TRUST_WEAK, ("games disagree on matched round keys",)
        for g in twin_set.games:
            level, game_notes = _game_round_trust(g, rn)
            levels.append(level)
            notes.extend(game_notes)
    if TRUST_WEAK in levels:
        return TRUST_WEAK, tuple(dict.fromkeys(notes))
    if all(level == TRUST_VERIFIED for level in levels):
        return TRUST_VERIFIED, ()
    return TRUST_FALLBACK, tuple(dict.fromkeys(notes))


def partition_late_round_twin_sets(
    sets: list[LateRoundTwinSet],
) -> tuple[list[LateRoundTwinSet], list[LateRoundTwinSet]]:
    """Split trusted (verified/fallback) vs weak (production-excluded)."""
    trusted: list[LateRoundTwinSet] = []
    weak: list[LateRoundTwinSet] = []
    for twin_set in sets:
        if twin_set.is_production_safe:
            trusted.append(twin_set)
        else:
            weak.append(twin_set)
    return trusted, weak


def build_late_round_twin_sets(
    corpus: list[GameFingerprint],
    *,
    max_round: int = LATE_ROUND_MAX,
    min_round: int = LATE_ROUND_MIN,
) -> list[LateRoundTwinSet]:
    """Exact late-round twin sets for the Similar page (R3 / R3→R4 / R3→R4→R5)."""
    start = max(LATE_ROUND_MIN, min_round)
    end = min(max_round, LATE_ROUND_MAX)
    sets: list[LateRoundTwinSet] = []

    def _bucket_key(fp: GameFingerprint, through_round: int) -> str | None:
        parts: list[str] = []
        for rn in range(LATE_ROUND_MIN, through_round + 1):
            key = draw_round_key(fp.draw_cards, rn)
            if key is None:
                return None
            parts.append(f"R{rn}:{key}")
        return "||".join(parts)

    for through in range(start, end + 1):
        buckets: dict[str, list[GameFingerprint]] = {}
        for fp in corpus:
            if not fp.winner_suit:
                continue
            key = _bucket_key(fp, through)
            if key is None:
                continue
            buckets.setdefault(key, []).append(fp)

        matched_rounds = tuple(range(LATE_ROUND_MIN, through + 1))
        stage = "→".join(f"R{n}" for n in matched_rounds)
        for key, games in buckets.items():
            if len(games) < 2:
                continue
            sample = games[0]
            round_cards: list[tuple[int, tuple[str, ...]]] = []
            for rn in matched_rounds:
                cards = draw_round_cards(sample.draw_cards, rn)
                if cards is None:
                    round_cards = []
                    break
                round_cards.append((rn, cards))
            if len(round_cards) != len(matched_rounds):
                continue
            winners, agreement, same = _winner_stats(games)
            candidate = LateRoundTwinSet(
                stage=stage,
                round_n=through,
                matched_rounds=matched_rounds,
                key=key,
                games=tuple(sorted(games, key=lambda g: g.game_id)),
                winner_counts=winners,
                agreement_pct=agreement,
                winners_same=same,
                round_cards=tuple(round_cards),
            )
            trust, trust_notes = assess_late_round_twin_set(candidate)
            sets.append(
                LateRoundTwinSet(
                    stage=candidate.stage,
                    round_n=candidate.round_n,
                    matched_rounds=candidate.matched_rounds,
                    key=candidate.key,
                    games=candidate.games,
                    winner_counts=candidate.winner_counts,
                    agreement_pct=candidate.agreement_pct,
                    winners_same=candidate.winners_same,
                    round_cards=candidate.round_cards,
                    trust=trust,
                    trust_notes=trust_notes,
                )
            )

    # Deepest first, then larger sets, then stable key.
    sets.sort(key=lambda s: (-s.round_n, -s.size, s.key))
    return sets
