"""Internal ops notifications (missed winners) — never client-facing channels."""

from __future__ import annotations

from typing import Any

from game_analyzer.alerts import alert_settings_from_config, deliver_ops_alert
from game_analyzer.store import GameStore

_MISSED_WINNER_ALERTED: set[str] = set()


def format_missed_winner_message(
    game_id: str,
    *,
    started_at: str,
    shot_count: int,
    public_base_url: str = "",
) -> str:
    base = public_base_url.rstrip("/")
    unfinished_link = f"{base}/unfinished" if base else "/unfinished"
    game_link = f"{base}/game/{game_id}" if base else f"/game/{game_id}"
    return (
        f"[MISSED-WINNER] Game {game_id} — {shot_count} shot(s), no winner captured. "
        f"Started {started_at}. "
        f"Review: {unfinished_link} · {game_link} · game_id={game_id}"
    )


def notify_missed_winner(
    config: dict[str, Any],
    store: GameStore,
    game_id: str,
) -> bool:
    """Slack DM / ops channel when a tracked game ends without winner_suit."""
    if not game_id or game_id in _MISSED_WINNER_ALERTED:
        return False
    game = store.get_game(game_id)
    if game is None or game.winner_suit:
        return False

    settings = alert_settings_from_config(config)
    if not settings.ops_webhook_url:
        return False

    message = format_missed_winner_message(
        game_id,
        started_at=game.started_at,
        shot_count=len(game.frames),
        public_base_url=settings.public_base_url,
    )
    if not deliver_ops_alert(settings, message, dedupe_key=game_id):
        return False
    _MISSED_WINNER_ALERTED.add(game_id)
    return True


def reset_missed_winner_memory() -> None:
    """Test helper / capture restart."""
    _MISSED_WINNER_ALERTED.clear()
