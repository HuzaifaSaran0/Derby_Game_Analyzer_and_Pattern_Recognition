"""Read-only confidence tiers for a locked (or candidate) guess — does not change picks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from game_analyzer.deck_combos import combo_metrics, remaining_values
from game_analyzer.monte_carlo import monte_carlo_win_probs
from game_analyzer.race_values import (
    SUIT_NAMES,
    TRACK_LENGTH,
    guess_ready,
    race_guess,
    suits_match,
    track_position,
)


class ConfidenceLevel(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


@dataclass(frozen=True)
class ConfidenceThresholds:
    gap_low: int = 5
    gap_high: int = 10
    gap_very_high: int = 15
    gap_mc_combo: int = 8
    mc_high: float = 0.60
    mc_very_high: float = 0.75
    mc_low: float = 0.45
    mc_margin_high: float = 0.15
    mc_margin_low: float = 0.10
    rivals_weak_count: int = 2
    rivals_to_go_gap: int = 8


DEFAULT_THRESHOLDS = ConfidenceThresholds()


@dataclass(frozen=True)
class ConfidenceResult:
    level: ConfidenceLevel
    pick: str | None
    track_leader: str | None
    track_gap: int | None
    pick_on_track_leader: bool
    mc_probs: dict[str, float] | None
    mc_pick: float | None
    mc_margin: float | None
    rivals_weak_count: int
    draw_rounds: int
    reasons: tuple[str, ...]
    should_alert: bool = False

    @property
    def ready(self) -> bool:
        return self.level is not ConfidenceLevel.NONE


def _handicap_readable(handicap_cards: tuple[tuple[str, ...], ...]) -> bool:
    if len(handicap_cards) != 4:
        return False
    return all(len(row) == 3 for row in handicap_cards)


def _track_gap(track_moved: dict[str, int | None]) -> tuple[str | None, int | None]:
    ranked = [(suit, pos) for suit, pos in track_moved.items() if pos is not None]
    if len(ranked) < 2:
        return None, None
    ranked.sort(key=lambda item: item[1], reverse=True)
    leader, top = ranked[0]
    second = ranked[1][1]
    return leader, top - second


def _rivals_weak_count(
    pick: str,
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
    track_moved: dict[str, int | None],
) -> int:
    values = remaining_values(handicap_cards, draw_cards)
    pick_moved = track_moved.get(pick)
    if pick_moved is None:
        return 0
    pick_metrics = combo_metrics(values.get(pick), pick_moved)
    pick_to_go = pick_metrics.to_go if pick_metrics else TRACK_LENGTH
    weak = 0
    for suit in SUIT_NAMES:
        if suits_match(suit, pick):
            continue
        moved = track_moved.get(suit)
        metrics = combo_metrics(values.get(suit), moved)
        if metrics is None or moved is None:
            continue
        if metrics.can_finish_in_2:
            continue
        if metrics.to_go >= pick_to_go + DEFAULT_THRESHOLDS.rivals_to_go_gap:
            weak += 1
    return weak


def _classify_level(
    *,
    pick: str | None,
    track_leader: str | None,
    track_gap: int | None,
    mc_pick: float | None,
    mc_margin: float | None,
    rivals_weak: int,
    thresholds: ConfidenceThresholds,
) -> tuple[ConfidenceLevel, tuple[str, ...]]:
    if pick is None or track_gap is None:
        return ConfidenceLevel.LOW, ("no pick or unreadable track",)

    reasons: list[str] = []
    pick_on_leader = track_leader is not None and suits_match(pick, track_leader)

    if track_gap < thresholds.gap_low:
        reasons.append(f"tight race (gap {track_gap})")
    if mc_pick is not None and mc_pick < thresholds.mc_low:
        reasons.append(f"low MC ({mc_pick:.0%})")
    if mc_margin is not None and mc_margin < thresholds.mc_margin_low:
        reasons.append(f"small MC margin ({mc_margin:.0%})")

    if (
        track_gap >= thresholds.gap_very_high
        or (mc_pick is not None and mc_pick >= thresholds.mc_very_high and track_gap >= thresholds.gap_mc_combo)
    ):
        if track_gap >= thresholds.gap_very_high:
            reasons.append(f"large track gap ({track_gap})")
        if mc_pick is not None and mc_pick >= thresholds.mc_very_high:
            reasons.append(f"strong MC ({mc_pick:.0%})")
        return ConfidenceLevel.VERY_HIGH, tuple(reasons)

    if (
        (pick_on_leader and track_gap >= thresholds.gap_high)
        or (
            mc_pick is not None
            and mc_pick >= thresholds.mc_high
            and track_gap is not None
            and track_gap >= thresholds.gap_low
            and mc_margin is not None
            and mc_margin >= thresholds.mc_margin_high
        )
        or (
            pick_on_leader
            and track_gap >= thresholds.gap_low
            and rivals_weak >= thresholds.rivals_weak_count
        )
    ):
        if pick_on_leader and track_gap >= thresholds.gap_high:
            reasons.append(f"track lead +{track_gap}")
        if mc_pick is not None and mc_pick >= thresholds.mc_high:
            reasons.append(f"MC {mc_pick:.0%}")
        if rivals_weak >= thresholds.rivals_weak_count:
            reasons.append(f"{rivals_weak} weak rivals")
        return ConfidenceLevel.HIGH, tuple(reasons)

    if track_gap < thresholds.gap_low or (
        mc_pick is not None and mc_pick < thresholds.mc_low
    ) or (mc_margin is not None and mc_margin < thresholds.mc_margin_low):
        return ConfidenceLevel.LOW, tuple(reasons) if reasons else ("mixed signals",)

    return ConfidenceLevel.MEDIUM, ("guess ready but not a strong edge",)


def evaluate_confidence(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
    *,
    pick: str | None = None,
    simulations: int = 2000,
    seed: int | None = None,
    thresholds: ConfidenceThresholds | None = None,
) -> ConfidenceResult:
    """Score how actionable the current pick is. Never changes ``race_guess`` output."""
    thresholds = thresholds or DEFAULT_THRESHOLDS
    rounds = len(draw_cards) // 3

    if not guess_ready(draw_cards):
        return ConfidenceResult(
            level=ConfidenceLevel.NONE,
            pick=pick,
            track_leader=None,
            track_gap=None,
            pick_on_track_leader=False,
            mc_probs=None,
            mc_pick=None,
            mc_margin=None,
            rivals_weak_count=0,
            draw_rounds=rounds,
            reasons=("need 2 draw rounds (6 cards)",),
        )

    if not _handicap_readable(handicap_cards):
        return ConfidenceResult(
            level=ConfidenceLevel.LOW,
            pick=pick,
            track_leader=None,
            track_gap=None,
            pick_on_track_leader=False,
            mc_probs=None,
            mc_pick=None,
            mc_margin=None,
            rivals_weak_count=0,
            draw_rounds=rounds,
            reasons=("handicap not fully readable",),
        )

    chosen = pick or race_guess(handicap_cards, draw_cards)
    track_moved = track_position(draw_cards)
    track_leader, track_gap = _track_gap(track_moved)
    mc_probs = monte_carlo_win_probs(
        handicap_cards,
        draw_cards,
        simulations=simulations,
        seed=seed,
    )
    mc_pick = mc_probs.get(chosen) if chosen and mc_probs else None
    mc_margin = None
    if mc_probs and chosen:
        others = sorted((prob for suit, prob in mc_probs.items() if not suits_match(suit, chosen)), reverse=True)
        if others:
            mc_margin = mc_pick - others[0] if mc_pick is not None else None

    rivals_weak = _rivals_weak_count(chosen, handicap_cards, draw_cards, track_moved) if chosen else 0
    level, reasons = _classify_level(
        pick=chosen,
        track_leader=track_leader,
        track_gap=track_gap,
        mc_pick=mc_pick,
        mc_margin=mc_margin,
        rivals_weak=rivals_weak,
        thresholds=thresholds,
    )

    return ConfidenceResult(
        level=level,
        pick=chosen,
        track_leader=track_leader,
        track_gap=track_gap,
        pick_on_track_leader=bool(
            chosen and track_leader and suits_match(chosen, track_leader)
        ),
        mc_probs=mc_probs,
        mc_pick=mc_pick,
        mc_margin=mc_margin,
        rivals_weak_count=rivals_weak,
        draw_rounds=rounds,
        reasons=reasons,
        should_alert=False,
    )


def format_confidence_text(result: ConfidenceResult) -> str:
    if result.level is ConfidenceLevel.NONE:
        return "— (need 2 draw rounds)"
    headline = result.level.value
    if result.pick:
        headline = f"{headline} — {result.pick.title()}"
    details: list[str] = []
    if result.track_gap is not None:
        details.append(f"gap +{result.track_gap}")
    if result.mc_pick is not None:
        details.append(f"MC {result.mc_pick:.0%}")
    if result.rivals_weak_count:
        details.append(f"{result.rivals_weak_count} weak rivals")
    if details:
        return f"{headline} ({', '.join(details)})"
    if result.reasons:
        return f"{headline} ({result.reasons[0]})"
    return headline
