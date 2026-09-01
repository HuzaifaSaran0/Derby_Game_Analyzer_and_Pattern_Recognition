"""Ops alerts and unfinished games API."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from game_analyzer.models import ExtractionResult, GamePhase, RaceState
from game_analyzer.ops_alerts import format_missed_winner_message, notify_missed_winner, reset_missed_winner_memory
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.web import create_app

PNG = b"x"


def _record_in_progress(store: GameStore, tmp_path: Path, game_id: str) -> None:
    shot = tmp_path / f"{game_id}.png"
    shot.write_bytes(PNG)
    store.record(
        SessionDecision(
            recording=True,
            session_id=f"game_{game_id}",
            seq=1,
            phase=GamePhase.IN_PLAY,
            reason="test",
            should_save=True,
            game_id=game_id,
            table_cards=(("Spades", ("AS",)),),
        ),
        ExtractionResult(
            race_state=RaceState.BETTING,
            winner_suit=None,
            high_low=None,
            confident=False,
            draw_cards=("5H", "7S", "AD"),
            handicap_cards=(("AS",), ("2H",), ("3C",), ("4D",)),
        ),
        shot,
        datetime(2026, 9, 1, 12, 0, 0),
    )


def test_format_missed_winner_message():
    text = format_missed_winner_message(
        "105436955",
        started_at="2026-09-01T18:58:20",
        shot_count=6,
        public_base_url="http://example.com",
    )
    assert "105436955" in text
    assert "6 shot" in text
    assert "http://example.com/unfinished" in text


def test_notify_missed_winner_once(tmp_path: Path):
    reset_missed_winner_memory()
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    _record_in_progress(store, tmp_path, "100")
    config = {"alerts": {"ops_webhook_url": "https://hooks.slack.com/services/test"}}
    settings_path = tmp_path / "ops.log"

    with patch("game_analyzer.ops_alerts.alert_settings_from_config") as mock_settings:
        from game_analyzer.alerts import AlertSettings

        mock_settings.return_value = AlertSettings(
            ops_webhook_url="https://hooks.slack.com/services/test",
            public_base_url="http://localhost:8000",
            ops_log_path=settings_path,
        )
        with patch("game_analyzer.alerts.post_webhook") as post:
            assert notify_missed_winner(config, store, "100") is True
            assert notify_missed_winner(config, store, "100") is False
            post.assert_called_once()


def test_api_unfinished_lists_rows(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    _record_in_progress(store, tmp_path, "200")
    app = create_app(store, auth_enabled=False)
    client = TestClient(app)
    res = client.get("/api/unfinished")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["game_id"] == "200"
    assert data["items"][0]["shot_count"] == 1


def test_api_unfinished_cleanup(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    _record_in_progress(store, tmp_path, "300")
    app = create_app(store, auth_enabled=False)
    client = TestClient(app)
    res = client.post("/api/unfinished/cleanup")
    assert res.status_code == 200
    assert res.json()["deleted"] == 1
    assert client.get("/api/unfinished").json()["total"] == 0
