from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum


class RaceState(str, Enum):
    UNKNOWN = "UNKNOWN"
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
class ExtractionResult:
    race_state: RaceState
    winner_suit: Suit | None
    high_low: HighLow | None
    confident: bool
    notes: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["race_state"] = self.race_state.value
        data["winner_suit"] = self.winner_suit.value if self.winner_suit else None
        data["high_low"] = self.high_low.value if self.high_low else None
        return data
