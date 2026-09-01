"""Background winner poll saves FINISHED once per game."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest

from game_analyzer.live import (
    GAME_STORE,
    SESSION_TRACKER,
    WinnerPollWatcher,
    _try_capture_winner,
    stop_winner_poll,
)
from game_analyzer.models import ExtractionResult, RaceState, Suit

HANDICAP = (
    ("AS", "KS", "QS"),
    ("2H", "3H", "4H"),
    ("6C", "8C", "9C"),
    ("10D", "JD", "QD"),
)
PNG = b"x"
FRAME = np.zeros((4, 4, 3), dtype=np.uint8)


def _finished_result() -> ExtractionResult:
    return ExtractionResult(
        race_state=RaceState.FINISHED,
        winner_suit=Suit.CLUBS,
        high_low=None,
        confident=True,
        draw_cards=("5H", "7S", "AD"),
        handicap_cards=HANDICAP,
    )


def _in_play_result() -> ExtractionResult:
    return ExtractionResult(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=("5H", "7S", "AD"),
        handicap_cards=HANDICAP,
    )


@pytest.fixture
def tmp_store(tmp_path: Path, monkeypatch):
    store = GAME_STORE.__class__(tmp_path / "games.sqlite", root=tmp_path)
    monkeypatch.setattr("game_analyzer.live.GAME_STORE", store)
    return store


@pytest.fixture(autouse=True)
def reset_tracker():
    SESSION_TRACKER.__init__()
    yield
    stop_winner_poll()


def _open_session(game_id: str = "555") -> None:
    tracker = SESSION_TRACKER
    tracker.observe(
        ExtractionResult(
            race_state=RaceState.BETTING,
            winner_suit=None,
            high_low=None,
            confident=False,
            draw_cards=(),
            handicap_cards=HANDICAP,
        ),
        datetime(2026, 9, 1, 12, 0, 0),
        game_id=game_id,
    )
    tracker.observe(
        _in_play_result(),
        datetime(2026, 9, 1, 12, 1, 0),
        game_id=game_id,
    )


def test_winner_poll_saves_finished_once(tmp_path: Path, tmp_store, monkeypatch):
    _open_session("777")
    config = {
        "capture": {
            "winner_poll_enabled": True,
            "winner_poll_seconds": 0.05,
            "finished_capture_settle_seconds": 0,
        }
    }
    finished = _finished_result()

    monkeypatch.setattr("game_analyzer.live.LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr("game_analyzer.live.read_page_game_id", lambda _cap: "777")
    monkeypatch.setattr("game_analyzer.live.grab_frame", lambda _cfg: FRAME)
    monkeypatch.setattr("game_analyzer.live.extract_real", lambda _frame, _cfg: finished)
    monkeypatch.setattr("game_analyzer.live.write_image", lambda path, _frame: path.write_bytes(PNG))

    assert _try_capture_winner(config) is True
    game = tmp_store.get_game("777")
    assert game is not None
    assert game.winner_suit == "CLUBS"
    assert len(game.frames) == 1

    assert _try_capture_winner(config) is False
    game = tmp_store.get_game("777")
    assert len(game.frames) == 1


def test_winner_poll_ignores_when_no_open_session(tmp_path: Path, monkeypatch):
    config = {"capture": {"winner_poll_enabled": True, "finished_capture_settle_seconds": 0}}
    monkeypatch.setattr("game_analyzer.live.read_page_game_id", lambda _cap: "999")
    monkeypatch.setattr("game_analyzer.live.grab_frame", lambda _cfg: FRAME)
    monkeypatch.setattr("game_analyzer.live.extract_real", lambda _frame, _cfg: _finished_result())

    assert _try_capture_winner(config) is False


def test_winner_poll_ignores_non_finished_screen(tmp_path: Path, monkeypatch):
    _open_session("888")
    config = {"capture": {"winner_poll_enabled": True, "finished_capture_settle_seconds": 0}}
    monkeypatch.setattr("game_analyzer.live.read_page_game_id", lambda _cap: "888")
    monkeypatch.setattr("game_analyzer.live.grab_frame", lambda _cfg: FRAME)
    monkeypatch.setattr("game_analyzer.live.extract_real", lambda _frame, _cfg: _in_play_result())

    assert _try_capture_winner(config) is False


def test_winner_poll_watcher_runs_until_stopped(tmp_path: Path, tmp_store, monkeypatch):
    _open_session("666")
    config = {
        "capture": {
            "winner_poll_enabled": True,
            "winner_poll_seconds": 0.05,
            "finished_capture_settle_seconds": 0,
        }
    }
    finished = _finished_result()
    calls = {"n": 0}

    def _extract(_frame, _cfg):
        calls["n"] += 1
        return finished

    monkeypatch.setattr("game_analyzer.live.LIVE_DIR", tmp_path / "live")
    monkeypatch.setattr("game_analyzer.live.read_page_game_id", lambda _cap: "666")
    monkeypatch.setattr("game_analyzer.live.grab_frame", lambda _cfg: FRAME)
    monkeypatch.setattr("game_analyzer.live.extract_real", _extract)
    monkeypatch.setattr("game_analyzer.live.write_image", lambda path, _frame: path.write_bytes(PNG))

    watcher = WinnerPollWatcher()
    watcher.start(config)
    import time

    time.sleep(0.25)
    watcher.stop()

    game = tmp_store.get_game("666")
    assert game is not None
    assert game.winner_suit == "CLUBS"
    assert len(game.frames) == 1
    assert calls["n"] >= 1
