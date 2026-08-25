from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.web import create_app

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


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
        table_cards=(("Spades", ("AS", "2S")), ("Hearts", ("4H",))),
    )
    defaults.update(kwargs)
    return SessionDecision(**defaults)


def _client(tmp_path: Path) -> TestClient:
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    store.record(_decision(), _result(), shot, now)
    store.record(
        _decision(
            seq=2,
            phase=GamePhase.FINISHED,
            game_id="100",
            table_cards=(("Spades", ("AS", "2S", "KS")), ("Hearts", ("4H",))),
        ),
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.CLUBS),
        shot,
        now,
    )
    store.record(
        _decision(game_id="99", session_id="game_99", seq=1),
        _result(),
        shot,
        now,
    )
    return TestClient(create_app(store))


def test_home_lists_games(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/history")
    assert response.status_code == 200
    assert "History" in response.text
    assert "All games" not in response.text


def test_live_page(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/")
    assert response.status_code == 200
    assert "Win chance" in response.text
    assert "/static/dashboard.js" in response.text
    assert "All games" not in response.text


def test_home_empty(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    response = TestClient(create_app(store), follow_redirects=False).get("/games")
    assert response.status_code in {302, 307}
    assert response.headers.get("location") == "/history"


def test_game_page_shows_table_and_shots(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/game/100")
    assert response.status_code == 200
    assert "Card table" in response.text
    assert "Screenshots" in response.text
    assert "Winner:" in response.text
    assert "Clubs" in response.text
    assert "/shot/100/1" in response.text
    assert "♠" in response.text
    assert "data-carousel" in response.text
    assert 'id="lightbox"' in response.text
    assert "/static/game.js" in response.text
    assert "/static/live.js" in response.text
    assert "data-game-id" in response.text
    assert "/static/home.js" not in response.text


def test_home_includes_live_script(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/history")
    assert "/static/history-page.js" in response.text
    assert "/static/live.js" in response.text
    assert "/static/cards.js" in response.text
    assert "data-live-status" in response.text
    assert "All games" not in response.text


def test_similar_and_stats_api(tmp_path: Path):
    client = _client(tmp_path)
    stats = client.get("/api/stats").json()
    assert "guess" in stats
    assert "confidence_text" in stats
    similar = client.get("/api/similar").json()
    assert "corpus_n" in similar
    assert "clusters" in similar
    page = client.get("/similar")
    assert page.status_code == 200
    assert "Similar" in page.text
    history = client.get("/history")
    assert history.status_code == 200
    hist = client.get("/api/history/100").json()
    assert hist["game_id"] == "100"
    assert hist["shot_count"] >= 1
    assert hist["frames"] == []
    shots = client.get("/api/history/100/shots").json()
    assert len(shots["frames"]) >= 1
    assert shots["frames"][0]["url"].startswith("/shot/100/")


def test_api_games_and_game_payload(tmp_path: Path):
    client = _client(tmp_path)
    games = client.get("/api/games").json()["games"]
    ids = [g["game_id"] for g in games]
    assert ids == ["99", "100"]
    payload = client.get("/api/game/100").json()
    assert payload["winner"] == "Clubs"
    assert client.get("/game/100/live").json()["game_id"] == "100"
    assert client.get("/games.json").json()["games"][0]["game_id"] in {"99", "100"}
    json_from_html = client.get("/game/100", headers={"Accept": "application/json"}).json()
    assert json_from_html["winner"] == "Clubs"
    assert payload["frames"][0]["seq"] == 1
    assert payload["frames"][0]["url"].startswith("/shot/100/1")
    assert payload["table"][0]["name"] == "Spades"
    assert payload["table"][0]["cards"][0]["code"] == "AS"
    assert payload["table"][0]["cards"][0]["rank"] == "A"
    assert payload["table"][0]["cards"][0]["symbol"] == "♠"
    live = client.get("/api/live").json()
    assert live.get("ready") is True
    assert live["game_id"] == games[0]["game_id"]


def test_api_picks_up_new_screenshot(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot = tmp_path / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    store.record(_decision(), _result(), shot, now)
    client = TestClient(create_app(store))
    assert len(client.get("/api/game/100").json()["frames"]) == 1
    store.record(
        _decision(seq=2, phase=GamePhase.IN_PLAY, table_cards=(("Spades", ("AS", "2S", "KS")),)),
        _result(),
        shot,
        now,
    )
    payload = client.get("/api/game/100").json()
    assert len(payload["frames"]) == 2
    assert payload["frames"][1]["seq"] == 2


def test_api_is_not_cached(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/api/games")
    assert "no-store" in response.headers.get("cache-control", "")
    scripts = client.get("/static/live.js")
    assert scripts.status_code == 200
    assert b"ngrok-skip-browser-warning" in scripts.content


def test_shot_is_served(tmp_path: Path):
    client = _client(tmp_path)
    response = client.get("/shot/100/1")
    assert response.status_code == 200
    assert response.content.startswith(b"\x89PNG")


def test_missing_game_is_404(tmp_path: Path):
    client = _client(tmp_path)
    assert client.get("/game/missing").status_code == 404
    assert client.get("/shot/missing/1").status_code == 404
