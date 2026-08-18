from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RaceState(str, Enum):
    UNKNOWN = "UNKNOWN"
    BETTING = "BETTING"
    IN_PROGRESS = "IN_PROGRESS"
    FINISHED = "FINISHED"


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
        """Merge starting handicap rows with newly drawn cards by suit."""
        rows = {
            Suit.SPADES: list(self.handicap_cards[0]) if len(self.handicap_cards) > 0 else [],
            Suit.HEARTS: list(self.handicap_cards[1]) if len(self.handicap_cards) > 1 else [],
            Suit.CLUBS: list(self.handicap_cards[2]) if len(self.handicap_cards) > 2 else [],
            Suit.DIAMONDS: list(self.handicap_cards[3]) if len(self.handicap_cards) > 3 else [],
        }
        for card in self.draw_cards:
            if len(card) < 2:
                continue
            suit_letter = card[-1]
            for suit in Suit:
                if suit.value[0] == suit_letter:
                    rows[suit].append(card)
                    break
        return tuple((suit.value.title(), tuple(rows[suit])) for suit in Suit)

    def combined_suit_cards_text(self) -> str:
        lines = []
        for suit_name, cards in self.combined_suit_cards():
            text = ", ".join(cards) if cards else "-"
            lines.append(f"{suit_name}: {text}")
        return "\n".join(lines)
