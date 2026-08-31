"""Tests for capture health heartbeat and /api/health."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from game_analyzer.capture_health import (
    evaluate_capture_health,
    mark_capture_started,
    mark_capture_stopped,
    read_capture_status,
    record_capture_error,
    record_capture_tick,
    setup_capture_logging,
    tail_capture_log,
)
from game_analyzer.models import ExtractionResult, GamePhase, RaceState
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.web import create_app
from fastapi.testclient import TestClient

PNG = b"x"


def _config(tmp_path: Path) -> dict:
    return {
        "health": {
            "status_path": str(tmp_path / "capture_status.json"),
            "log_path": str(tmp_path / "capture.log"),
            "capture_stale_seconds": 60,
            "game_stale_seconds": 45,
        }
    }


def test_capture_status_round_trip(tmp_path: Path):
    cfg = _config(tmp_path)
    mark_capture_started(source="test", config=cfg)
    record_capture_tick(
        game_id="105",
        phase="IN_PLAY",
        recording=True,
        in_progress=True,
        saved=True,
        config=cfg,
    )
    status = read_capture_status(cfg)
    assert status["capture_running"] is True
    assert status["game_id"] == "105"
    mark_capture_stopped(reason="done", config=cfg)
    assert read_capture_status(cfg)["capture_running"] is False


def test_record_capture_error_writes_log(tmp_path: Path):
    cfg = _config(tmp_path)
    setup_capture_logging(cfg)
    record_capture_error(RuntimeError("boom"), context="unit test", config=cfg)
    lines = tail_capture_log(config=cfg)
    assert lines
    assert any("boom" in line for line in lines)


def test_evaluate_capture_health_stale_when_no_heartbeat(tmp_path: Path):
    cfg = _config(tmp_path)
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    mark_capture_started(source="test", config=cfg)
    status_path = Path(cfg["health"]["status_path"])
    data = read_capture_status(cfg)
    old = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    data["last_heartbeat_at"] = old
    status_path.write_text(json.dumps(data), encoding="utf-8")
    payload = evaluate_capture_health(store, config=cfg)
    assert payload["status"] == "degraded"
    assert payload["capture"]["state"] == "stale"


def test_evaluate_capture_health_game_stale(tmp_path: Path):
    cfg = _config(tmp_path)
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    old_time = datetime.now(timezone.utc) - timedelta(minutes=3)
    store.record(
        SessionDecision(
            recording=True,
            session_id="game_105",
            seq=1,
            phase=GamePhase.IN_PLAY,
            reason="test",
            should_save=True,
            game_id="105",
            table_cards=(("Spades", ("AS",)),),
        ),
        ExtractionResult(
            race_state=RaceState.IN_PROGRESS,
            winner_suit=None,
            high_low=None,
            confident=True,
            draw_cards=(),
            handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
        ),
        shot,
        old_time,
    )
    mark_capture_started(source="test", config=cfg)
    record_capture_tick(
        game_id="105",
        phase="IN_PLAY",
        recording=True,
        in_progress=True,
        saved=True,
        config=cfg,
    )
    payload = evaluate_capture_health(store, config=cfg)
    assert payload["game"]["state"] == "stale"
    assert payload["status"] == "degraded"


def test_api_health_route(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    client = TestClient(create_app(store=store, auth_enabled=False))
    response = client.get("/api/health")
    assert response.status_code in {200, 503}
    body = response.json()
    assert "capture" in body
    assert "game" in body
    assert body["web"] == "ok"
