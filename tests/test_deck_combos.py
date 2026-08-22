from game_analyzer.deck_combos import (
    combo_metrics,
    combo_side_score,
    draw_share,
    full_suit_cards,
    remaining_card_labels,
    remaining_values,
)
from game_analyzer.race_values import track_position

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
ROUND1 = ("5H", "7S", "AD")
ROUND2 = ("3C", "6D", "4S")
SIX_DRAWS = ROUND1 + ROUND2


def test_full_suit_has_thirteen_cards():
    spades = full_suit_cards("Spades")
    assert len(spades) == 13
    assert spades[0] == "AS"
    assert spades[-1] == "KS"


def test_remaining_cards_after_handicap_and_draws():
    labels = remaining_card_labels(HANDICAP, SIX_DRAWS)
    assert "5H" not in labels["Hearts"]
    assert "AS" not in labels["Spades"]
    assert "AD" not in labels["Diamonds"]
    assert "3C" not in labels["Clubs"]
    assert len(labels["Hearts"]) == 13 - 3 - 1


def test_remaining_values_match_labels():
    labels = remaining_card_labels(HANDICAP, SIX_DRAWS)
    values = remaining_values(HANDICAP, SIX_DRAWS)
    for suit, cards in labels.items():
        assert values[suit] is not None
        assert len(values[suit]) == len(cards)


def test_can_finish_in_two_when_pair_reaches_target():
    metrics = combo_metrics((11, 10, 4, 3), moved=15)
    assert metrics is not None
    assert metrics.to_go == 17
    assert metrics.can_finish_in_2 is True
    assert metrics.finish_potential == 1.0


def test_combo_potential_lower_for_small_cards():
    metrics = combo_metrics((2, 3, 4, 5), moved=10)
    assert metrics is not None
    assert metrics.can_finish_in_2 is False
    assert metrics.finish_potential < 1.0


def test_draw_share_sums_to_one():
    labels = remaining_card_labels(HANDICAP, SIX_DRAWS)
    share = draw_share(labels)
    assert all(value is not None for value in share.values())
    assert abs(sum(share.values()) - 1.0) < 1e-9


def test_combo_side_score_after_two_rounds():
    moved = track_position(SIX_DRAWS)
    scores = combo_side_score(HANDICAP, SIX_DRAWS, moved)
    assert all(score is not None for score in scores.values())
    assert all(0.0 <= score <= 1.0 for score in scores.values())
