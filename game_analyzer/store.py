from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from game_analyzer.models import ExtractionResult
from game_analyzer.race_values import (
    GuessAccuracy,
    PreRaceOutcome,
    all_draws_from_in_play_frames,
    card_race_value,
    draws_for_guess,
    guess_accuracy,
    guess_ready,
    lock_guess,
    parse_draw_list,
    parse_handicap_rows,
    pre_race_outcome,
)
from game_analyzer.session import SessionDecision

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "games.sqlite"

_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS games (
  id INTEGER PRIMARY KEY,
  game_id TEXT NOT NULL UNIQUE,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  winner_suit TEXT,
  handicap_json TEXT NOT NULL DEFAULT '[]',
  draws_json TEXT NOT NULL DEFAULT '[]',
  table_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS frames (
  id INTEGER PRIMARY KEY,
  game_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  phase TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  screenshot_path TEXT NOT NULL,
  draw_cards_json TEXT NOT NULL DEFAULT '[]',
  handicap_json TEXT NOT NULL DEFAULT '[]',
  UNIQUE(game_id, seq),
  FOREIGN KEY(game_id) REFERENCES games(game_id)
);
"""


@dataclass(frozen=True)
class StoredFrame:
    seq: int
    phase: str
    captured_at: str
    screenshot_path: Path
    draw_cards: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredGame:
    game_id: str
    started_at: str
    finished_at: str | None
    winner_suit: str | None
    guess_suit: str | None
    handicap_cards: tuple[tuple[str, ...], ...]
    draw_cards: tuple[str, ...]
    guess_draw_cards: tuple[str, ...]
    table_cards: list
    frames: tuple[StoredFrame, ...]


def _draws_beyond_handicap(
    handicap: tuple[tuple[str, ...], ...],
    table,
) -> tuple[str, ...]:
    """Cards on the suit table that are not handicap — best-effort full draw list."""
    hc = {c for row in handicap for c in row if c}
    out: list[str] = []
    seen: set[str] = set()
    for item in table or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        for card in item[1] or []:
            if not card or str(card).startswith("?") or card in hc or card in seen:
                continue
            seen.add(card)
            out.append(card)
    return tuple(out)


def _stored_all_draws(
    draw_cards: tuple[str, ...],
    frames: tuple[StoredFrame, ...],
) -> tuple[str, ...]:
    """Every draw card saved for this game (all rounds)."""
    from_frames = all_draws_from_in_play_frames((f.phase, f.draw_cards) for f in frames)
    if from_frames and len(from_frames) > len(draw_cards):
        return from_frames
    if draw_cards:
        return draw_cards
    return from_frames


@dataclass(frozen=True)
class CleanupReport:
    games_before: int
    frames_before: int
    games_after: int
    frames_after: int
    repaired_draws: tuple[tuple[str, int], ...]
    deleted: tuple[tuple[str, str], ...]

    @property
    def deleted_count(self) -> int:
        return len(self.deleted)

    @property
    def repaired_count(self) -> int:
        return len(self.repaired_draws)


def _handicap_quality(handicap_json: str) -> str:
    handicap = parse_handicap_rows(json.loads(handicap_json or "[]"))
    if len(handicap) < 4:
        return "incomplete_rows"
    for row in handicap:
        if len(row) < 3:
            return "short_row"
        for card in row:
            if not card or str(card).startswith("?") or card_race_value(card) is None:
                return "unreadable"
    return "ok"


def _dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"))


class GameStore:
    def __init__(self, path: Path | None = None, root: Path | None = None) -> None:
        self.path = path or DEFAULT_DB
        self.root = root or ROOT
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._similarity_corpus_cache: tuple[bool, tuple] | None = None
        with self._connect() as con:
            con.executescript(_SCHEMA)
            self._ensure_guess_columns(con)

    def _ensure_guess_columns(self, con: sqlite3.Connection) -> None:
        columns = {row[1] for row in con.execute("PRAGMA table_info(games)")}
        if "guess_suit" not in columns:
            con.execute("ALTER TABLE games ADD COLUMN guess_suit TEXT")
        if "guess_draws_json" not in columns:
            con.execute("ALTER TABLE games ADD COLUMN guess_draws_json TEXT")

    def _connect(self, *, autocommit: bool = False) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path), timeout=10)
        con.row_factory = sqlite3.Row
        if autocommit:
            con.isolation_level = None
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA busy_timeout=5000;")
        con.execute("PRAGMA foreign_keys=ON;")
        return con

    def record(
        self,
        decision: SessionDecision,
        result: ExtractionResult,
        screenshot: Path,
        captured_at: datetime,
        root: Path | None = None,
    ) -> None:
        if not decision.recording or not decision.should_save:
            return
        self._similarity_corpus_cache = None
        game_id = decision.game_id or decision.session_id
        if not game_id:
            return
        root = root or self.root
        rel = screenshot
        try:
            rel = screenshot.resolve().relative_to(root.resolve())
        except ValueError:
            rel = screenshot
        stamp = captured_at.isoformat(timespec="seconds")
        table = [[suit, list(cards)] for suit, cards in decision.table_cards]
        handicap = [list(row) for row in result.handicap_cards]
        cumulative_draws = list(decision.drawn_cards) if decision.drawn_cards else list(result.draw_cards)
        round_draws = list(result.draw_cards)
        winner = result.winner_suit.value if result.winner_suit else None
        finished = stamp if decision.phase.value == "FINISHED" else None
        guess_suit = decision.locked_guess
        guess_draws = list(decision.locked_guess_draws) if decision.locked_guess_draws else None

        with self._connect() as con:
            self._ensure_guess_columns(con)
            # Never shrink draws_json: FINISHED OCR often returns only the last round.
            existing = con.execute(
                "SELECT draws_json FROM games WHERE game_id=?", (game_id,)
            ).fetchone()
            if existing is not None:
                prev = parse_draw_list(json.loads(existing["draws_json"] or "[]"))
                if len(prev) > len(cumulative_draws):
                    cumulative_draws = list(prev)
            con.execute(
                """
                INSERT INTO games (game_id, started_at, finished_at, winner_suit,
                                   guess_suit, guess_draws_json,
                                   handicap_json, draws_json, table_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                  finished_at=COALESCE(excluded.finished_at, games.finished_at),
                  winner_suit=COALESCE(excluded.winner_suit, games.winner_suit),
                  guess_suit=COALESCE(excluded.guess_suit, games.guess_suit),
                  guess_draws_json=COALESCE(excluded.guess_draws_json, games.guess_draws_json),
                  handicap_json=excluded.handicap_json,
                  draws_json=excluded.draws_json,
                  table_json=excluded.table_json
                """,
                (
                    game_id,
                    stamp,
                    finished,
                    winner,
                    guess_suit,
                    _dumps(guess_draws) if guess_draws else None,
                    _dumps(handicap),
                    _dumps(cumulative_draws),
                    _dumps(table),
                ),
            )
            con.execute(
                """
                INSERT INTO frames (game_id, seq, phase, captured_at, screenshot_path,
                                    draw_cards_json, handicap_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, seq) DO UPDATE SET
                  phase=excluded.phase,
                  captured_at=excluded.captured_at,
                  screenshot_path=excluded.screenshot_path,
                  draw_cards_json=excluded.draw_cards_json,
                  handicap_json=excluded.handicap_json
                """,
                (
                    game_id,
                    decision.seq,
                    decision.phase.value,
                    stamp,
                    str(rel),
                    _dumps(round_draws),
                    _dumps(handicap),
                ),
            )

    def list_games(self, *, newest_first: bool = True) -> list[dict]:
        order = "DESC" if newest_first else "ASC"
        with self._connect(autocommit=True) as con:
            rows = con.execute(
                f"""
                SELECT game_id, started_at, finished_at, winner_suit,
                       (SELECT COUNT(*) FROM frames f WHERE f.game_id = games.game_id) AS shot_count
                FROM games
                ORDER BY id {order}
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def list_game_ids(self, *, finished_only: bool = False) -> list[str]:
        with self._connect(autocommit=True) as con:
            if finished_only:
                rows = con.execute(
                    "SELECT game_id FROM games WHERE winner_suit IS NOT NULL ORDER BY id ASC"
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT game_id FROM games ORDER BY id ASC"
                ).fetchall()
        return [r["game_id"] for r in rows]

    def delete_games_without_winner(self) -> int:
        """Remove unfinished/abandoned games (no winner_suit)."""
        deleted = 0
        with self._connect() as con:
            rows = con.execute(
                "SELECT game_id FROM games WHERE winner_suit IS NULL"
            ).fetchall()
            for row in rows:
                gid = row["game_id"]
                con.execute("DELETE FROM frames WHERE game_id=?", (gid,))
                con.execute("DELETE FROM games WHERE game_id=?", (gid,))
                deleted += 1
        self._similarity_corpus_cache = None
        return deleted

    def get_game(self, game_id: str, root: Path | None = None) -> StoredGame | None:
        root = root or self.root
        with self._connect(autocommit=True) as con:
            game = con.execute(
                "SELECT * FROM games WHERE game_id = ?", (game_id,)
            ).fetchone()
            if game is None:
                return None
            frame_rows = con.execute(
                "SELECT seq, phase, captured_at, screenshot_path, draw_cards_json "
                "FROM frames WHERE game_id = ? ORDER BY seq ASC",
                (game_id,),
            ).fetchall()
        frames = tuple(
            StoredFrame(
                seq=row["seq"],
                phase=row["phase"],
                captured_at=row["captured_at"],
                screenshot_path=(root / row["screenshot_path"])
                if not Path(row["screenshot_path"]).is_absolute()
                else Path(row["screenshot_path"]),
                draw_cards=parse_draw_list(json.loads(row["draw_cards_json"] or "[]")),
            )
            for row in frame_rows
        )
        table = json.loads(game["table_json"] or "[]")
        handicap = parse_handicap_rows(json.loads(game["handicap_json"] or "[]"))
        draw_cards = _stored_all_draws(
            parse_draw_list(json.loads(game["draws_json"] or "[]")),
            frames,
        )
        stored_guess_draws = parse_draw_list(json.loads(game["guess_draws_json"] or "[]"))
        guess_draw_cards = stored_guess_draws or draws_for_guess(draw_cards)
        guess_suit = game["guess_suit"]
        # Older rows locked before FINISHED ingest — recompute from stored draws when missing.
        if not guess_suit and handicap and guess_ready(guess_draw_cards):
            locked = lock_guess(handicap, guess_draw_cards)
            if locked is not None:
                guess_suit = locked.suit
                guess_draw_cards = locked.draw_cards
        return StoredGame(
            game_id=game["game_id"],
            started_at=game["started_at"],
            finished_at=game["finished_at"],
            winner_suit=game["winner_suit"],
            guess_suit=guess_suit,
            handicap_cards=handicap,
            draw_cards=draw_cards,
            guess_draw_cards=guess_draw_cards,
            table_cards=table,
            frames=frames,
        )

    def pre_race_guess_accuracy(self) -> GuessAccuracy:
        records: list[
            tuple[str | None, tuple[tuple[str, ...], ...], tuple[str, ...], str | None]
        ] = []
        for game_id in self.list_game_ids():
            game = self.get_game(game_id)
            if game is None or not game.winner_suit:
                continue
            records.append(
                (
                    game.winner_suit,
                    game.handicap_cards,
                    game.guess_draw_cards,
                    game.guess_suit,
                )
            )
        return guess_accuracy(records)

    def _finished_game_inputs(
        self,
    ) -> list[tuple[str | None, tuple[tuple[str, ...], ...], tuple[str, ...]]]:
        rows: list[tuple[str | None, tuple[tuple[str, ...], ...], tuple[str, ...]]] = []
        for game_id in self.list_game_ids():
            game = self.get_game(game_id)
            if game is None or not game.winner_suit:
                continue
            draws = game.draw_cards or game.guess_draw_cards
            if not draws:
                continue
            rows.append((game.winner_suit, game.handicap_cards, draws))
        return rows

    def similarity_corpus(self, *, finished_only: bool = True):
        """Fingerprints for similarity — rebuild draws from IN_PLAY frames (not short draws_json)."""
        from game_analyzer.similarity import GameFingerprint, build_fingerprint

        cached = self._similarity_corpus_cache
        if cached is not None and cached[0] == finished_only:
            return list(cached[1])

        corpus: list[GameFingerprint] = []
        with self._connect(autocommit=True) as con:
            rows = con.execute(
                """
                SELECT game_id, winner_suit, handicap_json, draws_json,
                       guess_draws_json, table_json
                FROM games
                ORDER BY id ASC
                """
            ).fetchall()
            frame_rows = con.execute(
                """
                SELECT game_id, phase, draw_cards_json
                FROM frames
                ORDER BY game_id ASC, seq ASC
                """
            ).fetchall()

        frames_by_game: dict[str, list[tuple[str, tuple[str, ...]]]] = {}
        for fr in frame_rows:
            frames_by_game.setdefault(fr["game_id"], []).append(
                (
                    fr["phase"],
                    parse_draw_list(json.loads(fr["draw_cards_json"] or "[]")),
                )
            )

        for row in rows:
            winner = row["winner_suit"]
            if finished_only and not winner:
                continue
            handicap = parse_handicap_rows(json.loads(row["handicap_json"] or "[]"))
            if not handicap:
                continue
            raw = parse_draw_list(json.loads(row["draws_json"] or "[]"))
            guess = parse_draw_list(json.loads(row["guess_draws_json"] or "[]"))
            from_frames = all_draws_from_in_play_frames(
                frames_by_game.get(row["game_id"], ())
            )
            table = json.loads(row["table_json"] or "[]")
            from_table = _draws_beyond_handicap(handicap, table)
            # Prefer the longest accurate source. Frames are best; table fills gaps
            # when capture missed IN_PLAY rounds but still saved the suit table.
            draws = max((from_frames, raw, guess, from_table), key=len)
            fp = build_fingerprint(
                row["game_id"],
                handicap,
                draws,
                winner_suit=winner,
            )
            if fp is not None:
                corpus.append(fp)
        self._similarity_corpus_cache = (finished_only, tuple(corpus))
        return list(corpus)

    def similarity_clusters(self, *, exact_only: bool = False):
        from game_analyzer.similarity import build_clusters

        return build_clusters(self.similarity_corpus(), exact_only=exact_only)

    def invalidate_similarity_cache(self) -> None:
        self._similarity_corpus_cache = None

    def find_similar_to(
        self,
        game_id: str | None = None,
        *,
        handicap_cards=None,
        draw_cards: tuple[str, ...] = (),
        exact_only: bool = False,
        exclude_game_id: str | None = None,
    ):
        """Find similar finished games for a stored game id or live card state."""
        from game_analyzer.similarity import build_fingerprint, find_matches

        corpus = self.similarity_corpus()
        if game_id:
            query = next((fp for fp in corpus if fp.game_id == game_id), None)
            if query is None:
                game = self.get_game(game_id)
                if game is None:
                    return []
                query = build_fingerprint(
                    game.game_id,
                    game.handicap_cards,
                    game.draw_cards or game.guess_draw_cards,
                    winner_suit=game.winner_suit,
                )
            if query is None:
                return []
            return find_matches(query, corpus, exact_only=exact_only)

        if handicap_cards is None:
            return []
        qid = exclude_game_id or "__live__"
        query = build_fingerprint(qid, handicap_cards, draw_cards, winner_suit=None)
        if query is None:
            return []
        return find_matches(query, corpus, exact_only=exact_only)

    def live_twin_signal(
        self,
        handicap_cards,
        draw_cards: tuple[str, ...] = (),
        *,
        exclude_game_id: str | None = None,
    ):
        from game_analyzer.similarity import build_fingerprint, evaluate_live_twin

        query = build_fingerprint(
            exclude_game_id or "__live__",
            handicap_cards,
            draw_cards,
            winner_suit=None,
        )
        if query is None:
            return None
        corpus = [
            fp
            for fp in self.similarity_corpus()
            if exclude_game_id is None or fp.game_id != exclude_game_id
        ]
        return evaluate_live_twin(query, corpus)

    def late_round_cascade(
        self,
        draw_cards: tuple[str, ...] = (),
        *,
        live_game_id: str | None = None,
        max_round: int = 5,
    ):
        """R3→R4→R5 exact draw cascade against finished games."""
        from game_analyzer.similarity import evaluate_late_round_cascade

        return evaluate_late_round_cascade(
            draw_cards,
            self.similarity_corpus(),
            live_game_id=live_game_id,
            max_round=max_round,
        )

    def late_round_stats(self, *, max_round: int = 5):
        from game_analyzer.similarity import late_round_corpus_stats

        return late_round_corpus_stats(self.similarity_corpus(), max_round=max_round)

    def late_round_twin_sets(self, *, max_round: int = 5, min_round: int = 3):
        from game_analyzer.similarity import build_late_round_twin_sets

        return build_late_round_twin_sets(
            self.similarity_corpus(),
            max_round=max_round,
            min_round=min_round,
        )

    def pre_race_outcome_for(self, game_id: str) -> PreRaceOutcome | None:
        game = self.get_game(game_id)
        if game is None:
            return None
        rounds = len(game.guess_draw_cards) // 3 if game.guess_draw_cards else 0
        return pre_race_outcome(
            game.winner_suit,
            game.handicap_cards,
            game.guess_draw_cards,
            locked_guess=game.guess_suit,
            locked_draw_rounds=rounds,
        )

    def repair_empty_draws(self) -> list[tuple[str, int]]:
        """Rebuild ``draws_json`` from saved IN_PLAY frames when the game row is empty."""
        repaired: list[tuple[str, int]] = []
        with self._connect() as con:
            rows = con.execute(
                "SELECT game_id, draws_json FROM games WHERE winner_suit IS NOT NULL"
            ).fetchall()
            for row in rows:
                draws = parse_draw_list(json.loads(row["draws_json"] or "[]"))
                if draws:
                    continue
                frame_rows = con.execute(
                    "SELECT phase, draw_cards_json FROM frames WHERE game_id=? ORDER BY seq",
                    (row["game_id"],),
                ).fetchall()
                rebuilt = all_draws_from_in_play_frames(
                    (
                        frame["phase"],
                        parse_draw_list(json.loads(frame["draw_cards_json"] or "[]")),
                    )
                    for frame in frame_rows
                )
                if not rebuilt:
                    continue
                con.execute(
                    "UPDATE games SET draws_json=? WHERE game_id=?",
                    (_dumps(list(rebuilt)), row["game_id"]),
                )
                repaired.append((row["game_id"], len(rebuilt)))
        return repaired

    def cleanup_sensible(self) -> CleanupReport:
        """Drop abandoned games and finished rows with unreadable/incomplete handicap."""
        with self._connect() as con:
            games_before = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            frames_before = con.execute("SELECT COUNT(*) FROM frames").fetchone()[0]

        repaired = tuple(self.repair_empty_draws())
        deleted: list[tuple[str, str]] = []
        with self._connect() as con:
            for row in con.execute(
                "SELECT game_id, winner_suit, handicap_json FROM games"
            ).fetchall():
                if row["winner_suit"] is None:
                    reason = "abandoned"
                elif _handicap_quality(row["handicap_json"]) != "ok":
                    reason = f"broken_handicap:{_handicap_quality(row['handicap_json'])}"
                else:
                    continue
                game_id = row["game_id"]
                con.execute("DELETE FROM frames WHERE game_id=?", (game_id,))
                con.execute("DELETE FROM games WHERE game_id=?", (game_id,))
                deleted.append((game_id, reason))
            games_after = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
            frames_after = con.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
        return CleanupReport(
            games_before=games_before,
            frames_before=frames_before,
            games_after=games_after,
            frames_after=frames_after,
            repaired_draws=repaired,
            deleted=tuple(deleted),
        )
