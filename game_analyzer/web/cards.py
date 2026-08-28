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


def friendly_card_label(card: str) -> str:
    """Plain label for alerts, e.g. ``5♦``."""
    disp = card_display(card)
    if not disp["suit"]:
        return disp["code"]
    return f"{disp['rank']}{disp['symbol']}"


def friendly_cards_text(cards) -> str:
    labels = [friendly_card_label(c) for c in (cards or []) if c]
    return " · ".join(labels) if labels else "—"


def draw_round_label(round_n: int) -> str:
    """Plain label for one draw round, e.g. 'Third round draw cards'."""
    names = {
        1: "First round draw cards",
        2: "Second round draw cards",
        3: "Third round draw cards",
        4: "Fourth round draw cards",
        5: "Fifth round draw cards",
    }
    return names.get(round_n, f"Round {round_n} draw cards")


def winner_display(suit: str | None) -> dict:
    name = (suit or "").strip().title() or None
    if not name:
        return {"name": None, "symbol": "?", "color": "#888", "label": "Unknown"}
    style = SUIT_STYLES.get(name, {"symbol": "?", "color": "#888"})
    return {
        "name": name,
        "symbol": style["symbol"],
        "color": style["color"],
        "label": f"{style['symbol']} {name}",
    }


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


def all_draw_rounds_payload(
    fp,
    *,
    matched_rounds: tuple[int, ...] | None = None,
) -> list[dict]:
    """Every saved draw round for one game, in order."""
    from game_analyzer.similarity import draw_round_cards, full_draw_rounds

    matched = set(matched_rounds or ())
    rounds_seen = full_draw_rounds(fp.draw_cards)
    rows: list[dict] = []
    for round_n in range(1, rounds_seen + 1):
        cards = draw_round_cards(fp.draw_cards, round_n)
        if not cards:
            continue
        rows.append(
            {
                "round_n": round_n,
                "label": draw_round_label(round_n),
                "cards": styled_cards(cards),
                "codes": list(cards),
                "matched": round_n in matched if matched else False,
            }
        )
    return rows


def late_round_game_payload(
    fp,
    *,
    matched_rounds: tuple[int, ...],
    round_cards: tuple[tuple[int, tuple[str, ...]], ...] | None = None,
) -> dict:
    """Handicap + every draw round saved for this game."""
    from game_analyzer.similarity import GameFingerprint, draw_round_cards, full_draw_rounds

    del round_cards
    assert isinstance(fp, GameFingerprint)
    winner = fp.winner_suit.title() if fp.winner_suit else None
    frame_r3 = draw_round_cards(fp.frame_draws, 3) if fp.frame_draws else None
    chosen_r3 = draw_round_cards(fp.draw_cards, 3)
    frame_verified = (
        bool(fp.frame_draws)
        and frame_r3 is not None
        and chosen_r3 is not None
        and frame_r3 == chosen_r3
    )
    draw_rounds = all_draw_rounds_payload(fp, matched_rounds=matched_rounds)
    return {
        "game_id": fp.game_id,
        "winner": winner,
        "handicap": handicap_table(fp.handicap_cards),
        "draw_source": fp.draw_source,
        "frame_verified": frame_verified,
        "draw_rounds": draw_rounds,
        "matched_round_ns": list(matched_rounds),
        "draw_count": len(fp.draw_cards),
        "draw_rounds_count": full_draw_rounds(fp.draw_cards),
    }
