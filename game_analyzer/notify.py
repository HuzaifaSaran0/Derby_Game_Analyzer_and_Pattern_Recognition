"""Desktop notifications (OS toast) — not the in-app alert banner."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TWIN_LOG = ROOT / "data" / "twins.log"


def send_desktop_notification(
    title: str,
    body: str,
    *,
    urgency: str = "normal",
    expire_ms: int = 8000,
) -> bool:
    """Fire a system notification via notify-send when available."""
    binary = shutil.which("notify-send")
    if not binary:
        return False
    try:
        subprocess.run(
            [
                binary,
                "--app-name=Game Analyzer",
                f"--urgency={urgency}",
                f"--expire-time={expire_ms}",
                title,
                body,
            ],
            check=False,
            timeout=5,
            capture_output=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def append_twin_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(message.rstrip() + "\n")
