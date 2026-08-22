from datetime import datetime
from pathlib import Path

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore

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
        handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


def _decision(**kwargs) -> SessionDecision:
    defaults = dict(
        recording=True,
        session_id="game_100",
        seq=1,
        phase=GamePhase.DEALT,
        reason="test",
        should_save=True,
        game_id="100",
        table_cards=(("Spades", ("AS", "2S")),),
    )
    defaults.update(kwargs)
    return SessionDecision(**defaults)


def test_store_saves_game_frames_and_winner(tmp_path: Path):
    db = tmp_path / "games.sqlite"
    store = GameStore(db)
    shot1 = tmp_path / "001.png"
    shot2 = tmp_path / "002.png"
    shot1.write_bytes(b"x")
    shot2.write_bytes(b"y")
    now = datetime(2026, 8, 18, 18, 0, 0)

    store.record(_decision(seq=1, phase=GamePhase.DEALT), _result(), shot1, now, root=tmp_path)
    store.record(
        _decision(seq=2, phase=GamePhase.FINISHED),
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.CLUBS),
        shot2,
        now,
        root=tmp_path,
    )

    assert store.list_game_ids() == ["100"]
    listed = store.list_games()
    assert listed[0]["game_id"] == "100"
    assert listed[0]["shot_count"] == 2
    assert listed[0]["winner_suit"] == "CLUBS"
    game = store.get_game("100", root=tmp_path)
    assert game is not None
    assert game.winner_suit == "CLUBS"
    assert len(game.frames) == 2
    assert game.frames[0].phase == "DEALT"
    assert game.frames[1].screenshot_path.name == "002.png"


def test_store_rebuilds_two_round_draws_from_frames(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite")
    shot = tmp_path / "001.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 8, 18, 18, 0, 0)

    store.record(
        _decision(seq=1, phase=GamePhase.DEALT, game_id="200"),
        _result(handicap_cards=HANDICAP),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(
            seq=2,
            phase=GamePhase.IN_PLAY,
            game_id="200",
            drawn_cards=ROUND1,
        ),
        _result(handicap_cards=HANDICAP, draw_cards=ROUND1),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(
            seq=3,
            phase=GamePhase.IN_PLAY,
            game_id="200",
            drawn_cards=SIX_DRAWS,
        ),
        _result(handicap_cards=HANDICAP, draw_cards=ROUND2),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(
            seq=4,
            phase=GamePhase.FINISHED,
            game_id="200",
            drawn_cards=SIX_DRAWS,
        ),
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.DIAMONDS,
            handicap_cards=HANDICAP,
            draw_cards=ROUND2,
        ),
        shot,
        now,
        root=tmp_path,
    )

    game = store.get_game("200", root=tmp_path)
    assert game is not None
    assert game.frames[1].draw_cards == ROUND1
    assert game.frames[2].draw_cards == ROUND2
    assert game.draw_cards == SIX_DRAWS
    outcome = store.pre_race_outcome_for("200")
    assert outcome is not None
    assert outcome.guess == "Diamonds"
    assert outcome.correct is True


def test_store_keeps_all_draw_rounds_but_guesses_on_first_two(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite")
    shot = tmp_path / "001.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 8, 18, 18, 0, 0)
    round3 = ("2C", "9H", "5S")
    all_nine = SIX_DRAWS + round3

    for seq, phase, round_cards, drawn in [
        (1, GamePhase.DEALT, (), ()),
        (2, GamePhase.IN_PLAY, ROUND1, ROUND1),
        (3, GamePhase.IN_PLAY, ROUND2, SIX_DRAWS),
        (4, GamePhase.IN_PLAY, round3, all_nine),
        (5, GamePhase.FINISHED, round3, all_nine),
    ]:
        store.record(
            _decision(
                seq=seq,
                phase=phase,
                game_id="300",
                drawn_cards=drawn,
            ),
            _result(
                race_state=RaceState.FINISHED if phase == GamePhase.FINISHED else RaceState.BETTING,
                winner_suit=Suit.HEARTS if phase == GamePhase.FINISHED else None,
                handicap_cards=HANDICAP,
                draw_cards=round_cards,
            ),
            shot,
            now,
            root=tmp_path,
        )

    game = store.get_game("300", root=tmp_path)
    assert game is not None
    assert game.draw_cards == all_nine
    assert game.guess_draw_cards == SIX_DRAWS


def test_store_pre_race_guess_accuracy(tmp_path: Path):
    db = tmp_path / "games.sqlite"
    store = GameStore(db)
    shot = tmp_path / "001.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 8, 18, 18, 0, 0)

    store.record(
        _decision(
            seq=1,
            phase=GamePhase.FINISHED,
            game_id="101",
            drawn_cards=SIX_DRAWS,
        ),
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.DIAMONDS,
            handicap_cards=HANDICAP,
            draw_cards=ROUND2,
        ),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(
            seq=1,
            phase=GamePhase.FINISHED,
            game_id="102",
            drawn_cards=SIX_DRAWS,
        ),
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.CLUBS,
            handicap_cards=HANDICAP,
            draw_cards=ROUND2,
        ),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(seq=1, phase=GamePhase.DEALT, game_id="103"),
        _result(handicap_cards=HANDICAP),
        shot,
        now,
        root=tmp_path,
    )

    stats = store.pre_race_guess_accuracy()
    assert stats.total == 2
    assert stats.correct == 1
    assert stats.percent == 50.0


def test_store_skips_waiting_frames(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite")
    store.record(
        _decision(recording=False, should_save=False),
        _result(),
        tmp_path / "wait.png",
        datetime.now(),
        root=tmp_path,
    )
    assert store.list_game_ids() == []


def test_store_cleanup_sensible(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite")
    shot = tmp_path / "001.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 8, 18, 18, 0, 0)

    store.record(
        _decision(seq=1, phase=GamePhase.DEALT, game_id="abandoned"),
        _result(handicap_cards=HANDICAP),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(seq=1, phase=GamePhase.FINISHED, game_id="broken"),
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.HEARTS,
            handicap_cards=(("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C")),
        ),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(
            seq=1,
            phase=GamePhase.FINISHED,
            game_id="good",
            drawn_cards=SIX_DRAWS,
        ),
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.DIAMONDS,
            handicap_cards=HANDICAP,
            draw_cards=ROUND2,
        ),
        shot,
        now,
        root=tmp_path,
    )

    report = store.cleanup_sensible()
    assert report.deleted_count == 2
    assert store.list_game_ids() == ["good"]
    assert report.games_after == 1
