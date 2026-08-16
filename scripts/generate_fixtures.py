from game_analyzer.config import load_config
from game_analyzer.fixtures import generate

if __name__ == "__main__":
    generate(load_config())
    print("wrote fixtures/images and fixtures/templates")
