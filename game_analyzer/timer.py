"""Parse the on-page round countdown from CDP / innerText samples.

Authoritative source: the large circle digit in the top header (0–37).
Footer text like "1st 32 to go" is a LAST RESORT only — it often disagrees with
the circle (e.g. circle=24 while footer still says 32).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TimerReading:
    seconds: int
    source: str  # "header" | "footer"


_FOOTER_RE = re.compile(r"(?:\d+(?:st|nd|rd|th)\s+)?(\d{1,2})\s+to\s+go\b", re.I)


def parse_timer_from_text(text: str) -> TimerReading | None:
    """Best-effort parse from document.body.innerText (unit-testable, no browser)."""
    if not text:
        return None

    header = _header_seconds_from_text(text)
    footer = _footer_seconds_from_text(text)

    if header is not None:
        return TimerReading(seconds=header, source="header")
    if footer is not None:
        return TimerReading(seconds=footer, source="footer")
    return None


def parse_timer_from_cdp_value(value: Any) -> TimerReading | None:
    """Parse the object returned by _TIMER_JS via Runtime.evaluate."""
    if not isinstance(value, dict):
        return None
    seconds = value.get("seconds")
    source = value.get("source")
    if not isinstance(seconds, int) or seconds < 0 or seconds > 60:
        return None
    if source not in {"header", "footer"}:
        return None
    return TimerReading(seconds=seconds, source=source)


def _footer_seconds_from_text(text: str) -> int | None:
    match = _FOOTER_RE.search(text)
    if not match:
        return None
    seconds = int(match.group(1))
    if 0 <= seconds <= 60:
        return seconds
    return None


def _header_seconds_from_text(text: str) -> int | None:
    """Heuristic: a standalone 1–2 digit line near the top, before the betting table."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    # Ignore obvious non-timer numbers in the header block.
    skip_prefixes = ("game id", "round", "back", "lay", "spades", "hearts", "clubs", "diamonds")

    for line in lines[:12]:
        lower = line.lower()
        if any(lower.startswith(prefix) for prefix in skip_prefixes):
            continue
        if _FOOTER_RE.search(line):
            continue
        if re.fullmatch(r"\d{1,2}", line):
            seconds = int(line)
            if 0 <= seconds <= 60:
                return seconds
    return None
