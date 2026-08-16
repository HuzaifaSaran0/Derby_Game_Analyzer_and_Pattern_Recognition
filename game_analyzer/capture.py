from __future__ import annotations

from typing import Any

import numpy as np


def grab_region(region: dict[str, int]) -> np.ndarray:
    """Capture a screen rectangle. Returns a BGR OpenCV image."""
    import mss

    with mss.mss() as sct:
        raw = np.array(sct.grab(region))
    # mss is BGRA
    return raw[:, :, :3]
