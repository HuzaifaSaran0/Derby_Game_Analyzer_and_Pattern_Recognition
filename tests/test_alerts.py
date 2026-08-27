"""Tests for similarity alert logging (late-round twin delivery)."""

from __future__ import annotations

from pathlib import Path

from game_analyzer.alerts import (
    AlertSettings,
    deliver_similarity_alert,
    parse_alert_log_line,
    read_recent_alerts,
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
    recent = read_recent_alerts(log_path, limit=5)
    assert len(recent) == 1
    assert recent[0]["kind"] == "twin-r3"
    all_rows = read_recent_alerts(log_path, limit=10, similarity_only=False)
    assert len(all_rows) == 4


def test_deliver_similarity_alert_writes_log(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    settings = AlertSettings(log_path=log_path)
    deliver_similarity_alert(
        settings,
        alert_kind="twin-r3",
        alert_message="[TWIN-R3] Game 9 — 1 past game(s) match R3 draws · link=/similar?stage=r3&ids=1",
    )
    recent = read_recent_alerts(log_path, limit=5)
    assert recent
    assert recent[0]["kind"] == "twin-r3"
    assert "link=" in recent[0]["message"]
