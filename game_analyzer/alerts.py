"""Client alert delivery for high-confidence guesses (Phase 2)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_analyzer.confidence import ConfidenceLevel, ConfidenceResult, format_confidence_text, level_at_least

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "data" / "alerts.log"

_LEVEL_ORDER = (
    ConfidenceLevel.NONE,
    ConfidenceLevel.LOW,
    ConfidenceLevel.MEDIUM,
    ConfidenceLevel.HIGH,
    ConfidenceLevel.VERY_HIGH,
)


@dataclass(frozen=True)
class AlertSettings:
    enabled: bool = False
    min_level: ConfidenceLevel = ConfidenceLevel.MEDIUM
    webhook_url: str = ""
    log_path: Path = DEFAULT_LOG
    allow_upgrade: bool = True
    allow_cancel: bool = True
    mc_upgrade_delta: float = 0.05


@dataclass(frozen=True)
class AlertTransition:
    fired: bool
    kind: str | None
    message: str | None


def alert_settings_from_config(config: dict[str, Any]) -> AlertSettings:
    raw = config.get("alerts") or {}
    min_name = str(raw.get("min_level", "MEDIUM")).upper()
    try:
        min_level = ConfidenceLevel(min_name)
    except ValueError:
        min_level = ConfidenceLevel.MEDIUM
    log_path = raw.get("log_path")
    return AlertSettings(
        enabled=bool(raw.get("enabled", False)),
        min_level=min_level,
        webhook_url=str(raw.get("webhook_url", "")).strip(),
        log_path=Path(log_path) if log_path else DEFAULT_LOG,
        allow_upgrade=bool(raw.get("allow_upgrade", True)),
        allow_cancel=bool(raw.get("allow_cancel", True)),
        mc_upgrade_delta=float(raw.get("mc_upgrade_delta", 0.05)),
    )


def format_alert_message(
    *,
    game_id: str | None,
    confidence: ConfidenceResult,
    kind: str,
) -> str:
    pick = confidence.pick or "?"
    parts = [
        f"[{kind.upper()}]",
        f"Game {game_id or '-'}",
        f"Pick {pick.title()}",
        f"Confidence {confidence.level.value}",
    ]
    if confidence.confidence_pct is not None:
        parts.append(f"{confidence.confidence_pct}%")
    if confidence.track_gap is not None:
        parts.append(f"gap +{confidence.track_gap}")
    if confidence.mc_pick is not None:
        parts.append(f"MC {confidence.mc_pick:.0%}")
    if confidence.rivals_weak_count:
        parts.append(f"{confidence.rivals_weak_count} weak rivals")
    if confidence.reasons:
        parts.append(confidence.reasons[0])
    return " — ".join(parts)


def compute_alert_transition(
    *,
    settings: AlertSettings,
    previously_sent: bool,
    previous_level: ConfidenceLevel | None,
    previous_mc_pick: float | None,
    previous_pick: str | None,
    confidence: ConfidenceResult,
    game_id: str | None,
) -> AlertTransition:
    if not settings.enabled:
        return AlertTransition(False, None, None)
    if not confidence.ready or not confidence.pick:
        return AlertTransition(False, None, None)

    qualifies = level_at_least(confidence.level, settings.min_level)
    prev_qualifies = (
        previous_level is not None and level_at_least(previous_level, settings.min_level)
    )

    if not previously_sent and qualifies:
        kind = "bet"
        return AlertTransition(
            True,
            kind,
            format_alert_message(game_id=game_id, confidence=confidence, kind=kind),
        )

    if previously_sent and settings.allow_upgrade and not prev_qualifies and qualifies:
        kind = "upgrade"
        return AlertTransition(
            True,
            kind,
            format_alert_message(game_id=game_id, confidence=confidence, kind=kind),
        )

    if previously_sent and settings.allow_upgrade and prev_qualifies and qualifies:
        level_up = (
            previous_level is not None
            and _LEVEL_ORDER.index(confidence.level) > _LEVEL_ORDER.index(previous_level)
        )
        mc_up = (
            previous_mc_pick is not None
            and confidence.mc_pick is not None
            and confidence.mc_pick >= previous_mc_pick + settings.mc_upgrade_delta
        )
        pick_changed = bool(
            previous_pick
            and confidence.pick
            and previous_pick.title() != confidence.pick.title()
        )
        if level_up or mc_up or pick_changed:
            kind = "upgrade"
            return AlertTransition(
                True,
                kind,
                format_alert_message(game_id=game_id, confidence=confidence, kind=kind),
            )

    if previously_sent and settings.allow_cancel and prev_qualifies and not qualifies:
        kind = "cancel"
        return AlertTransition(
            True,
            kind,
            format_alert_message(game_id=game_id, confidence=confidence, kind=kind),
        )

    return AlertTransition(False, None, None)


def append_alert_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{stamp}  {message}\n")


def parse_alert_log_line(line: str) -> dict[str, str] | None:
    """Parse ``{iso}  {message}`` rows from ``alerts.log``."""
    text = line.strip()
    if not text or text.startswith("WEBHOOK FAILED"):
        return None
    # Prefer splitting on first double-space after the timestamp.
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


def read_recent_alerts(path: Path, *, limit: int = 20) -> list[dict[str, str]]:
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


def deliver_alert(
    settings: AlertSettings,
    *,
    alert_fired: bool,
    alert_kind: str | None,
    alert_message: str | None,
) -> None:
    if not alert_fired or not alert_message:
        return
    append_alert_log(settings.log_path, alert_message)
    if settings.webhook_url:
        try:
            post_webhook(settings.webhook_url, alert_message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            append_alert_log(settings.log_path, f"WEBHOOK FAILED: {error} — {alert_message}")
    print(f"*** ALERT ({alert_kind}) *** {alert_message}")


def deliver_similarity_alert(
    settings: AlertSettings,
    *,
    alert_kind: str,
    alert_message: str,
) -> None:
    """Log a similarity/twin alert (independent of confidence alert enable flag)."""
    if not alert_message:
        return
    append_alert_log(settings.log_path, alert_message)
    if settings.webhook_url:
        try:
            post_webhook(settings.webhook_url, alert_message)
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            append_alert_log(settings.log_path, f"WEBHOOK FAILED: {error} — {alert_message}")
    print(f"*** ALERT ({alert_kind}) *** {alert_message}")


def confidence_summary_for_ui(
    confidence: ConfidenceResult,
    *,
    settings: AlertSettings,
    alert_fired: bool,
    alert_kind: str | None,
) -> str:
    text = format_confidence_text(confidence)
    if not settings.enabled:
        return text
    if alert_fired and alert_kind:
        return f"{text} — ALERT {alert_kind.upper()}"
    if level_at_least(confidence.level, settings.min_level):
        return f"{text} — would alert"
    return text
