from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.models import ExtractionResult, Suit
from game_analyzer.confidence import evaluate_confidence, format_confidence_text
from game_analyzer.race_values import race_snapshot, suits_match
from game_analyzer.store import GameStore
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
        # Keep default size under typical laptop usable height (~738 on 1366x768).
        # A minsize taller than the screen blocks the WM maximize button.
        self.geometry("900x700")
        self.minsize(800, 560)
        ctk.set_appearance_mode("dark")

        self.config_data = load_config()
        root = Path(__file__).resolve().parent.parent
        self.store = GameStore(root=root)
        self.paths = sorted((root / REAL_DIR_NAME).glob("*.png"))
        self.index = 0

        self.looping = False
        self.after_id = None
        self.last_session_text = "offline screenshot"
        self.last_table_cards = None
        self._result_value_labels: list[ctk.CTkLabel] = []

        nav = ctk.CTkFrame(self)
        nav.pack(fill="x", padx=12, pady=(8, 4))
        ctk.CTkButton(nav, text="Previous", width=120, command=self.prev).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Next", width=120, command=self.next).pack(side="left", padx=6)
        ctk.CTkButton(nav, text="Start capture", width=140, command=self.start_loop).pack(
            side="left", padx=6
        )
        ctk.CTkButton(nav, text="Stop", width=80, command=self.stop_loop).pack(side="left", padx=6)
        self.history_win = None
        ctk.CTkButton(nav, text="History", width=100, command=self.open_history).pack(
            side="right", padx=6
        )
        self.file_label = ctk.CTkLabel(nav, text="", font=("Consolas", 14))
        self.file_label.pack(side="left", padx=12)

        self.guess_stats = ctk.CTkLabel(
            self,
            text="",
            font=("Segoe UI", 14),
            anchor="w",
            justify="left",
        )
        self.guess_stats.pack(fill="x", padx=12, pady=(0, 4))
        self._refresh_guess_stats()

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(8, 4))
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        self.preview = ctk.CTkLabel(top, text="")
        self.preview.grid(row=0, column=0, sticky="nw", padx=(0, 12))

        right_col = ctk.CTkFrame(top, fg_color="transparent")
        right_col.grid(row=0, column=1, sticky="ne")

        remaining_panel = ctk.CTkFrame(right_col, fg_color=("#252525", "#181818"), corner_radius=8)
        remaining_panel.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            remaining_panel,
            text="Win chance (expected finish + track blend)",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", padx=12, pady=(10, 4))
        self.remaining_rows: dict[str, ctk.CTkLabel] = {}
        for suit_name in ["Spades", "Hearts", "Clubs", "Diamonds"]:
            style = SUIT_STYLES[suit_name]
            row = ctk.CTkFrame(remaining_panel, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=2)
            ctk.CTkLabel(
                row,
                text=f"{style['symbol']} {suit_name}",
                text_color=style["color"],
                font=("Segoe UI", 13, "bold"),
                width=110,
                anchor="w",
            ).pack(side="left")
            value = ctk.CTkLabel(row, text="—", font=("Consolas", 14), anchor="w")
            value.pack(side="left", padx=(8, 0))
            self.remaining_rows[suit_name] = value
        self.remaining_favourite = ctk.CTkLabel(
            remaining_panel,
            text="",
            font=("Segoe UI", 12),
            text_color="#aaaaaa",
            wraplength=280,
            justify="left",
        )
        self.remaining_favourite.pack(anchor="w", padx=12, pady=(6, 10))

        table_panel = ctk.CTkFrame(right_col, fg_color=("#252525", "#181818"), corner_radius=8)
        table_panel.pack(fill="x")
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

        results = ctk.CTkFrame(self, fg_color=("#2b2b2b", "#1e1e1e"))
        results.pack(fill="x", padx=12, pady=(0, 6))
        ctk.CTkLabel(results, text="Fetched data", font=("Segoe UI", 13, "bold")).pack(
            anchor="w", padx=12, pady=(8, 4)
        )
        left = ctk.CTkFrame(results, fg_color="transparent")
        left.pack(fill="x", padx=12, pady=(0, 14))
        self.result_state = self._result_row(left, "Race state")
        self.result_guess = self._result_row(left, "Locked guess")
        self.result_confidence = self._result_row(left, "Confidence")
        self.result_winner = self._result_row(left, "Winner (OCR)")
        self.result_phase = self._result_row(left, "Game phase")
        self.result_session = self._result_row(left, "Session")

        self.status = ctk.CTkLabel(
            self, text="", font=("Consolas", 13), justify="left", anchor="w", wraplength=860
        )
        self.status.pack(fill="x", padx=12, pady=(0, 6))

        self.log = ctk.CTkTextbox(self, height=100)
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log.insert(
            "end",
            "Reads winner row (green) + handicap cards + the 3 move cards.\n"
            "Fetched values appear in the panel under the screenshot.\n"
            "Saved live images are clean unless draw_overlays=true.\n\n",
        )

        # add="+" keeps CustomTkinter's own <Configure> handler intact
        self.bind("<Configure>", self._on_window_configure, add="+")

        if self.paths:
            self.show()

    def _on_window_configure(self, event) -> None:
        if event.widget is not self:
            return
        wrap = max(360, event.width - 48)
        self.status.configure(wraplength=wrap)
        for label in self._result_value_labels:
            label.configure(wraplength=max(420, event.width - 180))

    def _refresh_guess_stats(self) -> None:
        stats = self.store.pre_race_guess_accuracy()
        if stats.total == 0:
            self.guess_stats.configure(
                text="Guess accuracy: no scored games yet (need winner + 2 draw rounds)",
                text_color="#888888",
            )
            return
        self.guess_stats.configure(
            text=(
                f"Guess accuracy: {stats.correct}/{stats.total} "
                f"({stats.percent:.0f}%) — locked guess uses 2–3 draw rounds (never winner OCR)"
            ),
            text_color="#58a6ff" if stats.percent and stats.percent >= 50 else "#ff9f43",
        )

    def _result_row(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            row,
            text=f"{title}:",
            width=110,
            anchor="nw",
            font=("Segoe UI", 13),
        ).pack(side="left", anchor="n")
        value = ctk.CTkLabel(
            row,
            text="—",
            anchor="nw",
            justify="left",
            wraplength=760,
            font=("Consolas", 14),
        )
        value.pack(side="left", fill="x", expand=True, padx=(8, 0), anchor="n")
        self._result_value_labels.append(value)
        return value

    def _set_results(
        self,
        result: ExtractionResult,
        table_cards=None,
        drawn_cards: tuple[str, ...] = (),
        locked_guess: str | None = None,
        locked_guess_draws: tuple[str, ...] = (),
        locked_guess_rounds: int = 0,
    ) -> None:
        winner = result.winner_suit.value.title() if result.winner_suit else "none yet"
        state = {
            "FINISHED": "Race finished (winner highlighted)",
            "BETTING": "In progress / no winner yet",
            "UNKNOWN": "Could not read table",
            "IN_PROGRESS": "In progress",
        }.get(result.race_state.value, result.race_state.value)
        self.result_state.configure(text=state)
        if locked_guess:
            rounds_note = f"after {locked_guess_rounds} rounds"
            if result.winner_suit and suits_match(locked_guess, result.winner_suit.value):
                guess_text = f"{locked_guess.title()} ({rounds_note}) — matches winner"
            elif result.winner_suit:
                guess_text = f"{locked_guess.title()} ({rounds_note}) — differs from winner"
            else:
                guess_text = f"{locked_guess.title()} ({rounds_note})"
            self.result_guess.configure(text=guess_text)
        else:
            self.result_guess.configure(text="not locked yet (need 2 draw rounds)")
        guess_draws = locked_guess_draws if locked_guess_draws else drawn_cards
        if result.has_handicap_cards() and guess_draws:
            confidence = evaluate_confidence(
                tuple(result.handicap_cards),
                guess_draws,
                pick=locked_guess,
                simulations=1000,
            )
            self.result_confidence.configure(text=format_confidence_text(confidence))
        else:
            self.result_confidence.configure(text="—")
        self.result_winner.configure(text=winner)
        phase = result.game_phase()
        phase_text = {
            "START": "Start — no handicap cards yet",
            "DEALT": "Start — handicap dealt, no draws yet",
            "IN_PLAY": "In between — handicap + draw cards, no results",
            "FINISHED": "End — winner / results showing",
        }.get(phase.value, phase.value)
        self.result_phase.configure(text=phase_text)
        self.result_session.configure(text=self.last_session_text)
        self._render_remaining_values(
            result,
            drawn_cards,
            locked_guess=locked_guess,
            locked_guess_draws=locked_guess_draws,
            locked_guess_rounds=locked_guess_rounds,
        )
        self._render_card_table(result, table_cards)

    def _render_remaining_values(
        self,
        result: ExtractionResult,
        drawn_cards: tuple[str, ...] = (),
        locked_guess: str | None = None,
        locked_guess_draws: tuple[str, ...] = (),
        locked_guess_rounds: int = 0,
    ) -> None:
        if not result.has_handicap_cards():
            for label in self.remaining_rows.values():
                label.configure(text="—", text_color=("gray10", "gray90"))
            self.remaining_favourite.configure(text="Handicap not visible yet.")
            return

        guess_draws = locked_guess_draws if locked_guess_draws else drawn_cards
        snap = race_snapshot(result.handicap_cards, guess_draws)
        favourite = locked_guess if locked_guess else (snap.guess if snap.guess_ready else None)
        preview = snap.preview
        rounds_label = locked_guess_rounds or snap.draw_rounds_used
        for suit_name, label in self.remaining_rows.items():
            deck = snap.deck_remaining.get(suit_name)
            if deck is None:
                label.configure(text="?", text_color="#888888")
                continue
            deck_p = snap.deck_pct.get(suit_name)
            track_p = snap.track_pct.get(suit_name)
            expected_p = snap.expected_pct.get(suit_name)
            combo_p = snap.combo_pct.get(suit_name)
            combined = snap.combined_score.get(suit_name)
            is_best = suit_name == favourite or (
                favourite is None and snap.draw_rounds_used == 0 and suit_name == preview
            )
            is_preview = favourite is None and suit_name == preview and snap.draw_rounds_used > 0
            if snap.draw_rounds_used == 0:
                text = f"deck {deck_p * 100:.0f}% · score {combined * 100:.0f}%"
            elif favourite:
                text = (
                    f"deck {deck_p * 100:.0f}% · track {track_p * 100:.0f}% · "
                    f"finish {expected_p * 100:.0f}% · combo {combo_p * 100:.0f}% · "
                    f"score {combined * 100:.0f}%"
                )
            else:
                text = (
                    f"deck {deck_p * 100:.0f}% · track {track_p * 100:.0f}% · "
                    f"finish {expected_p * 100:.0f}% · score {combined * 100:.0f}%"
                )
            if is_best and favourite:
                color = SUIT_STYLES[suit_name]["color"]
            elif is_preview:
                color = "#aaaaaa"
            else:
                color = ("gray10", "gray90")
            label.configure(text=text, text_color=color)
        if favourite:
            if snap.layer4_weights:
                tw, fw, cw, sw = (int(w * 100) for w in snap.layer4_weights)
                self.remaining_favourite.configure(
                    text=(
                        f"Locked guess: {favourite} after {rounds_label} rounds "
                        f"({tw}% track + {fw}% future + {cw}% combo + {sw}% pool) — "
                        f"independent of winner row"
                    ),
                    text_color=SUIT_STYLES[favourite]["color"],
                )
            else:
                dw = int(snap.deck_weight * 100)
                tw = int(snap.track_weight * 100)
                self.remaining_favourite.configure(
                    text=f"Best chance: {favourite} ({dw}% future deck + {tw}% track)",
                    text_color=SUIT_STYLES[favourite]["color"],
                )
        elif snap.draw_rounds_used == 1 and preview:
            self.remaining_favourite.configure(
                text=(
                    f"Round 1/2 — preview leader {preview} "
                    f"(50% expected finish + 50% track). Need round 2 to lock guess."
                ),
                text_color="#888888",
            )
        elif snap.draw_rounds_used == 0 and preview:
            self.remaining_favourite.configure(
                text=f"Handicap preview: {preview} leads on deck (100% deck). Waiting for draw round 1.",
                text_color="#888888",
            )
        elif snap.guess_ready is False and snap.draw_rounds_used > 0:
            need = 2 - snap.draw_rounds_used
            self.remaining_favourite.configure(
                text=f"Round {snap.draw_rounds_used}/2 — need {need} more draw round(s) before guessing",
                text_color="#888888",
            )
        else:
            self.remaining_favourite.configure(
                text="Could not read all handicap/draw cards.",
                text_color="#888888",
            )

    def _render_card_table(self, result: ExtractionResult, table_cards=None) -> None:
        for frame in self.card_row_frames.values():
            for child in frame.winfo_children():
                child.destroy()

        rows = table_cards if table_cards else result.combined_suit_cards()
        for suit_name, cards in rows:
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

    def open_history(self) -> None:
        from game_analyzer.history import HistoryWindow

        if self.history_win is not None and self.history_win.winfo_exists():
            self.history_win.reload()
            self.history_win.lift()
            self.history_win.focus()
            return
        self.history_win = HistoryWindow(self, store=self.store)
        self.history_win.focus()
        self._refresh_guess_stats()

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
        self.looping = True
        mode = str(region.get("mode", "screen"))
        if mode.lower() in {"brave_cdp", "brave", "cdp"}:
            hint = (
                f"Brave CDP mode: first look in {wait:.0f}s, then one shot at card-reveal "
                f"(+{region.get('cards_appear_after', 10):.0f}s) and every "
                f"{region.get('round_seconds', 32):.0f}s round."
            )
        else:
            hint = (
                f"Screen mode: click Brave so the game is visible. First look in {wait:.0f}s, "
                f"then on the 10s / 32s round clock."
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

        path, frame, _result, decision = capture_once(self.config_data)
        if decision.recording:
            gid = decision.game_id or decision.session_id
            self.last_session_text = f"{gid}  #{decision.seq}  next {decision.next_wait_seconds:.0f}s"
        else:
            self.last_session_text = (
                f"waiting for next game start  (id {decision.game_id or '?'})"
            )
        if frame is not None:
            self.last_table_cards = decision.table_cards
            rel = f"{path.parent.name}/{path.name}" if path else decision.reason
            self.show_frame(
                frame,
                rel,
                table_cards=decision.table_cards,
                drawn_cards=decision.drawn_cards,
                locked_guess=decision.locked_guess,
                locked_guess_draws=decision.locked_guess_draws,
                locked_guess_rounds=decision.locked_guess_rounds,
            )
        else:
            self.result_session.configure(text=self.last_session_text)
        self._refresh_guess_stats()
        self.after_id = self.after(int(decision.next_wait_seconds * 1000), self._loop_tick)

    def show(self) -> None:
        path = self.paths[self.index]
        frame = read_image(path)
        self.show_frame(frame, f"{self.index + 1}/{len(self.paths)}  {path.name}")

    def show_frame(
        self,
        frame,
        label: str,
        table_cards=None,
        drawn_cards: tuple[str, ...] = (),
        locked_guess: str | None = None,
        locked_guess_draws: tuple[str, ...] = (),
        locked_guess_rounds: int = 0,
    ) -> None:
        result = extract_real(frame, self.config_data)
        if not drawn_cards and result.draw_cards:
            drawn_cards = tuple(result.draw_cards)
        rgb = frame[:, :, ::-1]
        if self.config_data.get("draw_overlays", False):
            shown = draw_table_overlay(rgb, self.config_data, result)
        else:
            shown = rgb
        image = Image.fromarray(shown).resize((560, 300))
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=(560, 300))
        self.preview.configure(image=photo)
        self.preview.image = photo

        self._set_results(
            result,
            table_cards,
            drawn_cards,
            locked_guess=locked_guess,
            locked_guess_draws=locked_guess_draws,
            locked_guess_rounds=locked_guess_rounds,
        )

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
