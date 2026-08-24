from game_analyzer.confidence import ConfidenceLevel
from game_analyzer.confidence_stats import (
    TierAccuracy,
    build_accuracy_report,
    draws_for_round,
    format_round_snapshot,
    snapshot_at_round,
)
from game_analyzer.race_values import race_guess

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
# Dominant Spades after 6 cards — HIGH/VERY_HIGH.
STRONG_SIX = ("AS", "KS", "QS", "10S", "9S", "8S")
# Add three more Spades for round 3.
STRONG_NINE = STRONG_SIX + ("7S", "6S", "5S")
# Tight race — typically not HIGH.
TIGHT_SIX = ("5H", "7S", "AD", "3C", "6D", "4S")


def test_draws_for_round_requires_full_rounds():
    assert draws_for_round(STRONG_SIX, 2) == STRONG_SIX
    assert draws_for_round(STRONG_SIX, 3) is None
    assert draws_for_round(STRONG_NINE, 3) == STRONG_NINE


def test_snapshot_round2_high_when_dominant():
    snap = snapshot_at_round(
        HANDICAP,
        STRONG_SIX,
        draw_rounds=2,
        winner_suit="Spades",
        simulations=300,
        seed=1,
    )
    assert snap.ready
    assert snap.is_strong
    assert snap.result is not None
    assert snap.result.pick == "Spades"
    assert snap.correct is True
    text = format_round_snapshot(snap)
    assert "R2:" in text
    assert "won" in text


def test_snapshot_round3_marks_wrong_when_winner_differs():
    snap = snapshot_at_round(
        HANDICAP,
        STRONG_NINE,
        draw_rounds=3,
        winner_suit="Hearts",
        simulations=200,
        seed=2,
    )
    assert snap.ready
    assert snap.correct is False
    assert "lost" in format_round_snapshot(snap)


def test_build_accuracy_report_separates_high_and_very_high():
    games = [
        ("Spades", HANDICAP, STRONG_SIX),
        ("Spades", HANDICAP, STRONG_NINE),
        ("Diamonds", HANDICAP, TIGHT_SIX),
    ]
    report = build_accuracy_report(games, simulations=250, seed=3)
    assert report.games_scored == 3
    summary = report.format_summary()
    assert "HIGH:" in summary
    assert "VERY_HIGH:" in summary
    assert "R2" in summary and "R3" in summary
    # Strong Spades games land in HIGH or VERY_HIGH, not merged into one bucket.
    strong_r2 = report.round2.high.total + report.round2.very_high.total
    assert strong_r2 >= 1
    strong_r3 = report.round3.high.total + report.round3.very_high.total
    assert strong_r3 >= 1


def test_tier_accuracy_format_empty():
    empty = TierAccuracy(2, ConfidenceLevel.HIGH, 0, 0)
    assert empty.format_line() == "R2 HIGH: no games yet"
    assert empty.percent is None


def test_snapshot_pick_matches_race_guess():
    snap = snapshot_at_round(HANDICAP, TIGHT_SIX, draw_rounds=2, simulations=150, seed=4)
    assert snap.result is not None
    assert snap.result.pick == race_guess(HANDICAP, TIGHT_SIX)
    assert snap.result.level is not ConfidenceLevel.NONE
