from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.vision import draw_table_overlay, extract_real, read_image

REAL_DIR_NAME = "fixtures/real"


class DemoApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Game Analyzer — your race screenshots")
        self.geometry("900x780")
        ctk.set_appearance_mode("dark")

        self.config_data = load_config()
        root = Path(__file__).resolve().parent.parent
        self.paths = sorted((root / REAL_DIR_NAME).glob("*.png"))
        self.index = 0

        self.preview = ctk.CTkLabel(self, text="")
        self.preview.pack(padx=12, pady=8)

        nav = ctk.CTkFrame(self)
        nav.pack(fill="x", padx=12)
        ctk.CTkButton(nav, text="Previous", width=120, command=self.prev).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Next", width=120, command=self.next).pack(side="left", padx=6)
        self.file_label = ctk.CTkLabel(nav, text="", font=("Consolas", 14))
        self.file_label.pack(side="left", padx=12)

        self.status = ctk.CTkLabel(self, text="", font=("Consolas", 15), justify="left")
        self.status.pack(padx=12, pady=6, anchor="w")

        self.log = ctk.CTkTextbox(self, height=160)
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log.insert(
            "end",
            "Yellow boxes = the 4 table rows we measure.\n"
            "Green box = that row looks like WINNER (bright green).\n"
            "S/H/C/D numbers = green minus red. Only a large + number is a winner.\n"
            "This does not read cards, odds, or 'to go' yet.\n\n",
        )

        if self.paths:
            self.show()

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

    def show(self) -> None:
        path = self.paths[self.index]
        frame = read_image(path)
        result = extract_real(frame, self.config_data)
        rgb = frame[:, :, ::-1]
        overlay = draw_table_overlay(rgb, self.config_data, result)
        image = Image.fromarray(overlay).resize((756, 520))
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=(756, 520))
        self.preview.configure(image=photo)
        self.preview.image = photo

        winner = result.winner_suit.value if result.winner_suit else "none"
        line = (
            f"{path.name}  state={result.race_state.value}  "
            f"winner={winner}  confident={result.confident}  [{result.notes}]"
        )
        self.file_label.configure(text=f"{self.index + 1}/{len(self.paths)}  {path.name}")
        self.status.configure(text=line)
        self.log.insert("end", line + "\n")
        self.log.see("end")
