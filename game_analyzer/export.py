"""Export clean game history from the SQLite store for external research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from game_analyzer.race_values import (
    SUIT_NAMES,
    TRACK_LENGTH,
    card_race_value,
    guess_ready,
    handicap_sums,
    suit_name_from_card,
    track_position,
)
from game_analyzer.store import DEFAULT_DB, GameStore, StoredFrame, StoredGame

DEFAULT_OUT = DEFAULT_DB.parent / "games_research_export.json"

META = {
    "description": (
        "Derby race card game: 4 suits (Spades, Hearts, Clubs, Diamonds). "
        "Each suit has 13 cards totaling 95 race points. Handicap removes 3 cards "
        "per suit. Each draw round reveals 3 cards without replacement from the "
        "remaining pool; matching suits move on the track by card value. "
        "First suit to reach 32 track points wins."
    ),
    "card_values": "A=11, 2-10=face, J/Q/K=10",
    "handicap_per_suit": 3,
    "cards_per_draw_round": 3,
    "track_length": TRACK_LENGTH,
    "suits": list(SUIT_NAMES),
}


def rebuild_rounds(frames: tuple[StoredFrame, ...]) -> list[list[str]]:
    rounds: list[list[str]] = []
    for frame in frames:
        if frame.phase not in ("IN_PLAY", "FINISHED") or not frame.draw_cards:
            continue
        cards = list(frame.draw_cards)
        if rounds:
            flat = [card for rd in rounds for card in rd]
            if len(cards) >= len(flat) and tuple(cards[: len(flat)]) == tuple(flat):
                cards = cards[len(flat) :]
        if cards:
            rounds.append(cards)
    return rounds


def first_to_32(rounds: list[list[str]]) -> tuple[str | None, dict[str, int]]:
    pos = {suit: 0 for suit in SUIT_NAMES}
    for rd in rounds:
        for card in rd:
            suit = suit_name_from_card(card)
            value = card_race_value(card)
            if suit and value:
                pos[suit] += value
        crossed = [suit for suit in SUIT_NAMES if pos[suit] >= TRACK_LENGTH]
        if crossed:
            return max(crossed, key=lambda s: pos[s]), pos
    return None, pos


def game_row(game: StoredGame) -> tuple[dict | None, str | None]:
    if not game.winner_suit:
        return None, "no_winner"
    if len(game.handicap_cards) != 4 or any(len(row) != 3 for row in game.handicap_cards):
        return None, "bad_handicap"

    rounds = rebuild_rounds(game.frames)
    flat = [card for rd in rounds for card in rd]
    if not flat or any(card_race_value(card) is None for card in flat):
        return None, "unreadable_cards"

    predicted, final_pos = first_to_32(rounds)
    winner = game.winner_suit.title()
    verified = predicted is not None and predicted.upper() == winner.upper()
    handicap = {suit: list(game.handicap_cards[i]) for i, suit in enumerate(SUIT_NAMES)}
    removed = handicap_sums(tuple(game.handicap_cards))
    deck_left = {
        suit: (95 - total if total is not None else None) for suit, total in removed.items()
    }
    moved_after_guess = track_position(tuple(game.guess_draw_cards))

    return (
        {
            "game_id": game.game_id,
            "started_at": game.started_at,
            "finished_at": game.finished_at,
            "winner": winner,
            "handicap": handicap,
            "handicap_removed_points": removed,
            "deck_points_left_after_handicap": deck_left,
            "draw_rounds": rounds,
            "all_draw_cards": flat,
            "total_rounds": len(rounds),
            "final_track_positions": final_pos,
            "guess_suit": game.guess_suit,
            "guess_draw_cards": list(game.guess_draw_cards),
            "guess_ready": guess_ready(game.guess_draw_cards),
            "track_after_guess_draws": moved_after_guess,
            "verified_first_to_32": verified,
        },
        None,
    )


def export_games(
    store: GameStore | None = None,
    *,
    verified_only: bool = False,
) -> tuple[list[dict], list[tuple[str, str]], dict]:
    store = store or GameStore()
    rows: list[dict] = []
    skipped: list[tuple[str, str]] = []

    for game_id in store.list_game_ids():
        game = store.get_game(game_id)
        if game is None:
            skipped.append((game_id, "missing"))
            continue
        row, reason = game_row(game)
        if row is None:
            skipped.append((game_id, reason or "unknown"))
            continue
        if verified_only and not row["verified_first_to_32"]:
            skipped.append((game_id, "not_verified"))
            continue
        rows.append(row)

    verified_count = sum(1 for row in rows if row["verified_first_to_32"])
    meta = {
        **META,
        "exported_games": len(rows),
        "verified_in_export": verified_count,
        "skipped": len(skipped),
        "verified_only_filter": verified_only,
    }
    return rows, skipped, meta


def write_export(
    path: Path,
    *,
    store: GameStore | None = None,
    verified_only: bool = False,
) -> dict:
    rows, skipped, meta = export_games(store, verified_only=verified_only)
    verified_rows = [row for row in rows if row["verified_first_to_32"]]
    payload = {
        "meta": meta,
        "games": rows,
        "verified_games_only": verified_rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return {
        "path": str(path.resolve()),
        "games": len(rows),
        "verified": len(verified_rows),
        "skipped": len(skipped),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export clean game history for research.")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--verified-only", action="store_true")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    store = GameStore(args.db) if args.db else GameStore()
    summary = write_export(args.output, store=store, verified_only=args.verified_only)
    print(f"Exported {summary['games']} games ({summary['verified']} verified first-to-32)")
    print(f"Skipped {summary['skipped']} games")
    print(f"File: {summary['path']}")


if __name__ == "__main__":
    main()
