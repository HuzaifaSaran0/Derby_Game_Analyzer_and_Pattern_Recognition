"""Live winner-sequence hints: after matching historical tails, what won next?"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from game_analyzer.models import Suit
from game_analyzer.store import GameStore

# Client notation: 1=Spades, 2=Hearts, 3=Clubs, 4=Diamonds
SUIT_TO_CODE: dict[str, int] = {
    Suit.SPADES.value: 1,
    Suit.HEARTS.value: 2,
    Suit.CLUBS.value: 3,
    Suit.DIAMONDS.value: 4,
    "SPADES": 1,
    "HEARTS": 2,
    "CLUBS": 3,
    "DIAMONDS": 4,
    "Spades": 1,
    "Hearts": 2,
    "Clubs": 3,
    "Diamonds": 4,
}

CODE_TO_SUIT: dict[int, str] = {
    1: "Spades",
    2: "Hearts",
    3: "Clubs",
    4: "Diamonds",
}

CODE_TO_SYMBOL: dict[int, str] = {
    1: "♠",
    2: "♥",
    3: "♣",
    4: "♦",
}

CODE_TO_COLOR: dict[int, str] = {
    1: "#31c96b",
    2: "#ff5a67",
    3: "#58a6ff",
    4: "#f2c94c",
}

SUIT_META: dict[str, dict[str, str]] = {
    str(code): {
        "symbol": CODE_TO_SYMBOL[code],
        "color": CODE_TO_COLOR[code],
        "name": CODE_TO_SUIT[code],
    }
    for code in (1, 2, 3, 4)
}

HINT_LEGEND = "1=♠ · 2=♥ · 3=♣ · 4=♦"

HINT_LENGTHS: tuple[int, ...] = tuple(range(4, 11))  # 4..10


def winner_code(suit: str | None) -> int | None:
    if not suit:
        return None
    key = suit.strip().upper()
    if key in SUIT_TO_CODE:
        return SUIT_TO_CODE[key]
    return SUIT_TO_CODE.get(suit.strip().title())


def _symbol(code: int) -> str:
    return CODE_TO_SYMBOL.get(code, str(code))


def _tail_label(codes: list[int]) -> str:
    return " ".join(_symbol(c) for c in codes)


def _suit_list_label(codes: list[int]) -> str:
    return " · ".join(_symbol(c) for c in codes)


@dataclass(frozen=True)
class HintRow:
    length: int
    tail: tuple[int, ...]
    match_count: int
    follow_up_counts: dict[int, int]

    @property
    def tail_text(self) -> str:
        return _tail_label(list(self.tail))

    @property
    def tail_suits(self) -> str:
        return _suit_list_label(list(self.tail))

    @property
    def next_game_number(self) -> int:
        return self.length + 1


def analyze_tail(finished_codes: list[int], length: int) -> HintRow | None:
    """Find every historical occurrence of the current tail and tally the next winner."""
    n = len(finished_codes)
    if length < 1 or n < length:
        return None
    tail = tuple(finished_codes[-length:])
    follow_counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}

    for start in range(n - length + 1):
        if tuple(finished_codes[start : start + length]) != tail:
            continue
        next_idx = start + length
        if next_idx >= n:
            continue
        code = finished_codes[next_idx]
        follow_counts[code] = follow_counts.get(code, 0) + 1

    match_count = sum(follow_counts.values())
    return HintRow(
        length=length,
        tail=tail,
        match_count=match_count,
        follow_up_counts=follow_counts,
    )


def _row_summary(row: HintRow) -> str:
    if row.match_count == 0:
        return (
            f"Last {row.length} winners ({row.tail_suits}): "
            "no identical run in history yet."
        )
    parts = [
        f"{_symbol(c)} {row.follow_up_counts[c]}"
        for c in sorted(row.follow_up_counts)
        if row.follow_up_counts[c] > 0
    ]
    best_code = max(
        (c for c, v in row.follow_up_counts.items() if v > 0),
        key=lambda c: row.follow_up_counts[c],
    )
    best_n = row.follow_up_counts[best_code]
    best_suit = _symbol(best_code)
    detail = ", ".join(parts)
    if row.match_count == 1:
        return (
            f"Last {row.length} ({row.tail_suits}): 1 past case — "
            f"next game was {best_suit}. ({detail})"
        )
    best_pct = int(round(100 * best_n / row.match_count))
    return (
        f"Last {row.length} ({row.tail_suits}): {row.match_count} past cases — "
        f"next game was usually {best_suit} ({best_n}/{row.match_count}, {best_pct}%). "
        f"({detail})"
    )


def _lead_summary(rows: list[HintRow]) -> str:
    with_matches = [r for r in rows if r.match_count > 0]
    if not with_matches:
        return "No matching winner runs in history for lengths 4–10 yet."

    def score(r: HintRow) -> tuple[int, int]:
        top = max(r.follow_up_counts.values()) if r.match_count else 0
        return (r.match_count, top)

    best = max(with_matches, key=score)
    top_code = max(best.follow_up_counts, key=best.follow_up_counts.get)
    top_n = best.follow_up_counts[top_code]
    top_suit = _symbol(top_code)
    if best.match_count == 1:
        return (
            f"Quick read: after the last {best.length} winners, history has 1 similar case — "
            f"the next game was {top_suit}."
        )
    pct = int(round(100 * top_n / best.match_count))
    return (
        f"Quick read: after the last {best.length} winners, {best.match_count} similar cases — "
        f"{top_suit} won next most often ({top_n}/{best.match_count}, {pct}%)."
    )


def live_winner_hints(store: GameStore) -> dict[str, Any]:
    """Hints from finished-game tails (current live game is the implied next outcome)."""
    finished_codes: list[int] = []
    for game_id in store.list_game_ids(finished_only=True):
        game = store.get_game(game_id)
        if game is None or not game.winner_suit:
            continue
        code = winner_code(game.winner_suit)
        if code is not None:
            finished_codes.append(code)

    min_len = min(HINT_LENGTHS)
    if len(finished_codes) < min_len:
        return {
            "legend": HINT_LEGEND,
            "suit_meta": SUIT_META,
            "finished_games": len(finished_codes),
            "lengths": list(HINT_LENGTHS),
            "lead_summary": (
                f"Need at least {min_len} finished games for winner hints "
                f"({len(finished_codes)} so far)."
            ),
            "rows": [],
        }

    rows: list[HintRow] = []
    for length in HINT_LENGTHS:
        row = analyze_tail(finished_codes, length)
        if row is not None:
            rows.append(row)

    payload_rows = []
    for row in rows:
        total = row.match_count
        percents = {
            str(c): (int(round(100 * row.follow_up_counts[c] / total)) if total else 0)
            for c in (1, 2, 3, 4)
        }
        payload_rows.append(
            {
                "length": row.length,
                "next_game_number": row.next_game_number,
                "tail": list(row.tail),
                "tail_text": row.tail_text,
                "tail_suits": row.tail_suits,
                "match_count": row.match_count,
                "follow_up_counts": {str(k): v for k, v in row.follow_up_counts.items()},
                "follow_up_percents": percents,
                "summary": _row_summary(row),
            }
        )

    return {
        "legend": HINT_LEGEND,
        "suit_meta": SUIT_META,
        "finished_games": len(finished_codes),
        "lengths": list(HINT_LENGTHS),
        "lead_summary": _lead_summary(rows),
        "rows": payload_rows,
    }


def live_winner_hints_if_in_progress(store: GameStore, *, in_progress: bool) -> dict[str, Any] | None:
    if not in_progress:
        return None
    return live_winner_hints(store)
