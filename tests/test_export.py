from datetime import datetime
from pathlib import Path

from game_analyzer.export import rebuild_rounds, write_export
from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore, StoredFrame

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
ROUND1 = ("5H", "7S", "AD")
ROUND2 = ("3C", "6D", "4S")


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


def _decision(**kwargs) -> SessionDecision:
    defaults = dict(
        recording=True,
        session_id="game_100",
        seq=1,
        phase=GamePhase.IN_PLAY,
        reason="test",
        should_save=True,
        game_id="100",
        table_cards=(("Spades", ("AS",)),),
        drawn_cards=ROUND1 + ROUND2,
        locked_guess="Hearts",
        locked_guess_draws=ROUND1 + ROUND2,
        locked_guess_rounds=2,
    )
    defaults.update(kwargs)
    return SessionDecision(**defaults)


def test_rebuild_rounds_handles_cumulative_frame_rows():
    frames = (
        StoredFrame(1, "IN_PLAY", "t1", Path("a.png"), ROUND1),
        StoredFrame(2, "IN_PLAY", "t2", Path("b.png"), ROUND1 + ROUND2),
    )
    assert rebuild_rounds(frames) == [list(ROUND1), list(ROUND2)]


def test_write_export_includes_game(tmp_path: Path):
    db = tmp_path / "games.sqlite"
    store = GameStore(db)
    shot = tmp_path / "001.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 8, 23, 12, 0, 0)

    store.record(
        _decision(phase=GamePhase.DEALT, seq=1, drawn_cards=()),
        _result(handicap_cards=HANDICAP),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(phase=GamePhase.IN_PLAY, seq=2, drawn_cards=ROUND1),
        _result(handicap_cards=HANDICAP, draw_cards=ROUND1),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        _decision(
            phase=GamePhase.FINISHED,
            seq=3,
            drawn_cards=ROUND1 + ROUND2,
            locked_guess="Hearts",
            locked_guess_draws=ROUND1 + ROUND2,
        ),
        _result(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.HEARTS,
            handicap_cards=HANDICAP,
            draw_cards=ROUND2,
        ),
        shot,
        now,
        root=tmp_path,
    )

    out = tmp_path / "export.json"
    summary = write_export(out, store=store)
    assert summary["games"] == 1
    assert '"game_id": "100"' in out.read_text(encoding="utf-8")
