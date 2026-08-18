from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from game_analyzer.models import ExtractionResult, GamePhase, merge_suit_cards


@dataclass(frozen=True)
class RoundTiming:
    round_seconds: float = 32.0
    cards_appear_after: float = 10.0
    start_poll_seconds: float = 3.0


@dataclass(frozen=True)
class SessionDecision:
    recording: bool
    session_id: str | None
    seq: int
    phase: GamePhase
    reason: str
    should_save: bool = True
    next_wait_seconds: float = 3.0
    game_id: str | None = None
    peek_id_only: bool = False
    table_cards: tuple[tuple[str, tuple[str, ...]], ...] = ()

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
    """One screenshot at start, then one per round after cards appear. Game ID ends the game."""

    def __init__(self, timing: RoundTiming | None = None) -> None:
        self.timing = timing or RoundTiming()
        self.session_id: str | None = None
        self.session_game_id: str | None = None
        self.seq = 0
        self._close_after_save = False
        self._game_index = 0
        self._last_fingerprint: tuple | None = None
        self._ignored_game_id: str | None = None
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
            game_id=game_id,
            peek_id_only=peek,
            table_cards=self._table_cards(),
        )

    def observe(
        self,
        result: ExtractionResult,
        captured_at: datetime | None = None,
        game_id: str | None = None,
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
            if phase in {GamePhase.START, GamePhase.DEALT}:
                self._ignored_game_id = None
                self.session_id = self._new_session_id(captured_at, game_id)
                self.session_game_id = game_id
                self.seq = 1
                self._last_fingerprint = fingerprint
                self._ingest_cards(result)
                if phase == GamePhase.START:
                    return SessionDecision(
                        recording=True,
                        session_id=self.session_id,
                        seq=self.seq,
                        phase=phase,
                        reason="game start — wait for cards to appear",
                        should_save=True,
                        next_wait_seconds=t.cards_appear_after,
                        game_id=game_id,
                        table_cards=self._table_cards(),
                    )
                return SessionDecision(
                    recording=True,
                    session_id=self.session_id,
                    seq=self.seq,
                    phase=phase,
                    reason="handicap dealt",
                    should_save=True,
                    next_wait_seconds=t.round_seconds,
                    game_id=game_id,
                    table_cards=self._table_cards(),
                )
            if game_id and game_id == self._ignored_game_id:
                return self._waiting(phase, game_id, "waiting for Game ID to change")
            if phase in {GamePhase.IN_PLAY, GamePhase.FINISHED}:
                self._ignored_game_id = game_id
                return self._waiting(phase, game_id, "waiting for next game start")
            return self._waiting(phase, game_id, "waiting for next game start")

        if phase == GamePhase.FINISHED:
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
                game_id=game_id or self.session_game_id,
                table_cards=self._table_cards(),
            )

        if phase == GamePhase.START:
            return SessionDecision(
                recording=True,
                session_id=self.session_id,
                seq=self.seq,
                phase=phase,
                reason="round waiting — cards not on screen yet",
                should_save=False,
                next_wait_seconds=t.cards_appear_after,
                game_id=game_id or self.session_game_id,
                table_cards=self._table_cards(),
            )

        if fingerprint == self._last_fingerprint:
            return SessionDecision(
                recording=True,
                session_id=self.session_id,
                seq=self.seq,
                phase=phase,
                reason="same cards — wait for next round",
                should_save=False,
                next_wait_seconds=t.round_seconds,
                game_id=game_id or self.session_game_id,
                table_cards=self._table_cards(),
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
            next_wait_seconds=t.round_seconds,
            game_id=game_id or self.session_game_id,
            table_cards=self._table_cards(),
        )
