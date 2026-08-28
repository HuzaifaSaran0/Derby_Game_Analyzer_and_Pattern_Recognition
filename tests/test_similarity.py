"""Tests for fingerprint similarity (exact-first, near secondary, live twin gate)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

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


def test_live_twin_requires_agreement():
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

    signal = evaluate_live_twin(query, twins)
    assert signal is not None
    assert signal.suggested_winner == "Spades"


def test_live_twin_needs_min_matches():
    query = build_fingerprint("live", HANDICAP_A, ())
    alone = [fp for fp in (build_fingerprint("1", HANDICAP_A, (), winner_suit="Spades"),) if fp]
    assert query
    assert evaluate_live_twin(query, alone) is None


def test_live_twin_rejects_low_agreement():
    query = build_fingerprint("live", HANDICAP_A, R1 + R2)
    mixed = [
        fp
        for fp in (
            build_fingerprint("1", HANDICAP_A, R1 + R2, winner_suit="Spades"),
            build_fingerprint("2", HANDICAP_A, R1 + R2, winner_suit="Hearts"),
        )
        if fp is not None
    ]
    assert query
    # 50% agreement < LIVE_AGREE_MIN (0.80)
    assert evaluate_live_twin(query, mixed) is None


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
    signal = store.live_twin_signal(HANDICAP_A, R1 + R2, exclude_game_id="99")
    assert signal is not None
    assert signal.suggested_winner == "Spades"


def test_similarity_draws_ignores_suit_table_order():
    from game_analyzer.store import _similarity_draws

    frames = ("3D", "7D", "4H", "QC", "3H", "5S", "6D", "10H", "7S")
    # Table groups by suit — same cards but wrong round order; longer than frames.
    table = ("5S", "7S", "JS", "4H", "3H", "10H", "QC", "3D", "7D", "6D", "KD")
    assert _similarity_draws(frames, (), (), table) == frames
    assert _similarity_draws((), (), (), table) == table


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


def test_late_round_cascade_and_stats():
    from game_analyzer.similarity import (
        draw_round_cards,
        evaluate_late_round_cascade,
        late_round_corpus_stats,
    )

    R3 = ("9S", "8H", "7C")
    R4 = ("6S", "5H", "4C")
    R5 = ("3S", "2H", "AC")
    other_r3 = ("9S", "8H", "7D")  # different R3
    draws_a = R1 + R2 + R3 + R4 + R5
    draws_b = R1 + ("3C", "6D", "5S") + R3 + R4 + ("KS", "QH", "JD")
    draws_c = R1 + R2 + R3 + ("AS", "KH", "QD")  # R3 match only
    draws_d = R1 + R2 + other_r3 + R4

    corpus = [
        fp
        for fp in (
            build_fingerprint("a", HANDICAP_A, draws_a, winner_suit="Spades"),
            build_fingerprint("b", HANDICAP_B, draws_b, winner_suit="Spades"),
            build_fingerprint("c", HANDICAP_NEAR, draws_c, winner_suit="Hearts"),
            build_fingerprint("d", HANDICAP_WEAK, draws_d, winner_suit="Clubs"),
        )
        if fp is not None
    ]
    assert draw_round_cards(draws_a, 3) == R3

    live = R1 + R2 + R3 + R4 + R5
    signals = evaluate_late_round_cascade(live, corpus, live_game_id="live")
    assert 3 in signals and 4 in signals
    assert set(signals[3].matched_game_ids) == {"a", "b", "c"}
    assert set(signals[4].matched_game_ids) == {"a", "b"}
    # R5 only a matches within R4 pool
    assert 5 in signals
    assert signals[5].matched_game_ids == ("a",)
    assert "link=/similar?stage=r3" in signals[3].message

    stats = late_round_corpus_stats(corpus)
    by_stage = {s.stage: s for s in stats}
    assert by_stage["R3"].twin_sets >= 1
    assert by_stage["R3→R4"].twin_sets >= 1
    assert by_stage["R3"].same_winner_pct is not None


def test_draw_round_key_requires_exact_order():
    from game_analyzer.similarity import draw_round_key

    a = ("9S", "8H", "7C")
    b = ("7C", "8H", "9C")  # same cards, different order
    assert draw_round_key(a, 1) == draw_round_key(("9S", "8H", "7C"), 1)
    assert draw_round_key(a, 1) != draw_round_key(b, 1)


def test_build_late_round_twin_sets():
    from game_analyzer.similarity import build_late_round_twin_sets

    R3 = ("9S", "8H", "7C")
    R4 = ("6S", "5H", "4C")
    R5 = ("3S", "2H", "AC")
    draws_a = R1 + R2 + R3 + R4 + R5
    draws_b = R1 + ("3C", "6D", "5S") + R3 + R4 + ("KS", "QH", "JD")
    draws_c = R1 + R2 + R3 + ("AS", "KH", "QD")

    corpus = [
        fp
        for fp in (
            build_fingerprint("a", HANDICAP_A, draws_a, winner_suit="Spades"),
            build_fingerprint("b", HANDICAP_B, draws_b, winner_suit="Spades"),
            build_fingerprint("c", HANDICAP_NEAR, draws_c, winner_suit="Hearts"),
        )
        if fp is not None
    ]
    sets = build_late_round_twin_sets(corpus)
    by_stage = {s.stage: s for s in sets}
    assert "R3" in by_stage
    assert set(g.game_id for g in by_stage["R3"].games) == {"a", "b", "c"}
    assert by_stage["R3"].matched_rounds == (3,)
    assert by_stage["R3"].round_cards[0][1] == R3
    assert "R3→R4" in by_stage
    assert set(g.game_id for g in by_stage["R3→R4"].games) == {"a", "b"}
    assert by_stage["R3→R4"].matched_rounds == (3, 4)


def test_store_late_round_apis(tmp_path: Path):
    store = GameStore(tmp_path / "games.sqlite")
    now = datetime(2026, 1, 1, 12, 0, 0)
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"x")
    R3 = ("9S", "8H", "7C")
    R4 = ("6S", "5H", "4C")
    full = R1 + R2 + R3 + R4

    for gid, winner in (("20", Suit.DIAMONDS), ("21", Suit.DIAMONDS)):
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
                drawn_cards=full,
            ),
            ExtractionResult(
                race_state=RaceState.FINISHED,
                winner_suit=winner,
                high_low=None,
                confident=True,
                handicap_cards=HANDICAP_A if gid == "20" else HANDICAP_B,
                draw_cards=full,
            ),
            shot,
            now,
            root=tmp_path,
        )

    signals = store.late_round_cascade(full, live_game_id="live99")
    assert 3 in signals
    assert set(signals[3].matched_game_ids) == {"20", "21"}
    assert 4 in signals
    stats = store.late_round_stats()
    assert any(s.round_n == 3 and s.twin_sets >= 1 for s in stats)
