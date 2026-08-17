from pathlib import Path

import pytest

from game_analyzer.cards import read_draw_cards
from game_analyzer.config import load_config
from game_analyzer.vision import extract_real, read_image

REAL_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "real"

pytestmark = pytest.mark.skipif(
    not any(REAL_DIR.glob("*.png")),
    reason="fixtures/real screenshots are local-only",
)

DRAW_CASES = {
    "11_draw_JD_QD_AH.png": ("JD", "QD", "AH"),
    "12_draw_JC_JD_3S.png": ("JC", "JD", "3S"),
    "13_AS_6S_7S.png": ("AS", "6S", "7S"),
    "14_5D_QH_2S.png": ("5D", "QH", "2S"),
    "15_6C_8C_10D.png": ("6C", "8C", "10D"),
    "16_4D_9D_AS.png": ("4D", "9D", "AS"),
    "17_2C_3D_9D.png": ("2C", "3D", "9D"),
    "18_AH_5H_9H.png": ("AH", "5H", "9H"),
    "19_5H_6H_AS.png": ("5H", "6H", "AS"),
    "22_JD_3H_JH.png": ("JD", "3H", "JH"),
    "25_3D_10H_4S.png": ("3D", "10H", "4S"),
    "26_QC_6H_KS.png": ("QC", "6H", "KS"),
    "27_AD_6S_KS.png": ("AD", "6S", "KS"),
    "28_8D_2H_5S.png": ("8D", "2H", "5S"),
    "29_AH_5S_10S.png": ("AH", "5S", "10S"),
    "30_AC_6C_3S.png": ("AC", "6C", "3S"),
    "31_7C_9D_KH.png": ("7C", "9D", "KH"),
    "32_4C_6C_7H.png": ("4C", "6C", "7H"),
    "33_3C_5C_8D.png": ("3C", "5C", "8D"),
    "34_9C_KC_8S.png": ("9C", "KC", "8S"),
    "35_7D_KD_9S.png": ("7D", "KD", "9S"),
    "36_4D_6D_4S.png": ("4D", "6D", "4S"),
}


def test_all_draw_card_goldens():
    for name, expected in DRAW_CASES.items():
        cards = read_draw_cards(read_image(REAL_DIR / name))
        assert len(cards) == 3, name
        assert tuple(c.label() for c in cards) == expected, name
        assert all(c.confident for c in cards), name


def test_extract_real_includes_draw_cards():
    config = load_config()
    for name, expected in DRAW_CASES.items():
        result = extract_real(read_image(REAL_DIR / name), config)
        assert result.draw_cards == expected, name
