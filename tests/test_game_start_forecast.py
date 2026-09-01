"""Game-start forecast: one evaluation per game, notify on MEDIUM/HIGH."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.winner_hints import (
    NOTIFY_TIERS,
    evaluate_game_start_forecast,
    forecast_alert_already_sent,
)

PNG = b"x"


def _record_winner(store: GameStore, game_id: str, winner: Suit, shot: Path, now: datetime) -> None:
    store.record(
        SessionDecision(
            recording=True,
            session_id=f"game_{game_id}",
            seq=1,
            phase=GamePhase.FINISHED,
            reason="test",
            should_save=True,
            game_id=game_id,
            table_cards=((winner.value.title(), ("AS",)),),
        ),
        ExtractionResult(
            race_state=RaceState.FINISHED,
            winner_suit=winner,
            high_low=None,
            confident=True,
            draw_cards=(),
            handicap_cards=(("AS",), ("2H",), ("3C",), ("4D",)),
        ),
        shot,
        now,
    )


def _seed_history(store: GameStore, shot: Path, now: datetime) -> None:
    pattern = [Suit.CLUBS, Suit.HEARTS, Suit.DIAMONDS, Suit.HEARTS]
    for i in range(1, 15):
        winner = pattern[(i - 1) % len(pattern)]
        _record_winner(store, str(i), winner, shot, now)


def test_evaluate_game_start_forecast_notifies_once(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    _seed_history(store, shot, now)

    log_path = tmp_path / "alerts.log"
    conf_path = tmp_path / "confidence.log"
    config = {
        "alerts": {"log_path": str(log_path), "webhook_url": "https://hooks.slack.com/test"},
        "winner_hints": {"notify": True, "confidence_log_path": str(conf_path)},
    }

    with patch("game_analyzer.alerts.deliver_winner_hint_alert") as deliver:
        first = evaluate_game_start_forecast(store, config, "999")
        second = evaluate_game_start_forecast(store, config, "999")
        assert first is not None
        assert first.tier in NOTIFY_TIERS
        assert second is None
        assert deliver.call_count == 1
        assert "Game 999" in deliver.call_args.kwargs["alert_message"]
        assert deliver.call_args.kwargs["dedupe_key"] == "game-start:999"


def test_evaluate_game_start_forecast_skips_low_tier(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    # Only a few games — not enough strong patterns for MEDIUM/HIGH notify path.
    _record_winner(store, "1", Suit.SPADES, shot, now)
    _record_winner(store, "2", Suit.HEARTS, shot, now)
    _record_winner(store, "3", Suit.CLUBS, shot, now)
    _record_winner(store, "4", Suit.DIAMONDS, shot, now)

    log_path = tmp_path / "alerts.log"
    conf_path = tmp_path / "confidence.log"
    config = {
        "alerts": {"log_path": str(log_path)},
        "winner_hints": {"notify": True, "confidence_log_path": str(conf_path)},
    }

    with patch("game_analyzer.alerts.deliver_winner_hint_alert") as deliver:
        result = evaluate_game_start_forecast(store, config, "100")
        assert result is not None
        assert result.tier == "NONE"
        deliver.assert_not_called()


def test_forecast_alert_already_sent(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    log_path.write_text(
        "2026-09-01T00:00:00+00:00  [WINNER-HINT] Game 555 — next winner likely 2 — history 70% (MEDIUM)\n",
        encoding="utf-8",
    )
    assert forecast_alert_already_sent(log_path, "555") is True
    assert forecast_alert_already_sent(log_path, "556") is False
