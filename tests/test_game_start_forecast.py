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
    # Repeating 6-suit block so lengths 6–10 find clear historical matches.
    pattern = [
        Suit.CLUBS,
        Suit.HEARTS,
        Suit.DIAMONDS,
        Suit.HEARTS,
        Suit.SPADES,
        Suit.HEARTS,
    ]
    for i in range(1, 25):
        winner = pattern[(i - 1) % len(pattern)]
        _record_winner(store, str(i), winner, shot, now)


def test_evaluate_game_start_forecast_notifies_once(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    # Clear streak history: many 3× Clubs → Diamonds, live ends on 3× Clubs.
    codes = []
    for _ in range(6):
        codes.extend([Suit.CLUBS, Suit.CLUBS, Suit.CLUBS, Suit.DIAMONDS])
    codes.extend([Suit.CLUBS, Suit.CLUBS, Suit.CLUBS])
    for i, winner in enumerate(codes, start=1):
        _record_winner(store, str(i), winner, shot, now)

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
        assert deliver.call_args.kwargs["dedupe_key"] == "game-start-streak:999"
        assert "streak" in deliver.call_args.kwargs["alert_message"]
        assert "Game 999" in deliver.call_args.kwargs["alert_message"]


def test_evaluate_game_start_forecast_no_slack_for_sequence_only(tmp_path: Path):
    """Sequence MEDIUM/HIGH must not Slack — only same-winner streaks notify."""
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
        result = evaluate_game_start_forecast(store, config, "888")
        assert result is not None
        # Trailing Hearts streak length 1 in _seed_history → no streak alert.
        streak_calls = [
            c for c in deliver.call_args_list if "streak" in str(c.kwargs.get("dedupe_key", ""))
        ]
        sequence_calls = [
            c for c in deliver.call_args_list if c.kwargs.get("dedupe_key") == "game-start:888"
        ]
        assert sequence_calls == []
        # No trailing same-winner streak of ≥2 in this seed → no Slack.
        assert streak_calls == []
        deliver.assert_not_called()


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
        "2026-09-01T00:00:00+00:00  [WINNER-HINT] Game 555 — next winner likely 2 — history 70% (MEDIUM)\n"
        "2026-09-01T00:01:00+00:00  [WINNER-HINT] Game 555 — streak 3×4 — next winner likely 1 — history 80% (HIGH)\n",
        encoding="utf-8",
    )
    assert forecast_alert_already_sent(log_path, "555") is True
    assert forecast_alert_already_sent(log_path, "555", streak=True) is True
    assert forecast_alert_already_sent(log_path, "556") is False
    assert forecast_alert_already_sent(log_path, "556", streak=True) is False


def test_reconcile_forecasts_with_alerts_patches_stale_log(tmp_path: Path):
    from game_analyzer.winner_hints import reconcile_forecasts_with_alerts

    alerts_path = tmp_path / "alerts.log"
    alerts_path.write_text(
        "2026-09-02T01:55:00+00:00  [WINNER-HINT] Game 105438221 — next winner likely 4 — "
        "history 67% (MEDIUM) — Last 4 (3 2 4 2) 3 cases → 4 (2/3, 67%) · link=/forecasts?game=105438221\n",
        encoding="utf-8",
    )
    stale = [
        {
            "at": "2026-09-02T01:54:00+00:00",
            "game_id": "105438221",
            "pick": None,
            "tier": "NONE",
            "notified": False,
        }
    ]
    merged = reconcile_forecasts_with_alerts(stale, alerts_path)
    assert len(merged) == 1
    row = merged[0]
    assert row["game_id"] == "105438221"
    assert row["pick"] == 4
    assert row["tier"] == "MEDIUM"
    assert row["notified"] is True
