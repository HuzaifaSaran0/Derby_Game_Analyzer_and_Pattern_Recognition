from datetime import datetime

from game_analyzer.models import ExtractionResult, RaceState, Suit
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


def test_accumulates_draw_rounds_without_guess_lock():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="100")
    decision = tracker.observe(_result(draw_cards=ROUND1), now, game_id="100")
    assert decision.locked_guess is None
    assert decision.drawn_cards == ROUND1

    decision = tracker.observe(_result(draw_cards=ROUND2), now, game_id="100")
    assert decision.locked_guess is None
    assert decision.drawn_cards == SIX_DRAWS
    assert decision.should_save is True


def test_finished_frame_ingests_final_round_cards():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)
    nine = SIX_DRAWS + ("2S", "3D", "4C")

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="200")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="200")
    tracker.observe(_result(draw_cards=ROUND2), now, game_id="200")

    finished = tracker.observe(
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.HEARTS,
            draw_cards=("2S", "3D", "4C"),
        ),
        now,
        game_id="200",
    )
    assert finished.phase.value == "FINISHED"
    assert finished.drawn_cards == nine
    assert finished.locked_guess is None


def test_finished_frame_completes_second_round_draws():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)

    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="210")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="210")
    finished = tracker.observe(
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.SPADES,
            draw_cards=ROUND2,
        ),
        now,
        game_id="210",
    )
    assert finished.drawn_cards == SIX_DRAWS
