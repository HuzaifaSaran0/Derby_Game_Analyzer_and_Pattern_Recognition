"""Round-2 / round-3 confidence snapshots and per-tier accuracy from stored games."""

from __future__ import annotations

from dataclasses import dataclass

from game_analyzer.confidence import (
    ConfidenceLevel,
    ConfidenceResult,
    evaluate_confidence,
    format_confidence_text,
)
from game_analyzer.race_values import CARDS_PER_DRAW_ROUND, race_guess, suits_match


@dataclass(frozen=True)
class RoundConfidenceSnapshot:
    draw_rounds: int
    result: ConfidenceResult | None
    correct: bool | None

    @property
    def ready(self) -> bool:
        return self.result is not None and self.result.ready

    @property
    def is_high(self) -> bool:
        return bool(self.result and self.result.level is ConfidenceLevel.HIGH)

    @property
    def is_very_high(self) -> bool:
        return bool(self.result and self.result.level is ConfidenceLevel.VERY_HIGH)

    @property
    def is_strong(self) -> bool:
        return self.is_high or self.is_very_high


@dataclass(frozen=True)
class TierAccuracy:
    """Hit-rate for one confidence tier at one round."""

    draw_rounds: int
    level: ConfidenceLevel
    total: int
    correct: int

    @property
    def percent(self) -> float | None:
        if self.total == 0:
            return None
        return round(100.0 * self.correct / self.total, 1)

    def format_line(self) -> str:
        label = f"R{self.draw_rounds} {self.level.value}"
        if self.total == 0:
            return f"{label}: no games yet"
        pct = self.percent if self.percent is not None else 0.0
        return f"{label}: {self.correct}/{self.total} ({pct:.0f}%)"


@dataclass(frozen=True)
class RoundTierAccuracy:
    draw_rounds: int
    high: TierAccuracy
    very_high: TierAccuracy

    def format_line(self) -> str:
        return f"{self.high.format_line()}  ·  {self.very_high.format_line()}"


@dataclass(frozen=True)
class ConfidenceAccuracyReport:
    round2: RoundTierAccuracy
    round3: RoundTierAccuracy
    games_scored: int

    def format_summary(self) -> str:
        return (
            f"R2  {self.round2.high.format_line().removeprefix('R2 ')}  ·  "
            f"{self.round2.very_high.format_line().removeprefix('R2 ')}"
            f"  |  "
            f"R3  {self.round3.high.format_line().removeprefix('R3 ')}  ·  "
            f"{self.round3.very_high.format_line().removeprefix('R3 ')}"
        )


def draws_for_round(draw_cards: tuple[str, ...], draw_rounds: int) -> tuple[str, ...] | None:
    need = draw_rounds * CARDS_PER_DRAW_ROUND
    if len(draw_cards) < need:
        return None
    return draw_cards[:need]


def snapshot_at_round(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
    *,
    draw_rounds: int,
    winner_suit: str | None = None,
    simulations: int = 600,
    seed: int | None = None,
) -> RoundConfidenceSnapshot:
    """Evaluate confidence using exactly ``draw_rounds`` of draw cards (2 or 3)."""
    sliced = draws_for_round(draw_cards, draw_rounds)
    if sliced is None:
        return RoundConfidenceSnapshot(draw_rounds=draw_rounds, result=None, correct=None)
    pick = race_guess(handicap_cards, sliced)
    result = evaluate_confidence(
        handicap_cards,
        sliced,
        pick=pick,
        simulations=simulations,
        seed=seed,
    )
    correct = None
    if winner_suit and result.pick:
        correct = suits_match(result.pick, winner_suit)
    return RoundConfidenceSnapshot(draw_rounds=draw_rounds, result=result, correct=correct)


def format_round_snapshot(snap: RoundConfidenceSnapshot) -> str:
    if snap.result is None:
        return f"R{snap.draw_rounds}: — (need {snap.draw_rounds} draw rounds)"
    text = format_confidence_text(snap.result)
    if snap.correct is True:
        return f"R{snap.draw_rounds}: {text}  ✓ won"
    if snap.correct is False:
        return f"R{snap.draw_rounds}: {text}  ✗ lost"
    return f"R{snap.draw_rounds}: {text}"


def _empty_round(draw_rounds: int) -> RoundTierAccuracy:
    return RoundTierAccuracy(
        draw_rounds=draw_rounds,
        high=TierAccuracy(draw_rounds, ConfidenceLevel.HIGH, 0, 0),
        very_high=TierAccuracy(draw_rounds, ConfidenceLevel.VERY_HIGH, 0, 0),
    )


def _tally_snap(
    snap: RoundConfidenceSnapshot,
    *,
    high_total: int,
    high_correct: int,
    vh_total: int,
    vh_correct: int,
) -> tuple[int, int, int, int]:
    if snap.correct is None:
        return high_total, high_correct, vh_total, vh_correct
    if snap.is_high:
        high_total += 1
        if snap.correct:
            high_correct += 1
    elif snap.is_very_high:
        vh_total += 1
        if snap.correct:
            vh_correct += 1
    return high_total, high_correct, vh_total, vh_correct


def build_accuracy_report(
    games: list[
        tuple[
            str | None,
            tuple[tuple[str, ...], ...],
            tuple[str, ...],
        ]
    ],
    *,
    simulations: int = 400,
    seed: int = 42,
) -> ConfidenceAccuracyReport:
    """Score HIGH and VERY_HIGH picks separately at round 2 and round 3.

    Each item is ``(winner_suit, handicap_cards, all_draw_cards)``.
    """
    r2_h = r2_hc = r2_vh = r2_vhc = 0
    r3_h = r3_hc = r3_vh = r3_vhc = 0
    scored = 0
    for index, (winner, handicap, draws) in enumerate(games):
        if not winner or not handicap:
            continue
        scored += 1
        game_seed = seed + index * 17
        snap2 = snapshot_at_round(
            handicap,
            draws,
            draw_rounds=2,
            winner_suit=winner,
            simulations=simulations,
            seed=game_seed,
        )
        r2_h, r2_hc, r2_vh, r2_vhc = _tally_snap(
            snap2,
            high_total=r2_h,
            high_correct=r2_hc,
            vh_total=r2_vh,
            vh_correct=r2_vhc,
        )
        snap3 = snapshot_at_round(
            handicap,
            draws,
            draw_rounds=3,
            winner_suit=winner,
            simulations=simulations,
            seed=game_seed + 1,
        )
        r3_h, r3_hc, r3_vh, r3_vhc = _tally_snap(
            snap3,
            high_total=r3_h,
            high_correct=r3_hc,
            vh_total=r3_vh,
            vh_correct=r3_vhc,
        )
    return ConfidenceAccuracyReport(
        round2=RoundTierAccuracy(
            2,
            TierAccuracy(2, ConfidenceLevel.HIGH, r2_h, r2_hc),
            TierAccuracy(2, ConfidenceLevel.VERY_HIGH, r2_vh, r2_vhc),
        ),
        round3=RoundTierAccuracy(
            3,
            TierAccuracy(3, ConfidenceLevel.HIGH, r3_h, r3_hc),
            TierAccuracy(3, ConfidenceLevel.VERY_HIGH, r3_vh, r3_vhc),
        ),
        games_scored=scored,
    )
