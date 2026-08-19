from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from game_analyzer.store import GameStore

WEB_DIR = Path(__file__).resolve().parent
SUIT_STYLES = {
    "Spades": {"symbol": "♠", "color": "#31c96b"},
    "Hearts": {"symbol": "♥", "color": "#ff5a67"},
    "Clubs": {"symbol": "♣", "color": "#58a6ff"},
    "Diamonds": {"symbol": "♦", "color": "#f2c94c"},
}
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _neighbors(game_ids: list[str], game_id: str) -> tuple[str | None, str | None]:
    if game_id not in game_ids:
        return None, None
    i = game_ids.index(game_id)
    prev_id = game_ids[i - 1] if i > 0 else None
    next_id = game_ids[i + 1] if i + 1 < len(game_ids) else None
    return prev_id, next_id


def _styled_table(raw) -> list[dict]:
    rows = []
    for item in raw or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        name, cards = item[0], item[1]
        style = SUIT_STYLES.get(str(name), {"symbol": "•", "color": "#ddd"})
        rows.append(
            {
                "name": name,
                "symbol": style["symbol"],
                "color": style["color"],
                "cards": list(cards),
            }
        )
    return rows


def _winner_label(winner_suit: str | None) -> str:
    return winner_suit.title() if winner_suit else "none yet"


def _game_payload(store: GameStore, game_id: str) -> dict | None:
    game = store.get_game(game_id)
    if game is None:
        return None
    ids = [g["game_id"] for g in store.list_games(newest_first=False)]
    prev_id, next_id = _neighbors(ids, game_id)
    latest_id = ids[-1] if ids else None
    return {
        "game_id": game.game_id,
        "winner": _winner_label(game.winner_suit),
        "winner_suit": game.winner_suit,
        "started_at": game.started_at,
        "finished_at": game.finished_at,
        "table": _styled_table(game.table_cards),
        "frames": [
            {
                "seq": frame.seq,
                "phase": frame.phase,
                "captured_at": frame.captured_at,
                "url": f"/shot/{game.game_id}/{frame.seq}?t={frame.captured_at}",
            }
            for frame in game.frames
        ],
        "prev_id": prev_id,
        "next_id": next_id,
        "latest_id": latest_id,
        "index": ids.index(game_id) + 1 if game_id in ids else 0,
        "total": len(ids),
    }


def create_app(store: GameStore | None = None) -> FastAPI:
    store = store or GameStore()
    app = FastAPI(title="Game Analyzer")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    def live_games() -> JSONResponse:
        games = store.list_games()
        return JSONResponse({"games": games}, headers=NO_CACHE)

    def live_game(game_id: str) -> JSONResponse:
        payload = _game_payload(store, game_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Game not found")
        return JSONResponse(payload, headers=NO_CACHE)

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request):
        games = store.list_games()
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={"games": games},
        )

    @app.get("/games.json")
    def games_json():
        return live_games()

    @app.get("/game/{game_id}/live")
    def game_live(game_id: str):
        return live_game(game_id)

    @app.get("/game/{game_id}", response_class=HTMLResponse)
    def game_page(request: Request, game_id: str):
        accept = request.headers.get("accept", "").split(",")[0].strip()
        if accept.startswith("application/json"):
            return live_game(game_id)
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")
        ids = [g["game_id"] for g in store.list_games(newest_first=False)]
        prev_id, next_id = _neighbors(ids, game_id)
        latest_id = ids[-1] if ids else None
        return templates.TemplateResponse(
            request=request,
            name="game.html",
            context={
                "game": game,
                "table": _styled_table(game.table_cards),
                "prev_id": prev_id,
                "next_id": next_id,
                "latest_id": latest_id,
                "index": ids.index(game_id) + 1 if game_id in ids else 0,
                "total": len(ids),
                "winner": _winner_label(game.winner_suit),
            },
        )

    @app.get("/shot/{game_id}/{seq}")
    def shot(game_id: str, seq: int):
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404)
        for frame in game.frames:
            if frame.seq == seq:
                path = frame.screenshot_path.resolve()
                if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
                    raise HTTPException(status_code=404)
                return FileResponse(path)
        raise HTTPException(status_code=404)

    @app.get("/api/games")
    def api_games():
        return live_games()

    @app.get("/api/game/{game_id}")
    def api_game(game_id: str):
        return live_game(game_id)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.middleware("http")
    async def disable_cache(request: Request, call_next):
        response = await call_next(request)
        for key, value in NO_CACHE.items():
            response.headers[key] = value
        return response

    return app


app = create_app()


def main() -> None:
    print("Game Analyzer web: http://0.0.0.0:8000")
    print("Stop any old server first (Ctrl+C), or it will keep 404ing /api/game.")
    uvicorn.run("game_analyzer.web:app", host="0.0.0.0", port=8000, reload=False)
