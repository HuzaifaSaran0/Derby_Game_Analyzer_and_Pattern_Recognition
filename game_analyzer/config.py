from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.json"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG
    with config_path.open() as handle:
        return json.load(handle)


def crop_box(roi: dict[str, int]) -> tuple[int, int, int, int]:
    """Return OpenCV slice bounds: y0, y1, x0, x1."""
    x = int(roi["left"])
    y = int(roi["top"])
    w = int(roi["width"])
    h = int(roi["height"])
    return y, y + h, x, x + w
