"""Same-winner streak forecasts (2–7 consecutive identical suits)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.winner_hints import (
    NOTIFY_TIERS,
    analyze_suit_streak,
    compute_streak_confidence,
    current_winner_streak,
    evaluate_game_start_forecast,
    format_streak_hint_alert_message,
)

PNG = b"x"


def test_current_winner_streak_longest_only():
    assert current_winner_streak([1, 2, 3]) is None
    assert current_winner_streak([4, 4]) == (4, 2)
    assert current_winner_streak([1, 4, 4, 4]) == (4, 3)
    assert current_winner_streak([4, 4, 4, 4, 4, 4, 4, 4]) == (4, 7)


def test_analyze_suit_streak_suit_specific():
    # Two historical 3× Diamonds (4) runs, next was Hearts (2) both times.
    history = [1, 4, 4, 4, 2, 3, 4, 4, 4, 2, 4, 4, 4]
    row = analyze_suit_streak(history, suit_code=4, length=3)
    assert row is not None
    assert row.match_count == 2
    assert row.follow_up_counts[2] == 2
    assert row.follow_up_counts[4] == 0


def test_compute_streak_confidence_none_without_streak():
    conf, row = compute_streak_confidence([1, 2, 3, 4, 1, 2])
    assert row is None
    assert conf.tier == "NONE"
    assert conf.pick is None


def test_compute_streak_confidence_medium_when_clear():
    # Trailing streak of three Spades (1). History: many 1,1,1 → 2.
    history = []
    for _ in range(5):
        history.extend([1, 1, 1, 2])
    history.extend([1, 1, 1])  # live trailing streak
    conf, row = compute_streak_confidence(history)
    assert row is not None
    assert row.length == 3
    assert row.tail == (1, 1, 1)
    assert conf.pick == 2
    assert conf.tier in NOTIFY_TIERS


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


def test_game_start_notifies_streak_only(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 9, 8, 12, 0, 0)

    # Build history with clear streak signal: many 3× Clubs → Diamonds, end on 3× Clubs.
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
        result = evaluate_game_start_forecast(store, config, "live-1")
        assert result is not None
        assert deliver.call_count == 1
        assert deliver.call_args.kwargs["dedupe_key"] == "game-start-streak:live-1"
        assert "streak" in deliver.call_args.kwargs["alert_message"]
        assert not any(
            c.kwargs.get("dedupe_key") == "game-start:live-1" for c in deliver.call_args_list
        )


def test_format_streak_hint_alert_message():
    from game_analyzer.winner_hints import WinnerHintAlertPattern

    text = format_streak_hint_alert_message(
        "42",
        [
            WinnerHintAlertPattern(
                length=3,
                tail_text="4 4 4",
                match_count=5,
                next_code=2,
                next_count=4,
                next_pct=80,
            )
        ],
        confidence_pct=80,
        tier="MEDIUM",
    )
    assert "streak 3×4 (Diamonds)" in text
    assert "next winner likely 2 (Hearts)" in text
    assert "5 similar streaks" in text
    assert "/forecasts?game=42" in text


def test_streak_should_notify_length_rules():
    from game_analyzer.winner_hints import (
        HintRow,
        LiveConfidence,
        WinnerHintAlertPattern,
        streak_should_notify,
    )

    pattern = WinnerHintAlertPattern(
        length=3, tail_text="1 1 1", match_count=4, next_code=2, next_count=3, next_pct=75
    )
    conf = LiveConfidence(
        pick=2,
        confidence_pct=75,
        tier="MEDIUM",
        supporting_patterns=(pattern,),
        total_cases=4,
        has_conflict=False,
    )
    row3 = HintRow(length=3, tail=(1, 1, 1), match_count=4, follow_up_counts={1: 0, 2: 3, 3: 1, 4: 0})
    assert streak_should_notify(conf, row3) is True

    row2 = HintRow(length=2, tail=(1, 1), match_count=3, follow_up_counts={1: 0, 2: 3, 3: 0, 4: 0})
    pattern2 = WinnerHintAlertPattern(
        length=2, tail_text="1 1", match_count=3, next_code=2, next_count=3, next_pct=100
    )
    conf2 = LiveConfidence(
        pick=2,
        confidence_pct=100,
        tier="MEDIUM",
        supporting_patterns=(pattern2,),
        total_cases=3,
        has_conflict=False,
    )
    assert streak_should_notify(conf2, row2) is False  # length 2 needs ≥5 cases

    row2b = HintRow(length=2, tail=(1, 1), match_count=5, follow_up_counts={1: 0, 2: 5, 3: 0, 4: 0})
    pattern2b = WinnerHintAlertPattern(
        length=2, tail_text="1 1", match_count=5, next_code=2, next_count=5, next_pct=100
    )
    conf2b = LiveConfidence(
        pick=2,
        confidence_pct=100,
        tier="MEDIUM",
        supporting_patterns=(pattern2b,),
        total_cases=5,
        has_conflict=False,
    )
    assert streak_should_notify(conf2b, row2b) is True


def test_compute_streak_accuracy(tmp_path: Path):
    from game_analyzer.winner_hints import append_confidence_log, compute_streak_accuracy

    path = tmp_path / "confidence.log"
    append_confidence_log(
        path,
        {
            "game_id": "1",
            "pick": 2,
            "tier": "MEDIUM",
            "notified": True,
            "streak": {
                "pick": 2,
                "tier": "MEDIUM",
                "notified": True,
                "actual_winner": 2,
                "pick_correct": True,
            },
            "actual_winner": 2,
        },
    )
    append_confidence_log(
        path,
        {
            "game_id": "2",
            "pick": 4,
            "tier": "HIGH",
            "notified": True,
            "streak": {
                "pick": 4,
                "tier": "HIGH",
                "notified": True,
                "actual_winner": 1,
                "pick_correct": False,
            },
            "actual_winner": 1,
        },
    )
    append_confidence_log(
        path,
        {
            "game_id": "3",
            "pick": 3,
            "tier": "MEDIUM",
            "streak": {"pick": 3, "tier": "MEDIUM", "notified": True},
        },
    )
    stats = compute_streak_accuracy(path)
    assert stats["resolved"] == 2
    assert stats["correct"] == 1
    assert stats["wrong"] == 1
    assert stats["accuracy_pct"] == 50
