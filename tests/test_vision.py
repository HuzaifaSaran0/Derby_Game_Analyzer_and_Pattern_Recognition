from pathlib import Path

import pytest

from game_analyzer.config import load_config
from game_analyzer.fixtures import GROUND_TRUTH, generate, load_ground_truth
from game_analyzer.models import HighLow, RaceState, Suit
from game_analyzer.vision import extract, read_image

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def config():
    cfg = load_config()
    generate(cfg)
    return cfg


def test_all_synthetic_fixtures(config):
    truth = load_ground_truth()
    assert GROUND_TRUTH.exists()
    assert len(truth) >= 9

    for rel_path, expected in truth.items():
        frame = read_image(ROOT / "fixtures" / rel_path)
        assert frame is not None, rel_path
        result = extract(frame, config)

        assert result.race_state.value == expected["race_state"], rel_path
        if expected["race_state"] == RaceState.FINISHED.value:
            assert result.confident, rel_path
            assert result.winner_suit == Suit(expected["winner_suit"]), rel_path
            assert result.high_low == HighLow(expected["high_low"]), rel_path
        else:
            assert result.winner_suit is None
            assert result.high_low is None
            assert not result.confident
