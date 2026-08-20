import time

import pytest

from game_analyzer.round_sync import (
    ResultWatchOutcome,
    SyncSettings,
    WaitTrigger,
    adaptive_poll_interval,
    retry_until_cards_change,
    run_result_watch,
    wait_for_next_capture,
)
from game_analyzer.session import WaitMode
from game_analyzer.timer import TimerReading


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_adaptive_poll_interval_tiers():
    s = SyncSettings()
    assert adaptive_poll_interval(25, s) == s.poll_slow
    assert adaptive_poll_interval(10, s) == s.poll_mid
    assert adaptive_poll_interval(4, s) == s.poll_fast
    assert adaptive_poll_interval(1, s) == s.poll_critical
    assert adaptive_poll_interval(None, s) == s.poll_slow


def test_fixed_schedule_sleep_uses_started_at(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)

    outcome = wait_for_next_capture(
        WaitMode.FIXED,
        32.0,
        SyncSettings(),
        lambda: None,
        started_at=1000.0,
    )
    assert outcome.trigger is WaitTrigger.SCHEDULE
    assert clock.now == pytest.approx(1032.0)


def test_fixed_schedule_subtracts_processing(monkeypatch):
    clock = FakeClock(start=1002.0)  # 2s already spent since capture
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)

    wait_for_next_capture(
        WaitMode.FIXED,
        32.0,
        SyncSettings(),
        lambda: None,
        started_at=1000.0,
    )
    assert clock.now == pytest.approx(1032.0)


def test_wait_timer_to_zero(monkeypatch):
    clock = FakeClock()
    readings = iter([TimerReading(18, "header"), TimerReading(3, "header"), TimerReading(1, "header")])

    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    monkeypatch.setattr(time, "sleep", clock.sleep)

    outcome = wait_for_next_capture(
        WaitMode.TIMER_TO_ZERO,
        42.0,
        SyncSettings(),
        lambda: next(readings, None),
        started_at=clock.monotonic(),
    )
    assert outcome.trigger is WaitTrigger.TIMER
    assert outcome.timer_seconds == 1
    assert clock.now == pytest.approx(1001.2)


def test_dual_trigger_retries_until_cards_change():
    calls = {"n": 0}

    def capture_fn():
        calls["n"] += 1
        return (calls["n"],)

    def should_retry(saved):
        return saved[0] < 2

    saved = retry_until_cards_change(
        SyncSettings(dual_trigger_settle_seconds=2.0, dual_trigger_peek_seconds=0.25),
        lambda: TimerReading(0, "header"),
        capture_fn,
        should_retry,
    )
    assert calls["n"] == 2
    assert saved == (2,)


def test_result_watch_finds_finished():
    calls = {"n": 0}

    def capture_fn():
        calls["n"] += 1
        return object()

    def decision_fn(_saved):
        phase = "FINISHED" if calls["n"] == 2 else "IN_PLAY"
        return phase, phase == "FINISHED", False

    outcome = run_result_watch(
        SyncSettings(result_window_seconds=10, result_poll_seconds=0.5),
        lambda: TimerReading(0, "header"),
        capture_fn,
        decision_fn,
    )
    assert outcome is ResultWatchOutcome.FINISHED
    assert calls["n"] == 2


def test_result_watch_detects_new_round():
    calls = {"n": 0}

    def capture_fn():
        calls["n"] += 1
        return object()

    def decision_fn(_saved):
        if calls["n"] == 2:
            return ("IN_PLAY", True, True)
        return ("IN_PLAY", False, False)

    outcome = run_result_watch(
        SyncSettings(result_window_seconds=10, result_poll_seconds=0.5),
        lambda: TimerReading(0, "header"),
        capture_fn,
        decision_fn,
    )
    assert outcome is ResultWatchOutcome.NEW_ROUND
