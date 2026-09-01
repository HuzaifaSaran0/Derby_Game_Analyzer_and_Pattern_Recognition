"""Tests for alert logging (winner hints + legacy similarity rows)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from game_analyzer.alerts import (
    AlertSettings,
    deliver_push_notifications,
    deliver_similarity_alert,
    deliver_winner_hint_alert,
    is_modern_winner_hint_message,
    parse_alert_log_line,
    post_discord_webhook,
    post_telegram_message,
    post_webhook,
    push_channels_configured,
    read_recent_alerts,
    winner_hint_already_logged,
)

_MODERN_MSG = (
    "[WINNER-HINT] Game 9 — next winner likely 3 — history 67% (MEDIUM) — "
    "Last 4 (3 2 4 2) 3 cases → 3 (2/3, 67%) · link=/forecasts?game=9"
)
_LEGACY_MSG = (
    "[WINNER-HINT] Game 9 — next winner likely 3 — "
    "Last 4 (3 2 4 2) 3 cases → 3 (2/3, 67%) · link=/"
)


def test_parse_twin_alert_extracts_link():
    line = (
        "2026-08-27T12:00:00+00:00  [TWIN-R3] Game 1 — 2 past game(s) match R3 draws "
        "[9S, 8H, 7C] · winners: Diamonds×2 · link=/similar?stage=r3&ids=20,21&live=1"
    )
    parsed = parse_alert_log_line(line)
    assert parsed is not None
    assert parsed["kind"] == "twin-r3"
    assert parsed["link"] == "/similar?stage=r3&ids=20,21&live=1"


def test_read_recent_alerts_skips_legacy_bet_rows(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-08-27T10:00:00+00:00  [BET] — Game 1 — Pick Spades — Confidence HIGH — 80%",
                "2026-08-27T11:00:00+00:00  [CANCEL] — Game 1 — Pick Spades — Confidence LOW — 40%",
                "2026-08-27T12:00:00+00:00  [TWIN-R3] Game 9 — 1 past game(s) match R3 draws "
                "· link=/similar?stage=r3&ids=1",
                "2026-08-27T13:00:00+00:00  [UPGRADE] — Game 2 — Pick Hearts — Confidence MEDIUM — 60%",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recent = read_recent_alerts(log_path, limit=5, similarity_only=True)
    assert len(recent) == 1
    assert recent[0]["kind"] == "twin-r3"
    # Default feed keeps similarity + winner-hint rows only (skips legacy BET/CANCEL/UPGRADE).
    all_rows = read_recent_alerts(log_path, limit=10, similarity_only=False, winner_hint_only=False)
    assert len(all_rows) == 1
    assert all_rows[0]["kind"] == "twin-r3"


def test_is_modern_winner_hint_message():
    assert is_modern_winner_hint_message(_MODERN_MSG)
    assert not is_modern_winner_hint_message(_LEGACY_MSG)
    assert not is_modern_winner_hint_message(
        "[WINNER-HINT] Game 9 — history 67% (LOW) · link=/forecasts?game=9"
    )


def test_read_recent_alerts_skips_legacy_winner_hint_rows(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    log_path.write_text(
        "\n".join(
            [
                "2026-08-27T10:00:00+00:00  " + _LEGACY_MSG,
                "2026-08-27T11:00:00+00:00  " + _MODERN_MSG,
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    recent = read_recent_alerts(log_path, limit=5, winner_hint_only=True)
    assert len(recent) == 1
    assert "/forecasts?game=9" in recent[0]["message"]


def test_deliver_winner_hint_alert_writes_log(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    settings = AlertSettings(log_path=log_path)
    deliver_winner_hint_alert(settings, alert_message=_MODERN_MSG)
    recent = read_recent_alerts(log_path, limit=5, winner_hint_only=True)
    assert recent
    assert recent[0]["kind"] == "winner-hint"
    assert "next winner likely 3" in recent[0]["message"]


def test_winner_hint_already_logged(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    settings = AlertSettings(log_path=log_path)
    deliver_winner_hint_alert(settings, alert_message=_MODERN_MSG, dedupe_key="9:next=3:4:3 2 4 2")
    assert winner_hint_already_logged(log_path, "9:next=3:4:3 2 4 2")
    assert not winner_hint_already_logged(log_path, "9:next=4:4:3 2 4 2")


def test_deliver_winner_hint_alert_skips_duplicate(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    settings = AlertSettings(log_path=log_path)
    key = "9:next=3:4:3 2 4 2"
    assert deliver_winner_hint_alert(settings, alert_message=_MODERN_MSG, dedupe_key=key) is True
    assert deliver_winner_hint_alert(settings, alert_message=_MODERN_MSG, dedupe_key=key) is False
    assert len(read_recent_alerts(log_path, limit=5, winner_hint_only=True)) == 1


def test_push_channels_configured():
    assert not push_channels_configured(AlertSettings())
    assert push_channels_configured(AlertSettings(webhook_url="https://hooks.slack.com/x"))
    assert push_channels_configured(
        AlertSettings(telegram_bot_token="123:abc", telegram_chat_id="999")
    )


@patch("game_analyzer.alerts._post_json")
def test_deliver_push_notifications_all_channels(mock_post: MagicMock):
    settings = AlertSettings(
        webhook_url="https://hooks.slack.com/slack",
        discord_webhook_url="https://discord.com/api/webhooks/x",
        telegram_bot_token="123:abc",
        telegram_chat_id="999",
    )
    errors = deliver_push_notifications(settings, "Hello forecast")
    assert errors == []
    assert mock_post.call_count == 3
    slack_url, slack_payload = mock_post.call_args_list[0][0]
    assert slack_payload == {"text": "Hello forecast"}
    discord_url, discord_payload = mock_post.call_args_list[1][0]
    assert discord_payload == {"content": "Hello forecast"}
    tg_url, tg_payload = mock_post.call_args_list[2][0]
    assert "sendMessage" in tg_url
    assert tg_payload["chat_id"] == "999"
    assert tg_payload["text"] == "Hello forecast"


@patch("game_analyzer.alerts.deliver_push_notifications", return_value=[])
def test_deliver_winner_hint_alert_sends_push_message(mock_push: MagicMock, tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    settings = AlertSettings(
        log_path=log_path,
        webhook_url="https://hooks.slack.com/slack",
    )
    push_text = "Strong forecast — HIGH confidence\nGame #9"
    deliver_winner_hint_alert(
        settings,
        alert_message=_MODERN_MSG,
        push_message=push_text,
    )
    mock_push.assert_called_once_with(settings, push_text)


@patch("game_analyzer.alerts._post_json")
def test_post_helpers(mock_post: MagicMock):
    post_webhook("https://hooks.slack.com/x", "msg")
    post_discord_webhook("https://discord.com/x", "msg")
    post_telegram_message("tok", "42", "msg")
    assert mock_post.call_count == 3
