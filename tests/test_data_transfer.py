"""Export / import backup bundles."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from game_analyzer.data_transfer import (
    MANIFEST_NAME,
    DB_ZIP_PATH,
    CACHE_ZIP_PATH,
    build_export_zip,
    data_summary,
    import_from_zip,
)
from game_analyzer.models import ExtractionResult, GamePhase, RaceState, Suit
from game_analyzer.session import SessionDecision
from game_analyzer.store import GameStore
from game_analyzer.web import create_app

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _decision(**kwargs) -> SessionDecision:
    defaults = dict(
        recording=True,
        session_id="game_100",
        seq=1,
        phase=GamePhase.DEALT,
        reason="test",
        should_save=True,
        game_id="100",
        table_cards=(("Spades", ("AS", "2S")),),
    )
    defaults.update(kwargs)
    return SessionDecision(**defaults)


def _result(**kwargs) -> ExtractionResult:
    defaults = dict(
        race_state=RaceState.BETTING,
        winner_suit=None,
        high_low=None,
        confident=False,
        draw_cards=(),
        handicap_cards=(("AS", "2S"), ("4H",), ("3C",), ("2D",)),
    )
    defaults.update(kwargs)
    return ExtractionResult(**defaults)


def _seed_store(tmp_path: Path, game_id: str = "100") -> GameStore:
    store = GameStore(tmp_path / "games.sqlite", root=tmp_path)
    shot_dir = tmp_path / "fixtures" / "live" / f"game_{game_id}"
    shot_dir.mkdir(parents=True)
    shot = shot_dir / "001.png"
    shot.write_bytes(PNG)
    now = datetime(2026, 8, 18, 18, 0, 0)
    store.record(_decision(game_id=game_id, session_id=f"game_{game_id}"), _result(), shot, now)
    store.record(
        _decision(
            game_id=game_id,
            session_id=f"game_{game_id}",
            seq=2,
            phase=GamePhase.FINISHED,
        ),
        _result(race_state=RaceState.FINISHED, winner_suit=Suit.CLUBS),
        shot,
        now,
    )
    return store


def test_data_summary_counts(tmp_path: Path):
    store = _seed_store(tmp_path)
    summary = data_summary(store)
    assert summary.games == 1
    assert summary.frames == 2
    assert summary.finished_games == 1
    assert summary.screenshot_files == 1
    assert summary.screenshot_bytes == len(PNG)


def test_export_zip_structure(tmp_path: Path):
    store = _seed_store(tmp_path)
    store.rebuild_similarity_cache()
    archive = tmp_path / "backup.zip"
    manifest = build_export_zip(store, archive)
    assert archive.is_file()
    assert manifest["games"] == 1
    assert manifest["screenshots"] == 1
    assert manifest["has_similarity_cache"] is True

    with zipfile.ZipFile(archive, "r") as zf:
        names = set(zf.namelist())
        assert MANIFEST_NAME in names
        assert DB_ZIP_PATH in names
        assert CACHE_ZIP_PATH in names
        assert any(n.startswith("fixtures/live/") for n in names)
        doc = json.loads(zf.read(MANIFEST_NAME))
        assert doc["format"] == 1


def test_import_merge_skips_existing(tmp_path: Path):
    source = _seed_store(tmp_path / "src")
    archive = tmp_path / "backup.zip"
    build_export_zip(source, archive)

    dest_root = tmp_path / "dest"
    dest = GameStore(dest_root / "games.sqlite", root=dest_root)
    report = import_from_zip(dest, archive, merge=True)
    assert report.ok
    assert report.games_added == 1
    assert report.frames_added == 2
    assert report.screenshots_copied == 1
    assert dest.list_game_ids() == ["100"]

    again = import_from_zip(dest, archive, merge=True)
    assert again.ok
    assert again.games_added == 0
    assert again.games_skipped == 1


def test_import_overwrite_replaces_existing(tmp_path: Path):
    source = _seed_store(tmp_path / "src")
    archive = tmp_path / "backup.zip"
    build_export_zip(source, archive)

    dest_root = tmp_path / "dest"
    dest = GameStore(dest_root / "games.sqlite", root=dest_root)
    import_from_zip(dest, archive, merge=True)

    again = import_from_zip(dest, archive, merge=True, overwrite=True)
    assert again.ok
    assert again.games_added == 0
    assert again.games_updated == 1
    assert again.games_skipped == 0
    assert dest.list_game_ids() == ["100"]


def test_web_data_routes(tmp_path: Path):
    store = _seed_store(tmp_path)
    client = TestClient(create_app(store, auth_enabled=False))

    page = client.get("/data")
    assert page.status_code == 200
    assert "Backup &amp; restore" in page.text or "Backup & restore" in page.text
    assert "data.js" in page.text

    status = client.get("/api/data/status")
    assert status.status_code == 200
    body = status.json()
    assert body["games"] == 1
    assert body["frames"] == 2

    export = client.get("/api/data/export")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/zip")
    assert len(export.content) > 100

    empty = tmp_path / "empty"
    empty.mkdir()
    empty_store = GameStore(empty / "games.sqlite", root=empty)
    empty_client = TestClient(create_app(empty_store, auth_enabled=False))
    imported = empty_client.post(
        "/api/data/import",
        content=export.content,
        headers={"Content-Type": "application/zip"},
    )
    assert imported.status_code == 200
    payload = imported.json()
    assert payload["ok"] is True
    assert payload["games_added"] == 1
    assert empty_store.list_game_ids() == ["100"]
