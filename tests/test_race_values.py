from game_analyzer.race_values import (
    FULL_SUIT_TOTAL,
    MAX_GUESS_DRAWS,
    TRACK_LENGTH,
    blend_weights,
    card_race_value,
    all_draws_from_in_play_frames,
    combined_scores,
    draws_for_guess,
    draws_from_in_play_frames,
    favourite_suit,
    guess_accuracy,
    guess_ready,
    pre_race_guess,
    pre_race_outcome,
    preview_guess,
    race_guess,
    remaining_after_handicap,
    remaining_deck,
    track_distance_to_go,
    track_position,
)

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
ROUND1 = ("5H", "7S", "AD")
ROUND2 = ("3C", "6D", "4S")
SIX_DRAWS = ROUND1 + ROUND2


def test_full_suit_total_is_95():
    ranks = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
    assert sum(card_race_value(f"{r}S") for r in ranks) == FULL_SUIT_TOTAL == 95


def test_remaining_after_handicap():
    remaining = remaining_after_handicap(HANDICAP)
    assert remaining["Spades"] == 64
    assert remaining["Hearts"] == 86
    assert favourite_suit(remaining) == "Hearts"


def test_blend_weights_by_round():
    assert blend_weights(0) == (1.0, 0.0)
    assert blend_weights(1) == (0.5, 0.5)
    assert blend_weights(2) == (0.25, 0.75)


def test_pre_race_guess_is_deck_only():
    assert pre_race_guess(HANDICAP) == "Hearts"


def test_preview_after_one_round():
    assert preview_guess(HANDICAP, ROUND1) == "Hearts"
    assert race_guess(HANDICAP, ROUND1) is None


def test_official_guess_blends_deck_and_track():
    # After 2 rounds Diamonds lead on track; blend picks Diamonds not pure deck leader Hearts.
    assert race_guess(HANDICAP, SIX_DRAWS) == "Diamonds"


def test_remaining_deck_subtracts_draws():
    remaining = remaining_deck(HANDICAP, ROUND1)
    assert remaining["Hearts"] == 86 - 5
    assert remaining["Spades"] == 64 - 7
    assert remaining["Diamonds"] == 95 - 30 - 11


def test_track_position_and_distance():
    assert track_position(ROUND1)["Hearts"] == 5
    assert track_distance_to_go(ROUND1)["Hearts"] == TRACK_LENGTH - 5


def test_combined_scores_between_deck_and_track():
    scores = combined_scores(HANDICAP, SIX_DRAWS)
    assert scores["Diamonds"] is not None
    assert scores["Hearts"] is not None
    assert scores["Diamonds"] > scores["Hearts"]


def test_draws_for_guess_limits_two_rounds():
    eight = SIX_DRAWS + ("2C", "9H")
    assert len(draws_for_guess(eight)) == MAX_GUESS_DRAWS


def test_guess_not_ready_until_two_rounds():
    assert guess_ready(ROUND1) is False
    assert guess_ready(SIX_DRAWS) is True


def test_draws_from_cumulative_frames():
    frames = [
        ("IN_PLAY", ROUND1),
        ("IN_PLAY", SIX_DRAWS),
    ]
    assert draws_from_in_play_frames(frames) == SIX_DRAWS


def test_draws_from_per_round_frames():
    frames = [
        ("IN_PLAY", ROUND1),
        ("IN_PLAY", ROUND2),
    ]
    assert draws_from_in_play_frames(frames) == SIX_DRAWS


def test_all_draws_keeps_every_round():
    round3 = ("2C", "9H", "5S")
    frames = [
        ("IN_PLAY", ROUND1),
        ("IN_PLAY", ROUND2),
        ("IN_PLAY", round3),
    ]
    all_draws = all_draws_from_in_play_frames(frames)
    assert all_draws == SIX_DRAWS + round3
    assert draws_from_in_play_frames(frames) == SIX_DRAWS


def test_guess_accuracy_requires_two_rounds():
    records = [
        ("HEARTS", HANDICAP, ROUND1),
        ("DIAMONDS", HANDICAP, SIX_DRAWS),
        ("CLUBS", HANDICAP, SIX_DRAWS),
    ]
    stats = guess_accuracy(records)
    assert stats.total == 2
    assert stats.correct == 1


def test_pre_race_outcome_after_two_rounds():
    outcome = pre_race_outcome("DIAMONDS", HANDICAP, SIX_DRAWS)
    assert outcome.guess == "Diamonds"
    assert outcome.correct is True
    assert outcome.guess_ready is True


def test_pre_race_outcome_before_two_rounds():
    outcome = pre_race_outcome("HEARTS", HANDICAP, ROUND1)
    assert outcome.guess is None
    assert outcome.guess_ready is False
    assert outcome.draw_rounds_used == 1


def test_unknown_handicap_makes_suit_none():
    handicap = (("?S", "4S", "7S"), ("2H", "3H", "5H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
    assert remaining_after_handicap(handicap)["Spades"] is None
