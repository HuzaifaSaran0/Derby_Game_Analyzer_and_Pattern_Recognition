"""Grab the already-open game window (same pixels as a manual screenshot).

This does not start Chrome or Chromium. You log into bpexch in any browser,
put the game on screen, then we copy that rectangle and run extract_real.
Works on Ubuntu and on a Windows RDP desktop as long as the game is visible.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from game_analyzer.capture import grab_frame, list_brave_tabs, list_monitors, read_page_game_id
from game_analyzer.config import load_config
from game_analyzer.session import GameSessionTracker, RoundTiming, SessionDecision
from game_analyzer.vision import draw_table_overlay, extract_real, write_image

ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = ROOT / "fixtures" / "live"
SESSION_TRACKER = GameSessionTracker()
_LAST_DECISION: SessionDecision | None = None
_LAST_FRAME = None
_LAST_PATH: Path | None = None
_LAST_RESULT = None


def _timing_from_config(config: dict) -> RoundTiming:
    cap = config.get("capture") or {}
    return RoundTiming(
        round_seconds=float(cap.get("round_seconds", 32)),
        cards_appear_after=float(cap.get("cards_appear_after", 10)),
        start_poll_seconds=float(cap.get("start_poll_seconds", 3)),
    )


def capture_once(config: dict | None = None):
    """Grab via screen box or Brave CDP, save PNG + overlay, return paths/result."""
    global _LAST_DECISION, _LAST_FRAME, _LAST_PATH, _LAST_RESULT
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

    frame = grab_frame(config)
    result = extract_real(frame, config)
    captured_at = datetime.now()
    decision = SESSION_TRACKER.observe(result, captured_at, game_id=game_id)
    folder = LIVE_DIR / decision.folder_name()
    folder.mkdir(parents=True, exist_ok=True)
    stem = decision.file_stem(captured_at)
    raw_path = folder / f"{stem}.png"
    if decision.should_save:
        write_image(raw_path, frame)
        if config.get("draw_overlays", False):
            overlay_path = folder / f"{stem}_boxes.png"
            overlay = draw_table_overlay(frame[:, :, ::-1], config, result)
            write_image(overlay_path, overlay[:, :, ::-1])
    _LAST_DECISION = decision
    _LAST_FRAME = frame
    _LAST_PATH = raw_path
    _LAST_RESULT = result
    return raw_path, frame, result, decision


def grab_and_analyze(delay: float | None = None) -> None:
    config = load_config()
    capture = config["capture"]
    wait = float(delay if delay is not None else capture.get("delay_seconds", 5))
    mode = str(capture.get("mode", "screen"))
    if mode.lower() in {"brave_cdp", "brave", "cdp"}:
        print(f"Mode=brave_cdp  port={capture.get('cdp_port', 9222)}")
        print("Your analyzer UI can stay in front; Brave does not need to be visible.")
    else:
        print("Mode=screen  (game must be visible in the capture box)")
        print(
            f"  left={capture['left']}  top={capture['top']}  "
            f"width={capture['width']}  height={capture['height']}"
        )
    print(f"Grabbing in {wait:.0f} seconds…")
    time.sleep(wait)
    _print_capture(capture_once(config))


def loop_forever(delay: float | None = None, interval: float | None = None) -> None:
    config = load_config()
    capture = config["capture"]
    wait = float(delay if delay is not None else capture.get("delay_seconds", 5))
    print(f"Mode={capture.get('mode', 'screen')}  first in {wait:.0f}s, then on the round clock. Ctrl+C to stop.")
    time.sleep(wait)
    while True:
        saved = capture_once(config)
        _print_capture(saved)
        time.sleep(saved[3].next_wait_seconds)


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


def _print_capture(saved) -> None:
    raw_path, _frame, result, decision = saved
    winner = result.winner_suit.value if result and result.winner_suit else "none"
    cards = ",".join(result.draw_cards) if result and result.draw_cards else "-"
    print(
        f"{raw_path.relative_to(LIVE_DIR) if raw_path else '-'}  phase={decision.phase.value}  "
        f"{decision.reason}  game={decision.game_id or '-'}  next={decision.next_wait_seconds:.0f}s  "
        f"winner={winner}  draw=[{cards}]  [{result.notes if result else ''}]"
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
