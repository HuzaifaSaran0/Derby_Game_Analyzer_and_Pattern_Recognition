from pathlib import Path

import pytest

from game_analyzer.config import load_config
from game_analyzer.models import RaceState, Suit
from game_analyzer.vision import extract_real, read_image

REAL_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real"

pytestmark = pytest.mark.skipif(
    not any(REAL_DIR.glob("*.png")),
    reason="fixtures/real screenshots are local-only",
)


def test_winner_frame_is_clubs():
    config = load_config()
    frame = read_image(REAL_DIR / "08_02-14-47.png")
    result = extract_real(frame, config)
    assert result.race_state == RaceState.FINISHED
    assert result.winner_suit == Suit.CLUBS
    assert result.confident


def test_winner_frame_is_hearts_new_race():
    config = load_config()
    result = extract_real(read_image(REAL_DIR / "10_19-44-33.png"), config)
    assert result.race_state == RaceState.FINISHED
    assert result.winner_suit == Suit.HEARTS
    assert result.confident


def test_mid_race_has_no_winner():
    config = load_config()
    result = extract_real(read_image(REAL_DIR / "09_19-43-47.png"), config)
    assert result.winner_suit is None
    assert result.race_state != RaceState.FINISHED


def test_earlier_frames_have_no_winner():
    config = load_config()
    for name in [
        "01_02-11-45.png",
        "03_02-12-11.png",
        "05_02-13-15.png",
        "07_02-14-15.png",
    ]:
        result = extract_real(read_image(REAL_DIR / name), config)
        assert result.winner_suit is None, name
        assert result.race_state != RaceState.FINISHED, name
