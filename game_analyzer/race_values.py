from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

"""Step 1: pre-race remaining points per suit after handicap cards are removed."""

FULL_SUIT_TOTAL = 95  # one suit: A=11, 2–10 face, J/Q/K=10 → 95 total

SUIT_NAMES = ("Spades", "Hearts", "Clubs", "Diamonds")


def card_race_value(card: str) -> int | None:
    """Points for one card label like ``AS`` or ``10H``. ``None`` if unreadable."""
    if not card or card.startswith("?"):
        return None
    rank = card[:-1]
    if rank == "A":
        return 11
    if rank in ("K", "Q", "J"):
        return 10
    if rank.isdigit():
        return int(rank)
    return None


def handicap_sums(handicap_cards: tuple[tuple[str, ...], ...]) -> dict[str, int | None]:
    """Sum of the three handicap card values removed from each suit."""
    out: dict[str, int | None] = {}
    for idx, suit_name in enumerate(SUIT_NAMES):
        row = handicap_cards[idx] if idx < len(handicap_cards) else ()
        total = 0
        for card in row:
            value = card_race_value(card)
            if value is None:
                out[suit_name] = None
                break
            total += value
        else:
            out[suit_name] = total if row else None
    return out


def remaining_after_handicap(handicap_cards: tuple[tuple[str, ...], ...]) -> dict[str, int | None]:
    """Points still in each suit's deck: 95 minus handicap sum."""
    removed = handicap_sums(handicap_cards)
    return {
        suit: (FULL_SUIT_TOTAL - total if total is not None else None)
        for suit, total in removed.items()
    }


def favourite_suit(remaining: dict[str, int | None]) -> str | None:
    """Suit with the highest remaining value — best pre-race chance."""
    ranked = [(s, v) for s, v in remaining.items() if v is not None]
    if len(ranked) < 4:
        return None
    best = max(ranked, key=lambda t: t[1])
    if any(v == best[1] for s, v in ranked if s != best[0]):
        # Tie — still return one favourite; UI can mention tie if needed.
        pass
    return best[0]


def pre_race_guess(handicap_cards: tuple[tuple[str, ...], ...]) -> str | None:
    """Pre-race pick: suit with the most points left after handicap."""
    return favourite_suit(remaining_after_handicap(handicap_cards))


def suits_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.upper() == b.upper()


def parse_handicap_rows(rows) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(row) for row in rows)


@dataclass(frozen=True)
class PreRaceOutcome:
    guess: str | None
    winner: str | None
    correct: bool | None


def pre_race_outcome(
    winner_suit: str | None,
    handicap_cards: tuple[tuple[str, ...], ...],
) -> PreRaceOutcome:
    guess = pre_race_guess(handicap_cards)
    if not winner_suit:
        return PreRaceOutcome(guess=guess, winner=None, correct=None)
    if not guess:
        return PreRaceOutcome(guess=None, winner=winner_suit, correct=None)
    return PreRaceOutcome(
        guess=guess,
        winner=winner_suit,
        correct=suits_match(guess, winner_suit),
    )


@dataclass(frozen=True)
class GuessAccuracy:
    correct: int
    total: int

    @property
    def percent(self) -> float | None:
        if self.total == 0:
            return None
        return round(100.0 * self.correct / self.total, 1)


def guess_accuracy(
    records: Iterable[tuple[str | None, tuple[tuple[str, ...], ...]]],
) -> GuessAccuracy:
    """Score pre-race picks on finished games only (caller passes rows with winners)."""
    correct = 0
    total = 0
    for winner, handicap in records:
        if not winner:
            continue
        guess = pre_race_guess(handicap)
        if not guess:
            continue
        total += 1
        if suits_match(guess, winner):
            correct += 1
    return GuessAccuracy(correct=correct, total=total)
