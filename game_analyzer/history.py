from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.race_values import pre_race_outcome
from game_analyzer.store import GameStore

THUMB = (280, 168)


class HistoryWindow(ctk.CTkToplevel):
    """Separate page: one saved game at a time — winner + all screenshots."""

    def __init__(self, master, store: GameStore | None = None) -> None:
        super().__init__(master)
        self.title("Game Analyzer — History")
        self.geometry("980x720")
        self.store = store or GameStore()
        self.game_ids: list[str] = []
        self.index = 0
        self._photos: list = []

        nav = ctk.CTkFrame(self)
        nav.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkButton(nav, text="Previous game", width=140, command=self.prev).pack(
            side="left", padx=6
        )
        ctk.CTkButton(nav, text="Next game", width=140, command=self.next).pack(
            side="left", padx=6
        )
        self.header = ctk.CTkLabel(nav, text="", font=("Consolas", 15))
        self.header.pack(side="left", padx=12)

        info = ctk.CTkFrame(self, fg_color=("#2b2b2b", "#1e1e1e"))
        info.pack(fill="x", padx=12, pady=(0, 8))
        self.winner_label = ctk.CTkLabel(
            info, text="Winner: —", font=("Segoe UI", 18, "bold"), anchor="w"
        )
        self.winner_label.pack(fill="x", padx=12, pady=(10, 2))
        self.guess_label = ctk.CTkLabel(
            info, text="Guess: —", font=("Segoe UI", 16), anchor="w"
        )
        self.guess_label.pack(fill="x", padx=12, pady=(0, 2))
        self.meta_label = ctk.CTkLabel(
            info, text="", font=("Consolas", 13), anchor="w", justify="left"
        )
        self.meta_label.pack(fill="x", padx=12, pady=(0, 10))

        self.shots = ctk.CTkScrollableFrame(self, label_text="Screenshots")
        self.shots.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.reload()

    def reload(self) -> None:
        self.game_ids = self.store.list_game_ids()
        if not self.game_ids:
            self.header.configure(text="No saved games yet")
            self.winner_label.configure(text="Winner: —")
            self.guess_label.configure(text="Guess: —")
            self.meta_label.configure(text="Capture a complete game first.")
            self._clear_shots()
            return
        self.index = min(self.index, len(self.game_ids) - 1)
        self.show()

    def prev(self) -> None:
        if not self.game_ids:
            return
        self.index = (self.index - 1) % len(self.game_ids)
        self.show()

    def next(self) -> None:
        if not self.game_ids:
            return
        self.index = (self.index + 1) % len(self.game_ids)
        self.show()

    def _clear_shots(self) -> None:
        for child in self.shots.winfo_children():
            child.destroy()
        self._photos = []

    def show(self) -> None:
        game_id = self.game_ids[self.index]
        game = self.store.get_game(game_id)
        if game is None:
            return
        self.header.configure(text=f"{self.index + 1}/{len(self.game_ids)}  Game ID {game.game_id}")
        winner = game.winner_suit.title() if game.winner_suit else "none yet"
        self.winner_label.configure(text=f"Winner: {winner}")
        outcome = pre_race_outcome(game.winner_suit, game.handicap_cards)
        self.guess_label.configure(text=self._guess_text(outcome))
        self.meta_label.configure(
            text=f"started {game.started_at}    finished {game.finished_at or '—'}    "
            f"screenshots {len(game.frames)}"
        )
        self._clear_shots()
        if not game.frames:
            ctk.CTkLabel(self.shots, text="No screenshots stored for this game.").pack(anchor="w")
            return
        for col, frame in enumerate(game.frames):
            cell = ctk.CTkFrame(self.shots, fg_color="transparent")
            cell.grid(row=col // 2, column=col % 2, padx=8, pady=8, sticky="nw")
            caption = f"#{frame.seq}  {frame.phase}  {frame.captured_at}"
            ctk.CTkLabel(cell, text=caption, font=("Consolas", 12), anchor="w").pack(anchor="w")
            path: Path = frame.screenshot_path
            if path.exists():
                image = Image.open(path).convert("RGB")
                image.thumbnail(THUMB)
                photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
                self._photos.append(photo)
                ctk.CTkLabel(cell, image=photo, text="").pack(anchor="w", pady=(4, 0))
            else:
                ctk.CTkLabel(cell, text=f"missing file: {path.name}").pack(anchor="w")

    @staticmethod
    def _guess_text(outcome) -> str:
        if outcome.guess is None:
            if outcome.winner:
                return "Guess: — (handicap not fully readable)"
            return "Guess: — (no finished winner yet)"
        guess = outcome.guess.title()
        if outcome.winner is None:
            return f"Guess: {guess} (waiting for winner)"
        if outcome.correct:
            return f"Guess: {guess}  ✓ correct"
        won = outcome.winner.title()
        return f"Guess: {guess}  ✗ wrong (won {won})"
