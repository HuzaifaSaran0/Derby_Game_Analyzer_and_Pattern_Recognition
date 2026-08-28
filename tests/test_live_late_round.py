"""Live late-round alert path: production trust filter + _maybe_late_round_alerts."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.similarity import evaluate_late_round_cascade
from game_analyzer.store import GameStore
from tests.test_late_round_golden import _record_game


def _reset_live_alert_state() -> None:
    import game_analyzer.live as live

    live._LATE_ROUND_GAME_ID = None
    live._LATE_ROUND_ALERTED = set()
    live._LAST_LATE_SIGNALS = {}


def _alert_config(log_path: Path) -> dict:
    return {
        "similarity": {"notify": True, "late_rounds": True, "log_path": str(log_path)},
        "alerts": {"log_path": str(log_path)},
    }


def _live_decision(
    game_id: str,
    drawn_cards: tuple[str, ...],
    *,
    should_save: bool = True,
) -> SessionDecision:
    return SessionDecision(
        recording=True,
        session_id=f"s_{game_id}",
        seq=9,
        phase=GamePhase.IN_PLAY,
        reason="test",
        should_save=should_save,
        game_id=game_id,
        table_cards=(),
        drawn_cards=drawn_cards,
    )


@pytest.fixture(autouse=True)
def _clean_live_alert_globals():
    _reset_live_alert_state()
    yield
    _reset_live_alert_state()


def test_production_filter_excludes_table_only_corpus(tmp_path: Path):
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
    live = corpus[0].draw_cards

    open_hits = evaluate_late_round_cascade(live, corpus, production_only=False)
    prod_hits = evaluate_late_round_cascade(live, corpus, production_only=True)

    assert 3 in open_hits
    assert set(open_hits[3].matched_game_ids) == {"table_a", "table_b"}
    assert prod_hits == {}


def test_store_late_round_cascade_defaults_to_production_only(tmp_path: Path):
    store = GameStore(tmp_path / "table.sqlite")
    table_cards = (
        ("Spades", ("5S", "7S", "JS")),
        ("Hearts", ("4H", "3H", "10H")),
        ("Clubs", ("QC",)),
        ("Diamonds", ("3D", "7D", "6D", "KD")),
    )
    _record_game(
        store,
        tmp_path,
        "table_a",
        in_play_rounds=(),
        winner=Suit.DIAMONDS,
        table_cards=table_cards,
    )
    _record_game(
        store,
        tmp_path,
        "table_b",
        in_play_rounds=(),
        winner=Suit.HEARTS,
        table_cards=table_cards,
    )
    corpus = store.similarity_corpus()
    live = corpus[0].draw_cards

    assert store.late_round_cascade(live, live_game_id="live") == {}
    open_signals = store.late_round_cascade(
        live, live_game_id="live", production_only=False
    )
    assert 3 in open_signals
    assert set(open_signals[3].matched_game_ids) == {"table_a", "table_b"}


def test_maybe_late_round_alerts_true_positive_pair(tmp_path: Path):
    import game_analyzer.live as live

    store = GameStore(tmp_path / "golden.sqlite")
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
    )
    _record_game(
        store,
        tmp_path,
        "105327795",
        in_play_rounds=(
            ("5C", "JC", "5S"),
            ("9C", "4D", "9H"),
            ("5D", "3S", "8S"),
        ),
        winner=Suit.HEARTS,
    )
    corpus = store.similarity_corpus()
    live_draws = next(fp for fp in corpus if fp.game_id == "105282623").draw_cards
    log_path = tmp_path / "alerts.log"
    config = _alert_config(log_path)

    with patch.object(live, "GAME_STORE", store):
        with patch.object(live, "deliver_similarity_alert") as deliver:
            live._maybe_late_round_alerts(
                config,
                _live_decision("LIVE777", live_draws),
            )
            assert deliver.call_count == 1
            kwargs = deliver.call_args.kwargs
            assert kwargs["alert_kind"] == "twin-r3"
            assert "105282623" in kwargs["alert_message"]
            assert "105327795" in kwargs["alert_message"]
            assert "link=/similar?stage=r3" in kwargs["alert_message"]


def test_maybe_late_round_alerts_skips_golden_false_positive(tmp_path: Path):
    import game_analyzer.live as live

    store = GameStore(tmp_path / "false.sqlite")
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
    corpus = store.similarity_corpus()
    live_draws = next(fp for fp in corpus if fp.game_id == "105250381").draw_cards
    log_path = tmp_path / "alerts.log"
    config = _alert_config(log_path)

    with patch.object(live, "GAME_STORE", store):
        with patch.object(live, "deliver_similarity_alert") as deliver:
            live._maybe_late_round_alerts(
                config,
                _live_decision("LIVE888", live_draws),
            )
            assert deliver.call_count == 1
            msg = deliver.call_args.kwargs["alert_message"]
            assert "105250381" in msg
            assert "105274961" not in msg


def test_maybe_late_round_alerts_dedupes_per_round(tmp_path: Path):
    import game_analyzer.live as live

    store = GameStore(tmp_path / "dedupe.sqlite")
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
    )
    _record_game(
        store,
        tmp_path,
        "105327795",
        in_play_rounds=(
            ("5C", "JC", "5S"),
            ("9C", "4D", "9H"),
            ("5D", "3S", "8S"),
        ),
        winner=Suit.HEARTS,
    )
    corpus = store.similarity_corpus()
    live_draws = next(fp for fp in corpus if fp.game_id == "105282623").draw_cards
    decision = _live_decision("LIVE999", live_draws)
    config = _alert_config(tmp_path / "alerts.log")

    with patch.object(live, "GAME_STORE", store):
        with patch.object(live, "deliver_similarity_alert") as deliver:
            live._maybe_late_round_alerts(config, decision)
            live._maybe_late_round_alerts(config, decision)
            assert deliver.call_count == 1


def test_maybe_late_round_alerts_respects_notify_off(tmp_path: Path):
    import game_analyzer.live as live

    store = GameStore(tmp_path / "off.sqlite")
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
    )
    corpus = store.similarity_corpus()
    live_draws = corpus[0].draw_cards
    config = {"similarity": {"notify": False, "late_rounds": True}}

    with patch.object(live, "GAME_STORE", store):
        with patch.object(live, "deliver_similarity_alert") as deliver:
            live._maybe_late_round_alerts(
                config,
                _live_decision("LIVE000", live_draws),
            )
            deliver.assert_not_called()
