from __future__ import annotations

import itertools
from dataclasses import dataclass

from game_analyzer.race_values import (
    SUIT_NAMES,
    TRACK_LENGTH,
    card_race_value,
    draws_for_guess,
    suit_name_from_card,
)

FULL_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")
SUIT_LETTER = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}


@dataclass(frozen=True)
class ComboMetrics:
    to_go: int
    max_2_sum: int
    max_3_sum: int
    can_finish_in_2: bool
    can_finish_in_3: bool
    finish_potential: float
    card_count: int


def full_suit_cards(suit_name: str) -> tuple[str, ...]:
    letter = SUIT_LETTER[suit_name]
    return tuple(f"{rank}{letter}" for rank in FULL_RANKS)


def remaining_card_labels(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> dict[str, tuple[str, ...] | None]:
    """Exact cards still in each suit after handicap and guess draws."""
    guess_draws = draws_for_guess(draw_cards)
    out: dict[str, tuple[str, ...] | None] = {}
    for idx, suit_name in enumerate(SUIT_NAMES):
        row = handicap_cards[idx] if idx < len(handicap_cards) else ()
        removed = set(row)
        readable = True
        for card in row:
            if card_race_value(card) is None:
                readable = False
                break
        for card in guess_draws:
            if suit_name_from_card(card) != suit_name:
                continue
            if card_race_value(card) is None:
                readable = False
                break
            removed.add(card)
        if not readable:
            out[suit_name] = None
            continue
        out[suit_name] = tuple(
            card for card in full_suit_cards(suit_name) if card not in removed
        )
    return out


def remaining_values(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> dict[str, tuple[int, ...] | None]:
    """Race values of exact remaining cards per suit."""
    labels = remaining_card_labels(handicap_cards, draw_cards)
    out: dict[str, tuple[int, ...] | None] = {}
    for suit_name, cards in labels.items():
        if cards is None:
            out[suit_name] = None
            continue
        values = [card_race_value(card) for card in cards]
        if any(value is None for value in values):
            out[suit_name] = None
        else:
            out[suit_name] = tuple(values)
    return out


def combo_metrics(values: tuple[int, ...] | None, moved: int | None) -> ComboMetrics | None:
    """2- and 3-card finish potential for one suit toward 32."""
    if values is None or moved is None:
        return None
    to_go = max(0, TRACK_LENGTH - moved)
    if to_go == 0:
        return ComboMetrics(
            to_go=0,
            max_2_sum=0,
            max_3_sum=0,
            can_finish_in_2=True,
            can_finish_in_3=True,
            finish_potential=1.0,
            card_count=len(values),
        )
    if not values:
        return ComboMetrics(
            to_go=to_go,
            max_2_sum=0,
            max_3_sum=0,
            can_finish_in_2=False,
            can_finish_in_3=False,
            finish_potential=0.0,
            card_count=0,
        )
    if any(value >= to_go for value in values):
        return ComboMetrics(
            to_go=to_go,
            max_2_sum=max(values),
            max_3_sum=max(values),
            can_finish_in_2=True,
            can_finish_in_3=True,
            finish_potential=1.0,
            card_count=len(values),
        )
    max_2 = max((a + b for a, b in itertools.combinations(values, 2)), default=0)
    max_3 = (
        max((sum(triple) for triple in itertools.combinations(values, 3)), default=0)
        if len(values) >= 3
        else max_2
    )
    can_2 = max_2 >= to_go
    can_3 = max_3 >= to_go
    finish_potential = min(
        1.0,
        max(
            max_2 / to_go if to_go else 0.0,
            max_3 / to_go if to_go else 0.0,
        ),
    )
    return ComboMetrics(
        to_go=to_go,
        max_2_sum=max_2,
        max_3_sum=max_3,
        can_finish_in_2=can_2,
        can_finish_in_3=can_3,
        finish_potential=finish_potential,
        card_count=len(values),
    )


def draw_share(
    remaining_labels: dict[str, tuple[str, ...] | None],
) -> dict[str, float | None]:
    """Share of global draw pool still belonging to each suit."""
    counts = {
        suit: (len(cards) if cards is not None else None)
        for suit, cards in remaining_labels.items()
    }
    if any(count is None for count in counts.values()):
        return {suit: None for suit in SUIT_NAMES}
    total = sum(counts.values())
    if total == 0:
        return {suit: None for suit in SUIT_NAMES}
    return {suit: counts[suit] / total for suit in SUIT_NAMES}


def combo_side_score(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
    track_moved: dict[str, int | None],
) -> dict[str, float | None]:
    """Layer 4 finish-path signal (0–1) from exact remaining cards."""
    labels = remaining_card_labels(handicap_cards, draw_cards)
    values = remaining_values(handicap_cards, draw_cards)
    out: dict[str, float | None] = {}
    for suit in SUIT_NAMES:
        metrics = combo_metrics(values[suit], track_moved.get(suit))
        if metrics is None or labels[suit] is None:
            out[suit] = None
        else:
            out[suit] = metrics.finish_potential
    return out
