"""Export / import game corpus (database, screenshots, twin cache) for deployment moves."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from game_analyzer.similarity_cache import (
    SIMILARITY_LOGIC_VERSION,
    load_cache,
    load_partitioned_twin_sets,
    validate_cache_document,
)
from game_analyzer.store import GameStore

EXPORT_FORMAT = 1
MANIFEST_NAME = "manifest.json"
DB_ZIP_PATH = "database/games.sqlite"
CACHE_ZIP_PATH = "cache/similarity_cache.json"
SCREENSHOTS_ZIP_PREFIX = "fixtures/live/"
MAX_IMPORT_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB


@dataclass(frozen=True)
class DataSummary:
    games: int
    frames: int
    finished_games: int
    screenshot_files: int
    screenshot_bytes: int
    cache_present: bool
    cache_built_at: str | None
    trusted_twin_sets: int | None


@dataclass
class ImportReport:
    games_added: int = 0
    games_updated: int = 0
    games_skipped: int = 0
    frames_added: int = 0
    screenshots_copied: int = 0
    screenshots_missing: int = 0
    cache_imported: bool = False
    cache_reused: bool = False
    cache_rebuilt: bool = False
    trusted_twin_sets: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": not self.errors,
            "games_added": self.games_added,
            "games_updated": self.games_updated,
            "games_skipped": self.games_skipped,
            "frames_added": self.frames_added,
            "screenshots_copied": self.screenshots_copied,
            "screenshots_missing": self.screenshots_missing,
            "cache_imported": self.cache_imported,
            "cache_reused": self.cache_reused,
            "cache_rebuilt": self.cache_rebuilt,
            "trusted_twin_sets": self.trusted_twin_sets,
            "errors": list(self.errors),
            "message": self.summary_message(),
        }

    def summary_message(self) -> str:
        if self.errors:
            return "Import failed: " + "; ".join(self.errors[:3])
        parts = [f"{self.games_added} games added"]
        if self.games_updated:
            parts.append(f"{self.games_updated} updated")
        if self.games_skipped:
            parts.append(f"{self.games_skipped} skipped (already present)")
        if self.screenshots_copied:
            parts.append(f"{self.screenshots_copied} screenshots copied")
        if self.screenshots_missing:
            parts.append(f"{self.screenshots_missing} screenshots missing in bundle")
        if self.cache_reused:
            parts.append("twin cache reused")
        elif self.cache_rebuilt:
            parts.append("twin cache rebuilt")
        if self.trusted_twin_sets:
            parts.append(f"{self.trusted_twin_sets} twin sets ready")
        return " · ".join(parts)


def _connect_ro(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _db_snapshot(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    src_con = sqlite3.connect(str(src))
    dest_con = sqlite3.connect(str(dest))
    try:
        with dest_con:
            src_con.backup(dest_con)
    finally:
        src_con.close()
        dest_con.close()


def _count_rows(db_path: Path) -> tuple[int, int]:
    with _connect_ro(db_path) as con:
        games = con.execute("SELECT COUNT(*) FROM games").fetchone()[0]
        frames = con.execute("SELECT COUNT(*) FROM frames").fetchone()[0]
    return int(games), int(frames)


def _screenshot_paths_from_db(db_path: Path) -> list[str]:
    with _connect_ro(db_path) as con:
        rows = con.execute(
            "SELECT DISTINCT screenshot_path FROM frames ORDER BY screenshot_path"
        ).fetchall()
    return [str(r["screenshot_path"]) for r in rows if r["screenshot_path"]]


def _resolve_under_root(root: Path, rel: str) -> Path | None:
    raw = Path(rel)
    full = raw if raw.is_absolute() else (root / raw)
    try:
        full = full.resolve()
        full.relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return full


def _zip_screenshot_arc(path: Path, root: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        return None
    text = rel.as_posix()
    if not text.startswith("fixtures/live/"):
        return None
    return text


def data_summary(store: GameStore) -> DataSummary:
    games_n, frames_n = _count_rows(store.path)
    finished = len(store.list_game_ids(finished_only=True))
    paths = _screenshot_paths_from_db(store.path)
    seen: set[Path] = set()
    total_bytes = 0
    for rel in paths:
        full = _resolve_under_root(store.root, rel)
        if full is None or not full.is_file() or full in seen:
            continue
        seen.add(full)
        total_bytes += full.stat().st_size
    cache = load_cache(store.similarity_cache_path)
    trusted = None
    if cache:
        trusted = len(cache.get("trusted_sets") or [])
    return DataSummary(
        games=games_n,
        frames=frames_n,
        finished_games=finished,
        screenshot_files=len(seen),
        screenshot_bytes=total_bytes,
        cache_present=bool(cache),
        cache_built_at=str(cache.get("built_at")) if cache else None,
        trusted_twin_sets=trusted,
    )


def build_export_zip(store: GameStore, dest: Path) -> dict[str, Any]:
    """Write a portable backup zip; returns manifest dict."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        db_copy = tmp_path / "games.sqlite"
        _db_snapshot(store.path, db_copy)
        games_n, frames_n = _count_rows(db_copy)
        shot_paths = _screenshot_paths_from_db(db_copy)
        manifest: dict[str, Any] = {
            "format": EXPORT_FORMAT,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "logic_version": SIMILARITY_LOGIC_VERSION,
            "games": games_n,
            "frames": frames_n,
            "screenshots": 0,
            "screenshot_bytes": 0,
            "has_similarity_cache": False,
        }
        included_shots: list[tuple[str, Path]] = []
        missing_shots = 0
        for rel in shot_paths:
            full = _resolve_under_root(store.root, rel)
            if full is None or not full.is_file():
                missing_shots += 1
                continue
            arc = _zip_screenshot_arc(full, store.root)
            if arc is None:
                missing_shots += 1
                continue
            included_shots.append((arc, full))
        manifest["screenshots"] = len(included_shots)
        manifest["screenshot_bytes"] = sum(p.stat().st_size for _, p in included_shots)
        manifest["screenshots_missing"] = missing_shots
        cache_doc = load_cache(store.similarity_cache_path)
        if cache_doc:
            manifest["has_similarity_cache"] = True
            manifest["corpus_fingerprint"] = cache_doc.get("corpus_fingerprint")

        if dest.exists():
            dest.unlink()
        with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2) + "\n")
            zf.write(db_copy, DB_ZIP_PATH)
            if cache_doc:
                zf.writestr(
                    CACHE_ZIP_PATH,
                    json.dumps(cache_doc, indent=2) + "\n",
                )
            for arc, full in included_shots:
                zf.write(full, arc)
        manifest["archive_bytes"] = dest.stat().st_size
        manifest["archive_sha256"] = _file_sha256(dest)
        return manifest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(zf: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = zf.read(MANIFEST_NAME).decode("utf-8")
        doc = json.loads(raw)
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid backup manifest: {exc}") from exc
    if int(doc.get("format") or 0) != EXPORT_FORMAT:
        raise ValueError("Unsupported backup format.")
    return doc


def _table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()]


def _safe_screenshot_target(root: Path, zip_name: str) -> Path | None:
    """Resolve a zip entry under fixtures/live/ without path traversal."""
    if not zip_name.startswith(SCREENSHOTS_ZIP_PREFIX) or zip_name.endswith("/"):
        return None
    parts = PurePosixPath(zip_name).parts
    if ".." in parts:
        return None
    target = root.joinpath(*parts)
    try:
        target.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return None
    return target


def import_from_zip(
    store: GameStore,
    archive: Path,
    *,
    merge: bool = True,
    overwrite: bool = False,
) -> ImportReport:
    """Import games, frames, screenshots, and optional twin cache from a backup zip."""
    report = ImportReport()
    if not archive.is_file():
        report.errors.append("Archive file not found.")
        return report
    if archive.stat().st_size > MAX_IMPORT_BYTES:
        report.errors.append("Archive exceeds maximum import size.")
        return report

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(archive, "r") as zf:
                _read_manifest(zf)
                if DB_ZIP_PATH not in zf.namelist():
                    report.errors.append("Backup missing database/games.sqlite.")
                    return report
                zf.extract(DB_ZIP_PATH, tmp_path)
                if CACHE_ZIP_PATH in zf.namelist():
                    zf.extract(CACHE_ZIP_PATH, tmp_path)
                    report.cache_imported = True
                for name in zf.namelist():
                    target = _safe_screenshot_target(store.root, name)
                    if target is None:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and merge and not overwrite:
                        continue
                    with zf.open(name) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    report.screenshots_copied += 1
        except (zipfile.BadZipFile, ValueError) as exc:
            report.errors.append(str(exc))
            return report

        source_db = tmp_path / DB_ZIP_PATH
        source_cache = tmp_path / CACHE_ZIP_PATH

        try:
            _merge_sqlite(store, source_db, report, merge=merge, overwrite=overwrite)
        except sqlite3.Error as exc:
            report.errors.append(f"Database merge failed: {exc}")
            return report

        if report.errors:
            return report

        store.invalidate_similarity_cache()
        if source_cache.is_file() and report.cache_imported:
            store.similarity_cache_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_cache, store.similarity_cache_path)

        corpus = store.similarity_corpus()
        cache_doc = load_cache(store.similarity_cache_path)
        if cache_doc and validate_cache_document(cache_doc, corpus):
            loaded = load_partitioned_twin_sets(corpus, store.similarity_cache_path)
            if loaded is not None:
                report.cache_reused = True
                report.trusted_twin_sets = len(loaded[0])
        if not report.cache_reused:
            doc = store.rebuild_similarity_cache()
            report.cache_rebuilt = True
            report.trusted_twin_sets = len(doc.get("trusted_sets") or [])

    return report


def _merge_sqlite(
    store: GameStore,
    source_db: Path,
    report: ImportReport,
    *,
    merge: bool,
    overwrite: bool,
) -> None:
    with _connect_ro(source_db) as src, store._connect() as dest:
        dest.execute("PRAGMA foreign_keys=ON")
        game_cols = _table_columns(dest, "games")
        frame_cols = _table_columns(dest, "frames")
        src_game_cols = set(_table_columns(src, "games"))
        src_frame_cols = set(_table_columns(src, "frames"))
        use_game_cols = [c for c in game_cols if c in src_game_cols and c != "id"]
        use_frame_cols = [c for c in frame_cols if c in src_frame_cols and c != "id"]

        existing = {row[0] for row in dest.execute("SELECT game_id FROM games").fetchall()}
        src_games = src.execute(
            f"SELECT {', '.join(use_game_cols)} FROM games ORDER BY id ASC"
        ).fetchall()

        for row in src_games:
            row_dict = dict(zip(use_game_cols, row))
            game_id = row_dict.get("game_id")
            if not game_id:
                continue
            if game_id in existing:
                if merge and not overwrite:
                    report.games_skipped += 1
                    continue
                if overwrite:
                    dest.execute("DELETE FROM frames WHERE game_id=?", (game_id,))
                    dest.execute("DELETE FROM games WHERE game_id=?", (game_id,))
                    report.games_updated += 1
                elif not merge:
                    report.games_skipped += 1
                    continue
            else:
                report.games_added += 1
            placeholders = ", ".join("?" for _ in use_game_cols)
            cols_sql = ", ".join(use_game_cols)
            dest.execute(
                f"INSERT INTO games ({cols_sql}) VALUES ({placeholders})",
                tuple(row_dict[c] for c in use_game_cols),
            )
            existing.add(game_id)

            frames = src.execute(
                f"SELECT {', '.join(use_frame_cols)} FROM frames WHERE game_id=? ORDER BY seq",
                (game_id,),
            ).fetchall()
            for frame_row in frames:
                frame_dict = dict(zip(use_frame_cols, frame_row))
                rel = str(frame_dict.get("screenshot_path") or "")
                full = _resolve_under_root(store.root, rel)
                if full is None or not full.is_file():
                    report.screenshots_missing += 1
                f_placeholders = ", ".join("?" for _ in use_frame_cols)
                f_cols_sql = ", ".join(use_frame_cols)
                dest.execute(
                    f"INSERT INTO frames ({f_cols_sql}) VALUES ({f_placeholders})",
                    tuple(frame_dict[c] for c in use_frame_cols),
                )
                report.frames_added += 1

        dest.commit()


def export_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"game_analyzer_backup_{stamp}.zip"
