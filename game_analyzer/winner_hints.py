"""Live winner-sequence hints: after matching historical tails, what won next?"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from game_analyzer.models import Suit
from game_analyzer.store import GameStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIDENCE_LOG = ROOT / "data" / "winner_confidence.log"

# Client notation: 1=Spades, 2=Hearts, 3=Clubs, 4=Diamonds
SUIT_TO_CODE: dict[str, int] = {
    Suit.SPADES.value: 1,
    Suit.HEARTS.value: 2,
    Suit.CLUBS.value: 3,
    Suit.DIAMONDS.value: 4,
    "SPADES": 1,
    "HEARTS": 2,
    "CLUBS": 3,
    "DIAMONDS": 4,
    "Spades": 1,
    "Hearts": 2,
    "Clubs": 3,
    "Diamonds": 4,
}

CODE_TO_SUIT: dict[int, str] = {
    1: "Spades",
    2: "Hearts",
    3: "Clubs",
    4: "Diamonds",
}

CODE_TO_SYMBOL: dict[int, str] = {
    1: "♠",
    2: "♥",
    3: "♣",
    4: "♦",
}

CODE_TO_COLOR: dict[int, str] = {
    1: "#31c96b",
    2: "#ff5a67",
    3: "#58a6ff",
    4: "#f2c94c",
}

SUIT_META: dict[str, dict[str, str]] = {
    str(code): {
        "symbol": CODE_TO_SYMBOL[code],
        "color": CODE_TO_COLOR[code],
        "name": CODE_TO_SUIT[code],
    }
    for code in (1, 2, 3, 4)
}

HINT_LEGEND = "1=Spades · 2=Hearts · 3=Clubs · 4=Diamonds"

HINT_LENGTHS: tuple[int, ...] = tuple(range(4, 11))  # 4..10


def winner_code(suit: str | None) -> int | None:
    if not suit:
        return None
    key = suit.strip().upper()
    if key in SUIT_TO_CODE:
        return SUIT_TO_CODE[key]
    return SUIT_TO_CODE.get(suit.strip().title())


def _code_label(code: int) -> str:
    return str(code)


def _tail_label(codes: list[int]) -> str:
    return " ".join(_code_label(c) for c in codes)


def _suit_list_label(codes: list[int]) -> str:
    return " · ".join(_code_label(c) for c in codes)


@dataclass(frozen=True)
class HintRow:
    length: int
    tail: tuple[int, ...]
    match_count: int
    follow_up_counts: dict[int, int]

    @property
    def tail_text(self) -> str:
        return _tail_label(list(self.tail))

    @property
    def tail_suits(self) -> str:
        return _suit_list_label(list(self.tail))

    @property
    def next_game_number(self) -> int:
        return self.length + 1


def analyze_tail(finished_codes: list[int], length: int) -> HintRow | None:
    """Find every historical occurrence of the current tail and tally the next winner."""
    n = len(finished_codes)
    if length < 1 or n < length:
        return None
    return search_pattern(finished_codes, tuple(finished_codes[-length:]))


def search_pattern(finished_codes: list[int], pattern: tuple[int, ...]) -> HintRow:
    """Find every occurrence of ``pattern`` in history and tally the next winner."""
    length = len(pattern)
    n = len(finished_codes)
    follow_counts: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0}
    if length < 1 or n < length:
        return HintRow(
            length=length,
            tail=pattern,
            match_count=0,
            follow_up_counts=follow_counts,
        )

    for start in range(n - length + 1):
        if tuple(finished_codes[start : start + length]) != pattern:
            continue
        next_idx = start + length
        if next_idx >= n:
            continue
        code = finished_codes[next_idx]
        follow_counts[code] = follow_counts.get(code, 0) + 1

    match_count = sum(follow_counts.values())
    return HintRow(
        length=length,
        tail=pattern,
        match_count=match_count,
        follow_up_counts=follow_counts,
    )


def finished_winner_codes(store: GameStore) -> list[int]:
    finished_codes: list[int] = []
    for game_id in store.list_game_ids(finished_only=True):
        game = store.get_game(game_id)
        if game is None or not game.winner_suit:
            continue
        code = winner_code(game.winner_suit)
        if code is not None:
            finished_codes.append(code)
    return finished_codes


def parse_pattern_codes(pattern: str, length: int) -> list[int] | None:
    parts = [p.strip() for p in pattern.split(",") if p.strip()]
    if len(parts) != length:
        return None
    codes: list[int] = []
    for part in parts:
        try:
            code = int(part)
        except ValueError:
            return None
        if code not in CODE_TO_SYMBOL:
            return None
        codes.append(code)
    return codes


def _row_payload(row: HintRow, *, summary: str) -> dict[str, Any]:
    total = row.match_count
    percents = {
        str(c): (int(round(100 * row.follow_up_counts[c] / total)) if total else 0)
        for c in (1, 2, 3, 4)
    }
    return {
        "length": row.length,
        "next_game_number": row.next_game_number,
        "tail": list(row.tail),
        "tail_text": row.tail_text,
        "tail_suits": row.tail_suits,
        "match_count": row.match_count,
        "follow_up_counts": {str(k): v for k, v in row.follow_up_counts.items()},
        "follow_up_percents": percents,
        "summary": summary,
    }


def _search_summary(row: HintRow) -> str:
    if row.match_count == 0:
        return f"Pattern ({row.tail_suits}): no identical run in history yet."
    parts = [
        f"{_code_label(c)} {row.follow_up_counts[c]}"
        for c in sorted(row.follow_up_counts)
        if row.follow_up_counts[c] > 0
    ]
    best_code = max(
        (c for c, v in row.follow_up_counts.items() if v > 0),
        key=lambda c: row.follow_up_counts[c],
    )
    best_n = row.follow_up_counts[best_code]
    best_suit = _code_label(best_code)
    detail = ", ".join(parts)
    if row.match_count == 1:
        return (
            f"Pattern ({row.tail_suits}): 1 past case — "
            f"next game was {best_suit}. ({detail})"
        )
    best_pct = int(round(100 * best_n / row.match_count))
    return (
        f"Pattern ({row.tail_suits}): {row.match_count} past cases — "
        f"next game was usually {best_suit} ({best_n}/{row.match_count}, {best_pct}%). "
        f"({detail})"
    )


def _row_summary(row: HintRow) -> str:
    if row.match_count == 0:
        return (
            f"Last {row.length} winners ({row.tail_suits}): "
            "no identical run in history yet."
        )
    parts = [
        f"{_code_label(c)} {row.follow_up_counts[c]}"
        for c in sorted(row.follow_up_counts)
        if row.follow_up_counts[c] > 0
    ]
    best_code = max(
        (c for c, v in row.follow_up_counts.items() if v > 0),
        key=lambda c: row.follow_up_counts[c],
    )
    best_n = row.follow_up_counts[best_code]
    best_suit = _code_label(best_code)
    detail = ", ".join(parts)
    if row.match_count == 1:
        return (
            f"Last {row.length} ({row.tail_suits}): 1 past case — "
            f"next game was {best_suit}. ({detail})"
        )
    best_pct = int(round(100 * best_n / row.match_count))
    return (
        f"Last {row.length} ({row.tail_suits}): {row.match_count} past cases — "
        f"next game was usually {best_suit} ({best_n}/{row.match_count}, {best_pct}%). "
        f"({detail})"
    )


def _lead_summary(rows: list[HintRow]) -> str:
    with_matches = [r for r in rows if r.match_count > 0]
    if not with_matches:
        return "No matching winner runs in history for lengths 4–10 yet."

    def score(r: HintRow) -> tuple[int, int]:
        top = max(r.follow_up_counts.values()) if r.match_count else 0
        return (r.match_count, top)

    best = max(with_matches, key=score)
    top_code = max(best.follow_up_counts, key=best.follow_up_counts.get)
    top_n = best.follow_up_counts[top_code]
    top_suit = _code_label(top_code)
    if best.match_count == 1:
        return (
            f"Quick read: after the last {best.length} winners, history has 1 similar case — "
            f"the next game was {top_suit}."
        )
    pct = int(round(100 * top_n / best.match_count))
    return (
        f"Quick read: after the last {best.length} winners, {best.match_count} similar cases — "
        f"{top_suit} won next most often ({top_n}/{best.match_count}, {pct}%)."
    )


def live_winner_hints(store: GameStore) -> dict[str, Any]:
    """Hints from finished-game tails (current live game is the implied next outcome)."""
    finished_codes = finished_winner_codes(store)

    min_len = min(HINT_LENGTHS)
    if len(finished_codes) < min_len:
        return {
            "legend": HINT_LEGEND,
            "suit_meta": SUIT_META,
            "finished_games": len(finished_codes),
            "lengths": list(HINT_LENGTHS),
            "lead_summary": (
                f"Need at least {min_len} finished games for winner hints "
                f"({len(finished_codes)} so far)."
            ),
            "confidence": live_confidence_payload(
                LiveConfidence(
                    pick=None,
                    confidence_pct=0,
                    tier="NONE",
                    supporting_patterns=(),
                    total_cases=0,
                    has_conflict=False,
                    skipped_reason=(
                        f"Need at least {min_len} finished games for confidence "
                        f"({len(finished_codes)} so far)."
                    ),
                )
            ),
            "rows": [],
        }

    rows: list[HintRow] = []
    for length in HINT_LENGTHS:
        row = analyze_tail(finished_codes, length)
        if row is not None:
            rows.append(row)

    payload_rows = []
    for row in rows:
        payload_rows.append(_row_payload(row, summary=_row_summary(row)))

    confidence = compute_live_confidence(rows)

    return {
        "legend": HINT_LEGEND,
        "suit_meta": SUIT_META,
        "finished_games": len(finished_codes),
        "lengths": list(HINT_LENGTHS),
        "lead_summary": _lead_summary(rows),
        "confidence": live_confidence_payload(confidence),
        "rows": payload_rows,
    }


def live_winner_hints_if_in_progress(store: GameStore, *, in_progress: bool) -> dict[str, Any] | None:
    if not in_progress:
        return None
    return live_winner_hints(store)


def search_winner_pattern(store: GameStore, pattern: list[int]) -> dict[str, Any]:
    """Manual history search for a user-selected winner sequence."""
    finished_codes = finished_winner_codes(store)
    row = search_pattern(finished_codes, tuple(pattern))
    return {
        "legend": HINT_LEGEND,
        "suit_meta": SUIT_META,
        "finished_games": len(finished_codes),
        "pattern": list(pattern),
        "result": _row_payload(row, summary=_search_summary(row)),
    }


@dataclass(frozen=True)
class WinnerHintAlertPattern:
    length: int
    tail_text: str
    match_count: int
    next_code: int
    next_count: int
    next_pct: int


@dataclass(frozen=True)
class LiveConfidence:
    pick: int | None
    confidence_pct: int
    tier: str
    supporting_patterns: tuple[WinnerHintAlertPattern, ...]
    total_cases: int
    has_conflict: bool
    skipped_reason: str | None = None


CONFIDENCE_TIERS = frozenset({"NONE", "LOW", "MEDIUM", "HIGH"})
NOTIFY_TIERS = frozenset({"MEDIUM", "HIGH"})


def _best_follow_up(row: HintRow) -> tuple[int, int, int] | None:
    active = [(c, row.follow_up_counts[c]) for c in row.follow_up_counts if row.follow_up_counts[c] > 0]
    if not active:
        return None
    best_code, best_n = max(active, key=lambda item: item[1])
    pct = int(round(100 * best_n / row.match_count)) if row.match_count else 0
    return best_code, best_n, pct


def evaluate_winner_hint_alerts(
    rows: list[HintRow],
    *,
    min_matches: int = 2,
    min_pct: int = 50,
) -> list[WinnerHintAlertPattern]:
    """Rows where history strongly favours one next winner."""
    alerts: list[WinnerHintAlertPattern] = []
    for row in rows:
        if row.match_count < 1:
            continue
        best = _best_follow_up(row)
        if best is None:
            continue
        best_code, best_n, pct = best
        others = [n for c, n in row.follow_up_counts.items() if n > 0 and c != best_code]
        clear_lead = not others or best_n > max(others)
        if row.match_count >= min_matches and pct >= min_pct and clear_lead:
            alerts.append(
                WinnerHintAlertPattern(
                    length=row.length,
                    tail_text=row.tail_text,
                    match_count=row.match_count,
                    next_code=best_code,
                    next_count=best_n,
                    next_pct=pct,
                )
            )
    return alerts


def group_winner_hint_alerts(
    patterns: list[WinnerHintAlertPattern],
) -> dict[int, list[WinnerHintAlertPattern]]:
    grouped: dict[int, list[WinnerHintAlertPattern]] = {}
    for pattern in patterns:
        grouped.setdefault(pattern.next_code, []).append(pattern)
    return grouped


def notifiable_winner_hint_groups(
    rows: list[HintRow],
    *,
    min_matches: int = 2,
    min_pct: int = 50,
) -> dict[int, list[WinnerHintAlertPattern]]:
    """Groups worth alerting when combined confidence tier is MEDIUM or HIGH."""
    confidence = compute_live_confidence(rows, min_matches=min_matches, min_pct=min_pct)
    if confidence.tier not in NOTIFY_TIERS or confidence.pick is None:
        return {}
    patterns = list(confidence.supporting_patterns)
    if not patterns:
        return {}
    return {confidence.pick: patterns}


def _historical_confidence_pct(patterns: list[WinnerHintAlertPattern] | list[dict[str, Any]]) -> int:
    """Weighted historical hit rate across supporting patterns (not vote share)."""
    if not patterns:
        return 0
    total_cases = 0
    weighted = 0.0
    for pattern in patterns:
        if isinstance(pattern, WinnerHintAlertPattern):
            cases = pattern.match_count
            pct = pattern.next_pct
        else:
            cases = int(pattern.get("match_count") or 0)
            pct = int(pattern.get("next_pct") or 0)
        total_cases += cases
        weighted += cases * pct
    if total_cases <= 0:
        return 0
    return int(round(weighted / total_cases))


def compute_live_confidence(
    rows: list[HintRow],
    *,
    min_matches: int = 2,
    min_pct: int = 50,
) -> LiveConfidence:
    """Combine trusted rows 4–10 into one pick, score, and tier."""
    trusted = evaluate_winner_hint_alerts(rows, min_matches=min_matches, min_pct=min_pct)
    if not trusted:
        return LiveConfidence(
            pick=None,
            confidence_pct=0,
            tier="NONE",
            supporting_patterns=(),
            total_cases=0,
            has_conflict=False,
            skipped_reason="No trusted historical patterns (need ≥2 cases, ≥50%, clear lead).",
        )

    votes: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0}
    for pattern in trusted:
        votes[pattern.next_code] += pattern.match_count * (pattern.next_pct / 100.0)

    total_weight = sum(votes.values())
    if total_weight <= 0:
        return LiveConfidence(
            pick=None,
            confidence_pct=0,
            tier="NONE",
            supporting_patterns=tuple(trusted),
            total_cases=sum(p.match_count for p in trusted),
            has_conflict=False,
            skipped_reason="No weighted votes from trusted patterns.",
        )

    pick = max(votes, key=lambda code: votes[code])
    supporting = tuple(p for p in trusted if p.next_code == pick)
    conflicting = [p for p in trusted if p.next_code != pick]
    total_cases = sum(p.match_count for p in supporting)
    confidence_pct = _historical_confidence_pct(list(supporting))
    tier = _confidence_tier(
        supporting=supporting,
        confidence_pct=confidence_pct,
        total_cases=total_cases,
        has_conflict=bool(conflicting),
    )
    return LiveConfidence(
        pick=pick,
        confidence_pct=confidence_pct,
        tier=tier,
        supporting_patterns=supporting,
        total_cases=total_cases,
        has_conflict=bool(conflicting),
        skipped_reason=None,
    )


def _confidence_tier(
    *,
    supporting: tuple[WinnerHintAlertPattern, ...],
    confidence_pct: int,
    total_cases: int,
    has_conflict: bool,
) -> str:
    if not supporting:
        return "NONE"

    supporting_count = len(supporting)
    min_cases = min(p.match_count for p in supporting)

    # HIGH: multiple groups agree AND each group has a meaningful sample (≥3 cases).
    if (
        supporting_count >= 2
        and not has_conflict
        and confidence_pct >= 70
        and min_cases >= 3
    ):
        return "HIGH"

    if supporting_count >= 2:
        return "MEDIUM"

    only = supporting[0]
    if only.match_count >= 3 and only.next_pct >= 67:
        return "MEDIUM"

    return "LOW"


def _pattern_payload(pattern: WinnerHintAlertPattern) -> dict[str, Any]:
    return {
        "length": pattern.length,
        "tail": pattern.tail_text,
        "match_count": pattern.match_count,
        "next_code": pattern.next_code,
        "next_count": pattern.next_count,
        "next_pct": pattern.next_pct,
    }


def live_confidence_payload(confidence: LiveConfidence) -> dict[str, Any]:
    pick = confidence.pick
    tier = confidence.tier
    if pick is None or tier == "NONE":
        summary = confidence.skipped_reason or "No clear historical edge for the next winner."
    elif tier == "LOW":
        suit = CODE_TO_SUIT.get(pick, "?")
        cases = confidence.total_cases
        game_word = "game" if cases == 1 else "games"
        summary = (
            f"No strong forecast — only {cases} similar {game_word} in history "
            f"(leaning {suit}, not enough to call)"
        )
    else:
        suit = CODE_TO_SUIT.get(pick, "?")
        n = len(confidence.supporting_patterns)
        cases = confidence.total_cases
        game_word = "game" if cases == 1 else "games"
        summary = f"Forecast: {suit} — {tier} · {cases} similar {game_word}"
        if n >= 2:
            summary += f" · {n} patterns agree"
        if confidence.confidence_pct:
            summary += f" · {confidence.confidence_pct}% historical hit rate"
    return {
        "pick": pick,
        "pick_label": CODE_TO_SUIT.get(pick, "") if pick else "",
        "pick_color": CODE_TO_COLOR.get(pick, "#ddd") if pick else "",
        "confidence_pct": confidence.confidence_pct,
        "tier": tier,
        "supporting_count": len(confidence.supporting_patterns),
        "total_cases": confidence.total_cases,
        "has_conflict": confidence.has_conflict,
        "summary": summary,
        "skipped_reason": confidence.skipped_reason,
        "supporting_patterns": [_pattern_payload(p) for p in confidence.supporting_patterns],
    }


def confidence_log_path_from_config(config: dict[str, Any]) -> Path:
    hints = config.get("winner_hints") or {}
    raw = hints.get("confidence_log_path")
    return Path(raw) if raw else DEFAULT_CONFIDENCE_LOG


def _row_snapshot(row: HintRow) -> dict[str, Any]:
    best = _best_follow_up(row)
    return {
        "length": row.length,
        "tail": row.tail_text,
        "match_count": row.match_count,
        "follow_up_counts": {str(k): v for k, v in row.follow_up_counts.items()},
        "best_next_code": best[0] if best else None,
        "best_next_count": best[1] if best else 0,
        "best_next_pct": best[2] if best else 0,
    }


def build_confidence_log_entry(
    *,
    game_id: str,
    confidence: LiveConfidence,
    rows: list[HintRow],
    notified: bool,
) -> dict[str, Any]:
    pick = confidence.pick
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "game_id": game_id,
        "pick": pick,
        "pick_label": CODE_TO_SUIT.get(pick, "") if pick else "",
        "confidence_pct": confidence.confidence_pct,
        "tier": confidence.tier,
        "supporting_count": len(confidence.supporting_patterns),
        "total_cases": confidence.total_cases,
        "has_conflict": confidence.has_conflict,
        "notified": notified,
        "skipped_reason": confidence.skipped_reason,
        "patterns": [_pattern_payload(p) for p in confidence.supporting_patterns],
        "all_rows": [_row_snapshot(row) for row in rows],
        "actual_winner": None,
        "actual_winner_label": "",
        "pick_correct": None,
        "resolved_at": None,
    }


def append_confidence_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, separators=(",", ":")) + "\n")


def read_confidence_log(path: Path, *, limit: int = 200) -> list[dict[str, Any]]:
    if limit <= 0 or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict[str, Any]] = []
    for line in reversed(lines):
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            entries.append(parsed)
        if len(entries) >= limit:
            break
    return entries


def confidence_already_logged(path: Path, game_id: str) -> bool:
    if not game_id or not path.is_file():
        return False
    for entry in read_confidence_log(path, limit=500):
        if str(entry.get("game_id") or "") == str(game_id):
            return True
    return False


def _read_confidence_log_lines(path: Path) -> list[str]:
    if not path.is_file():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def resolve_confidence_log_outcome(path: Path, game_id: str, winner_suit: str) -> bool:
    """Backfill the actual winner once a live game finishes."""
    code = winner_code(winner_suit)
    if code is None or not game_id:
        return False
    lines = _read_confidence_log_lines(path)
    if not lines:
        return False
    updated = False
    new_lines: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            entry = json.loads(text)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue
        if str(entry.get("game_id") or "") == str(game_id) and entry.get("actual_winner") is None:
            pick = entry.get("pick")
            entry["actual_winner"] = code
            entry["actual_winner_label"] = CODE_TO_SUIT.get(code, "")
            entry["pick_correct"] = pick is not None and int(pick) == code
            entry["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            updated = True
        new_lines.append(json.dumps(entry, separators=(",", ":")))
    if updated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated


def backfill_confidence_log_outcomes(path: Path, store: GameStore) -> int:
    """Persist missing forecast results from finished games already in the store."""
    lines = _read_confidence_log_lines(path)
    if not lines:
        return 0
    updated_count = 0
    new_lines: list[str] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            entry = json.loads(text)
        except json.JSONDecodeError:
            new_lines.append(line)
            continue
        game_id = str(entry.get("game_id") or "")
        if game_id and entry.get("actual_winner") is None:
            game = store.get_game(game_id)
            if game is not None and game.winner_suit:
                code = winner_code(game.winner_suit)
                if code is not None:
                    pick = entry.get("pick")
                    entry["actual_winner"] = code
                    entry["actual_winner_label"] = CODE_TO_SUIT.get(code, "")
                    entry["pick_correct"] = pick is not None and int(pick) == code
                    entry["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                    updated_count += 1
        new_lines.append(json.dumps(entry, separators=(",", ":")))
    if updated_count:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return updated_count


def outcome_payload_for_pick(
    *,
    predicted_pick: int | None,
    actual_code: int,
) -> dict[str, Any]:
    actual_label = CODE_TO_SUIT.get(actual_code, "")
    pick_correct = predicted_pick is not None and int(predicted_pick) == actual_code
    if predicted_pick is None:
        outcome_text = f"Actual winner: {actual_label} ({actual_code})"
    elif pick_correct:
        outcome_text = f"Actual winner: {actual_label} ({actual_code}) — prediction matched"
    else:
        predicted_label = CODE_TO_SUIT.get(int(predicted_pick), str(predicted_pick))
        outcome_text = (
            f"Actual winner: {actual_label} ({actual_code}) — predicted {predicted_label} ({predicted_pick})"
        )
    return {
        "actual_winner": actual_code,
        "actual_winner_label": actual_label,
        "actual_winner_color": CODE_TO_COLOR.get(actual_code, "#ddd"),
        "pick_correct": pick_correct,
        "outcome_text": outcome_text,
    }


def enrich_with_game_outcome(
    item: dict[str, Any],
    store: GameStore,
) -> dict[str, Any]:
    """Attach actual winner when the referenced live game has finished."""
    if item.get("actual_winner") is not None:
        if not item.get("outcome_text"):
            predicted = item.get("next_winner") or item.get("pick")
            predicted_pick = int(predicted) if predicted not in (None, "") else None
            item.update(
                outcome_payload_for_pick(
                    predicted_pick=predicted_pick,
                    actual_code=int(item["actual_winner"]),
                )
            )
        return item
    game_id = str(item.get("game_id") or "")
    if not game_id:
        return item
    game = store.get_game(game_id)
    if game is None or not game.winner_suit:
        return item
    actual_code = winner_code(game.winner_suit)
    if actual_code is None:
        return item
    predicted = item.get("next_winner") or item.get("pick")
    predicted_pick = int(predicted) if predicted not in (None, "") else None
    item.update(outcome_payload_for_pick(predicted_pick=predicted_pick, actual_code=actual_code))
    return item


def winner_hint_dedupe_key(
    game_id: str,
    patterns: list[WinnerHintAlertPattern] | list[dict[str, Any]],
) -> str:
    """Stable id for one live-game hint (same game + tails + favoured winner)."""
    if not game_id or not patterns:
        return ""
    next_code = patterns[0].next_code if isinstance(patterns[0], WinnerHintAlertPattern) else int(
        patterns[0].get("next_code") or 0
    )
    parts: list[str] = []
    for pattern in sorted(patterns, key=lambda p: p.length if isinstance(p, WinnerHintAlertPattern) else int(p.get("length") or 0)):
        if isinstance(pattern, WinnerHintAlertPattern):
            parts.append(f"{pattern.length}:{pattern.tail_text}")
        else:
            parts.append(f"{int(pattern.get('length') or 0)}:{pattern.get('tail') or ''}")
    return f"{game_id}:next={next_code}:{'|'.join(parts)}"


def winner_hint_headline(
    patterns: list[WinnerHintAlertPattern] | list[dict[str, Any]],
    *,
    next_code: int | str | None = None,
) -> str:
    """One-line summary for the notification bell."""
    if not patterns:
        return "Winner history hint"
    code = int(next_code or (
        patterns[0].next_code if isinstance(patterns[0], WinnerHintAlertPattern) else patterns[0].get("next_code") or 0
    ))
    suit = CODE_TO_SUIT.get(code, "?")
    if len(patterns) >= 2:
        return f"{suit} ({code}) — {len(patterns)} patterns"
    only = patterns[0]
    if isinstance(only, WinnerHintAlertPattern):
        pct, matched, total = only.next_pct, only.next_count, only.match_count
    else:
        pct = int(only.get("next_pct") or 0)
        matched = int(only.get("next_count") or 0)
        total = int(only.get("match_count") or 0)
    return f"{suit} ({code}) favored — {matched}/{total} history ({pct}%)"


def winner_hint_confidence_note(patterns: list[dict[str, Any]]) -> str:
    """Short trust line — sample size only (headline covers the pick)."""
    if not patterns:
        return ""
    pcts = [int(p.get("next_pct") or 0) for p in patterns]
    matches = [int(p.get("match_count") or 0) for p in patterns]
    min_pct = min(pcts)
    min_cases = min(matches)
    if len(patterns) >= 2:
        if min_cases <= 2:
            return (
                f"Only {min_cases} historical case{'s' if min_cases != 1 else ''} per pattern — weak sample."
            )
        if min(pcts) == max(pcts) == 100:
            return f"Weakest sample: {min_cases} cases per pattern."
        return f"Weakest pattern: {min_pct}% from {min_cases} cases."
    return f"{min_cases} historical case{'s' if min_cases != 1 else ''}."


_PATTERN_RE = re.compile(
    r"Last\s+(\d+)\s+\(([^)]+)\)\s+(\d+)\s+cases?\s+→\s+(\d+)\s+\((\d+)/(\d+),\s*(\d+)%\)"
)


def parse_winner_hint_patterns(message: str) -> list[dict[str, Any]]:
    """Extract pattern rows from a winner-hint log message."""
    patterns: list[dict[str, Any]] = []
    detail = message.split("—")[-1].split("· link=")[0] if "—" in message else message
    for chunk in detail.split("|"):
        m_pat = _PATTERN_RE.search(chunk.strip())
        if not m_pat:
            continue
        patterns.append(
            {
                "length": int(m_pat.group(1)),
                "tail": m_pat.group(2).strip(),
                "match_count": int(m_pat.group(3)),
                "next_code": int(m_pat.group(4)),
                "next_count": int(m_pat.group(5)),
                "next_total": int(m_pat.group(6)),
                "next_pct": int(m_pat.group(7)),
            }
        )
    return patterns


def dedupe_winner_hint_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest notification per game + pattern set."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get("dedupe_key") or item.get("id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def winner_forecast_link(game_id: str) -> str:
    """Deep link to the Forecasts page for one live game."""
    from urllib.parse import quote

    return f"/forecasts?game={quote(str(game_id), safe='')}"


def format_winner_hint_alert_message(
    game_id: str,
    patterns: list[WinnerHintAlertPattern],
    *,
    confidence_pct: int = 0,
    tier: str = "MEDIUM",
) -> str:
    if not patterns:
        return ""
    next_code = patterns[0].next_code
    parts = [
        (
            f"Last {p.length} ({p.tail_text}) "
            f"{p.match_count} case{'s' if p.match_count != 1 else ''} → {p.next_code} "
            f"({p.next_count}/{p.match_count}, {p.next_pct}%)"
        )
        for p in patterns
    ]
    detail = " | ".join(parts)
    return (
        f"[WINNER-HINT] Game {game_id} — next winner likely {next_code} — "
        f"history {confidence_pct}% ({tier}) — {detail} · link={winner_forecast_link(game_id)}"
    )


def winner_hint_rows_from_payload(rows: list[dict[str, Any]]) -> list[HintRow]:
    parsed: list[HintRow] = []
    for row in rows:
        tail = tuple(row.get("tail") or [])
        counts_raw = row.get("follow_up_counts") or {}
        counts = {int(k): int(v) for k, v in counts_raw.items()}
        parsed.append(
            HintRow(
                length=int(row.get("length") or len(tail)),
                tail=tail,
                match_count=int(row.get("match_count") or 0),
                follow_up_counts=counts,
            )
        )
    return parsed


def notification_item_from_alert(entry: dict[str, str]) -> dict[str, Any]:
    """Turn a log row into a notification payload for the web bell."""
    message = entry.get("message") or ""
    game_id = ""
    next_code = ""
    m_game = re.search(r"Game\s+(\S+)\s+—", message)
    if m_game:
        game_id = m_game.group(1)
    m_next = re.search(r"next winner likely\s+(\d)", message)
    if m_next:
        next_code = m_next.group(1)
    m_conf = re.search(r"(?:confidence|history)\s+(\d+)%\s+\((\w+)\)", message)
    confidence_pct = int(m_conf.group(1)) if m_conf else 0
    tier = m_conf.group(2).upper() if m_conf else ""
    patterns = parse_winner_hint_patterns(message)
    if patterns:
        confidence_pct = _historical_confidence_pct(patterns)
    code_int = int(next_code) if next_code else 0
    if tier not in CONFIDENCE_TIERS:
        tier = ""
    headline = winner_hint_headline(patterns, next_code=code_int) if patterns else "Winner history hint"
    if tier and confidence_pct:
        suit = CODE_TO_SUIT.get(code_int, "?")
        headline = f"{suit} ({code_int}) — {confidence_pct}% from history ({tier})"
    dedupe_key = winner_hint_dedupe_key(game_id, patterns) if game_id and patterns else (entry.get("id") or message)
    link = winner_forecast_link(game_id) if game_id else "/forecasts"
    return {
        "id": entry.get("id") or message,
        "kind": "winner-hint",
        "at": entry.get("at"),
        "title": f"Game {game_id}" if game_id else "Winner hint",
        "headline": headline,
        "confidence_pct": confidence_pct,
        "tier": tier,
        "confidence_note": winner_hint_confidence_note(patterns),
        "game_id": game_id,
        "next_winner": next_code,
        "winner_label": CODE_TO_SUIT.get(code_int, ""),
        "winner_color": CODE_TO_COLOR.get(code_int, "#ddd"),
        "pattern_count": len(patterns),
        "patterns": patterns,
        "dedupe_key": dedupe_key,
        "link": link,
    }
