from game_analyzer.models import ExtractionResult, RaceState


def test_combined_suit_cards_appends_draws_to_matching_rows():
    result = ExtractionResult(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=("5H", "7S", "AD"),
        handicap_cards=(
            ("AS", "2S", "3S"),
            ("4H", "6H", "KH"),
            ("3C", "8C", "QC"),
            ("2D", "7D", "10D"),
        ),
    )

    assert result.combined_suit_cards() == (
        ("Spades", ("AS", "2S", "3S", "7S")),
        ("Hearts", ("4H", "6H", "KH", "5H")),
        ("Clubs", ("3C", "8C", "QC")),
        ("Diamonds", ("2D", "7D", "10D", "AD")),
    )


def test_combined_suit_cards_text_formats_one_row_per_suit():
    result = ExtractionResult(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=("AH", "9S", "JD"),
        handicap_cards=(("2S",), ("5H",), ("KC",), ("4D",)),
    )

    assert result.combined_suit_cards_text() == "\n".join(
        [
            "Spades: 2S, 9S",
            "Hearts: 5H, AH",
            "Clubs: KC",
            "Diamonds: 4D, JD",
        ]
    )
