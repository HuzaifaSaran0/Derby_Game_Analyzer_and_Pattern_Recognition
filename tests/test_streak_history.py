"""Last-50 winner history retrospective + pagination."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.winner_hints import last_streak_games_report

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


def test_last_streak_games_report_marks_matches(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 9, 9, 12, 0, 0)

    # Seed several 3× Clubs → Diamonds, then another 3× Clubs → Hearts as the "current" outcome.
    codes = []
    for _ in range(4):
        codes.extend([Suit.CLUBS, Suit.CLUBS, Suit.CLUBS, Suit.DIAMONDS])
    codes.extend([Suit.CLUBS, Suit.CLUBS, Suit.CLUBS, Suit.HEARTS])
    for i, winner in enumerate(codes, start=1):
        _record_winner(store, str(1000 + i), winner, shot, now)

    report = last_streak_games_report(store, limit=50)
    assert report["total"] == len(codes)
    assert report["matched"] >= 1
    assert report["offset"] == 0
    assert report["has_newer"] is False
    # Newest row should be Hearts after 3× Clubs with a history match.
    newest = report["items"][0]
    assert newest["actual_winner"] == 2  # Hearts
    assert newest["matched"] is True
    assert newest["streak_length"] == 3
    assert newest["streak_suit"] == 3  # Clubs
    assert newest["history_best_next"] == 4  # Diamonds favored historically
    assert newest["history_pick_correct"] is False


def test_last_streak_games_report_paginates_older(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 9, 9, 12, 0, 0)

    for i in range(1, 61):
        suit = [Suit.SPADES, Suit.HEARTS, Suit.CLUBS, Suit.DIAMONDS][(i - 1) % 4]
        _record_winner(store, str(i), suit, shot, now)

    page0 = last_streak_games_report(store, limit=50, offset=0)
    assert page0["total_games"] == 60
    assert page0["total"] == 50
    assert page0["has_older"] is True
    assert page0["has_newer"] is False
    assert page0["items"][0]["game_id"] == "60"  # newest first
    assert page0["items"][-1]["game_id"] == "11"

    page1 = last_streak_games_report(store, limit=50, offset=50)
    assert page1["total"] == 10
    assert page1["has_older"] is False
    assert page1["has_newer"] is True
    assert page1["items"][0]["game_id"] == "10"
    assert page1["items"][-1]["game_id"] == "1"
