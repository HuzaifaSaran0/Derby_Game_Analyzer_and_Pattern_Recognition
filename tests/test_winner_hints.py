"""Tests for live winner-sequence hints."""

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.web import create_app
from game_analyzer.winner_hints import (
    analyze_tail,
    live_winner_hints,
    live_winner_hints_if_in_progress,
    parse_pattern_codes,
    search_pattern,
    search_winner_pattern,
    winner_code,
)

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"


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
        table_cards=(("Spades", ("AS", "2S")),),
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


def test_winner_code_maps_suits():
    assert winner_code("CLUBS") == 3
    assert winner_code("Hearts") == 2
    assert winner_code(None) is None


def test_analyze_tail_counts_historical_follow_ups():
    follow_ups = [4, 2, 4, 2, 4, 4, 4, 3, 1, 2]
    codes: list[int] = []
    for f in follow_ups:
        codes.extend([3, 2, 4, 2, f, 9])
    codes.extend([3, 2, 4, 2])

    row = analyze_tail(codes, 4)
    assert row is not None
    assert row.tail == (3, 2, 4, 2)
    assert row.match_count == 10
    assert row.follow_up_counts[4] == 5
    assert row.follow_up_counts[2] == 3
    assert row.follow_up_counts[3] == 1
    assert row.follow_up_counts[1] == 1
    from game_analyzer.winner_hints import _row_summary

    summary = _row_summary(row)
    assert "10 past cases" in summary
    assert "♦" in summary


def test_analyze_tail_no_match():
    row = analyze_tail([1, 2, 3, 4, 1, 2, 3, 5], 4)
    assert row is not None
    assert row.match_count == 0
    assert sum(row.follow_up_counts.values()) == 0


def test_analyze_tail_single_match_still_reported():
    row = analyze_tail([3, 2, 4, 2, 1, 9, 9, 3, 2, 4, 2], 4)
    assert row is not None
    assert row.match_count == 1
    assert row.follow_up_counts[1] == 1


def test_live_winner_hints_needs_minimum_finished_games(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    _record_winner(store, "1", Suit.SPADES, shot, now)
    _record_winner(store, "2", Suit.HEARTS, shot, now)
    store.record(_decision(game_id="3", session_id="game_3", seq=1), _result(), shot, now)

    hints = live_winner_hints(store)
    assert hints["finished_games"] == 2
    assert hints["rows"] == []
    assert "Need at least 4 finished games" in hints["lead_summary"]


def test_live_winner_hints_if_in_progress_only(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    assert live_winner_hints_if_in_progress(store, in_progress=False) is None


def test_api_live_winner_hints_in_progress_only(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)

    for i, winner in enumerate(
        [Suit.CLUBS, Suit.HEARTS, Suit.DIAMONDS, Suit.HEARTS] * 3,
        start=1,
    ):
        _record_winner(store, str(i), winner, shot, now)

    store.record(
        _decision(game_id="13", session_id="game_13", seq=1),
        _result(),
        shot,
        now,
    )

    client = TestClient(create_app(store, auth_enabled=False))
    live = client.get("/api/live").json()
    assert live["in_progress"] is True
    assert live["winner_hints"] is not None
    assert "rows" in live["winner_hints"]
    assert live["winner_hints"]["finished_games"] == 12

    store.record(
        _decision(
            game_id="13",
            session_id="game_13",
            seq=2,
            phase=GamePhase.FINISHED,
        ),
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.SPADES),
        shot,
        now,
    )
    finished = client.get("/api/live").json()
    assert finished["in_progress"] is False
    assert finished["winner_hints"] is None


def test_live_page_includes_winner_hints_panel(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    client = TestClient(create_app(store, auth_enabled=False))
    page = client.get("/")
    assert "Winner history hints" in page.text
    assert "data-winner-hints-panel" in page.text
    assert "Search winner pattern" in page.text
    assert "data-winner-search-panel" in page.text


def test_parse_pattern_codes():
    assert parse_pattern_codes("3,2,4,2", 4) == [3, 2, 4, 2]
    assert parse_pattern_codes("3,2,4", 4) is None
    assert parse_pattern_codes("3,2,9,2", 4) is None
    assert parse_pattern_codes("bad", 4) is None


def test_search_pattern_manual_tail():
    follow_ups = [4, 2, 4, 2, 4, 4, 4, 3, 1, 2]
    codes: list[int] = []
    for f in follow_ups:
        codes.extend([3, 2, 4, 2, f, 9])
    row = search_pattern(codes, (3, 2, 4, 2))
    assert row.match_count == 10
    assert row.follow_up_counts[4] == 5


def test_search_winner_pattern_api(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)

    for i, winner in enumerate(
        [Suit.CLUBS, Suit.HEARTS, Suit.DIAMONDS, Suit.HEARTS] * 3,
        start=1,
    ):
        _record_winner(store, str(i), winner, shot, now)

    client = TestClient(create_app(store, auth_enabled=False))
    resp = client.get("/api/winner-hints/search?length=4&pattern=3,2,4,2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["pattern"] == [3, 2, 4, 2]
    assert "result" in data
    assert data["finished_games"] == 12

    bad = client.get("/api/winner-hints/search?length=4&pattern=3,2,9,2")
    assert bad.status_code == 400
