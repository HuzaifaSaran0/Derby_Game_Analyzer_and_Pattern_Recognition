"""Tests for combined live winner confidence."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.winner_hints import (
    HintRow,
    LiveConfidence,
    _historical_confidence_pct,
    append_confidence_log,
    build_confidence_log_entry,
    compute_live_confidence,
    confidence_already_logged,
    enrich_with_game_outcome,
    live_confidence_payload,
    live_winner_hints,
    notifiable_winner_hint_groups,
    NOTIFY_TIERS,
    outcome_payload_for_pick,
    read_confidence_log,
    resolve_confidence_log_outcome,
    backfill_confidence_log_outcomes,
)

PNG = b"x"

PNG = b"x"


def test_historical_confidence_pct_single_pattern():
    from game_analyzer.winner_hints import WinnerHintAlertPattern

    patterns = [
        WinnerHintAlertPattern(
            length=4, tail_text="1 3 4 4", match_count=3, next_code=1, next_count=2, next_pct=67
        )
    ]
    assert _historical_confidence_pct(patterns) == 67


def test_compute_live_confidence_single_pattern_uses_history_rate():
    rows = [
        HintRow(length=4, tail=(1, 3, 4, 4), match_count=3, follow_up_counts={1: 2, 2: 1, 3: 0, 4: 0}),
    ]
    conf = compute_live_confidence(rows)
    assert conf.pick == 1
    assert conf.confidence_pct == 67
    assert conf.tier == "MEDIUM"


def test_compute_live_confidence_none_when_no_trusted_rows():
    rows = [
        HintRow(length=4, tail=(4, 3, 2, 3), match_count=2, follow_up_counts={1: 1, 2: 0, 3: 1, 4: 0}),
        HintRow(length=5, tail=(4, 4, 3, 2, 3), match_count=1, follow_up_counts={1: 0, 2: 0, 3: 1, 4: 0}),
    ]
    conf = compute_live_confidence(rows)
    assert conf.tier == "NONE"
    assert conf.pick is None


def test_compute_live_confidence_medium_when_two_patterns_agree():
    rows = [
        HintRow(length=4, tail=(4, 2, 3, 2), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 2}),
        HintRow(length=5, tail=(2, 4, 2, 3, 2), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 2}),
        HintRow(length=6, tail=(3, 2, 4, 2, 3, 2), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 2}),
    ]
    conf = compute_live_confidence(rows)
    assert conf.pick == 4
    assert conf.tier == "MEDIUM"
    assert conf.tier in NOTIFY_TIERS
    assert len(conf.supporting_patterns) == 3
    assert conf.confidence_pct == 100


def test_compute_live_confidence_high_requires_stronger_sample():
    rows = [
        HintRow(length=4, tail=(4, 2, 3, 2), match_count=3, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 3}),
        HintRow(length=5, tail=(2, 4, 2, 3, 2), match_count=3, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 3}),
    ]
    conf = compute_live_confidence(rows)
    assert conf.tier == "HIGH"


def test_notifiable_only_for_medium_or_high():
    low_rows = [
        HintRow(length=4, tail=(4, 2, 3, 2), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 2}),
    ]
    assert notifiable_winner_hint_groups(low_rows) == {}

    medium_rows = [
        HintRow(length=4, tail=(4, 2, 3, 2), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 2}),
        HintRow(length=5, tail=(2, 4, 2, 3, 2), match_count=2, follow_up_counts={1: 0, 2: 0, 3: 0, 4: 2}),
    ]
    groups = notifiable_winner_hint_groups(medium_rows)
    assert 4 in groups
    assert len(groups[4]) == 2


def test_live_winner_hints_includes_confidence_block(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    pattern = [Suit.DIAMONDS, Suit.HEARTS, Suit.CLUBS, Suit.HEARTS]
    for i in range(1, 15):
        winner = pattern[(i - 1) % len(pattern)]
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"game_{i}",
                seq=1,
                phase=GamePhase.DEALT,
                reason="test",
                should_save=True,
                game_id=str(i),
                table_cards=(("Spades", ("AS",)),),
            ),
            ExtractionResult(
                race_state=RaceState.BETTING,
                winner_suit=None,
                high_low=None,
                confident=False,
                draw_cards=(),
                handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
            ),
            shot,
            now,
        )
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"game_{i}",
                seq=2,
                phase=GamePhase.FINISHED,
                reason="test",
                should_save=True,
                game_id=str(i),
                table_cards=(("Spades", ("AS",)),),
            ),
            ExtractionResult(
                race_state=RaceState.FINISHED,
                winner_suit=winner,
                high_low=None,
                confident=True,
                draw_cards=(),
                handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
            ),
            shot,
            now,
        )

    hints = live_winner_hints(store)
    assert "confidence" in hints
    assert hints["confidence"]["tier"] in {"NONE", "LOW", "MEDIUM", "HIGH"}
    assert "summary" in hints["confidence"]


def test_confidence_log_round_trip(tmp_path: Path):
    log_path = tmp_path / "winner_confidence.log"
    entry = build_confidence_log_entry(
        game_id="105",
        confidence=LiveConfidence(
            pick=3,
            confidence_pct=72,
            tier="MEDIUM",
            supporting_patterns=(),
            total_cases=5,
            has_conflict=False,
        ),
        rows=[],
        notified=True,
    )
    append_confidence_log(log_path, entry)
    assert confidence_already_logged(log_path, "105")
    assert not confidence_already_logged(log_path, "999")
    rows = read_confidence_log(log_path, limit=10)
    assert rows[0]["game_id"] == "105"
    assert rows[0]["tier"] == "MEDIUM"


def test_live_confidence_payload_summary():
    payload = live_confidence_payload(
        LiveConfidence(
            pick=4,
            confidence_pct=100,
            tier="MEDIUM",
            supporting_patterns=(),
            total_cases=4,
            has_conflict=False,
        )
    )
    assert payload["pick"] == 4
    assert "Diamonds" in payload["summary"]
    assert "MEDIUM" in payload["summary"]
    assert payload["tier"] == "MEDIUM"
    assert "100% from history" not in payload["summary"]


def test_live_confidence_payload_low_avoids_misleading_pct():
    payload = live_confidence_payload(
        LiveConfidence(
            pick=4,
            confidence_pct=100,
            tier="LOW",
            supporting_patterns=(),
            total_cases=2,
            has_conflict=False,
        )
    )
    assert "No strong forecast" in payload["summary"]
    assert "100%" not in payload["summary"]
    assert "Diamonds" in payload["summary"]


def test_notify_tiers_constant():
    assert NOTIFY_TIERS == frozenset({"MEDIUM", "HIGH"})


def test_resolve_confidence_log_outcome(tmp_path: Path):
    log_path = tmp_path / "winner_confidence.log"
    entry = build_confidence_log_entry(
        game_id="105",
        confidence=LiveConfidence(
            pick=4,
            confidence_pct=100,
            tier="MEDIUM",
            supporting_patterns=(),
            total_cases=4,
            has_conflict=False,
        ),
        rows=[],
        notified=True,
    )
    append_confidence_log(log_path, entry)
    assert resolve_confidence_log_outcome(log_path, "105", "Diamonds")
    rows = read_confidence_log(log_path, limit=5)
    assert rows[0]["actual_winner"] == 4
    assert rows[0]["pick_correct"] is True


def test_backfill_confidence_log_outcomes(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    store.record(
        SessionDecision(
            recording=True,
            session_id="game_105",
            seq=1,
            phase=GamePhase.FINISHED,
            reason="test",
            should_save=True,
            game_id="105",
            table_cards=(("Spades", ("AS",)),),
        ),
        ExtractionResult(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.CLUBS,
            high_low=None,
            confident=True,
            draw_cards=(),
            handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
        ),
        shot,
        now,
    )
    log_path = tmp_path / "winner_confidence.log"
    append_confidence_log(
        log_path,
        build_confidence_log_entry(
            game_id="105",
            confidence=LiveConfidence(
                pick=4,
                confidence_pct=100,
                tier="MEDIUM",
                supporting_patterns=(),
                total_cases=4,
                has_conflict=False,
            ),
            rows=[],
            notified=True,
        ),
    )
    assert backfill_confidence_log_outcomes(log_path, store) == 1
    rows = read_confidence_log(log_path, limit=5)
    assert rows[0]["actual_winner"] == 3
    assert rows[0]["pick_correct"] is False


def test_enrich_with_game_outcome(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    store.record(
        SessionDecision(
            recording=True,
            session_id="game_105",
            seq=1,
            phase=GamePhase.FINISHED,
            reason="test",
            should_save=True,
            game_id="105",
            table_cards=(("Spades", ("AS",)),),
        ),
        ExtractionResult(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.CLUBS,
            high_low=None,
            confident=True,
            draw_cards=(),
            handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
        ),
        shot,
        now,
    )
    item = enrich_with_game_outcome({"game_id": "105", "next_winner": "4"}, store)
    assert item["actual_winner"] == 3
    assert item["pick_correct"] is False
    assert "Clubs" in item["outcome_text"]


def test_outcome_payload_for_pick():
    payload = outcome_payload_for_pick(predicted_pick=4, actual_code=3)
    assert payload["pick_correct"] is False
    assert "predicted Diamonds" in payload["outcome_text"]
