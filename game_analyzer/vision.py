from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from game_analyzer.config import crop_box
from game_analyzer.models import ExtractionResult, HighLow, RaceState, Suit

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "templates"

_SUIT_FILES = {
    Suit.SPADES: "suit_spades.png",
    Suit.HEARTS: "suit_hearts.png",
    Suit.CLUBS: "suit_clubs.png",
    Suit.DIAMONDS: "suit_diamonds.png",
}


def read_image(path: Path) -> np.ndarray:
    """Load an image as BGR uint8 (same channel order as OpenCV)."""
    rgb = np.array(Image.open(path).convert("RGB"))
    return rgb[:, :, ::-1].copy()


def write_image(path: Path, bgr: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = bgr[:, :, ::-1]
    Image.fromarray(rgb).save(path)


def _crop(frame: np.ndarray, roi: dict[str, int]) -> np.ndarray:
    y0, y1, x0, x1 = crop_box(roi)
    return frame[y0:y1, x0:x1]


def _mean_bgr(crop: np.ndarray) -> tuple[float, float, float]:
    mean = crop.reshape(-1, 3).mean(axis=0)
    return float(mean[0]), float(mean[1]), float(mean[2])


def classify_banner(crop: np.ndarray) -> RaceState:
    b, g, r = _mean_bgr(crop)
    if g > r + 40 and g > b + 40:
        return RaceState.FINISHED
    if r > g + 40 and r > b + 40:
        return RaceState.FINISHED
    return RaceState.IN_PROGRESS


def classify_high_low(crop: np.ndarray) -> HighLow | None:
    b, g, r = _mean_bgr(crop)
    if r > 120 and g > 100 and b < 80:
        return HighLow.HIGH
    if b > 120 and g > 100 and r < 80:
        return HighLow.LOW
    return None


def _to_gray(bgr: np.ndarray) -> np.ndarray:
    return (0.114 * bgr[:, :, 0] + 0.587 * bgr[:, :, 1] + 0.299 * bgr[:, :, 2]).astype(np.float32)


def _ncc(image: np.ndarray, template: np.ndarray) -> float:
    """Normalized correlation when image and template are the same size."""
    if image.shape != template.shape:
        h, w = template.shape
        if image.shape[0] < h or image.shape[1] < w:
            return -1.0
        image = image[:h, :w]
    a = image - image.mean()
    b = template - template.mean()
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom < 1e-6:
        return 0.0
    return float(np.sum(a * b) / denom)


_TEMPLATES: dict[Suit, np.ndarray] | None = None


def _load_templates() -> dict[Suit, np.ndarray]:
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    templates: dict[Suit, np.ndarray] = {}
    for suit, name in _SUIT_FILES.items():
        path = TEMPLATES_DIR / name
        if not path.exists():
            raise FileNotFoundError(f"Missing suit template: {path}")
        templates[suit] = _to_gray(read_image(path))
    _TEMPLATES = templates
    return templates


def classify_suit(crop: np.ndarray, threshold: float) -> tuple[Suit | None, float]:
    gray_crop = _to_gray(crop)
    best_suit: Suit | None = None
    best_score = -1.0
    for suit, template in _load_templates().items():
        score = _ncc(gray_crop, template)
        if score > best_score:
            best_score = score
            best_suit = suit
    if best_suit is None or best_score < threshold:
        return None, best_score
    return best_suit, best_score


def extract(frame: np.ndarray, config: dict) -> ExtractionResult:
    rois = config["rois"]
    threshold = float(config.get("match_threshold", 0.75))

    banner = classify_banner(_crop(frame, rois["banner"]))
    high_low = classify_high_low(_crop(frame, rois["high_low"]))
    suit, score = classify_suit(_crop(frame, rois["suit"]), threshold)
    notes = f"suit_score={score:.2f}"

    if banner != RaceState.FINISHED:
        return ExtractionResult(
            race_state=RaceState.IN_PROGRESS,
            winner_suit=None,
            high_low=None,
            confident=False,
            notes=notes,
        )

    confident = suit is not None and high_low is not None
    return ExtractionResult(
        race_state=RaceState.FINISHED,
        winner_suit=suit,
        high_low=high_low,
        confident=confident,
        notes=notes,
    )
