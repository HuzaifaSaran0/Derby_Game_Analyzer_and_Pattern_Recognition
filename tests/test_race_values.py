from game_analyzer.race_values import (
    FULL_SUIT_TOTAL,
    card_race_value,
    favourite_suit,
    guess_accuracy,
    pre_race_outcome,
    remaining_after_handicap,
)


def test_full_suit_total_is_95():
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    assert sum(card_race_value(f"{r}S") for r in ranks) == FULL_SUIT_TOTAL == 95


def test_remaining_after_handicap():
    # Spades removed: A(11)+K(10)+Q(10)=31 → 64 left (lowest handicap removal = highest remaining)
    # Hearts removed: 2+3+4=9 → 86 left
    handicap = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
    remaining = remaining_after_handicap(handicap)
    assert remaining["Spades"] == 64
    assert remaining["Hearts"] == 86
    assert favourite_suit(remaining) == "Hearts"


def test_guess_accuracy_ignores_games_without_winner():
    full = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
    records = [
        (None, full),
        ("HEARTS", full),
        ("CLUBS", full),
    ]
    stats = guess_accuracy(records)
    assert stats.total == 2
    assert stats.correct == 1


def test_pre_race_outcome():
    handicap = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
    outcome = pre_race_outcome("HEARTS", handicap)
    assert outcome.guess == "Hearts"
    assert outcome.correct is True


def test_unknown_handicap_makes_suit_none():
    handicap = (("?S", "4S", "7S"), ("2H", "3H", "5H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
    assert remaining_after_handicap(handicap)["Spades"] is None
