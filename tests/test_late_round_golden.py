"""Golden regression tests for late-round twin matching (production corpus cases)."""

from __future__ import annotations

from datetime import datetime

import pytest

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.similarity import (
    TRUST_VERIFIED,
    TRUST_WEAK,
    assess_late_round_twin_set,
    build_late_round_twin_sets,
    draw_round_cards,
    partition_late_round_twin_sets,
)
from game_analyzer.store import GameStore

HANDICAP = (
    ("AS", "KS", "QS"),
    ("2H", "3H", "4H"),
    ("6C", "8C", "9C"),
    ("10D", "JD", "QD"),
)


def _record_game(
    store: GameStore,
    tmp_path,
    game_id: str,
    *,
    in_play_rounds: tuple[tuple[str, ...], ...],
    winner: Suit,
    table_cards: tuple = (),
    draws_json: tuple[str, ...] = (),
) -> None:
    """Save a finished game with cumulative IN_PLAY frame draws."""
    shot = tmp_path / f"{game_id}.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 1, 1, 12, 0, 0)
    seq = 0
    for phase in (GamePhase.START, GamePhase.DEALT):
        seq += 1
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"s_{game_id}",
                seq=seq,
                phase=phase,
                reason="test",
                should_save=True,
                game_id=game_id,
                table_cards=table_cards,
            ),
            ExtractionResult(
                race_state=RaceState.BETTING,
                winner_suit=None,
                high_low=None,
                confident=True,
                handicap_cards=HANDICAP,
                draw_cards=(),
            ),
            shot,
            now,
            root=tmp_path,
        )
    cumulative: list[str] = []
    for rnd in in_play_rounds:
        seq += 1
        cumulative.extend(rnd)
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"s_{game_id}",
                seq=seq,
                phase=GamePhase.IN_PLAY,
                reason="test",
                should_save=True,
                game_id=game_id,
                table_cards=table_cards,
                drawn_cards=tuple(cumulative),
            ),
            ExtractionResult(
                race_state=RaceState.BETTING,
                winner_suit=None,
                high_low=None,
                confident=True,
                handicap_cards=HANDICAP,
                draw_cards=rnd,
            ),
            shot,
            now,
            root=tmp_path,
        )
    seq += 1
    store.record(
        SessionDecision(
            recording=True,
            session_id=f"s_{game_id}",
            seq=seq,
            phase=GamePhase.FINISHED,
            reason="test",
            should_save=True,
            game_id=game_id,
            table_cards=table_cards,
            drawn_cards=tuple(cumulative),
        ),
        ExtractionResult(
            race_state=RaceState.FINISHED,
            winner_suit=winner,
            high_low=None,
            confident=True,
            handicap_cards=HANDICAP,
            draw_cards=in_play_rounds[-1] if in_play_rounds else (),
        ),
        shot,
        now,
        root=tmp_path,
    )
    if draws_json:
        import json
        import sqlite3

        with sqlite3.connect(store.path) as con:
            con.execute(
                "UPDATE games SET draws_json=? WHERE game_id=?",
                (json.dumps(list(draws_json)), game_id),
            )
            con.commit()
        store.invalidate_similarity_cache()


def _r3_sets(store: GameStore):
    store.invalidate_similarity_cache()
    return [s for s in build_late_round_twin_sets(store.similarity_corpus()) if s.stage == "R3"]


def _pair_in_same_r3(store: GameStore, a: str, b: str) -> bool:
    for twin_set in _r3_sets(store):
        ids = {g.game_id for g in twin_set.games}
        if a in ids and b in ids:
            return True
    return False


@pytest.fixture
def golden_store(tmp_path):
    store = GameStore(tmp_path / "golden.sqlite")
    # Production false-positive pair (table order masked different frame R3).
    _record_game(
        store,
        tmp_path,
        "105250381",
        in_play_rounds=(
            ("3C", "10C", "AH"),
            ("9C", "2S", "QS"),
            ("4D", "5S", "9S"),
        ),
        winner=Suit.SPADES,
        table_cards=(
            ("Spades", ("2S", "QS", "5S", "9S")),
            ("Hearts", ("AH",)),
            ("Clubs", ("3C", "10C", "9C")),
            ("Diamonds", ("4D",)),
        ),
        draws_json=("10S",),
    )
    _record_game(
        store,
        tmp_path,
        "105274961",
        in_play_rounds=(
            ("3C", "2D", "AH"),
            ("10C", "4S", "8S"),
            ("AD", "6D", "7S"),
            ("9C", "6H", "9H"),
        ),
        winner=Suit.CLUBS,
        table_cards=(
            ("Spades", ("4S", "8S", "7S")),
            ("Hearts", ("AH", "6H", "9H")),
            ("Clubs", ("3C", "10C", "9C", "6C", "7C")),
            ("Diamonds", ("2D", "AD", "6D", "KD")),
        ),
        draws_json=("6C", "7C", "KD"),
    )
    # Production true-positive pair.
    _record_game(
        store,
        tmp_path,
        "105282623",
        in_play_rounds=(
            ("5C", "JC", "5S"),
            ("9C", "4D", "9H"),
            ("5D", "3S", "8S"),
        ),
        winner=Suit.SPADES,
        draws_json=(
            "5C", "JC", "5S", "9C", "4D", "9H", "5D", "3S", "8S", "QS", "KS"
        ),
    )
    _record_game(
        store,
        tmp_path,
        "105327795",
        in_play_rounds=(
            ("JC", "7D", "5H"),
            ("7C", "2H", "4H"),
            ("5D", "3S", "8S"),
            ("8C", "6D", "KD"),
        ),
        winner=Suit.DIAMONDS,
        draws_json=(
            "JC",
            "7D",
            "5H",
            "7C",
            "2H",
            "4H",
            "5D",
            "3S",
            "8S",
            "8C",
            "6D",
            "KD",
            "5C",
            "9D",
            "10S",
        ),
    )
    _record_game(
        store,
        tmp_path,
        "105275961",
        in_play_rounds=(
            ("10C", "4D", "QS"),
            ("4C", "7C", "9D"),
            ("6D", "JD", "QH"),
        ),
        winner=Suit.DIAMONDS,
        draws_json=("10C", "4D", "QS", "4C", "7C", "9D", "6D", "JD", "QH", "KD", "10H"),
    )
    _record_game(
        store,
        tmp_path,
        "105280099",
        in_play_rounds=(
            ("6C", "9C", "8H"),
            ("4C", "7C", "AH"),
            ("6D", "JD", "QH"),
            ("3S", "8S", "QS"),
        ),
        winner=Suit.SPADES,
        draws_json=(
            "6C",
            "9C",
            "8H",
            "4C",
            "7C",
            "AH",
            "6D",
            "JD",
            "QH",
            "3S",
            "8S",
            "QS",
            "9S",
            "JS",
        ),
    )
    return store


def test_golden_false_positive_pairs_never_match(golden_store: GameStore):
    assert not _pair_in_same_r3(golden_store, "105250381", "105274961")


def test_golden_true_positive_pairs_stay_matched(golden_store: GameStore):
    assert _pair_in_same_r3(golden_store, "105282623", "105327795")
    assert _pair_in_same_r3(golden_store, "105275961", "105280099")


def test_golden_matched_pairs_have_expected_r3(golden_store: GameStore):
    for a, b, expected in (
        ("105282623", "105327795", ("5D", "3S", "8S")),
        ("105275961", "105280099", ("6D", "JD", "QH")),
    ):
        matched = [
            s
            for s in _r3_sets(golden_store)
            if {g.game_id for g in s.games} == {a, b}
        ]
        assert len(matched) == 1
        assert draw_round_cards(matched[0].games[0].draw_cards, 3) == expected


def test_golden_true_pairs_are_frame_verified(golden_store: GameStore):
    trusted, excluded = golden_store.late_round_twin_sets_partitioned()
    assert not excluded
    for twin_set in trusted:
        assert twin_set.trust == TRUST_VERIFIED
        level, notes = assess_late_round_twin_set(twin_set)
        assert level == TRUST_VERIFIED
        assert not notes


def test_table_only_games_marked_weak_and_excluded(tmp_path):
    store = GameStore(tmp_path / "table.sqlite")
    table_cards = (
        ("Spades", ("5S", "7S", "JS")),
        ("Hearts", ("4H", "3H", "10H")),
        ("Clubs", ("QC",)),
        ("Diamonds", ("3D", "7D", "6D", "KD")),
    )
    for gid in ("table_a", "table_b"):
        _record_game(
            store,
            tmp_path,
            gid,
            in_play_rounds=(),
            winner=Suit.DIAMONDS,
            table_cards=table_cards,
        )
    corpus = store.similarity_corpus()
    assert all(fp.draw_source == "table" for fp in corpus)
    all_sets = store.late_round_twin_sets(production_only=False)
    assert all_sets
    assert all(s.trust == TRUST_WEAK for s in all_sets)
    trusted, excluded = store.late_round_twin_sets_partitioned()
    assert not trusted
    assert excluded
