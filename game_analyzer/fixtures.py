from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from game_analyzer.models import ExtractionResult, HighLow, RaceState, Suit
from game_analyzer.vision import write_image

ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = ROOT / "fixtures"
IMAGES_DIR = FIXTURES_DIR / "images"
TEMPLATES_DIR = FIXTURES_DIR / "templates"
GROUND_TRUTH = FIXTURES_DIR / "ground_truth.json"

FRAME_W, FRAME_H = 640, 360
TEMPLATE_SIZE = 64


def _blank_frame() -> np.ndarray:
    return np.full((FRAME_H, FRAME_W, 3), 30, dtype=np.uint8)


def _fill_roi(frame: np.ndarray, roi: dict[str, int], color: tuple[int, int, int]) -> None:
    x, y, w, h = roi["left"], roi["top"], roi["width"], roi["height"]
    frame[y : y + h, x : x + w] = color


def _letter_mask(letter: str, size: int = TEMPLATE_SIZE) -> np.ndarray:
    """Tiny 5x5 bitmap letters so we do not need OpenCV fonts."""
    glyphs = {
        "S": [
            "01110",
            "10000",
            "01100",
            "00001",
            "01110",
        ],
        "H": [
            "10001",
            "10001",
            "11111",
            "10001",
            "10001",
        ],
        "C": [
            "01110",
            "10001",
            "10000",
            "10001",
            "01110",
        ],
        "D": [
            "11100",
            "10010",
            "10001",
            "10010",
            "11100",
        ],
    }
    grid = np.array([[c == "1" for c in row] for row in glyphs[letter]], dtype=np.uint8)
    scale = size // 8
    return np.kron(grid, np.ones((scale, scale), dtype=np.uint8))


def make_suit_template(suit: Suit) -> np.ndarray:
    colors = {
        Suit.SPADES: (40, 40, 40),
        Suit.HEARTS: (40, 40, 200),
        Suit.CLUBS: (40, 160, 40),
        Suit.DIAMONDS: (20, 120, 200),
    }
    letters = {
        Suit.SPADES: "S",
        Suit.HEARTS: "H",
        Suit.CLUBS: "C",
        Suit.DIAMONDS: "D",
    }
    img = np.full((TEMPLATE_SIZE, TEMPLATE_SIZE, 3), 20, dtype=np.uint8)
    yy, xx = np.ogrid[:TEMPLATE_SIZE, :TEMPLATE_SIZE]
    circle = (xx - 31) ** 2 + (yy - 31) ** 2 <= 26**2
    img[circle] = colors[suit]
    mask = _letter_mask(letters[suit])
    y0 = (TEMPLATE_SIZE - mask.shape[0]) // 2
    x0 = (TEMPLATE_SIZE - mask.shape[1]) // 2
    y1, x1 = y0 + mask.shape[0], x0 + mask.shape[1]
    img[y0:y1, x0:x1][mask.astype(bool)] = (255, 255, 255)
    return img


def write_templates() -> None:
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    for suit in Suit:
        write_image(TEMPLATES_DIR / f"suit_{suit.value.lower()}.png", make_suit_template(suit))


def generate(config: dict) -> list[str]:
    write_templates()
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    rois = config["rois"]
    records: dict[str, dict] = {}

    cases: list[tuple[str, RaceState, Suit | None, HighLow | None]] = [
        ("in_progress.png", RaceState.IN_PROGRESS, None, None),
    ]
    for suit in Suit:
        for hl in HighLow:
            name = f"finished_{suit.value.lower()}_{hl.value.lower()}.png"
            cases.append((name, RaceState.FINISHED, suit, hl))

    for filename, state, suit, high_low in cases:
        frame = _blank_frame()
        if state == RaceState.FINISHED:
            _fill_roi(frame, rois["banner"], (40, 180, 40))
        else:
            _fill_roi(frame, rois["banner"], (70, 70, 70))

        if suit is not None:
            template = make_suit_template(suit)
            x, y = rois["suit"]["left"], rois["suit"]["top"]
            th, tw = template.shape[:2]
            frame[y : y + th, x : x + tw] = template
        else:
            _fill_roi(frame, rois["suit"], (50, 50, 50))

        if high_low == HighLow.HIGH:
            _fill_roi(frame, rois["high_low"], (20, 180, 220))
        elif high_low == HighLow.LOW:
            _fill_roi(frame, rois["high_low"], (200, 200, 40))
        else:
            _fill_roi(frame, rois["high_low"], (50, 50, 50))

        write_image(IMAGES_DIR / filename, frame)
        records[f"images/{filename}"] = {
            "race_state": state.value,
            "winner_suit": suit.value if suit else None,
            "high_low": high_low.value if high_low else None,
        }

    GROUND_TRUTH.write_text(json.dumps(records, indent=2) + "\n")
    return list(records)


def load_ground_truth() -> dict:
    return json.loads(GROUND_TRUTH.read_text())


def consensus(results: list[ExtractionResult], needed: int) -> ExtractionResult | None:
    if len(results) < needed:
        return None
    window = results[-needed:]
    keys = [(r.race_state, r.winner_suit, r.high_low, r.confident) for r in window]
    _, count = Counter(keys).most_common(1)[0]
    if count != needed:
        return None
    return window[-1]
