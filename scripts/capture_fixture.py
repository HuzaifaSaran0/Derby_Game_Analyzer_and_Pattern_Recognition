from __future__ import annotations

import argparse

from game_analyzer.capture import grab_region
from game_analyzer.config import load_config
from game_analyzer.fixtures import IMAGES_DIR
from game_analyzer.vision import write_image


def main() -> None:
    parser = argparse.ArgumentParser(description="Save one ROI screenshot into fixtures/images/")
    parser.add_argument("name", help="filename stem, e.g. real_winner_hearts")
    args = parser.parse_args()

    config = load_config()
    frame = grab_region(config["capture"])
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    path = IMAGES_DIR / f"{args.name}.png"
    write_image(path, frame)
    print(f"saved {path}")


if __name__ == "__main__":
    main()
