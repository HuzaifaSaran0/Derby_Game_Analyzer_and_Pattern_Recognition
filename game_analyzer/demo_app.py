from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.models import ExtractionResult
from game_analyzer.vision import draw_table_overlay, extract_real, read_image

REAL_DIR_NAME = "fixtures/real"


class DemoApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Game Analyzer — your race screenshots")
        self.geometry("900x860")
        ctk.set_appearance_mode("dark")

        self.config_data = load_config()
        root = Path(__file__).resolve().parent.parent
        self.paths = sorted((root / REAL_DIR_NAME).glob("*.png"))
        self.index = 0

        self.looping = False
        self.after_id = None

        self.preview = ctk.CTkLabel(self, text="")
        self.preview.pack(padx=12, pady=(8, 4))

        # Fetched extraction — always visible under the screenshot.
        results = ctk.CTkFrame(self, fg_color=("#2b2b2b", "#1e1e1e"))
        results.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(results, text="Fetched data", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2)
        )
        grid = ctk.CTkFrame(results, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 10))
        self.result_state = self._result_row(grid, 0, "Race state")
        self.result_winner = self._result_row(grid, 1, "Winner")
        self.result_cards = self._result_row(grid, 2, "Draw cards")

        nav = ctk.CTkFrame(self)
        nav.pack(fill="x", padx=12)
        ctk.CTkButton(nav, text="Previous", width=120, command=self.prev).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Next", width=120, command=self.next).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Start capture", width=140, command=self.start_loop).pack(
            side="left", padx=6
        )
        ctk.CTkButton(nav, text="Stop", width=80, command=self.stop_loop).pack(side="left", padx=6)
        self.file_label = ctk.CTkLabel(nav, text="", font=("Consolas", 14))
        self.file_label.pack(side="left", padx=12)

        self.status = ctk.CTkLabel(self, text="", font=("Consolas", 14), justify="left")
        self.status.pack(padx=12, pady=6, anchor="w")

        self.log = ctk.CTkTextbox(self, height=140)
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log.insert(
            "end",
            "Reads winner row (green) + the 3 move cards (rank+suit).\n"
            "Fetched values appear in the panel under the screenshot.\n"
            "Saved live images are clean unless draw_overlays=true.\n\n",
        )

        if self.paths:
            self.show()

    @staticmethod
    def _result_row(parent: ctk.CTkFrame, row: int, title: str) -> ctk.CTkLabel:
        ctk.CTkLabel(parent, text=f"{title}:", width=100, anchor="w", font=("Segoe UI", 13)).grid(
            row=row, column=0, sticky="w", pady=2
        )
        value = ctk.CTkLabel(parent, text="—", anchor="w", font=("Consolas", 15))
        value.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        parent.grid_columnconfigure(1, weight=1)
        return value

    def _set_results(self, result: ExtractionResult) -> None:
        winner = result.winner_suit.value.title() if result.winner_suit else "none yet"
        if result.draw_cards:
            cards = "  ·  ".join(result.draw_cards)
        else:
            cards = "none visible"
        state = {
            "FINISHED": "Race finished (winner highlighted)",
            "BETTING": "In progress / no winner yet",
            "UNKNOWN": "Could not read table",
            "IN_PROGRESS": "In progress",
        }.get(result.race_state.value, result.race_state.value)
        self.result_state.configure(text=state)
        self.result_winner.configure(text=winner)
        self.result_cards.configure(text=cards)

    def prev(self) -> None:
        if not self.paths:
            return
        self.index = (self.index - 1) % len(self.paths)
        self.show()

    def next(self) -> None:
        if not self.paths:
            return
        self.index = (self.index + 1) % len(self.paths)
        self.show()

    def start_loop(self) -> None:
        if self.looping:
            return
        region = self.config_data["capture"]
        wait = float(region.get("delay_seconds", 5))
        every = float(region.get("interval_seconds", 30))
        self.looping = True
        mode = str(region.get("mode", "screen"))
        if mode.lower() in {"brave_cdp", "brave", "cdp"}:
            hint = (
                f"Brave CDP mode: UI can stay in front. First shot in {wait:.0f}s, "
                f"then every {every:.0f}s."
            )
        else:
            hint = (
                f"Screen mode: click Brave so the game is visible. "
                f"First shot in {wait:.0f}s, then every {every:.0f}s."
            )
        self.status.configure(text=hint)
        self.after_id = self.after(int(wait * 1000), self._loop_tick)

    def stop_loop(self) -> None:
        self.looping = False
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.status.configure(text="Capture stopped.")

    def _loop_tick(self) -> None:
        if not self.looping:
            return
        from game_analyzer.live import capture_once

        path, frame, _result = capture_once(self.config_data)
        self.show_frame(frame, path.name)
        every = float(self.config_data["capture"].get("interval_seconds", 30))
        self.after_id = self.after(int(every * 1000), self._loop_tick)

    def show(self) -> None:
        path = self.paths[self.index]
        frame = read_image(path)
        self.show_frame(frame, f"{self.index + 1}/{len(self.paths)}  {path.name}")

    def show_frame(self, frame, label: str) -> None:
        result = extract_real(frame, self.config_data)
        rgb = frame[:, :, ::-1]
        if self.config_data.get("draw_overlays", False):
            shown = draw_table_overlay(rgb, self.config_data, result)
        else:
            shown = rgb
        image = Image.fromarray(shown).resize((756, 480))
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=(756, 480))
        self.preview.configure(image=photo)
        self.preview.image = photo

        self._set_results(result)

        winner = result.winner_suit.value if result.winner_suit else "none"
        cards = ",".join(result.draw_cards) if result.draw_cards else "-"
        line = (
            f"{label}  state={result.race_state.value}  "
            f"winner={winner}  draw=[{cards}]  [{result.notes}]"
        )
        self.file_label.configure(text=label)
        self.status.configure(text=line)
        self.log.insert("end", line + "\n")
        self.log.see("end")
