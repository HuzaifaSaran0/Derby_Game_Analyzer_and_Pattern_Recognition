"""Alert log + webhook delivery (similarity / twin alerts)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "data" / "alerts.log"


@dataclass(frozen=True)
class AlertSettings:
    webhook_url: str = ""
    log_path: Path = DEFAULT_LOG


def alert_settings_from_config(config: dict[str, Any]) -> AlertSettings:
    """Read notify paths from config.alerts or config.similarity."""
    raw = config.get("alerts") or {}
    sim = config.get("similarity") or {}
    log_path = raw.get("log_path") or sim.get("log_path")
    webhook = str(raw.get("webhook_url") or sim.get("webhook_url") or "").strip()
    return AlertSettings(
        webhook_url=webhook,
        log_path=Path(log_path) if log_path else DEFAULT_LOG,
    )


def append_alert_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}  {message}\n")


# Legacy confidence/guess alert tags — never surface in the notification panel.
_LEGACY_ALERT_KINDS = frozenset({"bet", "upgrade", "cancel", "alert"})


def is_similarity_alert(kind: str) -> bool:
    """True for late-round twin alerts (``twin-r3`` / ``twin-r4`` / ``twin-r5``)."""
    k = (kind or "").strip().lower()
    return k.startswith("twin-r") and k not in _LEGACY_ALERT_KINDS


def parse_alert_log_line(line: str) -> dict[str, str] | None:
    """Parse ``{iso}  {message}`` rows from ``alerts.log``."""
    text = line.strip()
    if not text or text.startswith("WEBHOOK FAILED"):
        return None
    stamp = ""
    message = text
    if "  " in text:
        stamp, message = text.split("  ", 1)
        stamp = stamp.strip()
        message = message.strip()
    if message.startswith("WEBHOOK FAILED"):
        return None
    kind = "alert"
    if message.startswith("[") and "]" in message:
        kind = message[1 : message.index("]")].lower()
    link = ""
    if " · link=" in message:
        link = message.rsplit(" · link=", 1)[-1].strip()
    elif " link=" in message:
        link = message.rsplit(" link=", 1)[-1].strip()
    return {
        "id": f"{stamp}|{message}",
        "at": stamp,
        "kind": kind,
        "message": message,
        "link": link,
    }


def read_recent_alerts(
    path: Path,
    *,
    limit: int = 20,
    similarity_only: bool = True,
) -> list[dict[str, str]]:
    """Newest-first alert entries from the log file (empty if missing).

    By default only late-round similarity twins are returned — legacy
    BET/UPGRADE/CANCEL confidence rows are skipped.
    """
    if limit <= 0 or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict[str, str]] = []
    for line in reversed(lines):
        parsed = parse_alert_log_line(line)
        if parsed is None:
            continue
        if similarity_only and not is_similarity_alert(parsed["kind"]):
            continue
        entries.append(parsed)
        if len(entries) >= limit:
            break
    return entries


def latest_alert(path: Path) -> dict[str, str] | None:
    rows = read_recent_alerts(path, limit=1)
    return rows[0] if rows else None


def post_webhook(url: str, message: str) -> None:
    payload = json.dumps({"text": message}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def deliver_similarity_alert(
    settings: AlertSettings,
    *,
    alert_kind: str,
    alert_message: str,
) -> None:
    """Log a similarity/twin alert."""
    if not alert_message:
        return
    append_alert_log(settings.log_path, alert_message)
    if settings.webhook_url:
        try:
            post_webhook(settings.webhook_url, alert_message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            append_alert_log(settings.log_path, f"WEBHOOK FAILED: {error} — {alert_message}")
    print(f"*** ALERT ({alert_kind}) *** {alert_message}")
