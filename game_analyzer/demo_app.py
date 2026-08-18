from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.models import ExtractionResult, Suit
from game_analyzer.vision import draw_table_overlay, extract_real, read_image

REAL_DIR_NAME = "fixtures/real"
SUIT_STYLES = {
    "Spades": {"symbol": "♠", "color": "#31c96b"},
    "Hearts": {"symbol": "♥", "color": "#ff5a67"},
    "Clubs": {"symbol": "♣", "color": "#58a6ff"},
    "Diamonds": {"symbol": "♦", "color": "#f2c94c"},
}


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

        nav = ctk.CTkFrame(self)
        nav.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkButton(nav, text="Previous", width=120, command=self.prev).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Next", width=120, command=self.next).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Start capture", width=140, command=self.start_loop).pack(
            side="left", padx=6
        )
        ctk.CTkButton(nav, text="Stop", width=80, command=self.stop_loop).pack(side="left", padx=6)
        self.file_label = ctk.CTkLabel(nav, text="", font=("Consolas", 14))
        self.file_label.pack(side="left", padx=12)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 4))
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        self.preview = ctk.CTkLabel(top, text="")
        self.preview.grid(row=0, column=0, sticky="nw", padx=(0, 12))

        table_panel = ctk.CTkFrame(top, fg_color=("#252525", "#181818"), corner_radius=8)
        table_panel.grid(row=0, column=1, sticky="ne")
        ctk.CTkLabel(table_panel, text="Generated table", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=12, pady=(10, 6)
        )
        self.card_table = ctk.CTkFrame(table_panel, fg_color="transparent")
        self.card_table.pack(fill="x", padx=12, pady=(0, 10))
        self.card_row_frames: dict[str, ctk.CTkFrame] = {}
        for row_idx, suit_name in enumerate(["Spades", "Hearts", "Clubs", "Diamonds"]):
            style = SUIT_STYLES[suit_name]
            row = ctk.CTkFrame(self.card_table, fg_color="transparent")
            row.grid(row=row_idx, column=0, sticky="ew", pady=4)
            row.grid_columnconfigure(1, weight=1)
            label = ctk.CTkLabel(
                row,
                text=f"{style['symbol']} {suit_name}",
                text_color=style["color"],
                font=("Segoe UI", 14, "bold"),
                width=110,
                anchor="w",
            )
            label.grid(row=0, column=0, sticky="w", padx=(0, 8))
            cards = ctk.CTkFrame(row, fg_color="transparent")
            cards.grid(row=0, column=1, sticky="w")
            self.card_row_frames[suit_name] = cards

        # Fetched extraction — always visible under the screenshot.
        results = ctk.CTkFrame(self, fg_color=("#2b2b2b", "#1e1e1e"))
        results.pack(fill="x", padx=12, pady=(0, 8))
        ctk.CTkLabel(results, text="Fetched data", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2)
        )
        left = ctk.CTkFrame(results, fg_color="transparent")
        left.pack(fill="x", padx=12, pady=(0, 10))
        self.result_state = self._result_row(left, 0, "Race state")
        self.result_winner = self._result_row(left, 1, "Winner")

        self.status = ctk.CTkLabel(self, text="", font=("Consolas", 14), justify="left")
        self.status.pack(padx=12, pady=6, anchor="w")

        self.log = ctk.CTkTextbox(self, height=140)
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log.insert(
            "end",
            "Reads winner row (green) + handicap cards + the 3 move cards.\n"
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
        value = ctk.CTkLabel(parent, text="—", anchor="w", justify="left", font=("Consolas", 15))
        value.grid(row=row, column=1, sticky="ew", pady=2, padx=(8, 0))
        parent.grid_columnconfigure(1, weight=1)
        return value

    def _set_results(self, result: ExtractionResult) -> None:
        winner = result.winner_suit.value.title() if result.winner_suit else "none yet"
        state = {
            "FINISHED": "Race finished (winner highlighted)",
            "BETTING": "In progress / no winner yet",
            "UNKNOWN": "Could not read table",
            "IN_PROGRESS": "In progress",
        }.get(result.race_state.value, result.race_state.value)
        self.result_state.configure(text=state)
        self.result_winner.configure(text=winner)
        self._render_card_table(result)

    def _render_card_table(self, result: ExtractionResult) -> None:
        for frame in self.card_row_frames.values():
            for child in frame.winfo_children():
                child.destroy()

        for suit_name, cards in result.combined_suit_cards():
            holder = self.card_row_frames[suit_name]
            if not cards:
                ctk.CTkLabel(holder, text="—", font=("Consolas", 15)).pack(side="left", padx=4)
                continue
            for card in cards:
                self._add_card_widget(holder, card)

    def _add_card_widget(self, parent: ctk.CTkFrame, card: str) -> None:
        rank = card[:-1] if len(card) > 1 else card
        suit_letter = card[-1] if len(card) > 1 else "?"
        suit = next((s for s in Suit if s.value[0] == suit_letter), None)
        if suit is None:
            ctk.CTkLabel(parent, text=card, font=("Consolas", 15)).pack(side="left", padx=4)
            return
        suit_name = suit.value.title()
        style = SUIT_STYLES[suit_name]
        card_box = ctk.CTkFrame(
            parent,
            width=48,
            height=60,
            corner_radius=6,
            fg_color="#ffffff",
            border_width=1,
            border_color="#b8b8b8",
        )
        card_box.pack(side="left", padx=3)
        card_box.pack_propagate(False)
        ctk.CTkLabel(
            card_box,
            text=rank,
            text_color=style["color"],
            font=("Segoe UI", 18, "bold"),
        ).pack(pady=(6, 0))
        ctk.CTkLabel(
            card_box,
            text=style["symbol"],
            text_color=style["color"],
            font=("Segoe UI Symbol", 18, "bold"),
        ).pack(expand=True)

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
        image = Image.fromarray(shown).resize((640, 380))
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=(640, 380))
        self.preview.configure(image=photo)
        self.preview.image = photo

        self._set_results(result)

        winner = result.winner_suit.value if result.winner_suit else "none"
        handicap = "|".join(",".join(row) for row in result.handicap_cards) if result.handicap_cards else "-"
        cards = ",".join(result.draw_cards) if result.draw_cards else "-"
        line = (
            f"{label}  state={result.race_state.value}  "
            f"winner={winner}  handicap=[{handicap}]  draw=[{cards}]  [{result.notes}]"
        )
        self.file_label.configure(text=label)
        self.status.configure(text=line)
        self.log.insert("end", line + "\n")
        self.log.see("end")
