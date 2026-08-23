"""Backtest confidence tiers on exported verified games (read-only)."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from game_analyzer.confidence import ConfidenceLevel, evaluate_confidence
from game_analyzer.race_values import guess_ready, parse_handicap_rows, race_guess, suits_match

DEFAULT_EXPORT = Path(__file__).resolve().parent.parent / "data" / "games_research_export.json"
DEFAULT_REPORT = Path(__file__).resolve().parent.parent / "data" / "confidence_backtest.json"


def _games_from_export(path: Path, *, verified_only: bool) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if verified_only:
        return list(payload.get("verified_games_only") or [])
    return list(payload.get("games") or [])


def run_backtest(
    export_path: Path,
    *,
    verified_only: bool = True,
    draw_cards: int = 6,
    simulations: int = 1500,
) -> dict:
    games = _games_from_export(export_path, verified_only=verified_only)
    by_level: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "correct": 0})
    skipped = Counter()
    evaluated = 0

    for game in games:
        winner = game.get("winner")
        handicap = parse_handicap_rows(
            [game["handicap"][suit] for suit in ("Spades", "Hearts", "Clubs", "Diamonds")]
        )
        all_draws = tuple(game.get("all_draw_cards") or [])
        guess_draws = tuple(game.get("guess_draw_cards") or [])
        draws = guess_draws if guess_ready(guess_draws) else all_draws[:draw_cards]
        if not winner or not guess_ready(draws):
            skipped["not_ready"] += 1
            continue

        pick = race_guess(handicap, draws)
        result = evaluate_confidence(handicap, draws, pick=pick, simulations=simulations)
        evaluated += 1
        level = result.level.value
        by_level[level]["total"] += 1
        if pick and suits_match(pick, winner):
            by_level[level]["correct"] += 1

    alert_levels = (ConfidenceLevel.HIGH.value, ConfidenceLevel.VERY_HIGH.value)
    alert_total = sum(by_level[level]["total"] for level in alert_levels)
    alert_correct = sum(by_level[level]["correct"] for level in alert_levels)

    summary = {
        "export_path": str(export_path.resolve()),
        "verified_only": verified_only,
        "draw_cards": draw_cards,
        "simulations": simulations,
        "games_in_export": len(games),
        "evaluated": evaluated,
        "skipped": dict(skipped),
        "by_level": {
            level: {
                **counts,
                "accuracy_pct": round(100.0 * counts["correct"] / counts["total"], 1)
                if counts["total"]
                else None,
            }
            for level, counts in sorted(by_level.items())
        },
        "high_plus": {
            "total": alert_total,
            "correct": alert_correct,
            "accuracy_pct": round(100.0 * alert_correct / alert_total, 1) if alert_total else None,
            "coverage_pct": round(100.0 * alert_total / evaluated, 1) if evaluated else None,
        },
    }
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Backtest confidence tiers on exported games.")
    parser.add_argument(
        "--export",
        type=Path,
        default=DEFAULT_EXPORT,
        help="Path to games_research_export.json (created via python -m game_analyzer.export if missing)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT,
        help="Where to write JSON summary",
    )
    parser.add_argument("--all-games", action="store_true", help="Use full games list, not verified only")
    parser.add_argument("--draw-cards", type=int, default=6)
    parser.add_argument("--simulations", type=int, default=1500)
    args = parser.parse_args(argv)

    export_path = args.export
    if not export_path.is_file():
        from game_analyzer.export import DEFAULT_OUT, write_export

        write_export(DEFAULT_OUT)
        export_path = DEFAULT_OUT

    summary = run_backtest(
        export_path,
        verified_only=not args.all_games,
        draw_cards=args.draw_cards,
        simulations=args.simulations,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Evaluated {summary['evaluated']} games from {summary['games_in_export']} exported")
    print("By confidence level:")
    for level, row in summary["by_level"].items():
        print(f"  {level:10s}  {row['correct']:4d}/{row['total']:<4d}  {row['accuracy_pct']}%")
    high = summary["high_plus"]
    print(
        f"HIGH+VERY_HIGH: {high['correct']}/{high['total']} = {high['accuracy_pct']}% "
        f"(coverage {high['coverage_pct']}%)"
    )
    print(f"Report: {args.report.resolve()}")


if __name__ == "__main__":
    main()
