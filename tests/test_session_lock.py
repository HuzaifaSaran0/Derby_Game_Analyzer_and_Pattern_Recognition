from datetime import datetime

from game_analyzer.models import ExtractionResult, RaceState, Suit
from game_analyzer.race_values import race_guess
from game_analyzer.session import GameSessionTracker

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
ROUND1 = ("5H", "7S", "AD")
ROUND2 = ("3C", "6D", "4S")
SIX_DRAWS = ROUND1 + ROUND2


def _result(**kwargs) -> ExtractionResult:
    defaults = dict(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=(),
        handicap_cards=HANDICAP,
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


def test_locks_guess_after_two_draw_rounds():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="100")
    decision = tracker.observe(
        _result(draw_cards=ROUND1),
        now,
        game_id="100",
    )
    assert decision.locked_guess is None

    decision = tracker.observe(
        _result(draw_cards=ROUND2),
        now,
        game_id="100",
    )
    assert decision.locked_guess == race_guess(HANDICAP, SIX_DRAWS)
    assert decision.locked_guess_draws == SIX_DRAWS
    assert decision.locked_guess_rounds == 2


def test_finished_frame_does_not_change_locked_guess():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="200")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="200")
    mid = tracker.observe(_result(draw_cards=ROUND2), now, game_id="200")
    locked = mid.locked_guess
    assert locked is not None

    finished = tracker.observe(
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.HEARTS,
            draw_cards=("2H", "3D", "4C"),
        ),
        now,
        game_id="200",
    )
    assert finished.locked_guess == locked
    assert finished.locked_guess_draws == SIX_DRAWS
    assert finished.locked_guess == race_guess(HANDICAP, SIX_DRAWS)
    # Finished cards are still stored for history.
    assert finished.drawn_cards == SIX_DRAWS + ("2H", "3D", "4C")


def test_finished_frame_completes_second_round_and_locks():
    """When round 2 only appears on the winner screen, still lock from those cards."""
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="210")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="210")
    assert tracker.locked_guess is None

    finished = tracker.observe(
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.CLUBS,
            draw_cards=ROUND2,
        ),
        now,
        game_id="210",
    )
    assert finished.locked_guess == race_guess(HANDICAP, SIX_DRAWS)
    assert finished.locked_guess_draws == SIX_DRAWS
    assert finished.locked_guess_rounds == 2
    assert finished.drawn_cards == SIX_DRAWS


def test_finished_partial_second_round_still_cannot_lock():
    """Winner overlay often hides a card — fewer than 6 draws still means no guess."""
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="220")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="220")
    finished = tracker.observe(
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.CLUBS,
            draw_cards=("JC", "QC"),
        ),
        now,
        game_id="220",
    )
    assert finished.locked_guess is None
    assert finished.drawn_cards == ROUND1 + ("JC", "QC")


def test_third_round_upgrades_lock_before_finished():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)
    round3 = ("2C", "9H", "5S")
    nine = SIX_DRAWS + round3

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="300")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="300")
    tracker.observe(_result(draw_cards=ROUND2), now, game_id="300")
    decision = tracker.observe(_result(draw_cards=round3), now, game_id="300")

    assert decision.locked_guess_rounds == 3
    assert decision.locked_guess_draws == nine
    assert decision.locked_guess == race_guess(HANDICAP, nine)
