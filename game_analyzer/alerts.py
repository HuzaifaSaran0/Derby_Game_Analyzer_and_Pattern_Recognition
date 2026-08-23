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


@dataclass(frozen=True)
class AlertSettings:
    enabled: bool = False
    min_level: ConfidenceLevel = ConfidenceLevel.HIGH
    webhook_url: str = ""
    log_path: Path = DEFAULT_LOG
    allow_upgrade: bool = True
    allow_cancel: bool = True


@dataclass(frozen=True)
class AlertTransition:
    fired: bool
    kind: str | None
    message: str | None


def alert_settings_from_config(config: dict[str, Any]) -> AlertSettings:
    raw = config.get("alerts") or {}
    min_name = str(raw.get("min_level", "HIGH")).upper()
    try:
        min_level = ConfidenceLevel(min_name)
    except ValueError:
        min_level = ConfidenceLevel.HIGH
    log_path = raw.get("log_path")
    return AlertSettings(
        enabled=bool(raw.get("enabled", False)),
        min_level=min_level,
        webhook_url=str(raw.get("webhook_url", "")).strip(),
        log_path=Path(log_path) if log_path else DEFAULT_LOG,
        allow_upgrade=bool(raw.get("allow_upgrade", True)),
        allow_cancel=bool(raw.get("allow_cancel", True)),
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
