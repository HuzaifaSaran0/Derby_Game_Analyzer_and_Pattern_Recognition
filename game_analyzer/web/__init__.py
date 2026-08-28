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
from game_analyzer.similarity import NEAR_SHARED_MIN, draw_round_cards
from game_analyzer.store import GameStore
from game_analyzer.web.cards import (
    late_round_game_payload,
    styled_cards,
    styled_table_rows,
)

WEB_DIR = Path(__file__).resolve().parent
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
STATIC_VER = "25"


def _neighbors(game_ids: list[str], game_id: str) -> tuple[str | None, str | None]:
    if game_id not in game_ids:
        return None, None
    i = game_ids.index(game_id)
    prev_id = game_ids[i - 1] if i > 0 else None
    next_id = game_ids[i + 1] if i + 1 < len(game_ids) else None
    return prev_id, next_id


def _winner_label(winner_suit: str | None) -> str:
    return winner_suit.title() if winner_suit else "none yet"


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
        "started_at": game.started_at,
        "finished_at": game.finished_at,
        "table": styled_table_rows(game.table_cards),
        "draw_note": f"draws saved {len(game.draw_cards)} total",
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
    finished = len(store.list_game_ids(finished_only=True))
    late = store.late_round_stats()
    bits: list[str] = []
    for stage in late:
        label = f"R{stage.round_n}"
        if not stage.twin_sets:
            bits.append(f"{label} twins —")
            continue
        if stage.same_winner_pct is not None:
            bits.append(
                f"{label} twins {stage.twin_sets} · same-winner {stage.same_winner_pct:.0f}%"
            )
        else:
            bits.append(f"{label} twins {stage.twin_sets}")
    return {
        "finished_games": finished,
        "late_round_text": " · ".join(bits) if bits else "Late-round twins —",
        "late_round_stats": [
            {
                "stage": s.stage,
                "round_n": s.round_n,
                "twin_sets": s.twin_sets,
                "games_in_sets": s.games_in_sets,
                "same_winner_sets": s.same_winner_sets,
                "same_winner_pct": s.same_winner_pct,
                "mean_agreement_pct": s.mean_agreement_pct,
            }
            for s in late
        ],
    }


def _alerts_payload(*, limit: int = 10) -> dict:
    settings = alert_settings_from_config(load_config())
    recent = read_recent_alerts(settings.log_path, limit=limit, similarity_only=True)
    return {
        "enabled": True,
        "mode": "similarity",
        "latest": recent[0] if recent else None,
        "recent": recent,
    }


def _similar_payload(store: GameStore, *, exact_only: bool = False) -> dict:
    """Similar page: late-round (R3/R4/R5) twin sets only."""
    del exact_only  # kept for URL compat; handicap near/exact browse removed
    corpus = store.similarity_corpus()
    twin_sets = store.late_round_twin_sets()
    late_stats_raw = store.late_round_stats()
    late_stats = [
        {
            "stage": s.stage,
            "round_n": s.round_n,
            "twin_sets": s.twin_sets,
            "games_in_sets": s.games_in_sets,
            "same_winner_sets": s.same_winner_sets,
            "same_winner_pct": s.same_winner_pct,
            "mean_agreement_pct": s.mean_agreement_pct,
        }
        for s in late_stats_raw
    ]
    # Headline counts must match the accuracy cards (same late_round_stats source).
    r3 = next((s for s in late_stats_raw if s.round_n == 3), None)
    games = {g.game_id for s in twin_sets for g in s.games}
    return {
        "corpus_n": len(corpus),
        "cluster_count": len(twin_sets),
        "exact_n": len(twin_sets),
        "near_n": 0,
        "near_same_n": 0,
        "near_mixed_n": 0,
        "near_shared_min": NEAR_SHARED_MIN,
        "games_shown": len(games),
        "r3_twin_sets": r3.twin_sets if r3 else 0,
        "r3_games": r3.games_in_sets if r3 else 0,
        "mode": "late_rounds",
        "late_round_stats": late_stats,
        "clusters": [
            {
                "headline": (
                    f"{s.stage} exact · {s.size} games"
                    + (
                        f" · {s.agreement_pct:.0f}% agree on {s.majority_winner}"
                        if s.agreement_pct is not None and s.majority_winner
                        else ""
                    )
                ),
                "badge": s.stage,
                "badge_kind": "exact",
                "key": s.key,
                "exact": True,
                "stage": s.stage,
                "round_n": s.round_n,
                "matched_rounds": list(s.matched_rounds),
                "match_pct": 100.0,
                "size": s.size,
                "winners_same": s.winners_same,
                "winner_counts": list(s.winner_counts),
                "majority_winner": s.majority_winner,
                "agreement_pct": s.agreement_pct,
                "round_cards": [
                    {
                        "round_n": rn,
                        "cards": styled_cards(cards),
                        "codes": list(cards),
                    }
                    for rn, cards in s.round_cards
                ],
                "games": [
                    late_round_game_payload(
                        g,
                        matched_rounds=s.matched_rounds,
                        round_cards=s.round_cards,
                    )
                    for g in s.games
                ],
                "game_ids": [g.game_id for g in s.games],
            }
            for s in twin_sets
        ],
    }


def _late_round_focus_payload(
    store: GameStore,
    *,
    round_n: int,
    game_ids: list[str],
    live_game_id: str | None = None,
) -> dict:
    """Alert deep-link: handicap + cascade-matched rounds (R3…Rn) only."""
    from game_analyzer.similarity import LATE_ROUND_MIN, build_fingerprint

    matched_rounds = tuple(range(LATE_ROUND_MIN, round_n + 1))
    corpus = {fp.game_id: fp for fp in store.similarity_corpus()}
    games = []
    winners: dict[str, int] = {}
    live_round_cards: list[str] = []
    shared_round_cards: list[tuple[int, tuple[str, ...]]] = []
    for gid in game_ids:
        fp = corpus.get(gid)
        if fp is None:
            game = store.get_game(gid)
            if game is None:
                continue
            fp = build_fingerprint(
                game.game_id,
                game.handicap_cards,
                game.draw_cards or game.guess_draw_cards,
                winner_suit=game.winner_suit,
            )
        if fp is None:
            continue
        if not shared_round_cards:
            for rn in matched_rounds:
                cards = draw_round_cards(fp.draw_cards, rn)
                if cards is None:
                    shared_round_cards = []
                    break
                shared_round_cards.append((rn, cards))
        round_cards = tuple(shared_round_cards) if shared_round_cards else ()
        if not round_cards:
            # Fall back to per-game extraction if sample incomplete.
            built: list[tuple[int, tuple[str, ...]]] = []
            for rn in matched_rounds:
                cards = draw_round_cards(fp.draw_cards, rn)
                if cards is None:
                    built = []
                    break
                built.append((rn, cards))
            round_cards = tuple(built)
        payload = late_round_game_payload(
            fp,
            matched_rounds=matched_rounds,
            round_cards=round_cards,
        )
        payload["round_n"] = round_n
        stage_cards = draw_round_cards(fp.draw_cards, round_n)
        payload["round_cards"] = list(stage_cards) if stage_cards else []
        games.append(payload)
        if fp.winner_suit:
            winners[fp.winner_suit.title()] = winners.get(fp.winner_suit.title(), 0) + 1
    if live_game_id:
        live = store.get_game(live_game_id)
        if live is not None:
            cards = draw_round_cards(live.draw_cards or live.guess_draw_cards, round_n)
            live_round_cards = list(cards) if cards else []
    winner_counts = sorted(winners.items(), key=lambda row: (-row[1], row[0]))
    total = sum(winners.values())
    majority = winner_counts[0][0] if winner_counts else None
    agreement = (
        round(100.0 * winner_counts[0][1] / total, 1) if total and winner_counts else None
    )
    return {
        "ready": bool(games),
        "stage": f"r{round_n}",
        "round_n": round_n,
        "matched_rounds": list(matched_rounds),
        "live_game_id": live_game_id,
        "live_round_cards": live_round_cards,
        "round_cards": [
            {
                "round_n": rn,
                "cards": styled_cards(cards),
                "codes": list(cards),
            }
            for rn, cards in shared_round_cards
        ],
        "games": games,
        "game_ids": [g["game_id"] for g in games],
        "winner_counts": winner_counts,
        "majority_winner": majority,
        "agreement_pct": agreement,
        "match_count": len(games),
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

    @app.get("/api/similar/late")
    def api_similar_late(
        stage: str = Query("r3"),
        ids: str = Query(""),
        live: str | None = Query(None),
    ):
        stage_clean = stage.strip().lower().lstrip("r")
        try:
            round_n = int(stage_clean)
        except ValueError:
            raise HTTPException(status_code=400, detail="stage must be r3, r4, or r5")
        if round_n not in {3, 4, 5}:
            raise HTTPException(status_code=400, detail="stage must be r3, r4, or r5")
        game_ids = [g.strip() for g in ids.split(",") if g.strip()]
        payload = _late_round_focus_payload(
            store,
            round_n=round_n,
            game_ids=game_ids,
            live_game_id=live,
        )
        return JSONResponse(payload, headers=NO_CACHE)

    @app.get("/api/similar/late-stats")
    def api_similar_late_stats():
        rows = [
            {
                "stage": s.stage,
                "round_n": s.round_n,
                "twin_sets": s.twin_sets,
                "games_in_sets": s.games_in_sets,
                "same_winner_sets": s.same_winner_sets,
                "same_winner_pct": s.same_winner_pct,
                "mean_agreement_pct": s.mean_agreement_pct,
            }
            for s in store.late_round_stats()
        ]
        return JSONResponse({"stages": rows}, headers=NO_CACHE)

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
