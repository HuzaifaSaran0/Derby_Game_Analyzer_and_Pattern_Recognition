from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from game_analyzer.models import Suit

TEMPLATES = Path(__file__).resolve().parent.parent / "fixtures" / "templates" / "cards"
DRAW_INDEX_DIR = TEMPLATES / "indexes" / "draw"
HANDICAP_CARD_DIR = TEMPLATES / "handicap_cards"
CARD_SIZE = (36, 26)  # h, w — normalize every draw-card crop
HANDICAP_CARD_SIZE = (19, 15)  # h, w — full mini-card in the handicap grid
HANDICAP_ROW_SUITS = (Suit.SPADES, Suit.HEARTS, Suit.CLUBS, Suit.DIAMONDS)
_RANK_ORDER = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13}


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
    confident = bool(
        rank and suit and score >= 0.85 and (margin >= 0.012 or score >= 0.98)
    )
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
    crops: list[np.ndarray] = []
    for box in detect_draw_cards(frame_bgr):
        x, y, bw, bh = box
        # Use the detector box tightly — templates were saved the same way.
        crop = rgb[y : y + bh, x : x + bw]
        crops.append(crop)
        cards.append(read_card(crop, box))
    return _reconcile_draw_black_suits(cards, crops)


def _reconcile_draw_black_suits(
    cards: list[CardRead], crops: list[np.ndarray]
) -> list[CardRead]:
    """When one draw card is a confident spade and other black cards tie C/S, use spades."""
    if len(cards) != 3 or len(crops) != 3:
        return cards
    confident_spades = [
        i for i, c in enumerate(cards) if c.suit == Suit.SPADES and c.confident and c.rank
    ]
    if len(confident_spades) != 1:
        return cards
    club_idxs = [i for i, c in enumerate(cards) if c.suit == Suit.CLUBS and c.rank]
    if not club_idxs:
        return cards
    bank = _draw_bank()
    margins: list[float] = []
    for i in club_idxs:
        _rank, _suit, _score, margin = match_card(crops[i], bank)
        margins.append(margin)
    if not all(m < 0.005 for m in margins):
        return cards
    out = list(cards)
    for i in club_idxs:
        c = out[i]
        out[i] = CardRead(
            rank=c.rank,
            suit=Suit.SPADES,
            confident=True,
            box=c.box,
            notes=c.notes,
        )
    return out


def _normalize_handicap_card(card_rgb: np.ndarray) -> np.ndarray:
    return cv2.resize(
        card_rgb,
        (HANDICAP_CARD_SIZE[1], HANDICAP_CARD_SIZE[0]),
        interpolation=cv2.INTER_AREA,
    ).astype(np.float32) / 255.0


def _rank_region(norm_rgb: np.ndarray) -> np.ndarray:
    """Top of a mini-card is the rank; suit pip sits below and confuses 2/3/8/9."""
    h = norm_rgb.shape[0]
    return norm_rgb[: max(4, int(h * 0.58)), :]


def _rank_ink_mask(card_rgb: np.ndarray) -> np.ndarray:
    h, w, _ = card_rgb.shape
    top = card_rgb[: max(3, int(round(h * 0.48))), : max(3, int(w * 0.85))]
    mask = _ink_mask(top)
    ys, xs = np.where(mask)
    if len(ys) == 0:
        return mask
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    return mask[y0:y1, x0:x1]


def _ace_or_four(card_rgb: np.ndarray) -> str | None:
    """Closed-top 4 vs pointed A look alike after 15×19 resize; native ink does not.

    A fills more of the left third and the bottom of the glyph (two legs).
    4 is open on the left and has a thinner bottom bar plus a right stem.
    """
    mask = _rank_ink_mask(card_rgb)
    if mask.size == 0:
        return None
    h, w = mask.shape
    left = float(mask[:, : max(1, w // 3)].mean())
    bot = float(mask[2 * h // 3 :, :].mean()) if h >= 3 else 0.0
    if bot >= 0.68 and left >= 0.54:
        return "A"
    if bot <= 0.64 and left <= 0.52:
        return "4"
    return None


def _digit_shape_bonus(card_rgb: np.ndarray, rank: str) -> float:
    """Tiny 2/3/8/9 and A/4 differ more in native ink shape than in 15×19 NCC."""
    if rank in {"A", "4"}:
        shape = _ace_or_four(card_rgb)
        if shape is None:
            return 0.0
        return 0.08 if shape == rank else -0.08
    if rank not in {"2", "3", "8", "9"}:
        return 0.0
    mask = _rank_ink_mask(card_rgb)
    if mask.size == 0:
        return 0.0
    h, w = mask.shape
    left = float(mask[:, : max(1, w // 3)].mean())
    bot = float(mask[2 * h // 3 :, :].mean()) if h >= 3 else 0.0
    inv = (~mask).astype(np.uint8) * 255
    filled = inv.copy()
    cv2.floodFill(filled, np.zeros((inv.shape[0] + 2, inv.shape[1] + 2), np.uint8), (0, 0), 0)
    holes = int(cv2.connectedComponents((filled == 255).astype(np.uint8))[0] - 1)
    if rank == "8":
        return 0.08 if holes >= 6 and left >= 0.75 else (-0.05 if left < 0.70 else 0.0)
    if rank == "9":
        return 0.08 if 3 <= holes <= 4 and bot < 0.55 else 0.0
    if rank == "3":
        return 0.08 if holes >= 5 and left <= 0.58 else (-0.05 if bot >= 0.84 and holes <= 3 else 0.0)
    if rank == "2":
        return 0.08 if holes <= 3 and bot >= 0.80 else (-0.05 if holes >= 5 and left <= 0.55 else 0.0)
    return 0.0


def _score_handicap_ranks(card_rgb: np.ndarray, suit: Suit) -> list[tuple[str, float]]:
    bank = _handicap_card_bank()
    probe = _normalize_handicap_card(card_rgb)
    probe_rank = _rank_region(probe)
    scores: list[tuple[str, float]] = []
    for (rank, bank_suit), templates in bank.items():
        if bank_suit != suit:
            continue
        full = max(_ncc(probe, tmpl) for tmpl in templates)
        glyph = max(_ncc(probe_rank, _rank_region(tmpl)) for tmpl in templates)
        score = 0.45 * full + 0.55 * glyph + _digit_shape_bonus(card_rgb, rank)
        scores.append((rank, score))
    scores.sort(key=lambda t: t[1], reverse=True)
    return scores


def _pick_q_or_9(candidates: list[str], locked: set[str]) -> str | None:
    options = [c for c in candidates if c in {"Q", "9"} and c not in locked]
    if len(options) != 2:
        return options[0] if len(options) == 1 else None
    locked_vals = [_RANK_ORDER[r] for r in locked if r in _RANK_ORDER]
    if 8 in locked_vals or any(v >= 10 for v in locked_vals):
        return "9"
    if locked_vals and all(v < 9 for v in locked_vals):
        return "Q"
    return options[0]


def _assign_unique_ranks(
    row_scores: list[list[tuple[str, float]]],
) -> list[tuple[str | None, float, float]]:
    """Each handicap row has 3 different ranks — never emit the same rank twice."""
    n = len(row_scores)
    assigned: list[str | None] = [None] * n
    used: set[str] = set()
    for _ in range(n):
        best: tuple[float, int, str] | None = None
        for idx, scores in enumerate(row_scores):
            if assigned[idx] is not None:
                continue
            for rank, score in scores:
                if rank in used:
                    continue
                if best is None or score > best[0]:
                    best = (score, idx, rank)
                break
        if best is None:
            break
        score, idx, rank = best
        assigned[idx] = rank
        used.add(rank)
    # Q and 9 are often identical at this size; only then use the other two ranks.
    for idx, rank in enumerate(assigned):
        if rank not in {"Q", "9"}:
            continue
        by_rank = {r: s for r, s in row_scores[idx]}
        other = "9" if rank == "Q" else "Q"
        if abs(by_rank.get(rank, 0.0) - by_rank.get(other, 0.0)) > 0.02:
            continue
        locked = {r for i, r in enumerate(assigned) if i != idx and r}
        pick = _pick_q_or_9(["Q", "9"], locked)
        if pick and pick not in locked:
            assigned[idx] = pick
            used.discard(rank)
            used.add(pick)
    picks: list[tuple[str | None, float, float]] = []
    for idx, rank in enumerate(assigned):
        scores = row_scores[idx]
        by_rank = {r: s for r, s in scores}
        score = by_rank.get(rank, 0.0) if rank else 0.0
        unused = [s for r, s in scores if r != rank]
        second = unused[0] if unused else 0.0
        picks.append((rank, min(score, 1.0), score - second))
    return picks


_HANDICAP_CARD_BANK: dict[tuple[str, Suit], list[np.ndarray]] | None = None


def _handicap_card_bank() -> dict[tuple[str, Suit], list[np.ndarray]]:
    global _HANDICAP_CARD_BANK
    if _HANDICAP_CARD_BANK is not None:
        return _HANDICAP_CARD_BANK
    bank: dict[tuple[str, Suit], list[np.ndarray]] = {}
    if not HANDICAP_CARD_DIR.exists():
        _HANDICAP_CARD_BANK = bank
        return bank
    for path in HANDICAP_CARD_DIR.glob("*.png"):
        base = path.stem.split("__", 1)[0]
        rank, suit_name = base.rsplit("_", 1)
        bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        bank.setdefault((rank, Suit[suit_name]), []).append(_normalize_handicap_card(rgb))
    _HANDICAP_CARD_BANK = bank
    return bank


def match_handicap_card(card_rgb: np.ndarray, suit: Suit) -> tuple[str | None, float, float]:
    scores = _score_handicap_ranks(card_rgb, suit)
    if not scores:
        return None, 0.0, 0.0
    rank, best = scores[0]
    second = scores[1][1] if len(scores) > 1 else 0.0
    return rank, min(best, 1.0), best - second


def detect_handicap_cards(frame_bgr: np.ndarray) -> list[list[tuple[int, int, int, int]]]:
    rgb = frame_bgr[:, :, ::-1]
    h, w, _ = rgb.shape
    region = rgb[0 : int(h * 0.35), 0 : int(w * 0.35)]
    r, g, b = region[:, :, 0], region[:, :, 1], region[:, :, 2]
    light = ((r > 185) & (g > 185) & (b > 185)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(light, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)

    n, _labels, stats, _cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
    boxes: list[tuple[int, int, int, int]] = []
    for i in range(1, n):
        x, y, bw, bh, area = map(int, stats[i])
        if area < 80 or area > 3000:
            continue
        if bw < 8 or bh < 10 or bw > 50 or bh > 50:
            continue
        if x < 40:
            continue
        boxes.append((x, y, bw, bh))

    rows: list[list[tuple[int, int, int, int]]] = []
    for box in boxes:
        for row in rows:
            if abs(row[0][1] - box[1]) <= 6:
                row.append(box)
                break
        else:
            rows.append([box])
    rows.sort(key=lambda group: group[0][1])
    return [sorted(row, key=lambda t: t[0])[:3] for row in rows if len(row) >= 3][:4]


def read_handicap_cards(frame_bgr: np.ndarray) -> tuple[tuple[str, ...], ...]:
    rgb = frame_bgr[:, :, ::-1]
    grid: list[tuple[str, ...]] = []
    for row_idx, row_boxes in enumerate(detect_handicap_cards(frame_bgr)):
        if row_idx >= len(HANDICAP_ROW_SUITS):
            break
        suit = HANDICAP_ROW_SUITS[row_idx]
        row_scores = []
        crops: list[np.ndarray] = []
        for box in row_boxes:
            x, y, bw, bh = box
            crop = rgb[y : y + bh, x : x + bw]
            crops.append(crop)
            row_scores.append(_score_handicap_ranks(crop, suit))
        picks = _assign_unique_ranks(row_scores)
        used = {rank for rank, _, _ in picks if rank}
        corrected: list[tuple[str | None, float, float]] = []
        for crop, (rank, score, margin) in zip(crops, picks):
            if rank in {"A", "4"}:
                shape = _ace_or_four(crop)
                if shape and shape != rank and shape not in used:
                    used.discard(rank)
                    used.add(shape)
                    rank = shape
            corrected.append((rank, score, margin))
        picks = corrected
        labels: list[str] = []
        for rank, score, margin in picks:
            confident = bool(rank and score >= 0.80 and (margin >= 0.010 or score >= 0.92))
            if confident and rank:
                labels.append(f"{rank}{suit.value[0]}")
            else:
                labels.append(f"?{suit.value[0]}")
        if len(labels) == 3:
            grid.append(tuple(labels))
    return tuple(grid)
