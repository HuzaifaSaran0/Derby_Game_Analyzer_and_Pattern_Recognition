"""Grab the already-open game window (same pixels as a manual screenshot).

Hybrid schedule (brave_cdp):
  - first shot of a game: read on-page timer, sleep that many seconds
  - after handicap: sleep ~37s to first draw
  - mid draws: sleep ~32s
  - after each IN_PLAY: poll ~13s for WINNER
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

from game_analyzer.alerts import alert_settings_from_config, deliver_similarity_alert
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
# Late-round (R3+) twin alerts: dedupe per live game / round.
_LATE_ROUND_GAME_ID: str | None = None
_LATE_ROUND_ALERTED: set[str] = set()
_LAST_LATE_SIGNALS: dict[int, object] = {}
_RETAKE_PREVIEW_HOOK: Callable[[Path, object, str | None], None] | None = None


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


def _maybe_late_round_alerts(config: dict, decision: SessionDecision) -> None:
    """Alert when R3/R4/R5 draw cards exactly match past games (cascade).

    Independent of handicap twin browsing.
    """
    global _LATE_ROUND_GAME_ID, _LATE_ROUND_ALERTED, _LAST_LATE_SIGNALS
    sim = config.get("similarity") or {}
    if sim.get("notify", True) is False:
        return
    if sim.get("late_rounds", True) is False:
        return
    if not decision.recording or not decision.should_save:
        return
    draws = tuple(decision.drawn_cards or ())
    if not draws:
        return

    from game_analyzer.similarity import (
        LATE_ROUND_MAX,
        LATE_ROUND_MIN,
        full_draw_rounds,
    )

    game_id = decision.game_id
    if game_id and game_id != _LATE_ROUND_GAME_ID:
        _LATE_ROUND_GAME_ID = game_id
        _LATE_ROUND_ALERTED = set()
        _LAST_LATE_SIGNALS = {}

    rounds_seen = full_draw_rounds(draws)
    if rounds_seen < LATE_ROUND_MIN:
        return

    max_round = int(sim.get("late_round_max", LATE_ROUND_MAX))
    signals = GAME_STORE.late_round_cascade(
        draws,
        live_game_id=game_id,
        max_round=max_round,
    )
    settings = alert_settings_from_config(config)
    for round_n, signal in signals.items():
        if round_n < LATE_ROUND_MIN:
            continue
        dedupe = f"{game_id or 'live'}:{round_n}"
        if dedupe in _LATE_ROUND_ALERTED:
            continue
        _LATE_ROUND_ALERTED.add(dedupe)
        _LAST_LATE_SIGNALS[round_n] = signal
        deliver_similarity_alert(
            settings,
            alert_kind=signal.kind,
            alert_message=signal.message,
        )


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


def capture_once(config: dict | None = None):
    """Grab via screen box or Brave CDP, save PNG + overlay, return paths/result."""
    global _LAST_DECISION, _LAST_FRAME, _LAST_PATH, _LAST_RESULT
    global _CAPTURE_STARTED_AT, _SCHEDULE_ANCHOR_AT, _TIMER_SAMPLED_AT, _FRAME_GRABBED_AT
    _CAPTURE_STARTED_AT = time.monotonic()
    config = config or load_config()
    SESSION_TRACKER.timing = _timing_from_config(config)
    capture = config["capture"]
    game_id = read_page_game_id(capture)

    if (
        _LAST_DECISION
        and _LAST_DECISION.peek_id_only
        and game_id
        and game_id == _LAST_DECISION.game_id
    ):
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
    decision = SESSION_TRACKER.observe(
        result,
        captured_at,
        game_id=game_id,
        timer_seconds=timer_seconds,
    )
    folder = LIVE_DIR / decision.folder_name()
    folder.mkdir(parents=True, exist_ok=True)
    stem = decision.file_stem(captured_at)
    raw_path = folder / f"{stem}.png"
    if decision.should_save:
        save_frame = frame
        if decision.phase == GamePhase.FINISHED:
            settle = float(capture.get("finished_capture_settle_seconds", 0.5))
            if settle > 0:
                time.sleep(settle)
                save_frame = grab_frame(config)
        write_image(raw_path, save_frame)
        if config.get("draw_overlays", False):
            overlay_path = folder / f"{stem}_boxes.png"
            overlay = draw_table_overlay(frame[:, :, ::-1], config, result)
            write_image(overlay_path, overlay[:, :, ::-1])
        GAME_STORE.record(decision, result, raw_path, captured_at)
        # Anchor fixed 32/37 schedule waits to saved shots (not result-window peeks).
        _SCHEDULE_ANCHOR_AT = _CAPTURE_STARTED_AT
        _maybe_late_round_alerts(config, decision)
        # ~9s later the back/lay table is on screen: swap the PNG in place (analysis
        # above already ran on this frame; timing of the next shot is unaffected).
        _schedule_lay_back_retake(config, decision, raw_path)
    _LAST_DECISION = decision
    _LAST_FRAME = frame
    _LAST_PATH = raw_path
    _LAST_RESULT = result
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
    while True:
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
