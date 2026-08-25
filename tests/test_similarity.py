"""Tests for fingerprint similarity (exact-first, near secondary, live twin gate)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from game_analyzer.confidence import ConfidenceLevel, ConfidenceResult, evaluate_confidence
from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.similarity import (
    MatchStage,
    build_clusters,
    build_fingerprint,
    compare_fingerprints,
    evaluate_live_twin,
    find_matches,
)
from game_analyzer.store import GameStore

HANDICAP_A = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
HANDICAP_NEAR = (("AS", "KS", "JS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
# 8 shared → Jaccard 0.50 — below tightened near threshold (0.60 / ≥9 shared).
HANDICAP_WEAK = (("AS", "KS", "JS"), ("2H", "3H", "5H"), ("6C", "8C", "TC"), ("10D", "JD", "KD"))
HANDICAP_B = (("2S", "3S", "4S"), ("AH", "KH", "QH"), ("2C", "3C", "4C"), ("5D", "6D", "7D"))
R1 = ("5H", "7S", "AD")
R2 = ("3C", "6D", "4S")


def test_exact_handicap_match():
    a = build_fingerprint("1", HANDICAP_A, (), winner_suit="Spades")
    b = build_fingerprint("2", HANDICAP_A, (), winner_suit="Spades")
    c = build_fingerprint("3", HANDICAP_NEAR, (), winner_suit="Hearts")
    assert a is not None and b is not None and c is not None
    hit = compare_fingerprints(a, b)
    assert hit is not None
    assert hit.exact and hit.match_pct == 100.0
    assert hit.stage is MatchStage.HANDICAP
    near = compare_fingerprints(a, c)
    assert near is not None
    assert not near.exact
    assert near.match_pct >= 60.0


def test_near_requires_stronger_overlap():
    a = build_fingerprint("1", HANDICAP_A, (), winner_suit="Spades")
    weak = build_fingerprint("w", HANDICAP_WEAK, (), winner_suit="Hearts")
    assert a and weak
    assert compare_fingerprints(a, weak) is None


def test_cluster_badges_distinguish_exact_and_near():
    from game_analyzer.similarity import cluster_kind_badge, build_clusters

    handicap_near2 = (
        ("AS", "KS", "10S"),
        ("2H", "3H", "4H"),
        ("6C", "8C", "9C"),
        ("10D", "JD", "QD"),
    )
    corpus = [
        fp
        for fp in (
            build_fingerprint("1", HANDICAP_A, (), winner_suit="Spades"),
            build_fingerprint("2", HANDICAP_A, (), winner_suit="Spades"),
            build_fingerprint("3", HANDICAP_NEAR, (), winner_suit="Spades"),
            build_fingerprint("4", handicap_near2, (), winner_suit="Hearts"),
        )
        if fp is not None
    ]
    clusters = build_clusters(corpus)
    exact = next(c for c in clusters if c.exact)
    assert cluster_kind_badge(exact) == "EXACT"
    near_only = [c for c in clusters if not c.exact]
    assert near_only
    assert near_only[0].winners_same is True
    assert "same winners" in cluster_kind_badge(near_only[0]).lower()
    mixed = next(c for c in near_only if c.winners_same is False)
    assert "mixed" in cluster_kind_badge(mixed).lower()
    assert "browse only" in cluster_kind_badge(mixed).lower()


def test_deeper_exact_stage_preferred():
    a = build_fingerprint("1", HANDICAP_A, R1 + R2, winner_suit="Clubs")
    b = build_fingerprint("2", HANDICAP_A, R1 + R2, winner_suit="Clubs")
    assert a and b
    hit = compare_fingerprints(a, b)
    assert hit is not None
    assert hit.exact
    assert hit.stage is MatchStage.HANDICAP_R2


def test_find_matches_sorts_exact_first():
    query = build_fingerprint("q", HANDICAP_A, R1, winner_suit=None)
    corpus = [
        fp
        for fp in (
            build_fingerprint("e", HANDICAP_A, R1, winner_suit="Spades"),
            build_fingerprint("n", HANDICAP_NEAR, R1, winner_suit="Hearts"),
            build_fingerprint("x", HANDICAP_B, (), winner_suit="Clubs"),
        )
        if fp is not None
    ]
    assert query
    hits = find_matches(query, corpus)
    assert hits
    assert hits[0].exact
    assert hits[0].other.game_id == "e"


def test_clusters_exact_and_winner_agreement():
    corpus = [
        fp
        for fp in (
            build_fingerprint("1", HANDICAP_A, R1 + R2, winner_suit="Spades"),
            build_fingerprint("2", HANDICAP_A, R1 + R2, winner_suit="Spades"),
            build_fingerprint("3", HANDICAP_A, R1 + R2, winner_suit="Hearts"),
        )
        if fp is not None
    ]
    clusters = build_clusters(corpus)
    exact_r2 = [
        c
        for c in clusters
        if c.exact and c.stage is MatchStage.HANDICAP_R2 and c.size >= 2
    ]
    assert exact_r2
    assert exact_r2[0].majority_winner == "Spades"
    assert exact_r2[0].agreement_pct == round(100 * 2 / 3, 1)


def test_live_twin_requires_agreement_and_checks_confidence():
    query = build_fingerprint("live", HANDICAP_A, R1 + R2)
    twins = [
        fp
        for fp in (
            build_fingerprint("1", HANDICAP_A, R1 + R2, winner_suit="Spades"),
            build_fingerprint("2", HANDICAP_A, R1 + R2, winner_suit="Spades"),
            build_fingerprint("3", HANDICAP_A, R1 + R2, winner_suit="Spades"),
        )
        if fp is not None
    ]
    assert query

    signal = evaluate_live_twin(query, twins, confidence=None)
    assert signal is not None
    assert signal.suggested_winner == "Spades"
    assert signal.confidence_agrees is None

    conf = evaluate_confidence(HANDICAP_A, R1 + R2, pick="Spades", simulations=200, seed=1)
    if conf.ready and conf.level in {ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH}:
        ok = evaluate_live_twin(query, twins, confidence=conf)
        assert ok is not None
        assert ok.confidence_agrees is True

    conflict = ConfidenceResult(
        level=ConfidenceLevel.HIGH,
        pick="Hearts",
        track_leader="Hearts",
        track_gap=5,
        pick_on_track_leader=True,
        mc_probs={"Hearts": 0.9, "Spades": 0.05, "Clubs": 0.03, "Diamonds": 0.02},
        mc_pick=0.9,
        mc_margin=0.85,
        rivals_weak_count=3,
        draw_rounds=2,
        reasons=("test conflict",),
        confidence_pct=90,
    )
    assert evaluate_live_twin(query, twins, confidence=conflict) is None


def test_live_twin_needs_min_matches():
    query = build_fingerprint("live", HANDICAP_A, ())
    alone = [fp for fp in (build_fingerprint("1", HANDICAP_A, (), winner_suit="Spades"),) if fp]
    assert query
    assert evaluate_live_twin(query, alone, confidence=None) is None


def test_store_similarity_apis(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite")
    now = datetime(2026, 1, 1, 12, 0, 0)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x")

    for gid, winner in (("10", Suit.SPADES), ("11", Suit.SPADES), ("12", Suit.SPADES)):
        store.record(
            SessionDecision(
                recording=True,
                session_id=f"game_{gid}",
                seq=1,
                phase=GamePhase.FINISHED,
                reason="test",
                should_save=True,
                game_id=gid,
                table_cards=(),
                drawn_cards=R1 + R2,
                locked_guess=winner.value.title(),
                locked_guess_draws=R1 + R2,
                locked_guess_rounds=2,
            ),
            ExtractionResult(
                race_state=RaceState.FINISHED,
                winner_suit=winner,
                high_low=None,
                confident=True,
                handicap_cards=HANDICAP_A,
                draw_cards=R1 + R2,
            ),
            shot,
            now,
            root=tmp_path,
        )

    corpus = store.similarity_corpus()
    assert len(corpus) == 3
    clusters = store.similarity_clusters()
    assert any(c.exact and c.size >= 2 for c in clusters)
    hits = store.find_similar_to("10")
    assert any(h.other.game_id == "11" and h.exact for h in hits)
    signal = store.live_twin_signal(HANDICAP_A, R1 + R2, confidence=None, exclude_game_id="99")
    assert signal is not None
    assert signal.suggested_winner == "Spades"


def test_similarity_corpus_rebuilds_short_draws_json_from_frames(tmp_path: Path):
    """Corpus must rebuild full draws from IN_PLAY frames when draws_json was overwritten short."""
    store = GameStore(tmp_path / "games.sqlite")
    now = datetime(2026, 1, 1, 12, 0, 0)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x")

    store.record(
        SessionDecision(
            recording=True,
            session_id="game_50",
            seq=1,
            phase=GamePhase.DEALT,
            reason="test",
            should_save=True,
            game_id="50",
            table_cards=(),
        ),
        ExtractionResult(
            race_state=RaceState.BETTING,
            winner_suit=None,
            high_low=None,
            confident=True,
            handicap_cards=HANDICAP_A,
            draw_cards=(),
        ),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        SessionDecision(
            recording=True,
            session_id="game_50",
            seq=2,
            phase=GamePhase.IN_PLAY,
            reason="test",
            should_save=True,
            game_id="50",
            table_cards=(),
            drawn_cards=R1,
        ),
        ExtractionResult(
            race_state=RaceState.BETTING,
            winner_suit=None,
            high_low=None,
            confident=True,
            handicap_cards=HANDICAP_A,
            draw_cards=R1,
        ),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        SessionDecision(
            recording=True,
            session_id="game_50",
            seq=3,
            phase=GamePhase.IN_PLAY,
            reason="test",
            should_save=True,
            game_id="50",
            table_cards=(),
            drawn_cards=R1 + R2,
        ),
        ExtractionResult(
            race_state=RaceState.BETTING,
            winner_suit=None,
            high_low=None,
            confident=True,
            handicap_cards=HANDICAP_A,
            draw_cards=R2,
        ),
        shot,
        now,
        root=tmp_path,
    )
    store.record(
        SessionDecision(
            recording=True,
            session_id="game_50",
            seq=4,
            phase=GamePhase.FINISHED,
            reason="test",
            should_save=True,
            game_id="50",
            table_cards=(),
            drawn_cards=R2,
            locked_guess="Spades",
            locked_guess_draws=R1 + R2,
            locked_guess_rounds=2,
        ),
        ExtractionResult(
            race_state=RaceState.FINISHED,
            winner_suit=Suit.SPADES,
            high_low=None,
            confident=True,
            handicap_cards=HANDICAP_A,
            draw_cards=R2,
        ),
        shot,
        now,
        root=tmp_path,
    )

    game = store.get_game("50", root=tmp_path)
    assert game is not None
    assert game.draw_cards == R1 + R2

    import json
    import sqlite3

    with sqlite3.connect(store.path) as con:
        con.execute(
            "UPDATE games SET draws_json=? WHERE game_id=?",
            (json.dumps(list(R2)), "50"),
        )
        con.commit()
    store.invalidate_similarity_cache()
    fp = next(f for f in store.similarity_corpus() if f.game_id == "50")
    assert len(fp.draw_cards) == 6
    assert set(fp.draw_cards) == set(R1 + R2)
