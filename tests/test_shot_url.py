"""Shot URL cache busting after lay/back retake replaces a PNG."""

from __future__ import annotations

import time
from pathlib import Path

from game_analyzer.web.__init__ import _shot_cache_token, _shot_url


def test_shot_url_changes_when_file_replaced(tmp_path: Path):
    shot = tmp_path / "fixtures" / "live" / "game_1" / "001.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"v1")
    captured = "2026-08-28T12:00:00"
    url1 = _shot_url("1", 1, shot, captured)
    time.sleep(0.05)
    shot.write_bytes(b"v2")
    url2 = _shot_url("1", 1, shot, captured)
    assert url1 != url2
    assert captured in url1
    assert captured in url2


def test_shot_cache_token_fallback(tmp_path: Path):
    missing = tmp_path / "nope.png"
    assert _shot_cache_token(missing, "2026-01-01") == "2026-01-01"
