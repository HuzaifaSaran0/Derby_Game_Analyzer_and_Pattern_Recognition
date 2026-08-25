"""Styled playing-card display for the web UI (matches desktop mini-cards)."""

from __future__ import annotations

from game_analyzer.models import Suit
from game_analyzer.race_values import SUIT_NAMES

SUIT_STYLES = {
    "Spades": {"symbol": "♠", "color": "#31c96b"},
    "Hearts": {"symbol": "♥", "color": "#ff5a67"},
    "Clubs": {"symbol": "♣", "color": "#58a6ff"},
    "Diamonds": {"symbol": "♦", "color": "#f2c94c"},
}

_LETTER_TO_SUIT = {s.value[0].upper(): s.value.title() for s in Suit}


def card_display(card: str) -> dict:
    """Turn ``AS`` / ``10D`` into rank + suit symbol + color."""
    text = str(card or "").strip()
    if not text or text.startswith("?"):
        return {"code": text or "?", "rank": "?", "symbol": "?", "color": "#888", "suit": None}
    if len(text) < 2:
        return {"code": text, "rank": text, "symbol": "?", "color": "#888", "suit": None}
    rank = text[:-1]
    suit_name = _LETTER_TO_SUIT.get(text[-1].upper())
    if not suit_name:
        return {"code": text, "rank": rank, "symbol": "?", "color": "#888", "suit": None}
    style = SUIT_STYLES[suit_name]
    return {
        "code": text,
        "rank": rank,
        "symbol": style["symbol"],
        "color": style["color"],
        "suit": suit_name,
    }


def styled_cards(cards) -> list[dict]:
    return [card_display(c) for c in (cards or [])]


def styled_table_rows(raw) -> list[dict]:
    rows = []
    for item in raw or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        name, cards = str(item[0]), list(item[1] or [])
        style = SUIT_STYLES.get(name, {"symbol": "•", "color": "#ddd"})
        rows.append(
            {
                "name": name,
                "symbol": style["symbol"],
                "color": style["color"],
                "cards": styled_cards(cards),
            }
        )
    return rows


def handicap_table(handicap: tuple[tuple[str, ...], ...]) -> list[dict]:
    rows = []
    for idx, suit in enumerate(SUIT_NAMES):
        cards = handicap[idx] if idx < len(handicap) else ()
        style = SUIT_STYLES[suit]
        rows.append(
            {
                "name": suit,
                "symbol": style["symbol"],
                "color": style["color"],
                "cards": styled_cards(cards),
            }
        )
    return rows


def draws_by_suit(draw_cards: tuple[str, ...]) -> list[dict]:
    buckets: dict[str, list[str]] = {s: [] for s in SUIT_NAMES}
    for card in draw_cards or ():
        disp = card_display(card)
        if disp["suit"]:
            buckets[disp["suit"]].append(card)
    rows = []
    for suit in SUIT_NAMES:
        style = SUIT_STYLES[suit]
        cards = buckets[suit]
        rows.append(
            {
                "name": suit,
                "symbol": style["symbol"],
                "color": style["color"],
                "cards": styled_cards(cards) if cards else [],
            }
        )
    return rows


def fingerprint_payload(fp) -> dict:
    from game_analyzer.similarity import GameFingerprint

    assert isinstance(fp, GameFingerprint)
    winner = fp.winner_suit.title() if fp.winner_suit else None
    return {
        "game_id": fp.game_id,
        "winner": winner,
        "handicap": handicap_table(fp.handicap_cards),
        "draws": draws_by_suit(fp.draw_cards),
        "draw_count": len(fp.draw_cards),
        "draw_rounds": len(fp.draw_cards) // 3 if fp.draw_cards else 0,
    }
