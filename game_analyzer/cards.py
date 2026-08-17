from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from game_analyzer.models import Suit

TEMPLATES = Path(__file__).resolve().parent.parent / "fixtures" / "templates" / "cards"
DRAW_INDEX_DIR = TEMPLATES / "indexes" / "draw"
HANDICAP_INDEX_DIR = TEMPLATES / "indexes" / "handicap"
CARD_SIZE = (36, 26)  # h, w — normalize every draw-card crop


@dataclass(frozen=True)
class CardRead:
    rank: str | None
    suit: Suit | None
    confident: bool
    box: tuple[int, int, int, int]
    notes: str = ""

    def label(self) -> str:
        suit_letter = self.suit.value[0] if self.suit else "?"
        return f"{self.rank or '?'}{suit_letter}"


def _ink_mask(rgb: np.ndarray) -> np.ndarray:
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    return ~((r > 195) & (g > 195) & (b > 195))


def _normalize_card(card_rgb: np.ndarray) -> np.ndarray:
    return cv2.resize(card_rgb, (CARD_SIZE[1], CARD_SIZE[0]), interpolation=cv2.INTER_AREA).astype(
        np.float32
    ) / 255.0


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    af = a.astype(np.float32).ravel()
    bf = b.astype(np.float32).ravel()
    af -= af.mean()
    bf -= bf.mean()
    denom = float(np.linalg.norm(af) * np.linalg.norm(bf))
    if denom < 1e-6:
        return 0.0
    return float(np.dot(af, bf) / denom)


def _parse_name(name: str) -> tuple[str, Suit]:
    base = name.split("__", 1)[0]
    rank, suit = base.rsplit("_", 1)
    return rank, Suit[suit]


def _is_red_card(card_rgb: np.ndarray) -> bool:
    ink = card_rgb[_ink_mask(card_rgb)]
    if len(ink) == 0:
        return False
    return float((ink[:, 0] > ink[:, 2] + 20).mean()) > 0.25


def _red_suit_from_shape(card_rgb: np.ndarray) -> Suit | None:
    """Heart has a top cleft; diamond is a solid rhombus. Used when NCC ties."""
    ink = _ink_mask(card_rgb)
    h, w = ink.shape
    region = ink[h // 2 : int(h * 0.90), : int(w * 0.70)]
    if int(region.sum()) < 10:
        return None
    ys, xs = np.where(region)
    top_y, bot_y = int(ys.min()), int(ys.max())
    left_x, right_x = int(xs.min()), int(xs.max())
    if bot_y - top_y < 4 or right_x - left_x < 3:
        return None
    # Top band of the suit glyph: hearts show two lobes with a center gap.
    band = region[top_y : top_y + max(2, (bot_y - top_y) // 4), left_x : right_x + 1]
    col_fill = band.mean(axis=0)
    mid = col_fill.shape[0] // 2
    left = float(col_fill[: max(1, mid - 1)].max()) if mid > 1 else 0.0
    right = float(col_fill[min(col_fill.shape[0] - 1, mid + 1) :].max()) if mid < col_fill.shape[0] - 1 else 0.0
    center = float(col_fill[max(0, mid - 1) : mid + 2].mean())
    if left > 0.35 and right > 0.35 and center < 0.2 * max(left, right):
        return Suit.HEARTS
    # Width profile: diamond peaks near the middle; heart peaks nearer the top.
    widths: list[int] = []
    for y in range(top_y, bot_y + 1):
        row = np.where(region[y, left_x : right_x + 1])[0]
        widths.append(int(row.max() - row.min() + 1) if len(row) else 0)
    if not any(widths):
        return None
    peak = int(np.argmax(widths))
    return Suit.DIAMONDS if peak >= len(widths) * 0.35 else Suit.HEARTS


def _load_bank(folder: Path) -> dict[str, np.ndarray]:
    bank: dict[str, np.ndarray] = {}
    if not folder.exists():
        return bank
    for path in folder.glob("*.png"):
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        bank[path.stem] = _normalize_card(rgb)
    return bank


_DRAW_BANK: dict[str, np.ndarray] | None = None


def _draw_bank() -> dict[str, np.ndarray]:
    global _DRAW_BANK
    if _DRAW_BANK is None:
        _DRAW_BANK = _load_bank(DRAW_INDEX_DIR)
    return _DRAW_BANK


def match_card(card_rgb: np.ndarray, bank: dict[str, np.ndarray]) -> tuple[str | None, Suit | None, float, float]:
    if not bank:
        return None, None, 0.0, 0.0
    red = _is_red_card(card_rgb)
    probe = _normalize_card(card_rgb)
    shape_suit = _red_suit_from_shape(card_rgb) if red else None

    best_by_label: dict[tuple[str, Suit], float] = {}
    for name, tmpl in bank.items():
        rank, suit = _parse_name(name)
        if red and suit not in {Suit.HEARTS, Suit.DIAMONDS}:
            continue
        if not red and suit not in {Suit.SPADES, Suit.CLUBS}:
            continue
        score = _ncc(probe, tmpl)
        # Prefer the suit that matches the glyph shape when look-alikes collide.
        if shape_suit is not None and suit == shape_suit:
            score += 0.03
        elif shape_suit is not None and suit in {Suit.HEARTS, Suit.DIAMONDS}:
            score -= 0.03
        key = (rank, suit)
        if score > best_by_label.get(key, -1.0):
            best_by_label[key] = score

    if not best_by_label:
        return None, None, 0.0, 0.0
    ranked = sorted(best_by_label.items(), key=lambda t: t[1], reverse=True)
    (rank, suit), best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    # Report unboosted-style margin; clamp display score into [0, 1].
    best = min(best, 1.0)
    return rank, suit, best, best - min(second, 1.0)


def read_card(card_rgb: np.ndarray, box: tuple[int, int, int, int]) -> CardRead:
    rank, suit, score, margin = match_card(card_rgb, _draw_bank())
    confident = bool(rank and suit and score >= 0.85 and margin >= 0.012)
    return CardRead(
        rank=rank,
        suit=suit,
        confident=confident,
        box=box,
        notes=f"score={score:.2f} margin={margin:.2f}",
    )


def detect_draw_cards(frame_bgr: np.ndarray) -> list[tuple[int, int, int, int]]:
    rgb = frame_bgr[:, :, ::-1]
    h, w, _ = rgb.shape
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    light = ((r > 185) & (g > 185) & (b > 185)).astype(np.uint8) * 255

    mask = np.zeros_like(light)
    mask[int(h * 0.40) : int(h * 0.78), 0 : int(w * 0.45)] = light[
        int(h * 0.40) : int(h * 0.78), 0 : int(w * 0.45)
    ]
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)

    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes: list[tuple[int, int, int, int]] = []
    for i in range(1, n):
        x, y, bw, bh, area = map(int, stats[i])
        if area < 250 or area > 5000:
            continue
        if bw < 16 or bh < 22 or bw > 70 or bh > 90:
            continue
        aspect = bh / max(bw, 1)
        if aspect < 1.05 or aspect > 2.4:
            continue
        boxes.append((x, y, bw, bh))

    if len(boxes) < 3:
        return sorted(boxes, key=lambda t: t[0])

    best: list[tuple[int, int, int, int]] = []
    for box in boxes:
        group = [b for b in boxes if abs(b[1] - box[1]) <= 12]
        if len(group) > len(best):
            best = group
    return sorted(best, key=lambda t: t[0])[:3]


def read_draw_cards(frame_bgr: np.ndarray) -> list[CardRead]:
    rgb = frame_bgr[:, :, ::-1]
    cards: list[CardRead] = []
    for box in detect_draw_cards(frame_bgr):
        x, y, bw, bh = box
        # Use the detector box tightly — templates were saved the same way.
        crop = rgb[y : y + bh, x : x + bw]
        cards.append(read_card(crop, box))
    return cards
