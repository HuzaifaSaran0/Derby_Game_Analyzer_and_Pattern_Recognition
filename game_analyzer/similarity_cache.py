"""Persistent cache for late-round twin sets (Similar page / notifications).

Rebuilt automatically when the corpus changes or similarity logic version bumps.
Safe to include in export/import bundles alongside ``games.sqlite``.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_analyzer.similarity import (
    LATE_ROUND_MAX,
    LATE_ROUND_MIN,
    GameFingerprint,
    LateRoundStageStats,
    LateRoundTwinSet,
    build_late_round_twin_sets,
    draw_round_key,
    late_round_corpus_stats,
    partition_late_round_twin_sets,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE_PATH = ROOT / "data" / "similarity_cache.json"

# Bump when late-round matching / trust rules change (invalidates old caches).
SIMILARITY_LOGIC_VERSION = "1"
CACHE_FORMAT = 1


def corpus_fingerprint(corpus: list[GameFingerprint]) -> str:
    """Stable hash of finished-game fingerprints used for twin matching."""
    lines: list[str] = []
    for fp in sorted(corpus, key=lambda g: g.game_id):
        if not fp.winner_suit:
            continue
        r3 = draw_round_key(fp.draw_cards, 3) or ""
        lines.append(
            "|".join(
                (
                    fp.game_id,
                    fp.winner_suit,
                    fp.draw_source,
                    str(len(fp.draw_cards)),
                    str(len(fp.frame_draws)),
                    r3,
                )
            )
        )
    payload = "\n".join(lines).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _twin_set_to_dict(twin_set: LateRoundTwinSet) -> dict[str, Any]:
    return {
        "stage": twin_set.stage,
        "round_n": twin_set.round_n,
        "matched_rounds": list(twin_set.matched_rounds),
        "key": twin_set.key,
        "game_ids": [g.game_id for g in twin_set.games],
        "winner_counts": [list(row) for row in twin_set.winner_counts],
        "agreement_pct": twin_set.agreement_pct,
        "winners_same": twin_set.winners_same,
        "round_cards": [[rn, list(cards)] for rn, cards in twin_set.round_cards],
        "trust": twin_set.trust,
        "trust_notes": list(twin_set.trust_notes),
    }


def _stats_to_dict(row: LateRoundStageStats) -> dict[str, Any]:
    return {
        "stage": row.stage,
        "round_n": row.round_n,
        "twin_sets": row.twin_sets,
        "games_in_sets": row.games_in_sets,
        "same_winner_sets": row.same_winner_sets,
        "same_winner_pct": row.same_winner_pct,
        "mean_agreement_pct": row.mean_agreement_pct,
    }


def _stats_from_dict(raw: dict[str, Any]) -> LateRoundStageStats:
    return LateRoundStageStats(
        stage=str(raw["stage"]),
        round_n=int(raw["round_n"]),
        twin_sets=int(raw["twin_sets"]),
        games_in_sets=int(raw["games_in_sets"]),
        same_winner_sets=int(raw["same_winner_sets"]),
        same_winner_pct=raw.get("same_winner_pct"),
        mean_agreement_pct=raw.get("mean_agreement_pct"),
    )


def _twin_set_from_dict(
    raw: dict[str, Any],
    corpus_by_id: dict[str, GameFingerprint],
) -> LateRoundTwinSet | None:
    games: list[GameFingerprint] = []
    for game_id in raw.get("game_ids") or []:
        fp = corpus_by_id.get(str(game_id))
        if fp is None:
            return None
        games.append(fp)
    if len(games) < 2:
        return None
    round_cards = tuple(
        (int(rn), tuple(str(c) for c in cards))
        for rn, cards in raw.get("round_cards") or []
    )
    winner_counts = tuple(
        (str(name), int(count)) for name, count in raw.get("winner_counts") or []
    )
    return LateRoundTwinSet(
        stage=str(raw["stage"]),
        round_n=int(raw["round_n"]),
        matched_rounds=tuple(int(n) for n in raw.get("matched_rounds") or ()),
        key=str(raw["key"]),
        games=tuple(sorted(games, key=lambda g: g.game_id)),
        winner_counts=winner_counts,
        agreement_pct=raw.get("agreement_pct"),
        winners_same=raw.get("winners_same"),
        round_cards=round_cards,
        trust=str(raw.get("trust") or "verified"),
        trust_notes=tuple(str(n) for n in raw.get("trust_notes") or ()),
    )


def _deserialize_sets(
    rows: list[dict[str, Any]],
    corpus_by_id: dict[str, GameFingerprint],
) -> list[LateRoundTwinSet] | None:
    out: list[LateRoundTwinSet] = []
    for raw in rows:
        twin_set = _twin_set_from_dict(raw, corpus_by_id)
        if twin_set is None:
            return None
        out.append(twin_set)
    return out


def build_cache_document(
    corpus: list[GameFingerprint],
    *,
    max_round: int = LATE_ROUND_MAX,
    min_round: int = LATE_ROUND_MIN,
) -> dict[str, Any]:
    """Compute twin sets + stats and return a JSON-serializable cache document."""
    all_sets = build_late_round_twin_sets(
        corpus, max_round=max_round, min_round=min_round
    )
    trusted, weak = partition_late_round_twin_sets(all_sets)
    stats = late_round_corpus_stats(corpus, max_round=max_round)
    finished = sum(1 for fp in corpus if fp.winner_suit)
    return {
        "format": CACHE_FORMAT,
        "logic_version": SIMILARITY_LOGIC_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus_fingerprint": corpus_fingerprint(corpus),
        "finished_games": finished,
        "max_round": max_round,
        "min_round": min_round,
        "trusted_sets": [_twin_set_to_dict(s) for s in trusted],
        "excluded_sets": [_twin_set_to_dict(s) for s in weak],
        "late_round_stats": [_stats_to_dict(s) for s in stats],
        "twin_set_count": len(all_sets),
    }


def validate_cache_document(
    doc: dict[str, Any],
    corpus: list[GameFingerprint],
    *,
    max_round: int = LATE_ROUND_MAX,
    min_round: int = LATE_ROUND_MIN,
) -> bool:
    if int(doc.get("format") or 0) != CACHE_FORMAT:
        return False
    if str(doc.get("logic_version") or "") != SIMILARITY_LOGIC_VERSION:
        return False
    if doc.get("corpus_fingerprint") != corpus_fingerprint(corpus):
        return False
    if int(doc.get("max_round") or LATE_ROUND_MAX) != max_round:
        return False
    if int(doc.get("min_round") or LATE_ROUND_MIN) != min_round:
        return False
    return True


def load_cache(path: Path = DEFAULT_CACHE_PATH) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


DEFAULT_CACHE_PATH = ROOT / "data" / "similarity_cache.json"
_CACHE_WRITE_LOCK = threading.Lock()
_CACHE_SAVE_RETRIES = 8


def save_cache(doc: dict[str, Any], path: Path = DEFAULT_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(doc, indent=2) + "\n"
    last_error: OSError | None = None
    with _CACHE_WRITE_LOCK:
        for attempt in range(_CACHE_SAVE_RETRIES):
            try:
                tmp.write_text(payload, encoding="utf-8")
                tmp.replace(path)
                return
            except OSError as error:
                last_error = error
                winerror = getattr(error, "winerror", None)
                if winerror not in {32, 5} and not isinstance(error, PermissionError):
                    raise
                if attempt + 1 >= _CACHE_SAVE_RETRIES:
                    break
                time.sleep(0.05 * (2**attempt))
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
    if last_error is not None:
        raise last_error


def invalidate_cache(path: Path = DEFAULT_CACHE_PATH) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


def load_partitioned_twin_sets(
    corpus: list[GameFingerprint],
    path: Path = DEFAULT_CACHE_PATH,
    *,
    max_round: int = LATE_ROUND_MAX,
    min_round: int = LATE_ROUND_MIN,
) -> tuple[list[LateRoundTwinSet], list[LateRoundTwinSet], list[LateRoundStageStats]] | None:
    doc = load_cache(path)
    if doc is None or not validate_cache_document(
        doc, corpus, max_round=max_round, min_round=min_round
    ):
        return None
    corpus_by_id = {fp.game_id: fp for fp in corpus}
    trusted = _deserialize_sets(doc.get("trusted_sets") or [], corpus_by_id)
    weak = _deserialize_sets(doc.get("excluded_sets") or [], corpus_by_id)
    if trusted is None or weak is None:
        return None
    stats = [_stats_from_dict(row) for row in doc.get("late_round_stats") or []]
    return trusted, weak, stats


def rebuild_cache(
    corpus: list[GameFingerprint],
    path: Path = DEFAULT_CACHE_PATH,
    *,
    max_round: int = LATE_ROUND_MAX,
    min_round: int = LATE_ROUND_MIN,
) -> dict[str, Any]:
    doc = build_cache_document(corpus, max_round=max_round, min_round=min_round)
    save_cache(doc, path)
    return doc


def cache_status(path: Path = DEFAULT_CACHE_PATH) -> dict[str, Any]:
    doc = load_cache(path)
    if not doc:
        return {"present": False, "path": str(path)}
    return {
        "present": True,
        "path": str(path),
        "built_at": doc.get("built_at"),
        "logic_version": doc.get("logic_version"),
        "finished_games": doc.get("finished_games"),
        "trusted_sets": len(doc.get("trusted_sets") or []),
        "excluded_sets": len(doc.get("excluded_sets") or []),
        "corpus_fingerprint": doc.get("corpus_fingerprint"),
    }
