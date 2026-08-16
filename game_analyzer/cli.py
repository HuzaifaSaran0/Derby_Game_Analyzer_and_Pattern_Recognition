from __future__ import annotations

from pathlib import Path

from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.vision import draw_table_overlay, extract_real, read_image, write_image

ROOT = Path(__file__).resolve().parent.parent
REAL_DIR = ROOT / "fixtures" / "real"
OVERLAY_DIR = REAL_DIR / "overlays"


def run() -> None:
    config = load_config()
    paths = sorted(REAL_DIR.glob("*.png"))
    if not paths:
        print("No screenshots in fixtures/real/")
        return

    OVERLAY_DIR.mkdir(parents=True, exist_ok=True)
    print("Reading your race screenshots.\n")
    print(f"{'file':22}  {'state':12}  {'winner':10}  scores (S H C D green-red)")
    print("-" * 78)

    for path in paths:
        frame = read_image(path)
        result = extract_real(frame, config)
        winner = result.winner_suit.value if result.winner_suit else "none"
        print(f"{path.name:22}  {result.race_state.value:12}  {winner:10}  {result.notes}")

        overlay = draw_table_overlay(frame[:, :, ::-1], config, result)
        write_image(OVERLAY_DIR / path.name, overlay[:, :, ::-1])

    print()
    print(f"Boxed copies saved in {OVERLAY_DIR}")
    print("Open those PNGs to see which table rows the code measured.")


if __name__ == "__main__":
    run()
