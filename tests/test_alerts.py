from datetime import datetime
from pathlib import Path

from game_analyzer.alerts import (
    AlertSettings,
    alert_settings_from_config,
    compute_alert_transition,
    deliver_alert,
    format_alert_message,
)
from game_analyzer.confidence import ConfidenceLevel, ConfidenceResult, evaluate_confidence, level_at_least
from game_analyzer.models import ExtractionResult, RaceState
from game_analyzer.session import GameSessionTracker

HANDICAP = (("AS", "KS", "QS"), ("2H", "3H", "4H"), ("6C", "8C", "9C"), ("10D", "JD", "QD"))
STRONG_R1 = ("AS", "KS", "QS")
STRONG_R2 = ("10S", "9S", "8S")
ROUND1 = ("5H", "7S", "AD")
ROUND2 = ("3C", "6D", "4S")


def _result(**kwargs) -> ExtractionResult:
    defaults = dict(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=(),
        handicap_cards=HANDICAP,
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


def test_level_at_least_helper():
    assert level_at_least(ConfidenceLevel.HIGH, ConfidenceLevel.HIGH)
    assert level_at_least(ConfidenceLevel.VERY_HIGH, ConfidenceLevel.HIGH)
    assert not level_at_least(ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH)


def test_alert_settings_default_disabled():
    settings = alert_settings_from_config({})
    assert settings.enabled is False
    assert settings.min_level is ConfidenceLevel.HIGH


def test_compute_bet_transition_when_qualifying():
    confidence = evaluate_confidence(
        HANDICAP,
        STRONG_R1 + STRONG_R2,
        pick="Spades",
        simulations=200,
        seed=1,
    )
    assert confidence.level in {ConfidenceLevel.HIGH, ConfidenceLevel.VERY_HIGH}
    transition = compute_alert_transition(
        settings=AlertSettings(enabled=True),
        previously_sent=False,
        previous_level=None,
        confidence=confidence,
        game_id="42",
    )
    assert transition.fired
    assert transition.kind == "bet"
    assert "Game 42" in (transition.message or "")


def test_compute_no_duplicate_when_still_high():
    confidence = evaluate_confidence(
        HANDICAP,
        STRONG_R1 + STRONG_R2,
        pick="Spades",
        simulations=200,
        seed=1,
    )
    transition = compute_alert_transition(
        settings=AlertSettings(enabled=True),
        previously_sent=True,
        previous_level=ConfidenceLevel.HIGH,
        confidence=confidence,
        game_id="42",
    )
    assert not transition.fired


def test_compute_upgrade_transition():
    low = ConfidenceResult(
        level=ConfidenceLevel.MEDIUM,
        pick="Spades",
        track_leader="Spades",
        track_gap=6,
        pick_on_track_leader=True,
        mc_probs=None,
        mc_pick=0.5,
        mc_margin=0.05,
        rivals_weak_count=0,
        draw_rounds=2,
        reasons=("medium",),
    )
    high = ConfidenceResult(
        level=ConfidenceLevel.HIGH,
        pick="Spades",
        track_leader="Spades",
        track_gap=12,
        pick_on_track_leader=True,
        mc_probs=None,
        mc_pick=0.7,
        mc_margin=0.2,
        rivals_weak_count=2,
        draw_rounds=3,
        reasons=("high",),
    )
    transition = compute_alert_transition(
        settings=AlertSettings(enabled=True),
        previously_sent=True,
        previous_level=ConfidenceLevel.MEDIUM,
        confidence=high,
        game_id="99",
    )
    assert transition.fired
    assert transition.kind == "upgrade"


def test_compute_cancel_transition():
    high = ConfidenceResult(
        level=ConfidenceLevel.HIGH,
        pick="Spades",
        track_leader="Spades",
        track_gap=12,
        pick_on_track_leader=True,
        mc_probs=None,
        mc_pick=0.7,
        mc_margin=0.2,
        rivals_weak_count=2,
        draw_rounds=2,
        reasons=("high",),
    )
    low = ConfidenceResult(
        level=ConfidenceLevel.LOW,
        pick="Spades",
        track_leader="Hearts",
        track_gap=2,
        pick_on_track_leader=False,
        mc_probs=None,
        mc_pick=0.3,
        mc_margin=0.02,
        rivals_weak_count=0,
        draw_rounds=3,
        reasons=("low",),
    )
    transition = compute_alert_transition(
        settings=AlertSettings(enabled=True),
        previously_sent=True,
        previous_level=ConfidenceLevel.HIGH,
        confidence=low,
        game_id="99",
    )
    assert transition.fired
    assert transition.kind == "cancel"


def test_session_does_not_fire_alert_when_disabled():
    tracker = GameSessionTracker()
    now = datetime(2026, 8, 22, 12, 0, 0)
    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="100")
    tracker.observe(_result(draw_cards=STRONG_R1), now, game_id="100")
    decision = tracker.observe(_result(draw_cards=STRONG_R2), now, game_id="100")
    assert decision.locked_guess is not None
    assert decision.alert_fired is False


def test_session_fires_bet_alert_when_enabled():
    tracker = GameSessionTracker()
    tracker.alert_settings = AlertSettings(enabled=True, min_level=ConfidenceLevel.HIGH)
    now = datetime(2026, 8, 22, 12, 0, 0)
    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="200")
    tracker.observe(_result(draw_cards=STRONG_R1), now, game_id="200")
    decision = tracker.observe(_result(draw_cards=STRONG_R2), now, game_id="200")
    assert decision.locked_guess == "Spades"
    assert decision.confidence_level in {"HIGH", "VERY_HIGH"}
    assert decision.alert_fired is True
    assert decision.alert_kind == "bet"
    assert decision.alert_message


def test_finished_path_never_fires_alert(tmp_path: Path):
    tracker = GameSessionTracker()
    tracker.alert_settings = AlertSettings(
        enabled=True,
        min_level=ConfidenceLevel.HIGH,
        log_path=tmp_path / "alerts.log",
    )
    now = datetime(2026, 8, 22, 12, 0, 0)
    tracker.observe(_result(handicap_cards=HANDICAP), now, game_id="300")
    tracker.observe(_result(draw_cards=ROUND1), now, game_id="300")
    finished = tracker.observe(
        _result(
            race_state=RaceState.FINISHED,
            draw_cards=ROUND2,
            winner_suit=None,
        ),
        now,
        game_id="300",
    )
    assert finished.locked_guess is not None
    assert finished.alert_fired is False


def test_deliver_alert_writes_log(tmp_path: Path):
    log_path = tmp_path / "alerts.log"
    settings = AlertSettings(enabled=True, log_path=log_path)
    deliver_alert(
        settings,
        alert_fired=True,
        alert_kind="bet",
        alert_message="[BET] test",
    )
    assert log_path.is_file()
    assert "[BET] test" in log_path.read_text(encoding="utf-8")


def test_format_alert_message_includes_pick():
    confidence = evaluate_confidence(HANDICAP, STRONG_R1 + STRONG_R2, pick="Spades", seed=2)
    text = format_alert_message(game_id="7", confidence=confidence, kind="bet")
    assert "Pick Spades" in text
    assert "Game 7" in text
