from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.background import BackgroundTask
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from urllib.parse import quote, urlencode

from game_analyzer.alerts import (
    alert_settings_from_config,
    read_recent_alerts,
)
from game_analyzer.config import load_config
from game_analyzer.data_transfer import (
    MAX_IMPORT_BYTES,
    build_export_zip,
    data_summary,
    export_filename,
    import_from_zip,
)
from game_analyzer.similarity import NEAR_SHARED_MIN, draw_round_cards, friendly_late_round_summary
from game_analyzer.store import GameStore
from game_analyzer.web.auth import (
    SESSION_USERNAME_KEY,
    authenticate,
    change_password,
    load_auth_record,
    session_secret,
)
from game_analyzer.web.session import SignedCookieSessionMiddleware
from game_analyzer.web.cards import (
    draw_round_label,
    friendly_cards_text,
    late_round_game_payload,
    styled_cards,
    styled_table_rows,
    winner_display,
)

WEB_DIR = Path(__file__).resolve().parent
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}
STATIC_VER = "32"


def _is_public_path(path: str, method: str) -> bool:
    if path.startswith("/static/"):
        return True
    if path == "/login":
        return True
    if path == "/logout" and method == "POST":
        return True
    return False


def _session_username(request: Request) -> str | None:
    user = request.session.get(SESSION_USERNAME_KEY)
    return user if user else None


def _safe_next_url(next_url: str | None) -> str:
    if not next_url or not next_url.startswith("/") or next_url.startswith("//"):
        return "/"
    if next_url.startswith("/login"):
        return "/"
    return next_url


def _form_value(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key) or [""]
    return str(values[0] if values else "")


async def _read_form(request: Request) -> dict[str, str]:
    body = await request.body()
    if not body:
        return {}
    from urllib.parse import parse_qs

    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: _form_value(parsed, key) for key in parsed}


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
    return {
        "finished_games": finished,
        "late_round_text": friendly_late_round_summary(late),
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


def _twin_set_payload(twin_set) -> dict:
    return {
        "headline": (
            f"{twin_set.stage} exact · {twin_set.size} games"
            + (
                f" · {twin_set.agreement_pct:.0f}% agree on {twin_set.majority_winner}"
                if twin_set.agreement_pct is not None and twin_set.majority_winner
                else ""
            )
        ),
        "badge": twin_set.stage,
        "badge_kind": "exact",
        "key": twin_set.key,
        "exact": True,
        "stage": twin_set.stage,
        "round_n": twin_set.round_n,
        "matched_rounds": list(twin_set.matched_rounds),
        "match_pct": 100.0,
        "size": twin_set.size,
        "winners_same": twin_set.winners_same,
        "winner_counts": list(twin_set.winner_counts),
        "majority_winner": twin_set.majority_winner,
        "agreement_pct": twin_set.agreement_pct,
        "trust": twin_set.trust,
        "trust_notes": list(twin_set.trust_notes),
        "round_cards": [
            {
                "round_n": rn,
                "label": draw_round_label(rn),
                "cards": styled_cards(cards),
                "codes": list(cards),
            }
            for rn, cards in twin_set.round_cards
        ],
        "games": [
            late_round_game_payload(g, matched_rounds=twin_set.matched_rounds)
            for g in twin_set.games
        ],
        "game_ids": [g.game_id for g in twin_set.games],
    }


def _notifications_payload(store: GameStore) -> dict:
    """R3 twin sets as notification items (read/unread tracked client-side)."""
    twin_sets, excluded = store.late_round_twin_sets_partitioned()
    finished_at: dict[str, str | None] = {}
    with store._connect(autocommit=True) as con:
        for row in con.execute("SELECT game_id, finished_at FROM games").fetchall():
            finished_at[row["game_id"]] = row["finished_at"]

    items: list[dict] = []
    for twin_set in twin_sets:
        if twin_set.stage != "R3":
            continue
        r3_cards = next((list(cards) for rn, cards in twin_set.round_cards if rn == 3), [])
        game_ids = [g.game_id for g in twin_set.games]
        cards_text = friendly_cards_text(r3_cards)
        game_rows = []
        for g in twin_set.games:
            w = winner_display(g.winner_suit)
            game_rows.append(
                {
                    "game_id": g.game_id,
                    "winner": w["name"],
                    "winner_symbol": w["symbol"],
                    "winner_color": w["color"],
                    "winner_label": w["label"],
                }
            )
        stamps = [finished_at.get(gid) for gid in game_ids if finished_at.get(gid)]
        at = max(stamps) if stamps else None
        n = twin_set.size
        if twin_set.winners_same and twin_set.majority_winner:
            majority = winner_display(twin_set.majority_winner)
            winner_note = f"Same winner — {majority['label']}"
            verdict = "same"
        elif twin_set.winners_same is False:
            winner_note = "Different winners"
            verdict = "different"
        else:
            winner_note = "Winner comparison unavailable"
            verdict = "unknown"

        items.append(
            {
                "id": twin_set.key,
                "kind": "twin-r3",
                "at": at,
                "title": f"{n} games drew the same cards in round 3",
                "cards_text": cards_text,
                "link": f"/similar?set={quote(twin_set.key, safe='')}",
                "game_ids": game_ids,
                "games": game_rows,
                "winners_same": twin_set.winners_same,
                "winner_note": winner_note,
                "verdict": verdict,
                "trust": twin_set.trust,
                "size": n,
            }
        )

    items.sort(key=lambda row: row.get("at") or "", reverse=True)
    return {
        "items": items,
        "total": len(items),
        "excluded_weak": len([s for s in excluded if s.stage == "R3"]),
    }


def _similar_payload(store: GameStore, *, exact_only: bool = False) -> dict:
    """Similar page: late-round (R3/R4/R5) twin sets only."""
    del exact_only  # kept for URL compat; handicap near/exact browse removed
    corpus = store.similarity_corpus()
    twin_sets, excluded = store.late_round_twin_sets_partitioned()
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
    verified_n = sum(1 for s in twin_sets if s.trust == "verified")
    fallback_n = sum(1 for s in twin_sets if s.trust == "fallback")
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
        "trusted_sets": len(twin_sets),
        "verified_sets": verified_n,
        "fallback_sets": fallback_n,
        "excluded_weak_sets": len(excluded),
        "mode": "late_rounds",
        "late_round_stats": late_stats,
        "clusters": [_twin_set_payload(s) for s in twin_sets],
        "excluded_clusters": [_twin_set_payload(s) for s in excluded],
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
                "label": draw_round_label(rn),
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


def create_app(
    store: GameStore | None = None,
    *,
    auth_enabled: bool = True,
    auth_path: Path | None = None,
    session_secret_path: Path | None = None,
) -> FastAPI:
    store = store or GameStore()
    app = FastAPI(title="Game Analyzer")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    if auth_enabled:
        import game_analyzer.web.auth as auth_mod

        if auth_path is not None:
            auth_mod.AUTH_FILE = auth_path
        if session_secret_path is not None:
            auth_mod.SESSION_SECRET_FILE = session_secret_path
        load_auth_record()

    def _ctx(request: Request, **extra):
        logged_in = _session_username(request) if auth_enabled else None
        return {
            "request": request,
            "static_ver": STATIC_VER,
            "logged_in": bool(logged_in),
            "username": logged_in,
            **extra,
        }

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        if not auth_enabled or _is_public_path(request.url.path, request.method):
            return await call_next(request)
        if _session_username(request):
            return await call_next(request)
        if request.url.path.startswith("/api/") or request.headers.get("accept", "").startswith(
            "application/json"
        ):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401, headers=NO_CACHE)
        query = urlencode({"next": request.url.path})
        return RedirectResponse(url=f"/login?{query}", status_code=302)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str | None = Query(None)):
        if auth_enabled and _session_username(request):
            return RedirectResponse(_safe_next_url(next), status_code=302)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,
                "static_ver": STATIC_VER,
                "error": None,
                "form_username": "",
                "next_url": _safe_next_url(next),
                "login_action": (
                    f"/login?{urlencode({'next': _safe_next_url(next)})}"
                    if next and _safe_next_url(next) != "/"
                    else "/login"
                ),
            },
        )

    @app.post("/login")
    async def login_submit(request: Request, next: str | None = Query(None)):
        form = await _read_form(request)
        username = form.get("username", "").strip()
        password = form.get("password", "")
        next_url = _safe_next_url(next)
        if auth_enabled and authenticate(username, password):
            request.session[SESSION_USERNAME_KEY] = username
            return RedirectResponse(next_url, status_code=302)
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,
                "static_ver": STATIC_VER,
                "error": "Invalid username or password.",
                "form_username": username,
                "next_url": next_url,
                "login_action": (
                    f"/login?{urlencode({'next': next_url})}"
                    if next_url != "/"
                    else "/login"
                ),
            },
            status_code=401,
        )

    @app.post("/logout")
    def logout(request: Request):
        if auth_enabled:
            request.session.clear()
        return RedirectResponse("/login", status_code=302)

    @app.get("/change-password", response_class=HTMLResponse)
    def change_password_page(request: Request):
        username = _session_username(request) if auth_enabled else None
        if auth_enabled and not username:
            return RedirectResponse("/login", status_code=302)
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context=_ctx(request, active="account", username=username or "admin"),
        )

    @app.post("/change-password")
    async def change_password_submit(request: Request):
        username = _session_username(request) if auth_enabled else None
        if auth_enabled and not username:
            return RedirectResponse("/login", status_code=302)
        form = await _read_form(request)
        current_password = form.get("current_password", "")
        new_password = form.get("new_password", "")
        confirm_password = form.get("confirm_password", "")
        new_username = form.get("new_username", "").strip() or None
        if new_password != confirm_password:
            return templates.TemplateResponse(
                request=request,
                name="change_password.html",
                context=_ctx(
                    request,
                    active="account",
                    username=username,
                    error="New passwords do not match.",
                ),
                status_code=400,
            )
        ok, message = change_password(
            username or "",
            current_password,
            new_password,
            new_username=new_username,
        )
        if not ok:
            return templates.TemplateResponse(
                request=request,
                name="change_password.html",
                context=_ctx(request, active="account", username=username, error=message),
                status_code=400,
            )
        if auth_enabled:
            record = load_auth_record()
            request.session[SESSION_USERNAME_KEY] = record["username"]
        return templates.TemplateResponse(
            request=request,
            name="change_password.html",
            context=_ctx(
                request,
                active="account",
                username=load_auth_record()["username"],
                success="Password updated.",
            ),
        )

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

    @app.get("/data", response_class=HTMLResponse)
    def data_page(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="data.html",
            context=_ctx(request, active="data"),
        )

    @app.get("/api/data/status")
    def api_data_status():
        summary = data_summary(store)
        return JSONResponse(
            {
                "games": summary.games,
                "frames": summary.frames,
                "finished_games": summary.finished_games,
                "screenshot_files": summary.screenshot_files,
                "screenshot_bytes": summary.screenshot_bytes,
                "cache_present": summary.cache_present,
                "cache_built_at": summary.cache_built_at,
                "trusted_twin_sets": summary.trusted_twin_sets,
            },
            headers=NO_CACHE,
        )

    @app.get("/api/data/export")
    def api_data_export():
        import tempfile

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        path = Path(tmp.name)
        tmp.close()
        try:
            build_export_zip(store, path)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        fname = export_filename()
        return FileResponse(
            path,
            media_type="application/zip",
            filename=fname,
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
            background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
        )

    @app.post("/api/data/import")
    async def api_data_import(request: Request):
        import tempfile

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_IMPORT_BYTES:
                    raise HTTPException(status_code=413, detail="Backup file too large.")
            except ValueError:
                pass
        body = await request.body()
        if len(body) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="Backup file too large.")
        if not body:
            raise HTTPException(status_code=400, detail="Empty upload.")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
        path = Path(tmp.name)
        try:
            tmp.write(body)
            tmp.close()
            report = import_from_zip(store, path, merge=True)
        finally:
            path.unlink(missing_ok=True)
        status = 200 if report.ok else 400
        return JSONResponse(report.to_dict(), status_code=status, headers=NO_CACHE)

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

    @app.get("/api/notifications")
    def api_notifications():
        return JSONResponse(_notifications_payload(store), headers=NO_CACHE)

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

    if auth_enabled:
        app.add_middleware(
            SignedCookieSessionMiddleware,
            secret_key=session_secret(),
            max_age=60 * 60 * 24 * 14,
            same_site="lax",
        )

    return app


app = create_app()


def main() -> None:
    print("Game Analyzer web: http://0.0.0.0:8000")
    print("Stop any old server first (Ctrl+C), or it will keep 404ing /api/game.")
    uvicorn.run("game_analyzer.web:app", host="0.0.0.0", port=8000, reload=False)
