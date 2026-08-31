"""Capture heartbeat + log file for health checks and crash diagnosis."""

from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STATUS_PATH = ROOT / "data" / "capture_status.json"
DEFAULT_LOG_PATH = ROOT / "data" / "capture.log"

_LOGGER: logging.Logger | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def status_path_from_config(config: dict[str, Any] | None = None) -> Path:
    health = (config or {}).get("health") or {}
    raw = health.get("status_path")
    return Path(raw) if raw else DEFAULT_STATUS_PATH


def log_path_from_config(config: dict[str, Any] | None = None) -> Path:
    health = (config or {}).get("health") or {}
    raw = health.get("log_path")
    return Path(raw) if raw else DEFAULT_LOG_PATH


def health_thresholds(config: dict[str, Any] | None = None) -> tuple[int, int]:
    health = (config or {}).get("health") or {}
    capture_stale = int(health.get("capture_stale_seconds", 150))
    game_stale = int(health.get("game_stale_seconds", 120))
    return capture_stale, game_stale


def setup_capture_logging(config: dict[str, Any] | None = None) -> logging.Logger:
    """File logger for capture crashes and errors."""
    global _LOGGER
    log_path = log_path_from_config(config)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = log_path.resolve()
    logger = logging.getLogger("game_analyzer.capture")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == resolved:
            _LOGGER = logger
            return logger
        logger.removeHandler(handler)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    _LOGGER = logger
    return logger


def _read_status(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_status(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":"), indent=2) + "\n", encoding="utf-8")


def mark_capture_started(*, source: str, config: dict[str, Any] | None = None) -> None:
    path = status_path_from_config(config)
    now = _utc_now()
    data = _read_status(path)
    data.update(
        {
            "capture_running": True,
            "source": source,
            "pid": os.getpid(),
            "started_at": now,
            "last_heartbeat_at": now,
            "stopped_at": None,
            "stopped_reason": None,
            "last_error": None,
            "last_error_at": None,
        }
    )
    _write_status(path, data)
    setup_capture_logging(config).info("Capture started (%s, pid=%s)", source, os.getpid())


def mark_capture_stopped(*, reason: str = "stopped", config: dict[str, Any] | None = None) -> None:
    path = status_path_from_config(config)
    data = _read_status(path)
    data.update(
        {
            "capture_running": False,
            "stopped_at": _utc_now(),
            "stopped_reason": reason,
        }
    )
    _write_status(path, data)
    setup_capture_logging(config).info("Capture stopped (%s)", reason)


def record_capture_tick(
    *,
    game_id: str | None,
    phase: str | None,
    recording: bool,
    in_progress: bool,
    saved: bool,
    notes: str = "",
    config: dict[str, Any] | None = None,
) -> None:
    """Heartbeat after each capture poll (saved or peek)."""
    path = status_path_from_config(config)
    now = _utc_now()
    data = _read_status(path)
    data.update(
        {
            "capture_running": True,
            "last_heartbeat_at": now,
            "last_capture_at": now,
            "game_id": game_id or "",
            "phase": phase or "",
            "recording": bool(recording),
            "in_progress": bool(in_progress),
            "last_saved": bool(saved),
            "last_notes": notes[:240],
        }
    )
    _write_status(path, data)


def record_capture_error(
    error: BaseException,
    *,
    context: str = "",
    config: dict[str, Any] | None = None,
) -> None:
    path = status_path_from_config(config)
    now = _utc_now()
    message = f"{context}: {error}" if context else str(error)
    data = _read_status(path)
    data.update(
        {
            "last_error_at": now,
            "last_error": message[:500],
            "last_heartbeat_at": now,
        }
    )
    _write_status(path, data)
    logger = setup_capture_logging(config)
    logger.error("%s\n%s", message, traceback.format_exc())


def read_capture_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return _read_status(status_path_from_config(config))


def _parse_iso_age_seconds(at: str | None) -> int | None:
    if not at:
        return None
    try:
        dt = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - dt).total_seconds()))
    except ValueError:
        return None


def tail_capture_log(*, lines: int = 50, config: dict[str, Any] | None = None) -> list[str]:
    log_path = log_path_from_config(config)
    if not log_path.is_file() or lines <= 0:
        return []
    try:
        all_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return all_lines[-lines:]


def evaluate_capture_health(
    store,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build /api/health payload from heartbeat file + latest game in store."""
    config = config or {}
    capture_stale, game_stale = health_thresholds(config)
    status = read_capture_status(config)
    checked_at = _utc_now()

    heartbeat_age = _parse_iso_age_seconds(status.get("last_heartbeat_at"))
    capture_running = bool(status.get("capture_running"))
    last_error = status.get("last_error") or None

    if not status:
        capture_state = "stopped"
        capture_message = "Capture has never run on this machine."
    elif not capture_running:
        capture_state = "stopped"
        reason = status.get("stopped_reason") or "stopped"
        capture_message = f"Capture is not running ({reason})."
    elif heartbeat_age is None:
        capture_state = "unknown"
        capture_message = "Capture status file has no heartbeat timestamp."
    elif heartbeat_age > capture_stale:
        capture_state = "stale"
        capture_message = (
            f"Capture has not responded for {heartbeat_age}s — "
            "possible crash, logout, or frozen game page."
        )
    elif last_error and status.get("last_error_at"):
        err_age = _parse_iso_age_seconds(status.get("last_error_at"))
        if err_age is not None and err_age <= capture_stale:
            capture_state = "error"
            capture_message = f"Last capture error ({err_age}s ago): {last_error}"
        else:
            capture_state = "running"
            capture_message = f"Capture active — last heartbeat {heartbeat_age}s ago."
    else:
        capture_state = "running"
        capture_message = f"Capture active — last heartbeat {heartbeat_age}s ago."

    games = store.list_games()
    game_state = "idle"
    game_message = "No live game in the store."
    game_id = status.get("game_id") or ""
    in_progress = False
    seconds_since_update: int | None = None

    if games:
        latest = store.get_game(games[0]["game_id"])
        if latest is not None:
            game_id = latest.game_id
            in_progress = latest.winner_suit is None
            if latest.frames:
                seconds_since_update = _parse_iso_age_seconds(latest.frames[-1].captured_at)
            if in_progress:
                if seconds_since_update is None:
                    game_state = "unknown"
                    game_message = f"Game #{game_id} in progress — no frame timestamps yet."
                elif seconds_since_update > game_stale:
                    game_state = "stale"
                    game_message = (
                        f"Game #{game_id} looks stuck — no new capture for {seconds_since_update}s. "
                        "Check bpexch login or whether the page froze."
                    )
                else:
                    game_state = "updating"
                    game_message = (
                        f"Game #{game_id} in progress — last capture {seconds_since_update}s ago."
                    )
            else:
                game_state = "idle"
                finished = latest.finished_at or "recently"
                game_message = f"Latest game #{game_id} finished ({finished}). Waiting for next live game."

    overall = "ok"
    if capture_state in {"stopped"} and not games:
        overall = "down"
    elif capture_state in {"stale", "error"} or game_state == "stale":
        overall = "degraded"
    elif capture_state == "stopped" and games:
        overall = "degraded"

    return {
        "status": overall,
        "checked_at": checked_at,
        "web": "ok",
        "capture": {
            "state": capture_state,
            "message": capture_message,
            "running": capture_running,
            "seconds_since_heartbeat": heartbeat_age,
            "source": status.get("source") or "",
            "pid": status.get("pid"),
            "started_at": status.get("started_at"),
            "last_capture_at": status.get("last_capture_at"),
        },
        "game": {
            "state": game_state,
            "message": game_message,
            "game_id": game_id or None,
            "in_progress": in_progress,
            "seconds_since_update": seconds_since_update,
        },
        "last_error": last_error,
        "last_error_at": status.get("last_error_at"),
    }
