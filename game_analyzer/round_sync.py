"""Hybrid wait logic: phase schedule + result window + same-cards retries.

Schedule (authoritative for this project):
  - game start: sleep on-page timer remaining (or first_round_remaining fallback)
  - after handicap (DEALT): sleep ~37s to first draw
  - mid draws (IN_PLAY): sleep ~32s
  - after every IN_PLAY save: poll ~13s for WINNER (result window)
  - if cards unchanged: short dual-trigger retries

Optional TIMER_* modes remain for debugging / fallback if config enables them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from game_analyzer.session import WaitMode
from game_analyzer.timer import TimerReading


class ResultWatchOutcome(str, Enum):
    FINISHED = "finished"
    NEW_ROUND = "new_round"
    TIMEOUT = "timeout"


class WaitTrigger(str, Enum):
    SCHEDULE = "schedule"
    TIMER = "timer"
    FALLBACK = "fallback"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class SyncSettings:
    enabled: bool = True
    capture_at: float = 1.0
    reset_above: float = 20.0
    poll_slow: float = 1.0
    poll_mid: float = 0.5
    poll_fast: float = 0.2
    poll_critical: float = 0.1
    mid_threshold: float = 15.0
    fast_threshold: float = 5.0
    critical_threshold: float = 2.0
    dual_trigger_enabled: bool = True
    dual_trigger_settle_seconds: float = 4.0
    dual_trigger_peek_seconds: float = 0.25
    result_window_seconds: float = 13.0
    result_poll_seconds: float = 0.5


@dataclass(frozen=True)
class WaitOutcome:
    trigger: WaitTrigger
    timer_seconds: int | None = None


TimerReader = Callable[[], TimerReading | None]
CaptureFn = Callable[[], object]
DecisionFn = Callable[[object], tuple]
ShouldRetryFn = Callable[[object], bool]


def timer_sync_enabled(capture: dict) -> bool:
    """True when CDP features (timer read, dual-trigger, result window) are on."""
    mode = str(capture.get("mode", "screen")).lower()
    if mode not in {"brave_cdp", "brave", "cdp"}:
        return False
    return bool(capture.get("use_timer_sync", True))


def sync_settings_from_config(config: dict) -> SyncSettings:
    cap = config.get("capture") or {}
    return SyncSettings(
        enabled=bool(cap.get("use_timer_sync", True)),
        capture_at=float(cap.get("timer_capture_at", 1.0)),
        reset_above=float(cap.get("timer_reset_above", 20.0)),
        poll_slow=float(cap.get("timer_poll_slow", 1.0)),
        poll_mid=float(cap.get("timer_poll_mid", 0.5)),
        poll_fast=float(cap.get("timer_poll_fast", 0.2)),
        poll_critical=float(cap.get("timer_poll_critical", 0.1)),
        mid_threshold=float(cap.get("timer_mid_threshold", 15.0)),
        fast_threshold=float(cap.get("timer_fast_threshold", 5.0)),
        critical_threshold=float(cap.get("timer_critical_threshold", 2.0)),
        dual_trigger_enabled=bool(cap.get("dual_trigger_enabled", True)),
        dual_trigger_settle_seconds=float(cap.get("dual_trigger_settle_seconds", 4.0)),
        dual_trigger_peek_seconds=float(cap.get("dual_trigger_peek_seconds", 0.25)),
        result_window_seconds=float(cap.get("result_window_seconds", 13.0)),
        result_poll_seconds=float(cap.get("result_poll_seconds", 0.5)),
    )


def adaptive_poll_interval(seconds: int | None, settings: SyncSettings) -> float:
    if seconds is None:
        return settings.poll_slow
    if seconds <= settings.critical_threshold:
        return settings.poll_critical
    if seconds <= settings.fast_threshold:
        return settings.poll_fast
    if seconds <= settings.mid_threshold:
        return settings.poll_mid
    return settings.poll_slow


def wait_for_next_capture(
    mode: WaitMode,
    wait_seconds: float,
    settings: SyncSettings,
    read_timer: TimerReader,
    *,
    started_at: float | None = None,
) -> WaitOutcome:
    """Block until the next capture moment."""
    if mode is WaitMode.POLL_GAME_ID:
        _sleep_fixed(wait_seconds, started_at)
        return WaitOutcome(trigger=WaitTrigger.SKIPPED)

    if mode is WaitMode.FIXED or not settings.enabled:
        _sleep_fixed(wait_seconds, started_at)
        return WaitOutcome(trigger=WaitTrigger.SCHEDULE)

    deadline = time.monotonic() + max(wait_seconds, 10.0) + 10.0

    if mode is WaitMode.TIMER_TO_ZERO:
        outcome = _wait_until_low(read_timer, settings, deadline)
        if outcome.trigger is WaitTrigger.TIMER:
            return outcome
        _sleep_remaining(wait_seconds, started_at)
        return WaitOutcome(trigger=WaitTrigger.FALLBACK)

    if mode is WaitMode.TIMER_CYCLE:
        outcome = _wait_cycle(read_timer, settings, deadline)
        if outcome.trigger is WaitTrigger.TIMER:
            return outcome
        _sleep_remaining(wait_seconds, started_at)
        return WaitOutcome(trigger=WaitTrigger.FALLBACK)

    _sleep_fixed(wait_seconds, started_at)
    return WaitOutcome(trigger=WaitTrigger.SCHEDULE)


def retry_until_cards_change(
    settings: SyncSettings,
    read_timer: TimerReader,
    capture_fn: CaptureFn,
    should_retry: ShouldRetryFn,
) -> object:
    """After a schedule wait, retry briefly if cards have not updated yet."""
    if not settings.dual_trigger_enabled:
        return capture_fn()

    saved = capture_fn()
    if not should_retry(saved):
        return saved

    deadline = time.monotonic() + settings.dual_trigger_settle_seconds
    while time.monotonic() < deadline:
        reading = read_timer()
        if reading is not None and reading.seconds >= settings.reset_above:
            break
        time.sleep(settings.dual_trigger_peek_seconds)
        saved = capture_fn()
        if not should_retry(saved):
            return saved
    return saved


def run_result_watch(
    settings: SyncSettings,
    read_timer: TimerReader,
    capture_fn: CaptureFn,
    decision_fn: DecisionFn,
) -> ResultWatchOutcome:
    """Poll during the ~12s FINISHED window after an IN_PLAY draw."""
    end = time.monotonic() + settings.result_window_seconds
    while time.monotonic() < end:
        time.sleep(settings.result_poll_seconds)
        saved = capture_fn()
        phase, should_save, _watch = decision_fn(saved)
        if should_save and phase == "FINISHED":
            return ResultWatchOutcome.FINISHED
        if should_save and phase == "IN_PLAY":
            return ResultWatchOutcome.NEW_ROUND
        reading = read_timer()
        if reading is not None and reading.seconds >= settings.reset_above:
            return ResultWatchOutcome.TIMEOUT
    return ResultWatchOutcome.TIMEOUT


def _wait_until_low(
    read_timer: TimerReader, settings: SyncSettings, deadline: float
) -> WaitOutcome:
    while time.monotonic() < deadline:
        reading = read_timer()
        if reading is not None and reading.seconds <= settings.capture_at:
            return WaitOutcome(trigger=WaitTrigger.TIMER, timer_seconds=reading.seconds)
        time.sleep(adaptive_poll_interval(reading.seconds if reading else None, settings))
    return WaitOutcome(trigger=WaitTrigger.FALLBACK)


def _wait_cycle(
    read_timer: TimerReader, settings: SyncSettings, deadline: float
) -> WaitOutcome:
    saw_reset = False
    while time.monotonic() < deadline:
        reading = read_timer()
        if reading is not None:
            if reading.seconds >= settings.reset_above:
                saw_reset = True
            if saw_reset and reading.seconds <= settings.capture_at:
                return WaitOutcome(trigger=WaitTrigger.TIMER, timer_seconds=reading.seconds)
        time.sleep(adaptive_poll_interval(reading.seconds if reading else None, settings))
    return WaitOutcome(trigger=WaitTrigger.FALLBACK)


def _sleep_fixed(seconds: float, started_at: float | None) -> None:
    if started_at is None:
        time.sleep(max(0.0, seconds))
        return
    remaining = seconds - (time.monotonic() - started_at)
    if remaining > 0:
        time.sleep(remaining)


def _sleep_remaining(wait_seconds: float, started_at: float | None) -> None:
    if started_at is None:
        time.sleep(max(0.0, wait_seconds))
        return
    elapsed = time.monotonic() - started_at
    remaining = max(0.0, wait_seconds - elapsed)
    if remaining > 0:
        time.sleep(remaining)
