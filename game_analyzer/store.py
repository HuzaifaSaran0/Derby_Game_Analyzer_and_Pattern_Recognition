from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from game_analyzer.models import ExtractionResult
from game_analyzer.race_values import GuessAccuracy, PreRaceOutcome, guess_accuracy, parse_handicap_rows, pre_race_outcome
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


@dataclass(frozen=True)
class StoredGame:
    game_id: str
    started_at: str
    finished_at: str | None
    winner_suit: str | None
    handicap_cards: tuple[tuple[str, ...], ...]
    table_cards: list
    frames: tuple[StoredFrame, ...]


def _dumps(value) -> str:
    return json.dumps(value, separators=(",", ":"))


class GameStore:
    def __init__(self, path: Path | None = None, root: Path | None = None) -> None:
        self.path = path or DEFAULT_DB
        self.root = root or ROOT
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)

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
        draws = list(result.draw_cards)
        winner = result.winner_suit.value if result.winner_suit else None
        finished = stamp if decision.phase.value == "FINISHED" else None

        with self._connect() as con:
            con.execute(
                """
                INSERT INTO games (game_id, started_at, finished_at, winner_suit,
                                   handicap_json, draws_json, table_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                  finished_at=COALESCE(excluded.finished_at, games.finished_at),
                  winner_suit=COALESCE(excluded.winner_suit, games.winner_suit),
                  handicap_json=excluded.handicap_json,
                  draws_json=excluded.draws_json,
                  table_json=excluded.table_json
                """,
                (
                    game_id,
                    stamp,
                    finished,
                    winner,
                    _dumps(handicap),
                    _dumps(draws),
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
                    _dumps(draws),
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

    def list_game_ids(self) -> list[str]:
        with self._connect(autocommit=True) as con:
            rows = con.execute(
                "SELECT game_id FROM games ORDER BY id ASC"
            ).fetchall()
        return [r["game_id"] for r in rows]

    def get_game(self, game_id: str, root: Path | None = None) -> StoredGame | None:
        root = root or self.root
        with self._connect(autocommit=True) as con:
            game = con.execute(
                "SELECT * FROM games WHERE game_id = ?", (game_id,)
            ).fetchone()
            if game is None:
                return None
            frame_rows = con.execute(
                "SELECT seq, phase, captured_at, screenshot_path FROM frames "
                "WHERE game_id = ? ORDER BY seq ASC",
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
            )
            for row in frame_rows
        )
        table = json.loads(game["table_json"] or "[]")
        handicap = parse_handicap_rows(json.loads(game["handicap_json"] or "[]"))
        return StoredGame(
            game_id=game["game_id"],
            started_at=game["started_at"],
            finished_at=game["finished_at"],
            winner_suit=game["winner_suit"],
            handicap_cards=handicap,
            table_cards=table,
            frames=frames,
        )

    def pre_race_guess_accuracy(self) -> GuessAccuracy:
        with self._connect(autocommit=True) as con:
            rows = con.execute(
                "SELECT winner_suit, handicap_json FROM games WHERE winner_suit IS NOT NULL"
            ).fetchall()
        records = [
            (row["winner_suit"], parse_handicap_rows(json.loads(row["handicap_json"] or "[]")))
            for row in rows
        ]
        return guess_accuracy(records)

    def pre_race_outcome_for(self, game_id: str) -> PreRaceOutcome | None:
        game = self.get_game(game_id)
        if game is None:
            return None
        return pre_race_outcome(game.winner_suit, game.handicap_cards)
