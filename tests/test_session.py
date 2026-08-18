from datetime import datetime

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import GameSessionTracker, RoundTiming


def _result(**kwargs) -> ExtractionResult:
    defaults = dict(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=(),
        handicap_cards=(),
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


HANDICAP = (
    ("AS", "2S", "3S"),
    ("4H", "6H", "KH"),
    ("3C", "8C", "QC"),
    ("2D", "7D", "10D"),
)

NOW = datetime(2026, 8, 18, 15, 30, 0)


def test_phase_from_cards_and_winner():
    assert _result().game_phase() == GamePhase.START
    assert _result(handicap_cards=HANDICAP).game_phase() == GamePhase.DEALT
    assert _result(handicap_cards=HANDICAP, draw_cards=("5H", "7S", "AD")).game_phase() == GamePhase.IN_PLAY
    assert _result(
        race_state=RaceState.FINISHED,
        winner_suit=Suit.CLUBS,
        handicap_cards=HANDICAP,
        draw_cards=("5H",),
    ).game_phase() == GamePhase.FINISHED


def test_tracker_waits_if_joined_mid_game_or_at_results():
    tracker = GameSessionTracker()
    mid = tracker.observe(_result(handicap_cards=HANDICAP, draw_cards=("5H",)), game_id="111")
    assert mid.recording is False
    assert mid.peek_id_only is True
    assert mid.next_wait_seconds == 3

    end = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.HEARTS, handicap_cards=HANDICAP),
        game_id="111",
    )
    assert end.recording is False


def test_round_clock_waits_10s_then_32s():
    tracker = GameSessionTracker(RoundTiming())
    start = tracker.observe(_result(), captured_at=NOW, game_id="105211667")
    assert start.recording
    assert start.session_id == "game_105211667"
    assert start.next_wait_seconds == 10

    dealt = tracker.observe(_result(handicap_cards=HANDICAP), captured_at=NOW, game_id="105211667")
    assert dealt.should_save is True
    assert dealt.next_wait_seconds == 32

    play = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H",)), captured_at=NOW, game_id="105211667"
    )
    assert play.should_save is True
    assert play.next_wait_seconds == 32

    same_round = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H",)), captured_at=NOW, game_id="105211667"
    )
    assert same_round.should_save is False
    assert same_round.next_wait_seconds == 32


def test_game_id_change_ends_game_even_without_winner():
    tracker = GameSessionTracker()
    tracker.observe(_result(handicap_cards=HANDICAP), captured_at=NOW, game_id="100")
    changed = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("9D",)),
        captured_at=NOW,
        game_id="200",
    )
    assert changed.recording is False
    assert changed.reason == "waiting for next game start"

    next_start = tracker.observe(_result(), captured_at=NOW, game_id="200")
    assert next_start.recording is True
    assert next_start.session_id == "game_200"


def test_tracker_groups_one_game_then_opens_the_next():
    tracker = GameSessionTracker()
    start = tracker.observe(_result(), captured_at=NOW, game_id="555")
    dealt = tracker.observe(_result(handicap_cards=HANDICAP), captured_at=NOW, game_id="555")
    play = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H",)), captured_at=NOW, game_id="555"
    )
    done = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.CLUBS, handicap_cards=HANDICAP),
        captured_at=NOW,
        game_id="555",
    )

    assert start.session_id == dealt.session_id == play.session_id
    assert done.recording and done.phase == GamePhase.FINISHED

    leftover = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.CLUBS),
        captured_at=NOW,
        game_id="555",
    )
    assert leftover.recording is False
    assert leftover.peek_id_only is True

    next_game = tracker.observe(_result(), captured_at=NOW, game_id="556")
    assert next_game.recording is True
    assert next_game.session_id == "game_556"
    assert next_game.seq == 1


def test_drawn_cards_append_across_rounds():
    tracker = GameSessionTracker()
    tracker.observe(_result(handicap_cards=HANDICAP), captured_at=NOW, game_id="777")
    round1 = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H", "7S", "AD")),
        captured_at=NOW,
        game_id="777",
    )
    round2 = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("3C", "6D", "4S")),
        captured_at=NOW,
        game_id="777",
    )
    assert round1.table_cards == (
        ("Spades", ("AS", "2S", "3S", "7S")),
        ("Hearts", ("4H", "6H", "KH", "5H")),
        ("Clubs", ("3C", "8C", "QC")),
        ("Diamonds", ("2D", "7D", "10D", "AD")),
    )
    assert round2.table_cards == (
        ("Spades", ("AS", "2S", "3S", "7S", "4S")),
        ("Hearts", ("4H", "6H", "KH", "5H")),
        ("Clubs", ("3C", "8C", "QC", "3C")),
        ("Diamonds", ("2D", "7D", "10D", "AD", "6D")),
    )
