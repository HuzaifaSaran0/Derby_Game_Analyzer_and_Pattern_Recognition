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

from game_analyzer.capture import grab_frame, list_brave_tabs, list_monitors
from game_analyzer.config import load_config
from game_analyzer.vision import draw_table_overlay, extract_real, write_image

ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = ROOT / "fixtures" / "live"


def capture_once(config: dict | None = None):
    """Grab via screen box or Brave CDP, save PNG + overlay, return paths/result."""
    config = config or load_config()
    frame = grab_frame(config)
    result = extract_real(frame, config)
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%H-%M-%S-%f")[:15]
    raw_path = LIVE_DIR / f"live_{stamp}.png"
    overlay_path = LIVE_DIR / f"live_{stamp}_boxes.png"
    write_image(raw_path, frame)
    overlay = draw_table_overlay(frame[:, :, ::-1], config, result)
    write_image(overlay_path, overlay[:, :, ::-1])
    return raw_path, frame, result


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
    every = float(interval if interval is not None else capture.get("interval_seconds", 30))
    print(f"Mode={capture.get('mode', 'screen')}  first in {wait:.0f}s, every {every:.0f}s. Ctrl+C to stop.")
    time.sleep(wait)
    while True:
        _print_capture(capture_once(config))
        time.sleep(every)


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
    raw_path, _frame, result = saved
    winner = result.winner_suit.value if result.winner_suit else "none"
    print(
        f"{raw_path.name}  state={result.race_state.value}  winner={winner}  "
        f"[{result.notes}]"
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
