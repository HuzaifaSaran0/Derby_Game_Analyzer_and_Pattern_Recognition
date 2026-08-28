"""Delayed back/lay retake: replace the saved PNG once the betting table is on screen."""

from __future__ import annotations

from pathlib import Path

from game_analyzer.live import _retake_delay_seconds, retake_screenshot_for_lay_back
from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit

CONFIG = {"capture": {"mode": "brave_cdp"}}


def _result(race_state: RaceState, *, draws: tuple[str, ...] = ("5H",)) -> ExtractionResult:
    return ExtractionResult(
        race_state=race_state,
        winner_suit=Suit.CLUBS if race_state == RaceState.FINISHED else None,
        high_low=None,
        confident=True,
        draw_cards=draws,
        handicap_cards=(("AS",), ("2H",), ("3C",), ("4D",)),
    )


def _fakes(tmp_path: Path, *, page_id="123", frame_state=RaceState.BETTING):
    path = tmp_path / "001_IN_PLAY.png"
    path.write_bytes(b"original")
    return path, dict(
        read_id=lambda capture: page_id,
        grab=lambda config: "fake-frame",
        extract=lambda frame, config: _result(frame_state),
        write=lambda p, frame: Path(p).write_bytes(b"retaken"),
    )


def test_delay_per_phase():
    cap = {}
    assert _retake_delay_seconds(cap, GamePhase.START) == 8.0
    assert _retake_delay_seconds(cap, GamePhase.DEALT) == 9.0
    assert _retake_delay_seconds(cap, GamePhase.IN_PLAY) == 9.0
    assert _retake_delay_seconds(cap, GamePhase.FINISHED) is None


def test_delay_configurable_and_disable():
    cap = {"recapture_delay_seconds": 10.5, "recapture_start_delay_seconds": 7}
    assert _retake_delay_seconds(cap, GamePhase.IN_PLAY) == 10.5
    assert _retake_delay_seconds(cap, GamePhase.START) == 7.0
    assert _retake_delay_seconds({"recapture_enabled": False}, GamePhase.IN_PLAY) is None


def test_retake_replaces_file(tmp_path: Path):
    path, fakes = _fakes(tmp_path)
    assert retake_screenshot_for_lay_back(CONFIG, path, "123", **fakes) is True
    assert path.read_bytes() == b"retaken"
    assert not path.with_name(path.stem + "_retake.png").exists()


def test_retake_aborts_when_game_changed(tmp_path: Path):
    path, fakes = _fakes(tmp_path, page_id="999")
    assert retake_screenshot_for_lay_back(CONFIG, path, "123", **fakes) is False
    assert path.read_bytes() == b"original"


def test_retake_proceeds_when_id_unreadable(tmp_path: Path):
    path, fakes = _fakes(tmp_path, page_id=None)
    assert retake_screenshot_for_lay_back(CONFIG, path, "123", **fakes) is True
    assert path.read_bytes() == b"retaken"


def test_retake_aborts_on_winner_screen(tmp_path: Path):
    path, fakes = _fakes(tmp_path, frame_state=RaceState.FINISHED)
    assert retake_screenshot_for_lay_back(CONFIG, path, "123", **fakes) is False
    assert path.read_bytes() == b"original"


def test_retake_survives_grab_failure(tmp_path: Path):
    path, fakes = _fakes(tmp_path)

    def boom(config):
        raise RuntimeError("CDP down")

    fakes["grab"] = boom
    assert retake_screenshot_for_lay_back(CONFIG, path, "123", **fakes) is False
    assert path.read_bytes() == b"original"
