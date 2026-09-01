from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG
    with config_path.open() as handle:
        data = json.load(handle)
    if path is None:
        local_path = config_path.parent / "config.local.json"
        if local_path.is_file():
            with local_path.open() as handle:
                data = _deep_merge(data, json.load(handle))
    return data


def crop_box(roi: dict[str, int]) -> tuple[int, int, int, int]:
    """Return OpenCV slice bounds: y0, y1, x0, x1."""
    x = int(roi["left"])
    y = int(roi["top"])
    w = int(roi["width"])
    h = int(roi["height"])
    return y, y + h, x, x + w
