from game_analyzer.confidence import (
    ConfidenceLevel,
    evaluate_confidence,
    format_confidence_text,
)
from game_analyzer.monte_carlo import monte_carlo_win_probs
from game_analyzer.race_values import guess_ready, race_guess, suits_match

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
ROUND1 = ("5H", "7S", "AD")
ROUND2 = ("3C", "6D", "4S")
SIX_DRAWS = ROUND1 + ROUND2

# Leader Spades at 22, Hearts 5, Clubs 3, Diamonds 17 after six cards.
DOMINANT_SIX = ("AS", "KS", "QS", "10S", "9S", "8S")


def test_monte_carlo_probs_sum_to_one():
    probs = monte_carlo_win_probs(HANDICAP, SIX_DRAWS, simulations=500, seed=1)
    assert probs is not None
    assert abs(sum(probs.values()) - 1.0) < 1e-9
    assert all(0.0 <= value <= 1.0 for value in probs.values())


def test_confidence_none_before_six_cards():
    result = evaluate_confidence(HANDICAP, ROUND1, simulations=200, seed=2)
    assert result.level is ConfidenceLevel.NONE
    assert guess_ready(ROUND1) is False
    assert "need 2 draw rounds" in result.reasons[0]


def test_confidence_high_on_large_track_gap():
    result = evaluate_confidence(
        HANDICAP,
        DOMINANT_SIX,
        pick="Spades",
        simulations=300,
        seed=3,
    )
    assert result.track_gap is not None
    assert result.track_gap >= 10
    assert result.level in {ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH}
    text = format_confidence_text(result)
    assert "HIGH" in text or "VERY_HIGH" in text


def test_evaluate_does_not_change_race_guess_pick():
    baseline = race_guess(HANDICAP, SIX_DRAWS)
    result = evaluate_confidence(HANDICAP, SIX_DRAWS, simulations=200, seed=4)
    assert result.pick == baseline


def test_format_confidence_text_for_none():
    result = evaluate_confidence(HANDICAP, ROUND1)
    assert format_confidence_text(result) == "— (need 2 draw rounds)"


def test_backtest_runs_on_export_if_present():
    from pathlib import Path

    export = Path(__file__).resolve().parent.parent / "data" / "games_research_export.json"
    if not export.is_file():
        return
    from game_analyzer.confidence_backtest import run_backtest

    summary = run_backtest(export, verified_only=True, simulations=400)
    assert summary["evaluated"] > 0
    assert "by_level" in summary
    assert summary["high_plus"]["total"] >= 0
