from __future__ import annotations


def main() -> None:
    try:
        from game_analyzer.demo_app import DemoApp
    except ModuleNotFoundError:
        print("No window UI: this Linux is missing tkinter (package python3-tk).")
        print("Printing the same results in the terminal.\n")
        from game_analyzer.cli import run

        run()
        return

    app = DemoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
