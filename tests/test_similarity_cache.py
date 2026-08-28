"""Tests for persisted late-round twin-set cache."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.similarity import build_late_round_twin_sets, partition_late_round_twin_sets
from game_analyzer.similarity_cache import (
    SIMILARITY_LOGIC_VERSION,
    build_cache_document,
    corpus_fingerprint,
    invalidate_cache,
    load_partitioned_twin_sets,
    rebuild_cache,
    validate_cache_document,
)
from game_analyzer.store import GameStore

HANDICAP = (
    ("AS", "KS", "QS"),
    ("2H", "3H", "4H"),
    ("6C", "8C", "9C"),
    ("10D", "JD", "QD"),
)
R1 = ("5H", "7S", "AD")
R2 = ("3C", "6D", "4S")
R3 = ("9S", "8H", "7C")


def _record_finished(store: GameStore, tmp_path: Path, game_id: str):
    shot = tmp_path / f"{game_id}.png"
    shot.write_bytes(b"x")
    now = datetime(2026, 1, 1, 12, 0, 0)
    cumulative: list[str] = []
    for phase in (GamePhase.START, GamePhase.DEALT):
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"s_{game_id}",
                seq=1,
                phase=phase,
                reason="test",
                should_save=True,
                game_id=game_id,
                table_cards=(),
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
    for rnd in (R1, R2, R3):
        cumulative.extend(rnd)
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"s_{game_id}",
                seq=2,
                phase=GamePhase.IN_PLAY,
                reason="test",
                should_save=True,
                game_id=game_id,
                table_cards=(),
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
    store.record(
        SessionDecision(
            recording=True,
            session_id=f"s_{game_id}",
            seq=3,
            phase=GamePhase.FINISHED,
            reason="test",
            should_save=True,
            game_id=game_id,
            table_cards=(),
            drawn_cards=tuple(cumulative),
        ),
        ExtractionResult(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.SPADES,
            high_low=None,
            confident=True,
            handicap_cards=HANDICAP,
            draw_cards=R3,
        ),
        shot,
        now,
        root=tmp_path,
    )


def test_cache_matches_fresh_partition(tmp_path: Path):
    cache_path = tmp_path / "similarity_cache.json"
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    store.similarity_cache_path = cache_path
    _record_finished(store, tmp_path, "a")
    _record_finished(store, tmp_path, "b")

    corpus = store.similarity_corpus()
    rebuild_cache(corpus, cache_path)
    loaded = load_partitioned_twin_sets(corpus, cache_path)
    assert loaded is not None
    cached_trusted, cached_weak, cached_stats = loaded

    all_sets = build_late_round_twin_sets(corpus)
    trusted, weak = partition_late_round_twin_sets(all_sets)
    assert [s.key for s in cached_trusted] == [s.key for s in trusted]
    assert [s.key for s in cached_weak] == [s.key for s in weak]
    assert len(cached_stats) >= 1

    via_store, weak_via = store.late_round_twin_sets_partitioned()
    assert [s.key for s in via_store] == [s.key for s in trusted]
    assert [s.key for s in weak_via] == [s.key for s in weak]


def test_cache_invalidates_when_corpus_changes(tmp_path: Path):
    cache_path = tmp_path / "similarity_cache.json"
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    store.similarity_cache_path = cache_path
    _record_finished(store, tmp_path, "a")
    corpus = store.similarity_corpus()
    doc = build_cache_document(corpus)
    assert validate_cache_document(doc, corpus)

    _record_finished(store, tmp_path, "b")
    corpus2 = store.similarity_corpus()
    assert not validate_cache_document(doc, corpus2)
    assert corpus_fingerprint(corpus) != corpus_fingerprint(corpus2)


def test_new_game_invalidates_disk_cache(tmp_path: Path):
    cache_path = tmp_path / "similarity_cache.json"
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    store.similarity_cache_path = cache_path
    _record_finished(store, tmp_path, "a")
    store.rebuild_similarity_cache()
    assert cache_path.is_file()

    _record_finished(store, tmp_path, "c")
    assert not cache_path.is_file()


def test_imported_cache_used_when_fingerprint_matches(tmp_path: Path):
    cache_path = tmp_path / "similarity_cache.json"
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    store.similarity_cache_path = cache_path
    _record_finished(store, tmp_path, "a")
    _record_finished(store, tmp_path, "b")
    store.rebuild_similarity_cache()

    store2 = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    store2.similarity_cache_path = cache_path
    store2.invalidate_similarity_cache()  # memory only; file kept
    trusted, _ = store2.late_round_twin_sets_partitioned()
    assert trusted
    assert cache_path.is_file()


def test_cache_document_has_logic_version(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    _record_finished(store, tmp_path, "x")
    doc = build_cache_document(store.similarity_corpus())
    assert doc["logic_version"] == SIMILARITY_LOGIC_VERSION
    assert doc["corpus_fingerprint"]


def test_invalidate_cache_removes_file(tmp_path: Path):
    cache_path = tmp_path / "similarity_cache.json"
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    store.similarity_cache_path = cache_path
    _record_finished(store, tmp_path, "z")
    rebuild_cache(store.similarity_corpus(), cache_path)
    invalidate_cache(cache_path)
    assert not cache_path.is_file()
