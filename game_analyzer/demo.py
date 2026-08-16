from __future__ import annotations

import argparse
import time

import customtkinter as ctk
from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.fixtures import IMAGES_DIR, consensus, generate
from game_analyzer.vision import extract, read_image


class DemoApp(ctk.CTk):
    def __init__(self, source: str) -> None:
        super().__init__()
        self.title("Game Analyzer — Phase 1")
        self.geometry("820x520")
        ctk.set_appearance_mode("dark")

        self.config_data = load_config()
        generate(self.config_data)
        self.source = source
        self.fixture_paths = sorted(IMAGES_DIR.glob("*.png"))
        self.fixture_index = 0
        self.repeat_left = 0
        self.recent = []

        self.preview = ctk.CTkLabel(self, text="")
        self.preview.pack(padx=16, pady=12)

        self.status = ctk.CTkLabel(self, text="starting…", font=("Consolas", 16), justify="left")
        self.status.pack(padx=16, pady=8, anchor="w")

        self.log = ctk.CTkTextbox(self, height=180)
        self.log.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        self.after(200, self.tick)

    def next_frame(self):
        if self.source == "screen":
            from game_analyzer.capture import grab_region

            return grab_region(self.config_data["capture"])

        needed = int(self.config_data.get("consensus_frames", 3))
        if not self.fixture_paths:
            return None
        if self.repeat_left <= 0:
            self.repeat_left = needed
            self.fixture_index += 1
        self.repeat_left -= 1
        path = self.fixture_paths[(self.fixture_index - 1) % len(self.fixture_paths)]
        return read_image(path)

    def tick(self) -> None:
        frame = self.next_frame()
        if frame is None:
            self.status.configure(text="no frame")
            self.after(500, self.tick)
            return

        result = extract(frame, self.config_data)
        self.recent.append(result)
        self.recent = self.recent[-10:]
        agreed = consensus(self.recent, int(self.config_data.get("consensus_frames", 3)))

        rgb = frame[:, :, ::-1]
        image = Image.fromarray(rgb).resize((640, 360))
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=(640, 360))
        self.preview.configure(image=photo)
        self.preview.image = photo

        shown = agreed or result
        flag = "OK" if shown.confident else "skip"
        line = (
            f"{flag}  state={shown.race_state.value}  "
            f"suit={shown.winner_suit.value if shown.winner_suit else '-'}  "
            f"hl={shown.high_low.value if shown.high_low else '-'}  {shown.notes}"
        )
        self.status.configure(text=line)
        if agreed and agreed.confident:
            stamp = time.strftime("%H:%M:%S")
            self.log.insert("end", f"[{stamp}] {line}\n")
            self.log.see("end")

        delay = 800 if self.source == "fixtures" else 250
        self.after(delay, self.tick)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=("fixtures", "screen"), default="fixtures")
    args = parser.parse_args()
    app = DemoApp(args.source)
    app.mainloop()


if __name__ == "__main__":
    main()
