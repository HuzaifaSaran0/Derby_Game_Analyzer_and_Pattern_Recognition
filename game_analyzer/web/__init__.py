from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from game_analyzer.alerts import (
    alert_settings_from_config,
    read_recent_alerts,
)
from game_analyzer.config import load_config
from game_analyzer.confidence import evaluate_confidence, format_confidence_text
from game_analyzer.confidence_stats import format_round_snapshot
from game_analyzer.race_values import pre_race_outcome, race_snapshot
from game_analyzer.similarity import (
    NEAR_SHARED_MIN,
    cluster_badge_kind,
    cluster_kind_badge,
    format_cluster_headline,
)
from game_analyzer.store import GameStore
from game_analyzer.web.cards import (
    SUIT_STYLES,
    card_display,
    fingerprint_payload,
    styled_table_rows,
)

WEB_DIR = Path(__file__).resolve().parent
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
STATIC_VER = "17"


def _neighbors(game_ids: list[str], game_id: str) -> tuple[str | None, str | None]:
    if game_id not in game_ids:
        return None, None
    i = game_ids.index(game_id)
    prev_id = game_ids[i - 1] if i > 0 else None
    next_id = game_ids[i + 1] if i + 1 < len(game_ids) else None
    return prev_id, next_id


def _winner_label(winner_suit: str | None) -> str:
    return winner_suit.title() if winner_suit else "none yet"


def _win_chance_rows(game) -> list[dict]:
    if not game.handicap_cards:
        return []
    draws = game.guess_draw_cards or game.draw_cards
    snap = race_snapshot(game.handicap_cards, draws)
    favourite = game.guess_suit if game.guess_suit else (snap.guess if snap.guess_ready else None)
    preview = snap.preview
    rows = []

    def pct(value: float | None) -> str:
        return f"{value * 100:.0f}%" if value is not None else "?"

    for suit_name in ("Spades", "Hearts", "Clubs", "Diamonds"):
        style = SUIT_STYLES[suit_name]
        deck = snap.deck_remaining.get(suit_name)
        if deck is None:
            rows.append(
                {
                    "suit": suit_name,
                    "symbol": style["symbol"],
                    "color": style["color"],
                    "text": "?",
                    "highlight": False,
                    "preview": False,
                }
            )
            continue
        deck_p = snap.deck_pct.get(suit_name)
        track_p = snap.track_pct.get(suit_name)
        expected_p = snap.expected_pct.get(suit_name)
        combo_p = snap.combo_pct.get(suit_name)
        combined = snap.combined_score.get(suit_name)
        is_best = suit_name == favourite or (
            favourite is None and snap.draw_rounds_used == 0 and suit_name == preview
        )
        is_preview = favourite is None and suit_name == preview and snap.draw_rounds_used > 0
        if snap.draw_rounds_used == 0:
            text = f"score {pct(combined)}  ·  deck {pct(deck_p)}"
        elif favourite:
            text = (
                f"score {pct(combined)}  ·  "
                f"deck {pct(deck_p)}  ·  track {pct(track_p)}  ·  "
                f"finish {pct(expected_p)}  ·  combo {pct(combo_p)}"
            )
        else:
            text = (
                f"score {pct(combined)}  ·  "
                f"deck {pct(deck_p)}  ·  track {pct(track_p)}  ·  "
                f"finish {pct(expected_p)}"
            )
        rows.append(
            {
                "suit": suit_name,
                "symbol": style["symbol"],
                "color": style["color"],
                "text": text,
                "highlight": bool(is_best and favourite),
                "preview": bool(is_preview),
            }
        )
    return rows


def _win_chance_note(game) -> str:
    if not game.handicap_cards:
        return "Handicap not visible yet."
    draws = game.guess_draw_cards or game.draw_cards
    snap = race_snapshot(game.handicap_cards, draws)
    favourite = game.guess_suit if game.guess_suit else (snap.guess if snap.guess_ready else None)
    preview = snap.preview
    rounds = len(game.guess_draw_cards) // 3 if game.guess_draw_cards else snap.draw_rounds_used
    if favourite:
        if snap.layer4_weights:
            tw, fw, cw, sw = (int(w * 100) for w in snap.layer4_weights)
            return (
                f"Locked guess: {favourite} after {rounds} rounds "
                f"({tw}% track + {fw}% future + {cw}% combo + {sw}% pool)"
            )
        dw = int(snap.deck_weight * 100)
        tw = int(snap.track_weight * 100)
        return f"Best chance: {favourite} ({dw}% future deck + {tw}% track)"
    if snap.draw_rounds_used == 1 and preview:
        return f"Round 1/2 — preview leader {preview}. Need round 2 to lock guess."
    if preview:
        return f"Preview leader: {preview} (not locked yet)"
    return "Waiting for draw rounds."


def _confidence_for_game(game) -> dict:
    draws = game.guess_draw_cards or game.draw_cards
    if not game.handicap_cards or not draws:
        return {"ready": False, "text": "—", "level": None, "pct": None}
    conf = evaluate_confidence(
        game.handicap_cards,
        draws,
        pick=game.guess_suit,
        simulations=600,
    )
    return {
        "ready": conf.ready,
        "text": format_confidence_text(conf),
        "level": conf.level.value if conf.ready else None,
        "pct": conf.confidence_pct,
        "pick": conf.pick,
        "track_gap": conf.track_gap,
        "mc_pick": conf.mc_pick,
        "rivals_weak": conf.rivals_weak_count,
    }


def _guess_text(game) -> str:
    outcome = pre_race_outcome(
        game.winner_suit,
        game.handicap_cards,
        game.guess_draw_cards,
        locked_guess=game.guess_suit,
        locked_draw_rounds=len(game.guess_draw_cards) // 3 if game.guess_draw_cards else 0,
    )
    winner = game.winner_suit.title() if game.winner_suit else "none yet"
    if not outcome.guess_ready:
        if outcome.draw_rounds_used:
            return (
                f"— (only {outcome.draw_rounds_used}/2 draw rounds readable — "
                f"need 6 cards)"
            )
        return "— (no draw rounds saved yet)"
    if outcome.guess is None:
        return "— (cards not fully readable)"
    guess = outcome.guess.title()
    rounds = outcome.draw_rounds_used or 2
    if outcome.winner is None:
        return f"{guess} (after {rounds} draw rounds) — waiting for winner"
    if outcome.correct:
        return f"{guess}  ✓ correct (winner: {winner})"
    return f"{guess}  ✗ wrong (winner: {winner})"


def _game_payload(store: GameStore, game_id: str, *, include_frames: bool = True) -> dict | None:
    game = store.get_game(game_id)
    if game is None:
        return None
    # History browses finished games only; live/game detail may still include in-progress.
    ids = store.list_game_ids(finished_only=True)
    if game.winner_suit and game_id in ids:
        prev_id, next_id = _neighbors(ids, game_id)
        latest_id = ids[-1] if ids else None
        index = ids.index(game_id) + 1
        total = len(ids)
    else:
        all_ids = [g["game_id"] for g in store.list_games(newest_first=False)]
        prev_id, next_id = _neighbors(all_ids, game_id)
        latest_id = all_ids[-1] if all_ids else None
        index = all_ids.index(game_id) + 1 if game_id in all_ids else 0
        total = len(all_ids)
    snap2, snap3 = store.confidence_snapshots_for(game_id, simulations=400)
    latest_frame = game.frames[-1] if game.frames else None
    frames = [
        {
            "seq": frame.seq,
            "phase": frame.phase,
            "captured_at": frame.captured_at,
            "url": f"/shot/{game.game_id}/{frame.seq}?t={frame.captured_at}",
        }
        for frame in game.frames
    ]
    return {
        "game_id": game.game_id,
        "winner": _winner_label(game.winner_suit),
        "winner_suit": game.winner_suit,
        "guess": game.guess_suit,
        "guess_text": _guess_text(game),
        "started_at": game.started_at,
        "finished_at": game.finished_at,
        "table": styled_table_rows(game.table_cards),
        "win_chance": _win_chance_rows(game),
        "win_chance_note": _win_chance_note(game),
        "confidence": _confidence_for_game(game),
        "confidence_r2": format_round_snapshot(snap2),
        "confidence_r3": format_round_snapshot(snap3),
        "draw_note": (
            f"draws saved {len(game.draw_cards)} total"
            f" · locked guess uses {len(game.guess_draw_cards)}"
            f" ({len(game.guess_draw_cards) // 3} rounds)"
        ),
        "shot_count": len(frames),
        "frames": frames if include_frames else [],
        "preview_url": (
            f"/shot/{game.game_id}/{latest_frame.seq}?t={latest_frame.captured_at}"
            if latest_frame and include_frames
            else None
        ),
        "prev_id": prev_id,
        "next_id": next_id,
        "latest_id": latest_id,
        "index": index,
        "total": total,
        "in_progress": game.winner_suit is None,
    }


def _stats_payload(store: GameStore) -> dict:
    guess = store.pre_race_guess_accuracy()
    report = store.confidence_accuracy_report(simulations=200)
    return {
        "guess": {
            "correct": guess.correct,
            "total": guess.total,
            "percent": guess.percent,
            "text": (
                f"Accuracy  {guess.correct}/{guess.total}  ({guess.percent:.0f}%)"
                if guess.total
                else "Accuracy  —  no scored games yet"
            ),
        },
        "confidence_text": report.format_summary(),
    }


def _alerts_payload(*, limit: int = 10) -> dict:
    settings = alert_settings_from_config(load_config())
    recent = read_recent_alerts(settings.log_path, limit=limit)
    return {
        "enabled": settings.enabled,
        "min_level": settings.min_level.value,
        "latest": recent[0] if recent else None,
        "recent": recent,
    }


def _similar_payload(store: GameStore, *, exact_only: bool = False) -> dict:
    corpus = store.similarity_corpus()
    clusters = store.similarity_clusters(exact_only=exact_only)
    exact_n = sum(1 for c in clusters if c.exact)
    near_n = sum(1 for c in clusters if not c.exact)
    games = {g.game_id for c in clusters for g in c.games}
    near_same_n = sum(1 for c in clusters if not c.exact and c.winners_same)
    near_mixed_n = sum(1 for c in clusters if not c.exact and c.winners_same is False)
    return {
        "corpus_n": len(corpus),
        "cluster_count": len(clusters),
        "exact_n": exact_n,
        "near_n": near_n,
        "near_same_n": near_same_n,
        "near_mixed_n": near_mixed_n,
        "near_shared_min": NEAR_SHARED_MIN,
        "games_shown": len(games),
        "clusters": [
            {
                "headline": format_cluster_headline(c),
                "badge": cluster_kind_badge(c),
                "badge_kind": cluster_badge_kind(c),
                "key": c.key,
                "exact": c.exact,
                "stage": c.stage.value,
                "match_pct": c.match_pct,
                "size": c.size,
                "winners_same": c.winners_same,
                "winner_counts": list(c.winner_counts),
                "majority_winner": c.majority_winner,
                "agreement_pct": c.agreement_pct,
                "games": [fingerprint_payload(g) for g in c.games],
                "game_ids": [g.game_id for g in c.games],
            }
            for c in clusters
        ],
    }


def create_app(store: GameStore | None = None) -> FastAPI:
    store = store or GameStore()
    app = FastAPI(title="Game Analyzer")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    def _ctx(request: Request, **extra):
        return {"request": request, "static_ver": STATIC_VER, **extra}

    def live_games() -> JSONResponse:
        games = store.list_games()
        return JSONResponse({"games": games}, headers=NO_CACHE)

    def live_game(game_id: str) -> JSONResponse:
        payload = _game_payload(store, game_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Game not found")
        return JSONResponse(payload, headers=NO_CACHE)

    @app.get("/", response_class=HTMLResponse)
    def live_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="live.html",
            context=_ctx(request, active="live"),
        )

    @app.get("/games")
    def games_page():
        # All-games list removed — History covers browsing saved games.
        return RedirectResponse(url="/history", status_code=302)

    @app.get("/history", response_class=HTMLResponse)
    def history_page(request: Request):
        ids = store.list_game_ids(finished_only=True)
        start_id = ids[-1] if ids else None
        return templates.TemplateResponse(
            request=request,
            name="history.html",
            context=_ctx(request, active="history", start_id=start_id),
        )

    @app.get("/similar", response_class=HTMLResponse)
    def similar_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="similar.html",
            context=_ctx(request, active="similar"),
        )

    @app.get("/games.json")
    def games_json():
        return live_games()

    @app.get("/api/stats")
    def api_stats():
        return JSONResponse(_stats_payload(store), headers=NO_CACHE)

    @app.get("/api/live")
    def api_live():
        games = store.list_games()
        alerts = _alerts_payload(limit=5)
        if not games:
            return JSONResponse(
                {"ready": False, "stats": _stats_payload(store), "alerts": alerts},
                headers=NO_CACHE,
            )
        latest_id = games[0]["game_id"]
        payload = _game_payload(store, latest_id)
        if payload is None:
            return JSONResponse(
                {"ready": False, "stats": _stats_payload(store), "alerts": alerts},
                headers=NO_CACHE,
            )
        payload["ready"] = True
        payload["stats"] = _stats_payload(store)
        payload["alerts"] = alerts
        return JSONResponse(payload, headers=NO_CACHE)

    @app.get("/api/alerts")
    def api_alerts(limit: int = Query(10, ge=1, le=50)):
        return JSONResponse(_alerts_payload(limit=limit), headers=NO_CACHE)

    @app.get("/api/similar")
    def api_similar(exact_only: bool = Query(False)):
        return JSONResponse(_similar_payload(store, exact_only=exact_only), headers=NO_CACHE)

    @app.get("/api/history/{game_id}")
    def api_history(game_id: str):
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="Game not found")
        if not game.winner_suit:
            raise HTTPException(status_code=404, detail="Unfinished game — not in History")
        # Skip frame URLs so Prev/Next stays fast; shots load on demand.
        payload = _game_payload(store, game_id, include_frames=False)
        if payload is None:
            raise HTTPException(status_code=404, detail="Game not found")
        payload["stats"] = _stats_payload(store)
        return JSONResponse(payload, headers=NO_CACHE)

    @app.get("/api/history/{game_id}/shots")
    def api_history_shots(game_id: str):
        payload = _game_payload(store, game_id, include_frames=True)
        if payload is None:
            raise HTTPException(status_code=404, detail="Game not found")
        return JSONResponse(
            {
                "game_id": payload["game_id"],
                "shot_count": payload["shot_count"],
                "frames": payload["frames"],
            },
            headers=NO_CACHE,
        )

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
        payload = _game_payload(store, game_id)
        return templates.TemplateResponse(
            request=request,
            name="game.html",
            context=_ctx(request, active="history", game=payload),
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
