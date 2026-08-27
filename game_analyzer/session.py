from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from game_analyzer.models import ExtractionResult, GamePhase, merge_suit_cards


class WaitMode(str, Enum):
    """How live.py should pause before the next screenshot."""

    FIXED = "fixed"  # phase schedule: sleep next_wait_seconds
    POLL_GAME_ID = "poll_game_id"
    TIMER_TO_ZERO = "timer_to_zero"  # optional: poll CDP until timer ~0
    TIMER_CYCLE = "timer_cycle"  # optional: wait reset then ~0


@dataclass(frozen=True)
class RoundTiming:
    """Phase schedule: timer at game start, ~37s after handicap, ~32s mid draws.

    first_round_remaining is only used when the on-page timer cannot be read.
    timer_wait_pad_seconds: circle shows floored whole seconds (25 means <26 left),
    so we add 1s when sleeping on a live timer reading to avoid capturing early.
    """

    handicap_wait_seconds: float = 37.0
    mid_round_seconds: float = 32.0
    first_round_remaining: float = 26.0
    cards_appear_after: float = 1.0
    start_poll_seconds: float = 1.5
    timer_wait_pad_seconds: float = 1.0
    # Kept for older configs / screen-mode fallbacks
    fallback_seconds: float = 42.0
    round_seconds: float = 37.0
    round_seconds_rest: float = 32.0


@dataclass(frozen=True)
class SessionDecision:
    recording: bool
    session_id: str | None
    seq: int
    phase: GamePhase
    reason: str
    should_save: bool = True
    next_wait_seconds: float = 3.0
    wait_mode: WaitMode = WaitMode.FIXED
    watch_result: bool = False
    game_id: str | None = None
    peek_id_only: bool = False
    # True when next_wait_seconds came from the on-page circle (anchor sleep to timer sample).
    wait_from_live_timer: bool = False
    table_cards: tuple[tuple[str, tuple[str, ...]], ...] = ()
    drawn_cards: tuple[str, ...] = ()
    # Legacy guess/confidence fields kept as unused stubs for older callers/tests.
    locked_guess: str | None = None
    locked_guess_draws: tuple[str, ...] = ()
    locked_guess_rounds: int = 0
    confidence_level: str | None = None
    confidence_reasons: tuple[str, ...] = ()
    confidence_pct: int | None = None
    alert_fired: bool = False
    alert_kind: str | None = None
    alert_message: str | None = None

    def folder_name(self) -> str:
        if self.recording and self.session_id:
            return self.session_id
        return "waiting"

    def file_stem(self, captured_at: datetime) -> str:
        clock = captured_at.strftime("%H-%M-%S-%f")[:15]
        if self.recording:
            return f"{self.seq:03d}_{self.phase.value}_{clock}"
        return f"wait_{self.phase.value}_{clock}"


class GameSessionTracker:
    """Screenshot on phase edges; waits follow the hybrid schedule + result polling in live.py."""

    def __init__(self, timing: RoundTiming | None = None) -> None:
        self.timing = timing or RoundTiming()
        self.session_id: str | None = None
        self.session_game_id: str | None = None
        self.seq = 0
        self._close_after_save = False
        self._game_index = 0
        self._last_fingerprint: tuple | None = None
        self._ignored_game_id: str | None = None
        self._ever_observed: bool = False
        self.handicap_cards: tuple[tuple[str, ...], ...] = ()
        self.drawn_cards: list[str] = []

    def _fingerprint(self, result: ExtractionResult) -> tuple:
        return (result.game_phase(), result.handicap_cards, result.draw_cards)

    def _new_session_id(self, captured_at: datetime, game_id: str | None) -> str:
        self._game_index += 1
        if game_id:
            return f"game_{game_id}"
        return f"game_{captured_at.strftime('%Y%m%d-%H%M%S')}_{self._game_index:02d}"

    def _reset_session(self) -> None:
        self.session_id = None
        self.session_game_id = None
        self.seq = 0
        self._close_after_save = False
        self.handicap_cards = ()
        self.drawn_cards = []

    def _table_cards(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return merge_suit_cards(self.handicap_cards, tuple(self.drawn_cards))

    def _ingest_cards(self, result: ExtractionResult) -> None:
        if result.has_handicap_cards() and not self.handicap_cards:
            self.handicap_cards = result.handicap_cards
        current = tuple(
            card for card in result.draw_cards if card and not str(card).startswith("?")
        )
        if not current:
            return
        n = len(current)
        if tuple(self.drawn_cards[-n:]) == current:
            return
        self.drawn_cards.extend(current)

    def _waiting(self, phase: GamePhase, game_id: str | None, reason: str) -> SessionDecision:
        peek = bool(game_id and game_id == self._ignored_game_id)
        return SessionDecision(
            recording=False,
            session_id=None,
            seq=0,
            phase=phase,
            reason=reason,
            should_save=False,
            next_wait_seconds=self.timing.start_poll_seconds,
            wait_mode=WaitMode.POLL_GAME_ID,
            game_id=game_id,
            peek_id_only=peek,
            table_cards=self._table_cards(),
            drawn_cards=tuple(self.drawn_cards),
        )

    def _begin_game(
        self,
        result: ExtractionResult,
        fingerprint: tuple,
        captured_at: datetime,
        game_id: str | None,
        timer_seconds: int | None,
        phase: GamePhase,
        *,
        should_save: bool = True,
        reason: str | None = None,
        ingest: bool = True,
    ) -> SessionDecision:
        """Open a session for this Game ID and sync wait to the circle timer when possible."""
        t = self.timing
        self._ignored_game_id = None
        self.session_id = self._new_session_id(captured_at, game_id)
        self.session_game_id = game_id
        # Unsaved sync shots (e.g. leftover previous result) must not consume seq 1,
        # or the first real save becomes 002_DEALT with no 001 on disk/UI.
        self.seq = 1 if should_save else 0
        self._last_fingerprint = fingerprint
        if ingest:
            self._ingest_cards(result)
        if phase == GamePhase.DEALT:
            # First-round handicap already up: follow remaining circle time, else full 37s.
            from_timer = timer_seconds is not None and timer_seconds > 0
            if from_timer:
                wait = self._padded_timer_wait(timer_seconds)
            else:
                wait = t.handicap_wait_seconds
            reason = reason or "joined at handicap — sync to timer for first draw"
        else:
            wait, from_timer = self._wait_after_start(timer_seconds)
            reason = reason or "new game detected — shot now, wait for handicap"
        return SessionDecision(
            recording=True,
            session_id=self.session_id,
            seq=self.seq,
            phase=phase,
            reason=reason,
            should_save=should_save,
            next_wait_seconds=wait,
            wait_mode=WaitMode.FIXED,
            game_id=game_id,
            wait_from_live_timer=from_timer,
            table_cards=self._table_cards(),
            drawn_cards=tuple(self.drawn_cards),
        )

    def _padded_timer_wait(self, timer_seconds: int) -> float:
        """Sleep on floored circle digit: display N ⇒ add pad so we are not 1s early."""
        return float(timer_seconds) + self.timing.timer_wait_pad_seconds

    def _wait_with_timer_or_default(
        self, timer_seconds: int | None, default_seconds: float
    ) -> float:
        """Circle remaining > 0 wins; otherwise the phase default (next full round)."""
        if timer_seconds is not None and timer_seconds > 0:
            return float(timer_seconds)
        return default_seconds

    def _wait_after_start(self, timer_seconds: int | None) -> tuple[float, bool]:
        """Game-start countdown: use circle time, or short settle if already 0.

        Returns (wait_seconds, from_live_timer).
        """
        t = self.timing
        if timer_seconds is not None and timer_seconds > 0:
            return self._padded_timer_wait(timer_seconds), True
        if timer_seconds == 0:
            return t.cards_appear_after, False
        return t.first_round_remaining, False

    def _wait_for_same_cards(self, phase: GamePhase, timer_seconds: int | None) -> float:
        t = self.timing
        if phase == GamePhase.START:
            wait, _ = self._wait_after_start(timer_seconds)
            return wait
        # After handicap is on screen, the next full segment to first draw is ~37s.
        if phase == GamePhase.DEALT:
            return t.handicap_wait_seconds
        return self._wait_with_timer_or_default(timer_seconds, t.mid_round_seconds)

    def _wait_for_new_cards(self, phase: GamePhase, timer_seconds: int | None) -> float:
        t = self.timing
        # Handicap → first draw is always the long ~37s segment (not mid-round 32).
        if phase == GamePhase.DEALT:
            return t.handicap_wait_seconds
        if phase == GamePhase.IN_PLAY:
            return self._wait_with_timer_or_default(timer_seconds, t.mid_round_seconds)
        return self._wait_with_timer_or_default(timer_seconds, t.mid_round_seconds)

    def observe(
        self,
        result: ExtractionResult,
        captured_at: datetime | None = None,
        game_id: str | None = None,
        timer_seconds: int | None = None,
    ) -> SessionDecision:
        if self._close_after_save:
            if self.session_game_id:
                self._ignored_game_id = self.session_game_id
            self._reset_session()

        phase = result.game_phase()
        captured_at = captured_at or datetime.now()
        fingerprint = self._fingerprint(result)
        t = self.timing

        if self.session_id and game_id and self.session_game_id and game_id != self.session_game_id:
            self._ignored_game_id = self.session_game_id
            self._reset_session()

        if self.session_id is None:
            self._ever_observed = True
            # Always honour ignore-list before opening a session. After FINISHED we
            # blacklist that Game ID; the result UI can clear to START while the ID
            # has not changed yet — must not create a second 001/002 for the same game.
            if game_id and game_id == self._ignored_game_id:
                return self._waiting(phase, game_id, "waiting for Game ID to change")
            if phase in {GamePhase.START, GamePhase.DEALT}:
                return self._begin_game(
                    result,
                    fingerprint,
                    captured_at,
                    game_id,
                    timer_seconds,
                    phase,
                )
            if phase == GamePhase.FINISHED:
                # Winner row can linger after Game ID already flipped to the next game.
                # Treat as previous result: ignore winner, sync to the new game's timer.
                if not result.has_draw_cards() and timer_seconds is not None and timer_seconds > 0:
                    return self._begin_game(
                        result,
                        fingerprint,
                        captured_at,
                        game_id,
                        timer_seconds,
                        GamePhase.START,
                        should_save=False,
                        reason="leftover previous result — sync new game to timer",
                        ingest=False,
                    )
                return self._waiting(
                    phase, game_id, "result still on screen — waiting for next game start"
                )
            if phase == GamePhase.IN_PLAY:
                # Truly mid-draw: skip this game (timing already unreliable).
                self._ignored_game_id = game_id
                return self._waiting(phase, game_id, "waiting for next game start")
            return self._waiting(phase, game_id, "waiting for next game start")

        if phase == GamePhase.FINISHED:
            # Winner-screen draw cards are often the only copy of the deciding round
            # (IN_PLAY for that round is frequently missed). Ingest them for similarity.
            self._ingest_cards(result)
            self._last_fingerprint = fingerprint
            self.seq += 1
            self._close_after_save = True
            return SessionDecision(
                recording=True,
                session_id=self.session_id,
                seq=self.seq,
                phase=phase,
                reason="game finished",
                should_save=True,
                next_wait_seconds=t.start_poll_seconds,
                wait_mode=WaitMode.POLL_GAME_ID,
                game_id=game_id or self.session_game_id,
                table_cards=self._table_cards(),
                drawn_cards=tuple(self.drawn_cards),
            )

        if phase == GamePhase.START:
            wait, from_timer = self._wait_after_start(timer_seconds)
            return SessionDecision(
                recording=True,
                session_id=self.session_id,
                seq=self.seq,
                phase=phase,
                reason="round waiting — cards not on screen yet",
                should_save=False,
                next_wait_seconds=wait,
                wait_mode=WaitMode.FIXED,
                game_id=game_id or self.session_game_id,
                wait_from_live_timer=from_timer,
                table_cards=self._table_cards(),
                drawn_cards=tuple(self.drawn_cards),
            )

        if fingerprint == self._last_fingerprint:
            return SessionDecision(
                recording=True,
                session_id=self.session_id,
                seq=self.seq,
                phase=phase,
                reason="same cards — wait for next round",
                should_save=False,
                next_wait_seconds=self._wait_for_same_cards(phase, timer_seconds),
                wait_mode=WaitMode.FIXED,
                game_id=game_id or self.session_game_id,
                table_cards=self._table_cards(),
                drawn_cards=tuple(self.drawn_cards),
            )

        self._ingest_cards(result)
        self._last_fingerprint = fingerprint
        self.seq += 1
        return SessionDecision(
            recording=True,
            session_id=self.session_id,
            seq=self.seq,
            phase=phase,
            reason="new round cards",
            should_save=True,
            next_wait_seconds=self._wait_for_new_cards(phase, timer_seconds),
            wait_mode=WaitMode.FIXED,
            watch_result=phase == GamePhase.IN_PLAY,
            game_id=game_id or self.session_game_id,
            table_cards=self._table_cards(),
            drawn_cards=tuple(self.drawn_cards),
        )
