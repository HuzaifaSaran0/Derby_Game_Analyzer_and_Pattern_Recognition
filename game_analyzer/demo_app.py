from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.config import load_config
from game_analyzer.models import ExtractionResult, Suit
from game_analyzer.race_values import race_snapshot, suits_match
from game_analyzer.store import GameStore
from game_analyzer.vision import draw_table_overlay, extract_real

SUIT_STYLES = {
    "Spades": {"symbol": "♠", "color": "#31c96b"},
    "Hearts": {"symbol": "♥", "color": "#ff5a67"},
    "Clubs": {"symbol": "♣", "color": "#58a6ff"},
    "Diamonds": {"symbol": "♦", "color": "#f2c94c"},
}

# UI palette
UI_BG = "#0f1117"
UI_PANEL = "#181b22"
UI_PANEL_ALT = "#1f2430"
UI_BORDER = "#2d3340"
UI_TEXT = "#e6edf3"
UI_MUTED = "#8b949e"
UI_ACCENT = "#58a6ff"
UI_SUCCESS = "#3fb950"
UI_WARN = "#d4a72c"
UI_FONT = ("Segoe UI", 12)
UI_FONT_SM = ("Segoe UI", 11)
UI_FONT_MONO = ("Consolas", 11)
UI_FONT_TITLE = ("Segoe UI", 12, "bold")
UI_FONT_HEADING = ("Segoe UI", 13, "bold")


class DemoApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Game Analyzer")
        self.geometry("900x700")
        self.minsize(800, 560)
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=UI_BG)

        self.config_data = load_config()
        root = Path(__file__).resolve().parent.parent
        self.store = GameStore(root=root)

        self.looping = False
        self.after_id = None
        self.last_session_text = "offline screenshot"
        self.last_table_cards = None
        self._result_value_labels: list[ctk.CTkLabel] = []
        self._preview_rgb = None
        self._window_width = 900

        toolbar = ctk.CTkFrame(self, fg_color=UI_PANEL, corner_radius=8, border_width=1, border_color=UI_BORDER)
        toolbar.pack(fill="x", padx=12, pady=(10, 6))
        nav = ctk.CTkFrame(toolbar, fg_color="transparent")
        nav.pack(fill="x", padx=10, pady=8)
        btn_style = {"height": 32, "font": UI_FONT, "corner_radius": 6}
        ctk.CTkButton(nav, text="Start capture", width=120, command=self.start_loop, **btn_style).pack(
            side="left", padx=(0, 6)
        )
        ctk.CTkButton(nav, text="Stop", width=72, command=self.stop_loop, fg_color="#5a3030", hover_color="#7a4040", **btn_style).pack(
            side="left", padx=(0, 6)
        )
        self.history_win = None
        self.similar_win = None
        ctk.CTkButton(nav, text="History", width=88, command=self.open_history, **btn_style).pack(side="right")
        ctk.CTkButton(nav, text="Similar", width=88, command=self.open_similar, **btn_style).pack(
            side="right", padx=(0, 6)
        )
        self.file_label = ctk.CTkLabel(
            nav,
            text="Start capture to begin",
            font=UI_FONT_MONO,
            text_color=UI_MUTED,
            anchor="w",
        )
        self.file_label.pack(side="left", fill="x", expand=True, padx=(12, 12))

        self.header = ctk.CTkFrame(self, fg_color="transparent")
        self.header.pack(fill="x", padx=12, pady=(0, 6))

        self.guess_stats = ctk.CTkLabel(
            self.header,
            text="",
            font=UI_FONT,
            anchor="w",
            justify="left",
            text_color=UI_MUTED,
        )
        self.guess_stats.pack(fill="x", pady=(0, 2))
        self.confidence_stats = ctk.CTkLabel(
            self.header,
            text="Late-round similarity  ·  computing…",
            font=UI_FONT_SM,
            anchor="w",
            justify="left",
            text_color=UI_MUTED,
        )
        self.confidence_stats.pack(fill="x", pady=(0, 4))
        self._similarity_stats_job = None
        self._refresh_guess_stats()
        self._schedule_similarity_stats()

        self.confidence_strip = ctk.CTkLabel(
            self.header,
            text="  —",
            font=UI_FONT_TITLE,
            text_color=UI_MUTED,
            fg_color=UI_PANEL,
            corner_radius=8,
            anchor="w",
            justify="left",
            wraplength=860,
            height=32,
        )
        self.confidence_strip.pack(fill="x", pady=(0, 4))
        self._twin_notified: set[str] = set()
        self._twin_toast_job = None

        self.twin_toast = ctk.CTkLabel(
            self.header,
            text="",
            font=UI_FONT_SM,
            text_color=UI_ACCENT,
            fg_color=UI_PANEL_ALT,
            corner_radius=8,
            anchor="w",
            justify="left",
            wraplength=860,
        )
        self._twin_toast_visible = False

        self.main_scroll = ctk.CTkScrollableFrame(
            self,
            fg_color="transparent",
            scrollbar_button_color=UI_PANEL_ALT,
            scrollbar_button_hover_color=UI_BORDER,
        )
        self.main_scroll.pack(fill="both", expand=True, padx=12, pady=(0, 6))

        self._workspace_live = False
        self.idle_panel = ctk.CTkFrame(
            self.main_scroll,
            fg_color=UI_PANEL,
            corner_radius=12,
            border_width=1,
            border_color=UI_BORDER,
            height=420,
        )
        self.idle_panel.pack(fill="both", expand=True, pady=(4, 8))
        self.idle_panel.pack_propagate(False)
        idle_inner = ctk.CTkFrame(self.idle_panel, fg_color="transparent")
        idle_inner.place(relx=0.5, rely=0.48, anchor="center")
        ctk.CTkLabel(
            idle_inner,
            text="Game Analyzer",
            font=("Segoe UI", 28, "bold"),
            text_color=UI_TEXT,
        ).pack()
        ctk.CTkLabel(
            idle_inner,
            text="Press  Start capture  to start the system",
            font=("Segoe UI", 16),
            text_color=UI_ACCENT,
        ).pack(pady=(14, 6))
        ctk.CTkLabel(
            idle_inner,
            text=(
                "Live workspace stays clear until you begin —\n"
                "preview, win chance, card table, and session data appear after the first capture."
            ),
            font=UI_FONT,
            text_color=UI_MUTED,
            justify="center",
        ).pack(pady=(4, 0))
        ctk.CTkLabel(
            idle_inner,
            text="History and Similar are available anytime from the toolbar.",
            font=UI_FONT_SM,
            text_color=UI_MUTED,
        ).pack(pady=(18, 0))

        self.live_wrap = ctk.CTkFrame(self.main_scroll, fg_color="transparent")

        top = ctk.CTkFrame(self.live_wrap, fg_color="transparent")
        top.pack(fill="x", pady=(0, 4))
        top.grid_columnconfigure(0, weight=0)
        top.grid_columnconfigure(1, weight=1)

        left_col = ctk.CTkFrame(top, fg_color="transparent")
        left_col.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(0, 12))

        self.preview_frame = ctk.CTkFrame(
            left_col,
            fg_color=UI_PANEL,
            corner_radius=8,
            border_width=1,
            border_color=UI_BORDER,
        )
        self.preview_frame.grid(row=0, column=0, sticky="nw")
        self.preview = ctk.CTkLabel(
            self.preview_frame,
            text="Waiting for first capture…",
            font=UI_FONT,
            text_color=UI_MUTED,
            fg_color=UI_PANEL_ALT,
            corner_radius=6,
        )
        self.preview.pack(padx=4, pady=4)

        self.results_frame = ctk.CTkFrame(
            left_col,
            fg_color=UI_PANEL,
            corner_radius=8,
            border_width=1,
            border_color=UI_BORDER,
        )
        self.results_frame.grid(row=1, column=0, sticky="nw", pady=(8, 0))
        self.results_frame.grid_propagate(False)
        ctk.CTkLabel(
            self.results_frame,
            text="Session data",
            font=UI_FONT_HEADING,
            text_color=UI_TEXT,
        ).pack(anchor="w", padx=12, pady=(10, 6))
        fetched_rows = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        fetched_rows.pack(fill="x", padx=12, pady=(0, 10))
        self.result_state = self._result_row(fetched_rows, "Race state")
        self.result_guess = self._result_row(fetched_rows, "Guess")
        self.result_confidence = self._result_row(fetched_rows, "Alerts")
        self.result_winner = self._result_row(fetched_rows, "Winner (OCR)")
        self.result_phase = self._result_row(fetched_rows, "Game phase")
        self.result_session = self._result_row(fetched_rows, "Session")

        right_col = ctk.CTkFrame(top, fg_color="transparent")
        right_col.grid(row=0, column=1, rowspan=2, sticky="nsew")
        top.grid_columnconfigure(1, weight=1, minsize=320)

        remaining_panel = ctk.CTkFrame(
            right_col,
            fg_color=UI_PANEL,
            corner_radius=8,
            border_width=1,
            border_color=UI_BORDER,
        )
        remaining_panel.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(
            remaining_panel,
            text="Win chance",
            font=UI_FONT_HEADING,
            text_color=UI_TEXT,
        ).pack(anchor="w", padx=12, pady=(10, 2))
        ctk.CTkLabel(
            remaining_panel,
            text="Expected finish + track blend",
            font=UI_FONT_SM,
            text_color=UI_MUTED,
        ).pack(anchor="w", padx=12, pady=(0, 6))
        self.remaining_rows: dict[str, ctk.CTkLabel] = {}
        self.remaining_panel = remaining_panel
        for suit_name in ["Spades", "Hearts", "Clubs", "Diamonds"]:
            style = SUIT_STYLES[suit_name]
            row = ctk.CTkFrame(remaining_panel, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=3)
            ctk.CTkLabel(
                row,
                text=f"{style['symbol']} {suit_name}",
                text_color=style["color"],
                font=("Segoe UI", 13, "bold"),
                anchor="w",
            ).pack(anchor="w")
            value = ctk.CTkLabel(
                row,
                text="—",
                font=UI_FONT_MONO,
                anchor="nw",
                justify="left",
                wraplength=340,
                text_color=UI_TEXT,
            )
            value.pack(fill="x", anchor="w", pady=(2, 0))
            self.remaining_rows[suit_name] = value
        self.remaining_favourite = ctk.CTkLabel(
            remaining_panel,
            text="",
            font=UI_FONT_SM,
            text_color=UI_MUTED,
            wraplength=300,
            justify="left",
        )
        self.remaining_favourite.pack(anchor="w", padx=12, pady=(6, 10))

        table_panel = ctk.CTkFrame(
            right_col,
            fg_color=UI_PANEL,
            corner_radius=8,
            border_width=1,
            border_color=UI_BORDER,
        )
        table_panel.pack(fill="x")
        ctk.CTkLabel(
            table_panel,
            text="Card table",
            font=UI_FONT_HEADING,
            text_color=UI_TEXT,
        ).pack(anchor="w", padx=12, pady=(10, 6))
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

        self.status = ctk.CTkLabel(
            self.main_scroll,
            text="Ready — press Start capture when the game window is visible.",
            font=UI_FONT_MONO,
            justify="left",
            anchor="w",
            wraplength=860,
            text_color=UI_MUTED,
        )
        self.status.pack(fill="x", pady=(8, 4))

        # add="+" keeps CustomTkinter's own <Configure> handler intact
        self.bind("<Configure>", self._on_window_configure, add="+")

        self._refresh_layout_widths()
        self._apply_preview_placeholder()
    def _left_column_width(self, window_width: int) -> int:
        """Left column ~55% of window, leaving room for the right-hand panels."""
        target = int(window_width * 0.55)
        max_left = max(280, window_width - 340)
        return max(280, min(target, max_left))

    def _preview_size(self, window_width: int) -> tuple[int, int]:
        width = self._left_column_width(window_width)
        height = max(140, int(width * 278 / 520))
        return width, height

    def _right_column_width(self, window_width: int) -> int:
        return max(300, window_width - self._left_column_width(window_width) - 56)

    def _refresh_layout_widths(self) -> None:
        left_w = self._left_column_width(self._window_width)
        right_w = self._right_column_width(self._window_width)
        fetched_wrap = max(160, left_w - 120)
        stats_wrap = max(260, right_w - 24)
        self.results_frame.configure(width=left_w)
        for label in self._result_value_labels:
            label.configure(wraplength=fetched_wrap)
        for label in self.remaining_rows.values():
            label.configure(wraplength=stats_wrap)
        self.remaining_favourite.configure(wraplength=stats_wrap)

    def _apply_preview_placeholder(self) -> None:
        if self._preview_rgb is not None:
            return
        width, height = self._preview_size(self._window_width)
        self.preview.configure(
            text="Waiting for first capture…",
            image=None,
            width=width,
            height=height,
            text_color=UI_MUTED,
            fg_color=UI_PANEL_ALT,
        )
        self.preview.image = None

    def _show_live_workspace(self) -> None:
        if self._workspace_live:
            return
        self._workspace_live = True
        self.idle_panel.pack_forget()
        self.live_wrap.pack(fill="both", expand=True, before=self.status)
        self._apply_preview_placeholder()
        self._refresh_layout_widths()

    def _refresh_preview_image(self) -> None:
        if self._preview_rgb is None:
            self._apply_preview_placeholder()
            return
        width, height = self._preview_size(self._window_width)
        image = Image.fromarray(self._preview_rgb).resize((width, height))
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=(width, height))
        self.preview.configure(image=photo, text="", fg_color="transparent")
        self.preview.image = photo

    def _on_window_configure(self, event) -> None:
        if event.widget is not self:
            return
        self._window_width = event.width
        wrap = max(360, event.width - 48)
        self.status.configure(wraplength=wrap)
        self.confidence_strip.configure(wraplength=wrap)
        self.twin_toast.configure(wraplength=wrap)
        if not self._workspace_live:
            # Keep the idle hero filling most of the window.
            self.idle_panel.configure(height=max(320, event.height - 220))
        self._refresh_layout_widths()
        self._refresh_preview_image()

    def _refresh_guess_stats(self) -> None:
        finished = len(self.store.list_game_ids(finished_only=True))
        self.guess_stats.configure(
            text=f"Finished games  {finished}" if finished else "Finished games  —"
        )

    def _schedule_similarity_stats(self) -> None:
        if self._similarity_stats_job is not None:
            try:
                self.after_cancel(self._similarity_stats_job)
            except Exception:
                pass
        self._similarity_stats_job = self.after(200, self._refresh_similarity_stats)

    def _refresh_similarity_stats(self) -> None:
        self._similarity_stats_job = None
        from game_analyzer.similarity import friendly_late_round_summary

        stats = self.store.late_round_stats()
        r3 = next((s for s in stats if s.round_n == 3), None)
        if r3 and r3.twin_sets:
            label = friendly_late_round_summary([s for s in stats if s.round_n == 3])
        else:
            label = "Draw similarity · Round 3: no matches yet"
        self.confidence_stats.configure(
            text=label,
            text_color=UI_ACCENT,
        )

    def _result_row(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkLabel:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=2)
        ctk.CTkLabel(
            row,
            text=title,
            width=100,
            anchor="nw",
            font=UI_FONT_SM,
            text_color=UI_MUTED,
        ).pack(side="left", anchor="n")
        value = ctk.CTkLabel(
            row,
            text="—",
            anchor="nw",
            justify="left",
            wraplength=760,
            font=UI_FONT_MONO,
            text_color=UI_TEXT,
        )
        value.pack(side="left", fill="x", expand=True, padx=(8, 0), anchor="n")
        self._result_value_labels.append(value)
        return value

    def _set_results(
        self,
        result: ExtractionResult,
        table_cards=None,
        drawn_cards: tuple[str, ...] = (),
        **_ignored,
    ) -> None:
        winner = result.winner_suit.value.title() if result.winner_suit else "none yet"
        state = {
            "FINISHED": "Race finished (winner highlighted)",
            "BETTING": "In progress / no winner yet",
            "UNKNOWN": "Could not read table",
            "IN_PROGRESS": "In progress",
        }.get(result.race_state.value, result.race_state.value)
        self.result_state.configure(text=state)
        self.result_guess.configure(text="— (similarity alerts only)")
        self.result_confidence.configure(text="—")
        self.confidence_strip.configure(
            text="  Similarity  ·  late-round twin alerts only",
            text_color=UI_ACCENT,
            fg_color=UI_PANEL,
        )
        self._maybe_twin_notify(
            handicap_cards=tuple(result.handicap_cards) if result.has_handicap_cards() else (),
            draw_cards=tuple(drawn_cards) if drawn_cards else tuple(result.draw_cards or ()),
            game_id=None,
        )
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
        self._render_remaining_values(result, drawn_cards)
        self._render_card_table(result, table_cards)

    def _render_remaining_values(
        self,
        result: ExtractionResult,
        drawn_cards: tuple[str, ...] = (),
    ) -> None:
        if not result.has_handicap_cards():
            for label in self.remaining_rows.values():
                label.configure(text="—", text_color=("gray10", "gray90"))
            self.remaining_favourite.configure(text="Handicap not visible yet.")
            return

        guess_draws = drawn_cards
        snap = race_snapshot(result.handicap_cards, guess_draws)
        favourite = snap.guess if snap.guess_ready else None
        preview = snap.preview
        rounds_label = snap.draw_rounds_used

        def pct(value: float | None) -> str:
            return f"{value * 100:.0f}%" if value is not None else "?"

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
                text = f"score {pct(combined)}  ·  deck {pct(deck_p)}"
            elif favourite:
                text = (
                    f"score {pct(combined)}  ·  "
                    f"deck {pct(deck_p)}  ·  track {pct(track_p)}  ·  "
                    f"finish {pct(expected_p)}  ·  combo {pct(combo_p)}"
                )
            else:
                text = (
                    f"score {pct(combined)}  ·  "
                    f"deck {pct(deck_p)}  ·  track {pct(track_p)}  ·  "
                    f"finish {pct(expected_p)}"
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
                        f"Track leader: {favourite} after {rounds_label} rounds "
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

    def open_similar(self) -> None:
        from game_analyzer.similar_ui import SimilarWindow

        if self.similar_win is not None and self.similar_win.winfo_exists():
            self.similar_win.reload()
            self.similar_win.lift()
            self.similar_win.focus()
            return
        self.similar_win = SimilarWindow(self, store=self.store)
        self.similar_win.focus()

    def _set_twin_toast(self, *, visible: bool, text: str = "") -> None:
        if self._twin_toast_job is not None:
            try:
                self.after_cancel(self._twin_toast_job)
            except Exception:
                pass
            self._twin_toast_job = None
        if visible and text:
            self.twin_toast.configure(text=f"  Twin  ·  {text}")
            if not self._twin_toast_visible:
                # Below confidence strip; never replaces the bet alert banner.
                self.twin_toast.pack(fill="x", pady=(0, 4), after=self.confidence_strip)
                self._twin_toast_visible = True
            self._twin_toast_job = self.after(12000, lambda: self._set_twin_toast(visible=False))
        elif self._twin_toast_visible:
            self.twin_toast.pack_forget()
            self._twin_toast_visible = False

    def _maybe_twin_notify(
        self,
        *,
        handicap_cards,
        draw_cards: tuple[str, ...],
        game_id: str | None,
    ) -> None:
        if not handicap_cards:
            return
        sim_cfg = self.config_data.get("similarity") or {}
        if sim_cfg.get("notify", True) is False:
            return
        signal = self.store.live_twin_signal(
            handicap_cards,
            draw_cards,
            exclude_game_id=game_id,
        )
        if signal is None:
            return
        dedupe = (
            f"{game_id or getattr(self, '_twin_game_id', 'live')}:"
            f"{signal.stage.value}:{signal.suggested_winner}"
        )
        if dedupe in self._twin_notified:
            return
        self._twin_notified.add(dedupe)

        from datetime import datetime, timezone

        from game_analyzer.notify import DEFAULT_TWIN_LOG, append_twin_log, send_desktop_notification

        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        append_twin_log(DEFAULT_TWIN_LOG, f"{stamp}  {signal.message}")
        send_desktop_notification(
            f"Twin winner: {signal.suggested_winner}",
            signal.message,
            urgency="critical",
        )
        self._set_twin_toast(visible=True, text=signal.message)


    def start_loop(self) -> None:
        if self.looping:
            return
        self._show_live_workspace()
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
        self.file_label.configure(text="Capture starting…")
        self.after_id = self.after(int(wait * 1000), self._loop_tick)

    def stop_loop(self) -> None:
        self.looping = False
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        self.status.configure(text="Capture stopped.")
        if not self._workspace_live:
            self.file_label.configure(text="Start capture to begin")
        else:
            self.file_label.configure(text="Capture stopped — press Start capture to resume")

    def _loop_tick(self) -> None:
        if not self.looping:
            return
        from game_analyzer.live import capture_once

        path, frame, _result, decision = capture_once(self.config_data)
        gid = decision.game_id or decision.session_id
        if gid and getattr(self, "_twin_game_id", None) != gid:
            self._twin_game_id = gid
            self._twin_notified.clear()
            self._set_twin_toast(visible=False)
        if decision.recording:
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
            )
        else:
            self.result_session.configure(text=self.last_session_text)
        self._refresh_guess_stats()
        self.after_id = self.after(int(decision.next_wait_seconds * 1000), self._loop_tick)

    def show_frame(
        self,
        frame,
        label: str,
        table_cards=None,
        drawn_cards: tuple[str, ...] = (),
    ) -> None:
        self._show_live_workspace()
        result = extract_real(frame, self.config_data)
        if not drawn_cards and result.draw_cards:
            drawn_cards = tuple(result.draw_cards)
        rgb = frame[:, :, ::-1]
        if self.config_data.get("draw_overlays", False):
            shown = draw_table_overlay(rgb, self.config_data, result)
        else:
            shown = rgb
        self._preview_rgb = shown
        self._refresh_preview_image()

        self._set_results(
            result,
            table_cards,
            drawn_cards,
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
