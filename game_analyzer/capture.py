from __future__ import annotations

import numpy as np


def list_monitors() -> list[dict]:
    """Screen rectangles mss can see (same on Ubuntu and Windows)."""
    import mss

    with mss.mss() as sct:
        return list(sct.monitors)


def grab_region(region: dict[str, int]) -> np.ndarray:
    """Grab a desktop rectangle. Chrome/Firefox/Edge — whatever is in that box.

    Does not open a browser. Returns BGR uint8 (same as our saved screenshots).
    """
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
