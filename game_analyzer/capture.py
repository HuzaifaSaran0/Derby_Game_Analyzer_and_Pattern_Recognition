from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.error
import urllib.request
from io import BytesIO
from urllib.parse import urlparse

import numpy as np
from PIL import Image


def list_monitors() -> list[dict]:
    """Screen rectangles mss can see (same on Ubuntu and Windows)."""
    import mss

    with mss.mss() as sct:
        return list(sct.monitors)


def grab_region(region: dict[str, int]) -> np.ndarray:
    """Grab a desktop rectangle. Needs the game visible in that box."""
    import mss

    box = {
        "left": int(region["left"]),
        "top": int(region["top"]),
        "width": int(region["width"]),
        "height": int(region["height"]),
    }
    with mss.mss() as sct:
        raw = np.array(sct.grab(box))
    return raw[:, :, :3]


def list_brave_tabs(host: str = "127.0.0.1", port: int = 9222) -> list[dict]:
    """Tabs exposed by Brave/Chrome when started with --remote-debugging-port."""
    url = f"http://{host}:{port}/json"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Cannot reach Brave debug port at {url}. "
            "Close all Brave windows, then start Brave with "
            f"--remote-debugging-port={port} and open the game tab."
        ) from exc


def _pick_game_tab(tabs: list[dict], url_contains: str) -> dict:
    pages = [t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
    matches = [t for t in pages if url_contains.lower() in (t.get("url") or "").lower()]
    if matches:
        return matches[0]
    if pages:
        names = ", ".join((t.get("url") or "?")[:60] for t in pages[:5])
        raise RuntimeError(
            f"No tab URL contains '{url_contains}'. Open pages: {names}"
        )
    raise RuntimeError("No browser pages found on the debug port.")


def _ws_recv_frame(sock: socket.socket) -> bytes:
    header = sock.recv(2)
    if len(header) < 2:
        raise RuntimeError("CDP websocket closed early")
    length = header[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", sock.recv(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", sock.recv(8))[0]
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise RuntimeError("CDP websocket closed while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _ws_send_text(sock: socket.socket, text: str) -> None:
    payload = text.encode("utf-8")
    header = bytearray([0x81])
    mask_bit = 0x80
    n = len(payload)
    if n < 126:
        header.append(mask_bit | n)
    elif n < 65536:
        header.append(mask_bit | 126)
        header.extend(struct.pack("!H", n))
    else:
        header.append(mask_bit | 127)
        header.extend(struct.pack("!Q", n))
    mask = os.urandom(4)
    header.extend(mask)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    sock.sendall(header + masked)


def _cdp_screenshot_png(ws_url: str) -> bytes:
    parsed = urlparse(ws_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 9222
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    key = base64.b64encode(os.urandom(16)).decode("ascii")
    req = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    sock = socket.create_connection((host, port), timeout=10)
    try:
        sock.sendall(req.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("CDP websocket handshake failed")
            response += chunk
        if b"101" not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(f"CDP websocket handshake rejected: {response[:200]!r}")

        msg_id = 1
        _ws_send_text(
            sock,
            json.dumps(
                {
                    "id": msg_id,
                    "method": "Page.captureScreenshot",
                    "params": {"format": "png", "fromSurface": True},
                }
            ),
        )
        while True:
            payload = _ws_recv_frame(sock)
            data = json.loads(payload.decode("utf-8"))
            if data.get("id") != msg_id:
                continue
            if "error" in data:
                raise RuntimeError(f"CDP screenshot failed: {data['error']}")
            return base64.b64decode(data["result"]["data"])
    finally:
        sock.close()


def _png_bytes_to_bgr(png_bytes: bytes) -> np.ndarray:
    rgb = np.array(Image.open(BytesIO(png_bytes)).convert("RGB"))
    return rgb[:, :, ::-1].copy()


def _apply_crop(frame: np.ndarray, crop: dict | None) -> np.ndarray:
    if not crop:
        return frame
    h, w = frame.shape[:2]
    left = max(0, min(int(crop.get("left", 0)), w - 1))
    top = max(0, min(int(crop.get("top", 0)), h - 1))
    width = int(crop.get("width", w - left))
    height = int(crop.get("height", h - top))
    width = max(1, min(width, w - left))
    height = max(1, min(height, h - top))
    return frame[top : top + height, left : left + width].copy()


def auto_crop_derby_panel(frame: np.ndarray) -> np.ndarray:
    """Keep Derby Race only: drop sidebar, Matched Bets, and top site/game navbar."""
    rgb = frame[:, :, ::-1]
    h, w, _ = rgb.shape
    mid = rgb[h // 5 : (4 * h) // 5]
    lum = mid.mean(axis=2)
    white = (lum > 220).mean(axis=0)
    dark = (lum < 80).mean(axis=0)

    # Left = end of dark sidebar (+ thin white gutter).
    # Do not stop on a single bright icon column inside the nav — that used to
    # leave the whole sidebar in when CDP returned a wider tab.
    left = 0
    if dark[:15].mean() >= 0.35:
        gutter = None
        for x in range(40, w // 3):
            if white[x] <= 0.85:
                continue
            run = 0
            while x + run < w // 3 and white[x + run] > 0.85:
                run += 1
            if run >= 3 and dark[max(0, x - 30) : x].mean() > 0.45:
                gutter = x + run
                break
        if gutter is not None:
            left = gutter
        else:
            # Fallback: long dark run, then skip any white gutter.
            run = 0
            end = 0
            for x in range(w // 3):
                if dark[x] > 0.55:
                    run += 1
                    end = x
                else:
                    if run >= 50:
                        x2 = end + 1
                        while x2 < w // 3 and white[x2] > 0.5:
                            x2 += 1
                        left = x2
                        break
                    run = 0

    # Right = before the tall white Matched Bets panel.
    right = w
    run = 0
    for x in range(w - 1, w // 2, -1):
        if white[x] > 0.65:
            run += 1
            if run >= 30:
                right = x + 1
                while right > w // 2 and white[right - 1] > 0.65:
                    right -= 1
                break
        else:
            run = 0

    # Top = below Dashboard + Lobby/Hold'em teal navbar (last bright band in top quarter).
    row = rgb.mean(axis=(1, 2))
    top = 0
    y_limit = max(40, h // 4)
    in_bright = False
    last_bright_end = 0
    for y in range(y_limit):
        bright = row[y] > 170
        if bright:
            in_bright = True
            last_bright_end = y
        elif in_bright:
            last_bright_end = y
            in_bright = False
    if last_bright_end > 20:
        top = min(h - 50, last_bright_end + 2)

    if right - left < w // 3:
        return frame
    return frame[top:h, left:right].copy()


def grab_brave_tab(capture: dict) -> np.ndarray:
    """Screenshot the bpexch tab via Brave CDP. Works even if our app is in front.

    Brave must be started with --remote-debugging-port (same on Ubuntu and Windows).
    """
    host = str(capture.get("cdp_host", "127.0.0.1"))
    port = int(capture.get("cdp_port", 9222))
    needle = str(capture.get("url_contains", "bpexch.live"))
    tabs = list_brave_tabs(host, port)
    tab = _pick_game_tab(tabs, needle)
    png = _cdp_screenshot_png(tab["webSocketDebuggerUrl"])
    frame = _png_bytes_to_bgr(png)
    crop = capture.get("page_crop")
    if crop:
        return _apply_crop(frame, crop)
    if capture.get("auto_crop", True):
        return auto_crop_derby_panel(frame)
    return frame


def grab_frame(config: dict) -> np.ndarray:
    """Capture using config['capture']['mode']: 'screen' or 'brave_cdp'."""
    capture = config["capture"]
    mode = str(capture.get("mode", "screen")).lower()
    if mode in {"brave_cdp", "brave", "cdp"}:
        return grab_brave_tab(capture)
    return grab_region(capture)
