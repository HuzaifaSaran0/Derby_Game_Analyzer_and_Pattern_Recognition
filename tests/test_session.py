from datetime import datetime

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import GameSessionTracker, RoundTiming, WaitMode


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
    assert mid.next_wait_seconds == 1.5

    end = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.HEARTS, handicap_cards=HANDICAP),
        game_id="111",
    )
    assert end.recording is False


def test_hybrid_schedule_timer_then_37_then_32():
    tracker = GameSessionTracker(RoundTiming())
    start = tracker.observe(
        _result(), captured_at=NOW, game_id="105211667", timer_seconds=25
    )
    assert start.next_wait_seconds == 26
    assert start.wait_from_live_timer is True

    # After handicap appears: always 37s to first draw (ignore stale "32" timer reads).
    dealt = tracker.observe(
        _result(handicap_cards=HANDICAP),
        captured_at=NOW,
        game_id="105211667",
        timer_seconds=32,  # would be wrong if trusted
    )
    assert dealt.phase == GamePhase.DEALT
    assert dealt.next_wait_seconds == 37
    assert dealt.watch_result is False

    play = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H",)),
        captured_at=NOW,
        game_id="105211667",
        timer_seconds=0,
    )
    assert play.next_wait_seconds == 32
    assert play.watch_result is True

    same_round = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H",)),
        captured_at=NOW,
        game_id="105211667",
        timer_seconds=9,
    )
    assert same_round.should_save is False
    assert same_round.next_wait_seconds == 9


def test_dealt_mid_join_uses_circle_timer():
    tracker = GameSessionTracker(RoundTiming())
    tracker._ever_observed = True
    mid = tracker.observe(
        _result(handicap_cards=HANDICAP),
        captured_at=NOW,
        game_id="99",
        timer_seconds=27,
    )
    assert mid.next_wait_seconds == 28
    assert mid.wait_from_live_timer is True


def test_start_without_timer_uses_first_round_remaining():
    tracker = GameSessionTracker(RoundTiming())
    start = tracker.observe(_result(), captured_at=NOW, game_id="1")
    assert start.next_wait_seconds == 26


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
    assert tracker._ignored_game_id == "200"

    # Same id still mid-skip until Game ID changes.
    same = tracker.observe(_result(), captured_at=NOW, game_id="200")
    assert same.recording is False
    assert same.peek_id_only is True

    next_start = tracker.observe(_result(), captured_at=NOW, game_id="300", timer_seconds=20)
    assert next_start.recording is True
    assert next_start.session_id == "game_300"


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


def test_finished_leftover_with_timer_starts_new_game():
    """Result + new Game ID + timer → ignore winner, sync to remaining seconds."""
    tracker = GameSessionTracker()
    tracker._ever_observed = True
    tracker._ignored_game_id = "100"

    sync = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.SPADES),
        captured_at=NOW,
        game_id="411",
        timer_seconds=25,
    )
    assert sync.recording is True
    assert sync.should_save is False
    assert sync.seq == 0
    assert sync.session_id == "game_411"
    assert sync.next_wait_seconds == 26
    assert sync.wait_from_live_timer is True

    assert tracker._ignored_game_id is None

    dealt = tracker.observe(
        _result(handicap_cards=HANDICAP),
        captured_at=NOW,
        game_id="411",
        timer_seconds=0,
    )
    assert dealt.should_save is True
    assert dealt.seq == 1
    assert dealt.phase == GamePhase.DEALT


def test_finished_leftover_without_timer_does_not_blacklist():
    tracker = GameSessionTracker()
    tracker._ever_observed = True
    tracker._ignored_game_id = "100"
    leftover = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.SPADES),
        captured_at=NOW,
        game_id="411",
    )
    assert leftover.recording is False
    assert leftover.reason == "result still on screen — waiting for next game start"
    assert tracker._ignored_game_id == "100"


def test_after_finished_same_game_id_does_not_restart_session():
    """Result clears to START before Game ID changes — must not write another 001/002."""
    tracker = GameSessionTracker(RoundTiming())
    tracker.observe(_result(), captured_at=NOW, game_id="731", timer_seconds=25)
    tracker.observe(_result(handicap_cards=HANDICAP), captured_at=NOW, game_id="731")
    done = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.CLUBS, handicap_cards=HANDICAP),
        captured_at=NOW,
        game_id="731",
    )
    assert done.phase == GamePhase.FINISHED
    assert done.should_save is True

    # Next tick: same id, looks like START again (result UI gone / betting flash).
    again = tracker.observe(_result(), captured_at=NOW, game_id="731", timer_seconds=25)
    assert again.recording is False
    assert again.peek_id_only is True
    assert again.reason == "waiting for Game ID to change"

    # New id may start under leftover result + timer.
    nxt = tracker.observe(
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.SPADES),
        captured_at=NOW,
        game_id="732",
        timer_seconds=25,
    )
    assert nxt.recording is True
    assert nxt.should_save is False
    assert nxt.session_id == "game_732"
    assert nxt.next_wait_seconds == 26

    tracker = GameSessionTracker(RoundTiming())
    dealt = tracker.observe(
        _result(handicap_cards=HANDICAP),
        captured_at=NOW,
        game_id="99",
        timer_seconds=24,
    )
    assert dealt.recording is True
    assert dealt.should_save is True
    assert dealt.next_wait_seconds == 25
    assert dealt.wait_from_live_timer is True
    assert dealt.session_id == "game_99"


def test_in_play_without_session_still_skips_to_next_game():
    tracker = GameSessionTracker()
    tracker._ever_observed = True
    mid = tracker.observe(
        _result(handicap_cards=HANDICAP, draw_cards=("5H",)),
        captured_at=NOW,
        game_id="411",
    )
    assert mid.recording is False
    assert tracker._ignored_game_id == "411"


def test_drawn_cards_append_across_rounds():
    tracker = GameSessionTracker()
    tracker._ever_observed = True
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
