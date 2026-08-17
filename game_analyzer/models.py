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

    def to_dict(self) -> dict:
        return {
            "race_state": self.race_state.value,
            "winner_suit": self.winner_suit.value if self.winner_suit else None,
            "high_low": self.high_low.value if self.high_low else None,
            "confident": self.confident,
            "notes": self.notes,
            "draw_cards": list(self.draw_cards),
        }
