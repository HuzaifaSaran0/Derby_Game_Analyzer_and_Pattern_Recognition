"""Monte Carlo win probabilities from the exact remaining draw pool."""

from __future__ import annotations

import random
from collections import Counter

from game_analyzer.deck_combos import full_suit_cards
from game_analyzer.race_values import (
    SUIT_NAMES,
    TRACK_LENGTH,
    card_race_value,
    track_position,
)


def remaining_draw_pool(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
) -> list[tuple[str, int]] | None:
    """Cards still in the pool as (suit_name, race_value) pairs."""
    removed: set[str] = set(draw_cards)
    for row in handicap_cards:
        removed |= set(row)
    pool: list[tuple[str, int]] = []
    for suit_name in SUIT_NAMES:
        for card in full_suit_cards(suit_name):
            if card in removed:
                continue
            value = card_race_value(card)
            if value is None:
                return None
            pool.append((suit_name, value))
    return pool


def monte_carlo_win_probs(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
    *,
    simulations: int = 2000,
    seed: int | None = None,
) -> dict[str, float] | None:
    """Estimate each suit's win chance by shuffling the exact remaining pool."""
    pool = remaining_draw_pool(handicap_cards, draw_cards)
    if pool is None:
        return None
    moved = track_position(draw_cards)
    if any(moved[suit] is None for suit in SUIT_NAMES):
        return None
    start = {suit: int(moved[suit]) for suit in SUIT_NAMES}
    rng = random.Random(seed)
    wins = Counter({suit: 0 for suit in SUIT_NAMES})
    for _ in range(simulations):
        deck = list(pool)
        rng.shuffle(deck)
        pos = dict(start)
        finished = False
        for index in range(0, len(deck), 3):
            for suit, value in deck[index : index + 3]:
                pos[suit] += value
            crossed = [suit for suit in SUIT_NAMES if pos[suit] >= TRACK_LENGTH]
            if crossed:
                wins[max(crossed, key=lambda suit: pos[suit])] += 1
                finished = True
                break
        if not finished:
            wins[max(SUIT_NAMES, key=lambda suit: pos[suit])] += 1
    return {suit: wins[suit] / simulations for suit in SUIT_NAMES}
