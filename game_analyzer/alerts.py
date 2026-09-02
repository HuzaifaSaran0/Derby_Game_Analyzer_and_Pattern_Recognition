"""Alert log + webhook delivery (similarity / twin alerts)."""

from __future__ import annotations

import json
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "data" / "alerts.log"


ROOT_OPS_LOG = ROOT / "data" / "ops_alerts.log"


@dataclass(frozen=True)
class AlertSettings:
    webhook_url: str = ""
    ops_webhook_url: str = ""
    discord_webhook_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    public_base_url: str = ""
    log_path: Path = DEFAULT_LOG
    ops_log_path: Path = ROOT_OPS_LOG


def alert_settings_from_config(config: dict[str, Any]) -> AlertSettings:
    """Read notify paths from config.alerts or config.similarity."""
    raw = config.get("alerts") or {}
    sim = config.get("similarity") or {}
    tg = raw.get("telegram") or {}
    log_path = raw.get("log_path") or sim.get("log_path")
    webhook = str(raw.get("webhook_url") or sim.get("webhook_url") or "").strip()
    discord = str(raw.get("discord_webhook_url") or "").strip()
    tg_token = str(tg.get("bot_token") or raw.get("telegram_bot_token") or "").strip()
    tg_chat = str(tg.get("chat_id") or raw.get("telegram_chat_id") or "").strip()
    public_base = str(raw.get("public_base_url") or "").strip()
    ops_webhook = str(raw.get("ops_webhook_url") or "").strip()
    ops_log_path = raw.get("ops_log_path")
    return AlertSettings(
        webhook_url=webhook,
        ops_webhook_url=ops_webhook,
        discord_webhook_url=discord,
        telegram_bot_token=tg_token,
        telegram_chat_id=tg_chat,
        public_base_url=public_base,
        log_path=Path(log_path) if log_path else DEFAULT_LOG,
        ops_log_path=Path(ops_log_path) if ops_log_path else ROOT_OPS_LOG,
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


def is_winner_hint_alert(kind: str) -> bool:
    k = (kind or "").strip().lower()
    return k == "winner-hint"


def is_modern_winner_hint_message(message: str) -> bool:
    """Winner-hint rows we still surface in the bell (forecasts link + MEDIUM/HIGH)."""
    text = (message or "").strip()
    if "/forecasts?game=" not in text:
        return False
    return bool(re.search(r"(?:confidence|history)\s+\d+%\s+\((MEDIUM|HIGH)\)", text, re.I))


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


def winner_hint_already_logged(path: Path, dedupe_key: str) -> bool:
    """True if the log already contains this winner-hint alert."""
    if not dedupe_key or not path.is_file():
        return False
    from game_analyzer.winner_hints import notification_item_from_alert

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    for line in reversed(lines[-400:]):
        parsed = parse_alert_log_line(line)
        if parsed is None or not is_winner_hint_alert(parsed.get("kind") or ""):
            continue
        item = notification_item_from_alert(parsed)
        if item.get("dedupe_key") == dedupe_key:
            return True
    return False


def read_recent_alerts(
    path: Path,
    *,
    limit: int = 20,
    similarity_only: bool = False,
    winner_hint_only: bool = False,
) -> list[dict[str, str]]:
    """Newest-first alert entries from the log file (empty if missing)."""
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
        kind = parsed.get("kind") or ""
        if winner_hint_only and not is_winner_hint_alert(kind):
            continue
        if winner_hint_only and not is_modern_winner_hint_message(parsed.get("message") or ""):
            continue
        if similarity_only and not is_similarity_alert(kind):
            continue
        if not winner_hint_only and not similarity_only:
            if kind in _LEGACY_ALERT_KINDS or (
                not is_similarity_alert(kind) and not is_winner_hint_alert(kind)
            ):
                continue
        entries.append(parsed)
        if len(entries) >= limit:
            break
    return entries


def latest_alert(path: Path, *, winner_hint_only: bool = False) -> dict[str, str] | None:
    rows = read_recent_alerts(path, limit=1, winner_hint_only=winner_hint_only)
    return rows[0] if rows else None


def _webhook_ssl_context() -> ssl.SSLContext:
    """Use certifi CA bundle — Windows VPS Python often lacks system CAs for HTTPS."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _post_json(url: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10, context=_webhook_ssl_context()) as response:
        response.read()


def post_webhook(url: str, message: str) -> None:
    """Slack-style incoming webhook (``{"text": ...}``)."""
    _post_json(url, {"text": message})


def post_discord_webhook(url: str, message: str) -> None:
    _post_json(url, {"content": message})


def post_telegram_message(bot_token: str, chat_id: str, message: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    _post_json(url, {"chat_id": chat_id, "text": message})


def push_channels_configured(settings: AlertSettings) -> bool:
    return bool(
        settings.webhook_url
        or settings.discord_webhook_url
        or (settings.telegram_bot_token and settings.telegram_chat_id)
    )


def deliver_push_notifications(settings: AlertSettings, message: str) -> list[str]:
    """Send a plain-text alert to every configured push channel. Returns error strings."""
    if not message.strip():
        return []
    errors: list[str] = []
    if settings.webhook_url:
        try:
            post_webhook(settings.webhook_url, message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            errors.append(f"Slack/webhook: {error}")
    if settings.discord_webhook_url:
        try:
            post_discord_webhook(settings.discord_webhook_url, message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            errors.append(f"Discord: {error}")
    if settings.telegram_bot_token and settings.telegram_chat_id:
        try:
            post_telegram_message(settings.telegram_bot_token, settings.telegram_chat_id, message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            errors.append(f"Telegram: {error}")
    return errors


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


def deliver_ops_alert(
    settings: AlertSettings,
    message: str,
    *,
    dedupe_key: str = "",
) -> bool:
    """Internal ops alert — ops Slack/DM only, never client webhook or UI bell."""
    if not message.strip():
        return False
    if dedupe_key and ops_alert_already_logged(settings.ops_log_path, dedupe_key):
        return False
    append_alert_log(settings.ops_log_path, message)
    if settings.ops_webhook_url:
        try:
            post_webhook(settings.ops_webhook_url, message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            append_alert_log(
                settings.ops_log_path,
                f"WEBHOOK FAILED: {error} — {message}",
            )
    print(f"*** OPS ALERT *** {message}")
    return True


def ops_alert_already_logged(path: Path, dedupe_key: str) -> bool:
    if not dedupe_key or not path.is_file():
        return False
    needle = f"game_id={dedupe_key}"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(needle in line for line in lines[-200:])


def deliver_winner_hint_alert(
    settings: AlertSettings,
    *,
    alert_message: str,
    push_message: str = "",
    dedupe_key: str = "",
) -> bool:
    """Log a live winner-history hint alert. Returns False when skipped as duplicate."""
    if not alert_message:
        return False
    if dedupe_key and winner_hint_already_logged(settings.log_path, dedupe_key):
        return False
    append_alert_log(settings.log_path, alert_message)
    mobile_text = (push_message or alert_message).strip()
    if push_channels_configured(settings):
        for error in deliver_push_notifications(settings, mobile_text):
            append_alert_log(settings.log_path, f"WEBHOOK FAILED: {error} — {mobile_text}")
    print(f"*** ALERT (winner-hint) *** {alert_message}")
    return True
