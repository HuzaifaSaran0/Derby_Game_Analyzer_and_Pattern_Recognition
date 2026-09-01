"""Live winner-hint alert delivery during in-progress games."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.winner_hints import (
    HintRow,
    compute_live_confidence,
    dedupe_winner_hint_items,
    format_winner_hint_alert_message,
    format_winner_hint_push_message,
    notifiable_winner_hint_groups,
    notification_item_from_alert,
    NOTIFY_TIERS,
    winner_hint_dedupe_key,
    winner_hint_headline,
)

PNG = b"x"


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
        table_cards=(("Spades", ("AS",)),),
    )
    defaults.update(kwargs)
    return SessionDecision(**defaults)


def _record_winner(store: GameStore, game_id: str, winner: Suit, shot: Path, now: datetime) -> None:
    store.record(_decision(game_id=game_id, session_id=f"game_{game_id}", seq=1), _result(), shot, now)
    store.record(
        _decision(
            game_id=game_id,
            session_id=f"game_{game_id}",
            seq=2,
            phase=GamePhase.FINISHED,
        ),
        _result(race_state=RaceState.FINISHED, winner_suit=winner),
        shot,
        now,
    )


def test_notifiable_groups_when_multiple_lengths_agree():
    rows = [
        HintRow(length=4, tail=(3, 2, 4, 2), match_count=3, follow_up_counts={1: 0, 2: 0, 3: 3, 4: 0}),
        HintRow(length=5, tail=(3, 2, 4, 2, 4), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 2, 4: 0}),
    ]
    groups = notifiable_winner_hint_groups(rows, min_matches=2, min_pct=50)
    assert 3 in groups
    assert len(groups[3]) == 2
    conf = compute_live_confidence(rows, min_matches=2, min_pct=50)
    assert conf.tier in NOTIFY_TIERS


def test_format_and_parse_winner_hint_alert_message():
    from game_analyzer.winner_hints import WinnerHintAlertPattern

    patterns = [
        WinnerHintAlertPattern(
            length=4,
            tail_text="3 2 4 2",
            match_count=3,
            next_code=3,
            next_count=2,
            next_pct=67,
        )
    ]
    message = format_winner_hint_alert_message("105", patterns, confidence_pct=67, tier="MEDIUM")
    assert "[WINNER-HINT]" in message
    assert "next winner likely 3" in message
    assert "history 67% (MEDIUM)" in message
    entry = {
        "id": "1",
        "at": "2026-08-30T12:00:00+00:00",
        "kind": "winner-hint",
        "message": message,
        "link": "/",
    }
    item = notification_item_from_alert(entry)
    assert item["next_winner"] == "3"
    assert item["patterns"][0]["length"] == 4
    assert item["confidence_pct"] == 67
    assert item["tier"] == "MEDIUM"
    assert item["confidence_note"]
    assert item["dedupe_key"].startswith("105:next=3:")
    assert item["link"] == "/forecasts?game=105"


def test_format_winner_hint_push_message():
    from game_analyzer.winner_hints import WinnerHintAlertPattern

    patterns = [
        WinnerHintAlertPattern(
            length=4,
            tail_text="3 2 4 2",
            match_count=3,
            next_code=3,
            next_count=2,
            next_pct=67,
        )
    ]
    text = format_winner_hint_push_message(
        "105",
        patterns,
        confidence_pct=67,
        tier="HIGH",
        public_base_url="https://my-vps.example.com",
    )
    assert "Strong forecast" in text
    assert "Game #105" in text
    assert "Likely next winner: 3" in text
    assert "67%" in text
    assert "https://my-vps.example.com/forecasts?game=105" in text


def test_dedupe_winner_hint_items_keeps_newest():
    base = {
        "kind": "winner-hint",
        "game_id": "99",
        "next_winner": "4",
        "dedupe_key": "99:next=4:4:4 2 3 2",
        "patterns": [{"length": 4, "tail": "4 2 3 2", "match_count": 2, "next_code": 4, "next_pct": 100}],
    }
    items = dedupe_winner_hint_items(
        [
            {**base, "id": "new", "at": "2026-08-30T17:56:16+00:00"},
            {**base, "id": "old", "at": "2026-08-30T17:55:29+00:00"},
        ]
    )
    assert len(items) == 1
    assert items[0]["id"] == "new"


def test_winner_hint_headline_multiple_patterns():
    from game_analyzer.winner_hints import WinnerHintAlertPattern

    patterns = [
        WinnerHintAlertPattern(length=4, tail_text="4 2 3 2", match_count=2, next_code=4, next_count=2, next_pct=100),
        WinnerHintAlertPattern(length=5, tail_text="2 4 2 3 2", match_count=2, next_code=4, next_count=2, next_pct=100),
    ]
    assert winner_hint_headline(patterns) == "Diamonds (4) — 2 patterns"
    assert winner_hint_dedupe_key("13", patterns) == "13:next=4:4:4 2 3 2|5:2 4 2 3 2"
