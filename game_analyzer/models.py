from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RaceState(str, Enum):
    UNKNOWN = "UNKNOWN"
    BETTING = "BETTING"
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"


class GamePhase(str, Enum):
    """Where we are inside one Derby Race, from cards on screen — not wall-clock."""

    START = "START"  # no handicap yet (new game / waiting to deal)
    DEALT = "DEALT"  # handicap visible, no draw cards, no results
    IN_PLAY = "IN_PLAY"  # handicap + draw cards, no winner/loser
    FINISHED = "FINISHED"  # results / winner row


class Suit(str, Enum):
    SPADES = "SPADES"
    HEARTS = "HEARTS"
    CLUBS = "CLUBS"
    DIAMONDS = "DIAMONDS"


class HighLow(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


@dataclass(frozen=True)
class RowScore:
    suit: Suit
    green_minus_red: float
    is_winner_row: bool
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0


def merge_suit_cards(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Handicap rows first, then every drawn card appended to its suit."""
    rows = {
        Suit.SPADES: list(handicap_cards[0]) if len(handicap_cards) > 0 else [],
        Suit.HEARTS: list(handicap_cards[1]) if len(handicap_cards) > 1 else [],
        Suit.CLUBS: list(handicap_cards[2]) if len(handicap_cards) > 2 else [],
        Suit.DIAMONDS: list(handicap_cards[3]) if len(handicap_cards) > 3 else [],
    }
    for card in draw_cards:
        if len(card) < 2:
            continue
        suit_letter = card[-1]
        for suit in Suit:
            if suit.value[0] == suit_letter:
                rows[suit].append(card)
                break
    return tuple((suit.value.title(), tuple(rows[suit])) for suit in Suit)


@dataclass(frozen=True)
class ExtractionResult:
    race_state: RaceState
    winner_suit: Suit | None
    high_low: HighLow | None
    confident: bool
    notes: str = ""
    rows: tuple[RowScore, ...] = ()
    draw_cards: tuple[str, ...] = ()
    handicap_cards: tuple[tuple[str, ...], ...] = ()

    def to_dict(self) -> dict:
        return {
            "race_state": self.race_state.value,
            "winner_suit": self.winner_suit.value if self.winner_suit else None,
            "high_low": self.high_low.value if self.high_low else None,
            "confident": self.confident,
            "notes": self.notes,
            "draw_cards": list(self.draw_cards),
            "handicap_cards": [list(row) for row in self.handicap_cards],
        }

    def combined_suit_cards(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return merge_suit_cards(self.handicap_cards, self.draw_cards)

    def has_handicap_cards(self) -> bool:
        return any(
            card and not str(card).startswith("?")
            for row in self.handicap_cards
            for card in row
        )

    def has_draw_cards(self) -> bool:
        return any(card and not str(card).startswith("?") for card in self.draw_cards)

    def game_phase(self) -> GamePhase:
        """Start / mid / end from handicap, draws, and the winner row."""
        if self.winner_suit is not None or self.race_state == RaceState.FINISHED:
            return GamePhase.FINISHED
        if self.has_handicap_cards() and self.has_draw_cards():
            return GamePhase.IN_PLAY
        if self.has_handicap_cards():
            return GamePhase.DEALT
        return GamePhase.START

    def combined_suit_cards_text(self) -> str:
        lines = []
        for suit_name, cards in self.combined_suit_cards():
            text = ", ".join(cards) if cards else "-"
            lines.append(f"{suit_name}: {text}")
        return "\n".join(lines)
