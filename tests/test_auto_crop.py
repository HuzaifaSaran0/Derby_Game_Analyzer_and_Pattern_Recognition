"""auto_crop_derby_panel must not crop game content on winner screens."""

from __future__ import annotations

import numpy as np

from game_analyzer.capture import auto_crop_derby_panel


def _frame(h: int = 800, w: int = 1200) -> np.ndarray:
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    rgb[:] = (40, 40, 40)
    # Site navbar (top ~50px)
    rgb[:50, :] = (230, 230, 230)
    # Handicap grid starts ~60px — must survive crop
    rgb[60:120, 80:260] = (255, 255, 255)
    rgb[120:180, 80:260] = (200, 200, 200)
    return rgb[:, :, ::-1]  # BGR


def test_auto_crop_keeps_handicap_after_finish_flash():
    frame = _frame()
    h, w, _ = frame.shape
    # Simulate finish-line flash in the old scan zone (y=80..120, top quarter)
    frame[90:110, :, :] = (245, 245, 245)
    cropped = auto_crop_derby_panel(frame)
    ch, cw, _ = cropped.shape
    assert ch >= h - 80, f"crop too aggressive: removed {h - ch}px from top"
    assert cw <= w


def test_auto_crop_still_trims_navbar():
    frame = _frame()
    h, w, _ = frame.shape
    cropped = auto_crop_derby_panel(frame)
    ch, _, _ = cropped.shape
    assert ch < h
    assert ch >= h - 75
