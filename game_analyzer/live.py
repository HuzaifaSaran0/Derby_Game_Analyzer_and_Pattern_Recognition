"""Grab the already-open game window (same pixels as a manual screenshot).

Hybrid schedule (brave_cdp):
  - first shot of a game: read on-page timer, sleep that many seconds
  - after handicap: sleep ~37s to first draw
  - mid draws: sleep ~32s
  - background winner poll every ~1.2s while a game is open (one FINISHED save)
  - same-cards: short retries
"""

from __future__ import annotations

import argparse
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from game_analyzer.alerts import alert_settings_from_config, deliver_winner_hint_alert, winner_hint_already_logged
from game_analyzer.capture import grab_frame, list_brave_tabs, list_monitors, read_page_game_id, read_page_timer
from game_analyzer.config import load_config
from game_analyzer.models import GamePhase
from game_analyzer.round_sync import (
    ResultWatchOutcome,
    WaitTrigger,
    retry_until_cards_change,
    run_result_watch,
    sync_settings_from_config,
    timer_sync_enabled,
    wait_for_next_capture,
)
from game_analyzer.session import GameSessionTracker, RoundTiming, SessionDecision, WaitMode
from game_analyzer.store import GameStore
from game_analyzer.timer import TimerReading
from game_analyzer.vision import draw_table_overlay, extract_real, write_image

ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = ROOT / "fixtures" / "live"
SESSION_TRACKER = GameSessionTracker()
GAME_STORE = GameStore()
_LAST_DECISION: SessionDecision | None = None
_LAST_FRAME = None
_LAST_PATH: Path | None = None
_LAST_RESULT = None
_LAST_WAIT: WaitTrigger | None = None
_CAPTURE_STARTED_AT: float | None = None
_SCHEDULE_ANCHOR_AT: float | None = None
_TIMER_SAMPLED_AT: float | None = None
_FRAME_GRABBED_AT: float | None = None
# Live winner-hint alerts: dedupe per in-progress game / next-winner code.
_HINT_GAME_ID: str | None = None
_HINT_ALERTED: set[str] = set()
_CONFIDENCE_LOGGED: set[str] = set()
_RETAKE_PREVIEW_HOOK: Callable[[Path, object, str | None], None] | None = None
_CAPTURE_MUTEX = threading.RLock()


def set_retake_preview_hook(
    hook: Callable[[Path, object, str | None], None] | None,
) -> None:
    """Optional UI callback after a lay/back retake replaces the saved PNG (timer thread)."""
    global _RETAKE_PREVIEW_HOOK
    _RETAKE_PREVIEW_HOOK = hook


def _timing_from_config(config: dict) -> RoundTiming:
    cap = config.get("capture") or {}
    return RoundTiming(
        handicap_wait_seconds=float(cap.get("handicap_wait_seconds", cap.get("round_seconds", 37))),
        mid_round_seconds=float(cap.get("mid_round_seconds", cap.get("round_seconds_rest", 32))),
        first_round_remaining=float(cap.get("first_round_remaining", 26)),
        cards_appear_after=float(cap.get("cards_appear_after", 1.0)),
        start_poll_seconds=float(cap.get("start_poll_seconds", 1.5)),
        timer_wait_pad_seconds=float(cap.get("timer_wait_pad_seconds", 1.0)),
        fallback_seconds=float(cap.get("fallback_seconds", 42.0)),
        round_seconds=float(cap.get("round_seconds", 37)),
        round_seconds_rest=float(cap.get("round_seconds_rest", 32)),
    )


def _should_dual_retry(saved) -> bool:
    _path, _frame, _result, decision = saved
    if not decision.recording:
        return False
    if decision.should_save:
        return False
    return decision.reason == "same cards — wait for next round"


def _resolve_confidence_outcome(config: dict, game_id: str, winner_suit: str) -> None:
    from game_analyzer.winner_hints import confidence_log_path_from_config, resolve_confidence_log_outcome

    path = confidence_log_path_from_config(config)
    resolve_confidence_log_outcome(path, game_id, winner_suit)


def _maybe_winner_hint_alerts(config: dict, game_id: str | None) -> None:
    """Log live confidence and alert when tier is MEDIUM or HIGH."""
    global _HINT_GAME_ID, _HINT_ALERTED, _CONFIDENCE_LOGGED
    if not game_id:
        return
    hints_cfg = config.get("winner_hints") or {}
    if hints_cfg.get("notify", True) is False and hints_cfg.get("confidence_log", True) is False:
        return
    if game_id != _HINT_GAME_ID:
        _HINT_GAME_ID = game_id
        _HINT_ALERTED = set()

    from game_analyzer.winner_hints import (
        analyze_tail,
        append_confidence_log,
        build_confidence_log_entry,
        compute_live_confidence,
        confidence_already_logged,
        confidence_log_path_from_config,
        finished_winner_codes,
        format_winner_hint_alert_message,
        format_winner_hint_push_message,
        HINT_LENGTHS,
        notifiable_winner_hint_groups,
        NOTIFY_TIERS,
        winner_hint_dedupe_key,
    )

    finished_codes = finished_winner_codes(GAME_STORE)
    if len(finished_codes) < min(HINT_LENGTHS):
        return
    rows = []
    for length in HINT_LENGTHS:
        row = analyze_tail(finished_codes, length)
        if row is not None:
            rows.append(row)

    confidence = compute_live_confidence(rows)
    confidence_path = confidence_log_path_from_config(config)
    log_confidence = hints_cfg.get("confidence_log", True) is not False
    if (
        log_confidence
        and game_id not in _CONFIDENCE_LOGGED
        and not confidence_already_logged(confidence_path, game_id)
    ):
        notified = confidence.tier in NOTIFY_TIERS and bool(confidence.supporting_patterns)
        append_confidence_log(
            confidence_path,
            build_confidence_log_entry(
                game_id=game_id,
                confidence=confidence,
                rows=rows,
                notified=notified,
            ),
        )
        _CONFIDENCE_LOGGED.add(game_id)

    if hints_cfg.get("notify", True) is False:
        return

    groups = notifiable_winner_hint_groups(rows)
    if not groups:
        return

    settings = alert_settings_from_config(config)
    for next_code, patterns in groups.items():
        dedupe = winner_hint_dedupe_key(game_id, patterns)
        if dedupe in _HINT_ALERTED:
            continue
        if winner_hint_already_logged(settings.log_path, dedupe):
            _HINT_ALERTED.add(dedupe)
            continue
        message = format_winner_hint_alert_message(
            game_id,
            patterns,
            confidence_pct=confidence.confidence_pct,
            tier=confidence.tier,
        )
        push_message = format_winner_hint_push_message(
            game_id,
            patterns,
            confidence_pct=confidence.confidence_pct,
            tier=confidence.tier,
            public_base_url=settings.public_base_url,
        )
        if deliver_winner_hint_alert(
            settings,
            alert_message=message,
            push_message=push_message,
            dedupe_key=dedupe,
        ):
            _HINT_ALERTED.add(dedupe)


def _retake_delay_seconds(capture: dict, phase: GamePhase) -> float | None:
    """Seconds after the saved shot when the back/lay table should be on screen.

    None disables the retake (FINISHED shots, or recapture_enabled=false).
    """
    if not bool(capture.get("recapture_enabled", True)):
        return None
    if phase == GamePhase.FINISHED:
        return None
    if phase == GamePhase.START:
        return float(capture.get("recapture_start_delay_seconds", 8.0))
    return float(capture.get("recapture_delay_seconds", 9.0))


def retake_screenshot_for_lay_back(
    config: dict,
    path: Path,
    game_id: str | None,
    *,
    read_id=None,
    grab=None,
    extract=None,
    write=None,
) -> bool:
    """Re-grab the screen (back/lay table now visible) and swap the saved PNG in place.

    The original analysis/DB record is untouched — only the image file is replaced.
    Keeps the original file when the game changed or already shows the winner screen
    (the table never appeared for that round).
    """
    from game_analyzer.vision import extract_real, write_image

    read_id = read_id or read_page_game_id
    grab = grab or grab_frame
    extract = extract or extract_real
    write = write or write_image
    try:
        current_id = read_id(config["capture"])
        if game_id and current_id and current_id != game_id:
            return False
        frame = grab(config)
        result = extract(frame, config)
        if result.game_phase() == GamePhase.FINISHED:
            return False
        tmp = path.with_name(path.stem + "_retake.png")
        write(tmp, frame)
        os.replace(tmp, path)
        hook = _RETAKE_PREVIEW_HOOK
        if hook is not None:
            try:
                hook(path, frame, game_id)
            except Exception:
                pass
        return True
    except Exception:
        return False


def _schedule_lay_back_retake(config: dict, decision: SessionDecision, path: Path) -> None:
    """Fire the retake ~8-9s after the frame grab, without blocking the capture loop."""
    delay = _retake_delay_seconds(config["capture"], decision.phase)
    if delay is None:
        return
    remaining = delay
    if _FRAME_GRABBED_AT is not None:
        remaining = max(0.0, delay - (time.monotonic() - _FRAME_GRABBED_AT))
    timer = threading.Timer(
        remaining,
        retake_screenshot_for_lay_back,
        args=(config, path, decision.game_id),
    )
    timer.daemon = True
    timer.start()


def _winner_poll_enabled(config: dict) -> bool:
    return bool((config.get("capture") or {}).get("winner_poll_enabled", True))


def _winner_poll_seconds(config: dict) -> float:
    return float((config.get("capture") or {}).get("winner_poll_seconds", 1.2))


def _game_already_has_winner(game_id: str) -> bool:
    game = GAME_STORE.get_game(game_id)
    return game is not None and bool(game.winner_suit)


def _winner_poll_target_game_id() -> str | None:
    """Open in-progress session with no winner saved yet."""
    tracker = SESSION_TRACKER
    game_id = tracker.session_game_id
    if not tracker.session_id or not game_id:
        return None
    if tracker._close_after_save:
        return None
    if _game_already_has_winner(game_id):
        return None
    return game_id


def _persist_saved_frame(
    config: dict,
    decision: SessionDecision,
    result,
    frame,
    captured_at: datetime,
    *,
    raw_path: Path | None = None,
) -> Path:
    """Write PNG + DB row for a decision that already has should_save=True."""
    global _SCHEDULE_ANCHOR_AT
    capture = config["capture"]
    folder = LIVE_DIR / decision.folder_name()
    folder.mkdir(parents=True, exist_ok=True)
    stem = decision.file_stem(captured_at)
    path = raw_path or (folder / f"{stem}.png")
    save_frame = frame
    if decision.phase == GamePhase.FINISHED:
        settle = float(capture.get("finished_capture_settle_seconds", 0.5))
        if settle > 0:
            time.sleep(settle)
            save_frame = grab_frame(config)
    write_image(path, save_frame)
    if config.get("draw_overlays", False):
        overlay_path = folder / f"{stem}_boxes.png"
        overlay = draw_table_overlay(frame[:, :, ::-1], config, result)
        write_image(overlay_path, overlay[:, :, ::-1])
    GAME_STORE.record(decision, result, path, captured_at)
    if _CAPTURE_STARTED_AT is not None:
        _SCHEDULE_ANCHOR_AT = _CAPTURE_STARTED_AT
    if decision.phase == GamePhase.FINISHED and result.winner_suit and decision.game_id:
        _resolve_confidence_outcome(config, decision.game_id, result.winner_suit)
    if decision.phase != GamePhase.FINISHED and not result.winner_suit:
        _maybe_winner_hint_alerts(config, decision.game_id)
    _schedule_lay_back_retake(config, decision, path)
    return path


def _try_capture_winner(config: dict) -> bool:
    """Background poll: grab once, save FINISHED exactly once for the open game."""
    global _LAST_DECISION, _LAST_FRAME, _LAST_PATH, _LAST_RESULT
    if not _winner_poll_enabled(config):
        return False

    target_game_id = _winner_poll_target_game_id()
    if not target_game_id:
        return False

    capture = config["capture"]
    page_game_id = read_page_game_id(capture)
    if not page_game_id or page_game_id != target_game_id:
        return False

    try:
        frame = grab_frame(config)
        result = extract_real(frame, config)
    except Exception as exc:
        from game_analyzer.capture_health import record_capture_error

        record_capture_error(exc, context="winner poll grab failed", config=config)
        return False

    if result.game_phase() != GamePhase.FINISHED or not result.winner_suit:
        return False

    with _CAPTURE_MUTEX:
        target_game_id = _winner_poll_target_game_id()
        if not target_game_id:
            return False
        page_game_id = read_page_game_id(capture)
        if page_game_id != target_game_id:
            return False
        if _game_already_has_winner(target_game_id):
            return False

        captured_at = datetime.now()
        previous_game_id = SESSION_TRACKER.session_game_id
        SESSION_TRACKER.timing = _timing_from_config(config)
        decision = SESSION_TRACKER.observe(
            result,
            captured_at,
            game_id=page_game_id,
            timer_seconds=None,
        )
        _maybe_notify_missed_winner(config, previous_game_id, page_game_id)
        if not decision.should_save or decision.phase != GamePhase.FINISHED:
            return False
        if decision.game_id and _game_already_has_winner(decision.game_id):
            return False

        raw_path = _persist_saved_frame(config, decision, result, frame, captured_at)
        _LAST_DECISION = decision
        _LAST_FRAME = frame
        _LAST_PATH = raw_path
        _LAST_RESULT = result
        from game_analyzer.capture_health import record_capture_tick

        record_capture_tick(
            game_id=decision.game_id,
            phase=decision.phase.value if decision.phase else None,
            recording=bool(decision.recording),
            in_progress=False,
            saved=True,
            notes="winner poll",
            config=config,
        )
        return True


class WinnerPollWatcher:
    """Poll for FINISHED while a game is open; never blocks the main capture schedule."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._config: dict | None = None

    def start(self, config: dict) -> None:
        self.stop()
        if not _winner_poll_enabled(config):
            return
        self._config = config
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="winner-poll", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None
        self._config = None

    def _run(self) -> None:
        while not self._stop.is_set():
            config = self._config
            if config is not None:
                try:
                    _try_capture_winner(config)
                except Exception as exc:
                    from game_analyzer.capture_health import record_capture_error

                    record_capture_error(exc, context="winner poll tick failed", config=config)
            if self._stop.wait(_winner_poll_seconds(config or {})):
                break


_WINNER_POLL_WATCHER = WinnerPollWatcher()


def start_winner_poll(config: dict | None = None) -> None:
    _WINNER_POLL_WATCHER.start(config or load_config())


def stop_winner_poll() -> None:
    _WINNER_POLL_WATCHER.stop()


def _maybe_notify_missed_winner(config: dict, previous_game_id: str | None, page_game_id: str | None) -> None:
    if not previous_game_id or not page_game_id or page_game_id == previous_game_id:
        return
    from game_analyzer.ops_alerts import notify_missed_winner

    notify_missed_winner(config, GAME_STORE, previous_game_id)


def capture_once(config: dict | None = None):
    """Grab via screen box or Brave CDP, save PNG + overlay, return paths/result."""
    global _LAST_DECISION, _LAST_FRAME, _LAST_PATH, _LAST_RESULT
    global _CAPTURE_STARTED_AT, _SCHEDULE_ANCHOR_AT, _TIMER_SAMPLED_AT, _FRAME_GRABBED_AT
    config = config or load_config()
    try:
        return _capture_once_impl(config)
    except Exception as exc:
        from game_analyzer.capture_health import record_capture_error

        record_capture_error(exc, context="capture_once failed", config=config)
        raise


def _capture_once_impl(config: dict):
    global _LAST_DECISION, _LAST_FRAME, _LAST_PATH, _LAST_RESULT
    global _CAPTURE_STARTED_AT, _SCHEDULE_ANCHOR_AT, _TIMER_SAMPLED_AT, _FRAME_GRABBED_AT
    _CAPTURE_STARTED_AT = time.monotonic()
    SESSION_TRACKER.timing = _timing_from_config(config)
    capture = config["capture"]
    game_id = read_page_game_id(capture)

    if (
        _LAST_DECISION
        and _LAST_DECISION.peek_id_only
        and game_id
        and game_id == _LAST_DECISION.game_id
    ):
        from game_analyzer.capture_health import record_capture_tick

        record_capture_tick(
            game_id=_LAST_DECISION.game_id,
            phase=_LAST_DECISION.phase.value if _LAST_DECISION.phase else None,
            recording=bool(_LAST_DECISION.recording),
            in_progress=_LAST_RESULT is None or _LAST_RESULT.winner_suit is None,
            saved=False,
            notes="peek id only",
            config=config,
        )
        return _LAST_PATH, _LAST_FRAME, _LAST_RESULT, _LAST_DECISION

    # Sample timer before screenshot/OCR. Waiting "N seconds from capture start" after a
    # post-OCR timer read double-counts processing and fires ~1s early.
    timer = read_page_timer(capture) if timer_sync_enabled(capture) else None
    _TIMER_SAMPLED_AT = time.monotonic()
    timer_seconds = timer.seconds if timer is not None else None

    frame = grab_frame(config)
    _FRAME_GRABBED_AT = time.monotonic()
    result = extract_real(frame, config)
    captured_at = datetime.now()
    previous_game_id = SESSION_TRACKER.session_game_id

    with _CAPTURE_MUTEX:
        decision = SESSION_TRACKER.observe(
            result,
            captured_at,
            game_id=game_id,
            timer_seconds=timer_seconds,
        )
        _maybe_notify_missed_winner(config, previous_game_id, game_id)
        folder = LIVE_DIR / decision.folder_name()
        folder.mkdir(parents=True, exist_ok=True)
        stem = decision.file_stem(captured_at)
        raw_path = folder / f"{stem}.png"
        if decision.should_save:
            if (
                decision.phase == GamePhase.FINISHED
                and decision.game_id
                and _game_already_has_winner(decision.game_id)
            ):
                decision = SessionDecision(
                    recording=decision.recording,
                    session_id=decision.session_id,
                    seq=decision.seq,
                    phase=decision.phase,
                    reason="winner already saved — skip duplicate",
                    should_save=False,
                    next_wait_seconds=decision.next_wait_seconds,
                    wait_mode=decision.wait_mode,
                    watch_result=decision.watch_result,
                    game_id=decision.game_id,
                    peek_id_only=decision.peek_id_only,
                    wait_from_live_timer=decision.wait_from_live_timer,
                    table_cards=decision.table_cards,
                    drawn_cards=decision.drawn_cards,
                )
            else:
                raw_path = _persist_saved_frame(
                    config, decision, result, frame, captured_at, raw_path=raw_path
                )
        _LAST_DECISION = decision
        _LAST_FRAME = frame
        _LAST_PATH = raw_path
        _LAST_RESULT = result

    from game_analyzer.capture_health import record_capture_tick

    record_capture_tick(
        game_id=decision.game_id,
        phase=decision.phase.value if decision.phase else None,
        recording=bool(decision.recording),
        in_progress=result.winner_suit is None,
        saved=bool(decision.should_save),
        notes=result.notes if result else "",
        config=config,
    )
    return raw_path, frame, result, decision


def capture_when_ready(config: dict) -> tuple:
    """Capture, then dual-trigger retry if cards not updated yet."""
    settings = sync_settings_from_config(config)
    capture = config["capture"]
    read_timer = lambda: read_page_timer(capture)

    if not timer_sync_enabled(capture):
        return capture_once(config)

    return retry_until_cards_change(
        settings,
        read_timer,
        lambda: capture_once(config),
        _should_dual_retry,
    )


def _wait_after_capture(config: dict, decision: SessionDecision) -> None:
    global _LAST_WAIT
    capture = config["capture"]
    settings = sync_settings_from_config(config)
    # Live circle waits: anchor to timer sample (not capture/OCR start).
    # Fixed 32/37 waits: subtract processing from the saved-shot anchor.
    if decision.wait_from_live_timer and _TIMER_SAMPLED_AT is not None:
        started_at = _TIMER_SAMPLED_AT
    else:
        started_at = _SCHEDULE_ANCHOR_AT or _CAPTURE_STARTED_AT
    read_timer = lambda: read_page_timer(capture)

    outcome = wait_for_next_capture(
        decision.wait_mode,
        decision.next_wait_seconds,
        settings,
        read_timer,
        started_at=started_at,
    )
    _LAST_WAIT = outcome.trigger


def _maybe_watch_result(config: dict, decision: SessionDecision) -> ResultWatchOutcome | None:
    if not decision.watch_result:
        return None
    if not timer_sync_enabled(config["capture"]):
        return None

    settings = sync_settings_from_config(config)
    capture = config["capture"]
    read_timer = lambda: read_page_timer(capture)

    def _decision_info(saved):
        _path, _frame, _result, dec = saved
        return dec.phase.value, dec.should_save, dec.watch_result

    return run_result_watch(
        settings,
        read_timer,
        lambda: capture_once(config),
        _decision_info,
    )


def grab_and_analyze(delay: float | None = None) -> None:
    config = load_config()
    capture = config["capture"]
    wait = float(delay if delay is not None else capture.get("delay_seconds", 5))
    mode = str(capture.get("mode", "screen"))
    if mode.lower() in {"brave_cdp", "brave", "cdp"}:
        print(f"Mode=brave_cdp  port={capture.get('cdp_port', 9222)}")
        print("Your analyzer UI can stay in front; Brave does not need to be visible.")
        if timer_sync_enabled(capture):
            print("Schedule=hybrid (timer@start → 37s handicap → 32s mid → result poll).")
    else:
        print("Mode=screen  (game must be visible in the capture box)")
        print(
            f"  left={capture['left']}  top={capture['top']}  "
            f"width={capture['width']}  height={capture['height']}"
        )
    print(f"Grabbing in {wait:.0f} seconds…")
    time.sleep(wait)
    _print_capture(capture_when_ready(config), config)


def loop_forever(delay: float | None = None, interval: float | None = None) -> None:
    config = load_config()
    from game_analyzer.capture_health import mark_capture_started, mark_capture_stopped, record_capture_error

    mark_capture_started(source="live_loop", config=config)
    start_winner_poll(config)
    capture = config["capture"]
    wait = float(delay if delay is not None else capture.get("delay_seconds", 5))
    if timer_sync_enabled(capture):
        sync_note = "hybrid schedule (timer@start / 37s / 32s + result poll)"
    else:
        sync_note = "fixed sleeps"
    print(
        f"Mode={capture.get('mode', 'screen')}  first in {wait:.0f}s, "
        f"then {sync_note}. Ctrl+C to stop."
    )
    time.sleep(wait)
    try:
        while True:
            try:
                if _LAST_DECISION is not None:
                    decision = _LAST_DECISION
                    if decision.watch_result:
                        outcome = _maybe_watch_result(config, decision)
                        if outcome is ResultWatchOutcome.FINISHED:
                            if _LAST_DECISION is not None:
                                _print_capture(
                                    (_LAST_PATH, _LAST_FRAME, _LAST_RESULT, _LAST_DECISION),
                                    config,
                                )
                            continue
                        if outcome is ResultWatchOutcome.NEW_ROUND:
                            if _LAST_DECISION is not None:
                                _print_capture(
                                    (_LAST_PATH, _LAST_FRAME, _LAST_RESULT, _LAST_DECISION),
                                    config,
                                )
                            continue
                        # No winner — finish remaining mid-round wait from the draw shot.
                        _wait_after_capture(config, decision)
                    else:
                        _wait_after_capture(config, decision)

                saved = capture_when_ready(config)
                _print_capture(saved, config)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                record_capture_error(exc, context="live loop tick failed", config=config)
                time.sleep(float(capture.get("error_retry_seconds", 5)))
    finally:
        stop_winner_poll()
        mark_capture_stopped(reason="loop exited", config=config)


def print_tabs() -> None:
    config = load_config()
    capture = config["capture"]
    host = str(capture.get("cdp_host", "127.0.0.1"))
    port = int(capture.get("cdp_port", 9222))
    tabs = list_brave_tabs(host, port)
    print(f"Brave tabs on {host}:{port}")
    for tab in tabs:
        if tab.get("type") != "page":
            continue
        print(f"  {tab.get('title', '')[:40]!r}  {tab.get('url', '')}")


def _format_timer(reading: TimerReading | None) -> str:
    if reading is None:
        return "?"
    return f"{reading.seconds}s ({reading.source})"


def _print_capture(saved, config: dict) -> None:
    raw_path, _frame, result, decision = saved
    winner = result.winner_suit.value if result and result.winner_suit else "none"
    cards = ",".join(result.draw_cards) if result and result.draw_cards else "-"
    wait_label = decision.wait_mode.value if decision.wait_mode else "fixed"
    timer = read_page_timer(config["capture"]) if timer_sync_enabled(config["capture"]) else None
    trigger = _LAST_WAIT.value if _LAST_WAIT else "-"
    print(
        f"{raw_path.relative_to(LIVE_DIR) if raw_path else '-'}  phase={decision.phase.value}  "
        f"{decision.reason}  game={decision.game_id or '-'}  "
        f"wait={wait_label}/{decision.next_wait_seconds:.0f}s  trigger={trigger}  "
        f"timer={_format_timer(timer)}  "
        f"winner={winner}  draw=[{cards}]  "
        f"conf=-  "
        f"alert={decision.alert_kind or '-'}  "
        f"[{result.notes if result else ''}]"
    )


def print_monitors() -> None:
    print("Monitors (index 0 is the virtual full desktop):")
    for i, mon in enumerate(list_monitors()):
        print(f"  {i}: {mon}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Screenshot the desktop region in config.json and parse the winner row."
    )
    parser.add_argument("--list-monitors", action="store_true")
    parser.add_argument("--list-tabs", action="store_true", help="list Brave CDP tabs")
    parser.add_argument("--loop", action="store_true", help="grab every interval_seconds until Ctrl+C")
    parser.add_argument("--delay", type=float, default=None, help="seconds before first grab")
    args = parser.parse_args()
    if args.list_monitors:
        print_monitors()
        return
    if args.list_tabs:
        print_tabs()
        return
    if args.loop:
        loop_forever(args.delay)
        return
    grab_and_analyze(args.delay)


if __name__ == "__main__":
    main()
