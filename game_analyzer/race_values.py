from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

"""Race value helpers: deck points (95) and track distance (32)."""

FULL_SUIT_TOTAL = 95  # one suit: A=11, 2–10 face, J/Q/K=10 → 95 total
TRACK_LENGTH = 32  # first suit to reach 32 on draw cards wins
CARDS_PER_DRAW_ROUND = 3
MIN_GUESS_DRAW_ROUNDS = 2  # minimum draw rounds before an official guess
MAX_GUESS_DRAW_ROUNDS = 3  # use a third round when captured before FINISHED
MIN_GUESS_DRAWS = MIN_GUESS_DRAW_ROUNDS * CARDS_PER_DRAW_ROUND
MAX_GUESS_DRAWS = MAX_GUESS_DRAW_ROUNDS * CARDS_PER_DRAW_ROUND
GUESS_DRAW_ROUNDS = MIN_GUESS_DRAW_ROUNDS

# Option B: finish vs track blend by draw round (0–2).
# Round 0 = handicap only (raw deck), round 1 = preview, round 2 = official guess.
# Option C: from round 1 onward, "deck" side uses projected finish (moved + expected future).
BLEND_BY_ROUND: tuple[tuple[float, float], ...] = (
    (1.0, 0.0),  # 0 draw rounds — raw deck only
    (0.5, 0.5),  # 1 draw round — preview only
    (0.25, 0.75),  # 2+ draw rounds — kept for display / fallback
    (0.25, 0.75),  # 3 draw rounds — official guess uses Layer 4 blend
)

# Layer 4 (round 2 only): track + future + combo finish paths + draw-pool share.
LAYER4_WEIGHTS: tuple[float, float, float, float] = (0.50, 0.10, 0.15, 0.25)

MEAN_CARD_VALUE = FULL_SUIT_TOTAL / 13  # ~7.31 per card in a full suit

SUIT_NAMES = ("Spades", "Hearts", "Clubs", "Diamonds")
_SUIT_BY_LETTER = {"S": "Spades", "H": "Hearts", "C": "Clubs", "D": "Diamonds"}


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


def suit_name_from_card(card: str) -> str | None:
    if len(card) < 2:
        return None
    return _SUIT_BY_LETTER.get(card[-1].upper())


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


def draw_sums_by_suit(draw_cards: tuple[str, ...]) -> dict[str, int | None]:
    """How far each suit moved on the track (sum of its draw card values)."""
    out: dict[str, int | None] = {suit: 0 for suit in SUIT_NAMES}
    for card in draw_cards:
        suit_name = suit_name_from_card(card)
        if suit_name is None:
            continue
        value = card_race_value(card)
        if value is None:
            out[suit_name] = None
            continue
        if out[suit_name] is not None:
            out[suit_name] += value
    return out


def draws_for_guess(draw_cards: tuple[str, ...]) -> tuple[str, ...]:
    """Draw cards used for guessing: up to three rounds (nine cards) when available."""
    return draw_cards[:MAX_GUESS_DRAWS]


def guess_draw_rounds(draw_cards: tuple[str, ...]) -> int:
    """Full draw rounds included in the guess slice (0–3)."""
    return min(MAX_GUESS_DRAW_ROUNDS, len(draws_for_guess(draw_cards)) // CARDS_PER_DRAW_ROUND)


def draw_rounds_seen(draw_cards: tuple[str, ...]) -> int:
    """How many full or partial draw rounds are in the guess slice (0–3)."""
    return min(MAX_GUESS_DRAW_ROUNDS, len(draws_for_guess(draw_cards)) // CARDS_PER_DRAW_ROUND)


def guess_ready(draw_cards: tuple[str, ...]) -> bool:
    """True once at least two draw rounds (six cards) are available."""
    return len(draw_cards) >= MIN_GUESS_DRAWS


def all_draws_from_in_play_frames(
    frames: Iterable[tuple[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    """Rebuild every draw round from saved IN_PLAY frames (handles per-round or cumulative rows)."""
    ordered: list[str] = []
    for phase, cards in frames:
        if phase != "IN_PLAY" or not cards:
            continue
        if (
            ordered
            and len(cards) >= len(ordered)
            and tuple(cards[: len(ordered)]) == tuple(ordered)
        ):
            ordered.extend(cards[len(ordered) :])
        else:
            ordered.extend(cards)
    return tuple(ordered)


def draws_from_in_play_frames(
    frames: Iterable[tuple[str, tuple[str, ...]]],
) -> tuple[str, ...]:
    """Up to three draw rounds from saved IN_PLAY frames."""
    return draws_for_guess(all_draws_from_in_play_frames(frames))


def remaining_after_handicap(handicap_cards: tuple[tuple[str, ...], ...]) -> dict[str, int | None]:
    """Points still in each suit's deck: 95 minus handicap sum."""
    removed = handicap_sums(handicap_cards)
    return {
        suit: (FULL_SUIT_TOTAL - total if total is not None else None)
        for suit, total in removed.items()
    }


def remaining_deck(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> dict[str, int | None]:
    """Deck points left: 95 minus handicap and draw sums for each suit."""
    removed_h = handicap_sums(handicap_cards)
    removed_d = draw_sums_by_suit(draws_for_guess(draw_cards))
    out: dict[str, int | None] = {}
    for suit in SUIT_NAMES:
        h = removed_h[suit]
        d = removed_d[suit]
        if h is None or d is None:
            out[suit] = None
        else:
            out[suit] = FULL_SUIT_TOTAL - h - d
    return out


def track_position(draw_cards: tuple[str, ...]) -> dict[str, int | None]:
    """Distance each suit has moved toward 32 (draw cards only)."""
    return draw_sums_by_suit(draws_for_guess(draw_cards))


def track_distance_to_go(draw_cards: tuple[str, ...]) -> dict[str, int | None]:
    """How many track points each suit still needs to reach 32."""
    moved = track_position(draw_cards)
    return {
        suit: (TRACK_LENGTH - value if value is not None else None)
        for suit, value in moved.items()
    }


def blend_weights(draw_rounds: int) -> tuple[float, float]:
    """Return (deck_weight, track_weight) for 0–2 draw rounds seen."""
    idx = min(max(draw_rounds, 0), len(BLEND_BY_ROUND) - 1)
    return BLEND_BY_ROUND[idx]


def deck_score(deck_remaining: dict[str, int | None]) -> dict[str, float | None]:
    """Deck strength 0–1: points left divided by 95."""
    return {
        suit: (value / FULL_SUIT_TOTAL if value is not None else None)
        for suit, value in deck_remaining.items()
    }


def track_score(track_moved: dict[str, int | None]) -> dict[str, float | None]:
    """Track progress 0–1: distance moved toward 32."""
    return {
        suit: (value / TRACK_LENGTH if value is not None else None)
        for suit, value in track_moved.items()
    }


def expected_future_move(moved: int, deck_left: int) -> float:
    """Estimate how many more track points a suit can still draw from its pile."""
    if deck_left <= 0:
        return 0.0
    if moved <= 0:
        return deck_left * (MEAN_CARD_VALUE / TRACK_LENGTH)
    return deck_left * (moved / TRACK_LENGTH)


def expected_total(moved: int, deck_left: int) -> float:
    """Projected finish distance: already moved + expected future movement."""
    return moved + expected_future_move(moved, deck_left)


def future_score(
    track_moved: dict[str, int | None],
    deck_remaining: dict[str, int | None],
) -> dict[str, float | None]:
    """Option C deck-side signal: expected future movement only (0–1)."""
    out: dict[str, float | None] = {}
    for suit in SUIT_NAMES:
        moved = track_moved.get(suit)
        deck_left = deck_remaining.get(suit)
        if moved is None or deck_left is None:
            out[suit] = None
        else:
            out[suit] = expected_future_move(moved, deck_left) / TRACK_LENGTH
    return out


def finish_score(
    track_moved: dict[str, int | None],
    deck_remaining: dict[str, int | None],
) -> dict[str, float | None]:
    """Option C: projected distance to finish as 0–1 (capped at 32)."""
    out: dict[str, float | None] = {}
    for suit in SUIT_NAMES:
        moved = track_moved.get(suit)
        deck_left = deck_remaining.get(suit)
        if moved is None or deck_left is None:
            out[suit] = None
        else:
            total = expected_total(moved, deck_left)
            out[suit] = min(1.0, total / TRACK_LENGTH)
    return out


def finish_side_score(
    draw_rounds: int,
    deck_remaining: dict[str, int | None],
    track_moved: dict[str, int | None],
) -> dict[str, float | None]:
    """Non-track side: raw deck before draws, expected future movement after."""
    if draw_rounds <= 0:
        return deck_score(deck_remaining)
    return future_score(track_moved, deck_remaining)


def combined_scores(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> dict[str, float | None]:
    """Blend finish/deck + track scores using weights for current draw round."""
    from game_analyzer.deck_combos import combo_side_score, draw_share, remaining_card_labels

    rounds = draw_rounds_seen(draw_cards)
    deck_w, track_w = blend_weights(rounds)
    deck_rem = remaining_deck(handicap_cards, draw_cards)
    moved = track_position(draw_cards)
    finish = finish_side_score(rounds, deck_rem, moved)
    track = track_score(moved)
    if rounds >= MIN_GUESS_DRAW_ROUNDS:
        track_w4, future_w, combo_w, share_w = LAYER4_WEIGHTS
        combo = combo_side_score(handicap_cards, draw_cards, moved)
        share = draw_share(remaining_card_labels(handicap_cards, draw_cards))
        out: dict[str, float | None] = {}
        for suit in SUIT_NAMES:
            f = finish[suit]
            t = track[suit]
            c = combo[suit]
            s = share[suit]
            if f is None or t is None or c is None or s is None:
                out[suit] = None
            else:
                out[suit] = track_w4 * t + future_w * f + combo_w * c + share_w * s
        return out
    out = {}
    for suit in SUIT_NAMES:
        f = finish[suit]
        t = track[suit]
        if f is None or t is None:
            out[suit] = None
        else:
            out[suit] = deck_w * f + track_w * t
    return out


def favourite_combined(scores: dict[str, float | None]) -> str | None:
    ranked = [(s, v) for s, v in scores.items() if v is not None]
    if len(ranked) < 4:
        return None
    return max(ranked, key=lambda t: t[1])[0]


def favourite_suit(remaining: dict[str, int | None]) -> str | None:
    """Suit with the highest remaining deck value — best chance to win."""
    ranked = [(s, v) for s, v in remaining.items() if v is not None]
    if len(ranked) < 4:
        return None
    best = max(ranked, key=lambda t: t[1])
    return best[0]


def race_guess(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> str | None:
    """Official pick from two or three draw rounds (Layer 4 blend). Never uses winner OCR."""
    if not guess_ready(draw_cards):
        return None
    return favourite_combined(combined_scores(handicap_cards, draw_cards))


@dataclass(frozen=True)
class LockedGuess:
    suit: str
    draw_cards: tuple[str, ...]
    draw_rounds: int


def lock_guess(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...],
) -> LockedGuess | None:
    """Compute the guess to freeze before a FINISHED frame (card math only)."""
    if not guess_ready(draw_cards):
        return None
    used = draws_for_guess(draw_cards)
    guess = race_guess(handicap_cards, draw_cards)
    if not guess:
        return None
    return LockedGuess(suit=guess, draw_cards=used, draw_rounds=guess_draw_rounds(draw_cards))


def preview_guess(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> str | None:
    """Leading suit from the current blend (including handicap-only preview)."""
    return favourite_combined(combined_scores(handicap_cards, draw_cards))


def pre_race_guess(handicap_cards: tuple[tuple[str, ...], ...]) -> str | None:
    """Handicap-only pick (100% deck)."""
    return preview_guess(handicap_cards, ())


def suits_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    return a.upper() == b.upper()


def parse_handicap_rows(rows) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(row) for row in rows)


def parse_draw_list(rows) -> tuple[str, ...]:
    return tuple(rows)


@dataclass(frozen=True)
class RaceSnapshot:
    deck_remaining: dict[str, int | None]
    track_moved: dict[str, int | None]
    track_to_go: dict[str, int | None]
    deck_pct: dict[str, float | None]
    track_pct: dict[str, float | None]
    expected_pct: dict[str, float | None]
    combo_pct: dict[str, float | None]
    draw_share_pct: dict[str, float | None]
    remaining_cards: dict[str, tuple[str, ...] | None]
    combined_score: dict[str, float | None]
    deck_weight: float
    track_weight: float
    layer4_weights: tuple[float, float, float, float] | None
    guess: str | None
    preview: str | None
    draw_rounds_used: int
    guess_ready: bool


def race_snapshot(
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
) -> RaceSnapshot:
    from game_analyzer.deck_combos import combo_side_score, draw_share, remaining_card_labels

    rounds = draw_rounds_seen(draw_cards)
    ready = guess_ready(draw_cards)
    deck_rem = remaining_deck(handicap_cards, draw_cards)
    moved = track_position(draw_cards)
    deck_p = deck_score(deck_rem)
    track_p = track_score(moved)
    expected_p = finish_score(moved, deck_rem)
    combined = combined_scores(handicap_cards, draw_cards)
    deck_w, track_w = blend_weights(rounds)
    rem_cards = remaining_card_labels(handicap_cards, draw_cards)
    combo_p = combo_side_score(handicap_cards, draw_cards, moved)
    share_p = draw_share(rem_cards)
    layer4 = LAYER4_WEIGHTS if rounds >= MIN_GUESS_DRAW_ROUNDS else None
    return RaceSnapshot(
        deck_remaining=deck_rem,
        track_moved=moved,
        track_to_go=track_distance_to_go(draw_cards),
        deck_pct=deck_p,
        track_pct=track_p,
        expected_pct=expected_p,
        combo_pct=combo_p,
        draw_share_pct=share_p,
        remaining_cards=rem_cards,
        combined_score=combined,
        deck_weight=deck_w,
        track_weight=track_w,
        layer4_weights=layer4,
        guess=race_guess(handicap_cards, draw_cards),
        preview=preview_guess(handicap_cards, draw_cards),
        draw_rounds_used=rounds,
        guess_ready=ready,
    )


@dataclass(frozen=True)
class PreRaceOutcome:
    guess: str | None
    winner: str | None
    correct: bool | None
    draw_rounds_used: int = 0
    guess_ready: bool = False


def pre_race_outcome(
    winner_suit: str | None,
    handicap_cards: tuple[tuple[str, ...], ...],
    draw_cards: tuple[str, ...] = (),
    locked_guess: str | None = None,
    locked_draw_rounds: int = 0,
) -> PreRaceOutcome:
    if locked_guess:
        guess = locked_guess
        ready = True
        rounds_used = locked_draw_rounds or guess_draw_rounds(draw_cards)
    else:
        snapshot = race_snapshot(handicap_cards, draw_cards)
        guess = snapshot.guess
        ready = snapshot.guess_ready
        rounds_used = snapshot.draw_rounds_used
    if not winner_suit:
        return PreRaceOutcome(
            guess=guess,
            winner=None,
            correct=None,
            draw_rounds_used=rounds_used,
            guess_ready=ready,
        )
    if not guess:
        return PreRaceOutcome(
            guess=None,
            winner=winner_suit,
            correct=None,
            draw_rounds_used=rounds_used,
            guess_ready=ready,
        )
    return PreRaceOutcome(
        guess=guess,
        winner=winner_suit,
        correct=suits_match(guess, winner_suit),
        draw_rounds_used=rounds_used,
        guess_ready=ready,
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
    records: Iterable[
        tuple[
            str | None,
            tuple[tuple[str, ...], ...],
            tuple[str, ...],
            str | None,
        ]
    ],
) -> GuessAccuracy:
    """Score locked or recomputed picks on finished games with at least two draw rounds."""
    correct = 0
    total = 0
    for winner, handicap, draw_cards, stored_guess in records:
        if not winner or not guess_ready(draw_cards):
            continue
        guess = stored_guess or race_guess(handicap, draw_cards)
        if not guess:
            continue
        total += 1
        if suits_match(guess, winner):
            correct += 1
    return GuessAccuracy(correct=correct, total=total)
