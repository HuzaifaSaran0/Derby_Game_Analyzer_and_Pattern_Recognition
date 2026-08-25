"""Similar games page: card tables by default; screenshots on demand."""

from __future__ import annotations

from pathlib import Path

import customtkinter as ctk
from PIL import Image

from game_analyzer.race_values import SUIT_NAMES
from game_analyzer.similarity import GameFingerprint, SimilarityCluster, format_cluster_headline
from game_analyzer.store import GameStore

THUMB = (220, 132)
MODAL_MAX = (960, 640)
RENDER_BATCH = 4
UI_PANEL = "#181b22"
UI_PANEL_ALT = "#1f2430"
UI_BORDER = "#2d3340"
UI_MUTED = "#8b949e"
UI_TEXT = "#e6edf3"
UI_ACCENT = "#58a6ff"
UI_SUCCESS = "#3fb950"
UI_WARN = "#d4a72c"

SUIT_STYLES = {
    "Spades": {"symbol": "♠", "color": "#31c96b"},
    "Hearts": {"symbol": "♥", "color": "#ff5a67"},
    "Clubs": {"symbol": "♣", "color": "#58a6ff"},
    "Diamonds": {"symbol": "♦", "color": "#f2c94c"},
}


def _format_card_block(fp: GameFingerprint) -> str:
    winner = fp.winner_suit.title() if fp.winner_suit else "—"
    lines = [f"#{fp.game_id}  →  {winner}", "", "Handicap"]
    for idx, suit in enumerate(SUIT_NAMES):
        style = SUIT_STYLES[suit]
        cards = fp.handicap_cards[idx] if idx < len(fp.handicap_cards) else ()
        lines.append(f"  {style['symbol']} {suit:<9}  {' '.join(cards) if cards else '—'}")
    draws = fp.draw_cards
    lines.append("")
    lines.append(f"Draws ({len(draws)} cards · {len(draws) // 3} rounds)")
    if not draws:
        lines.append("  (none stored)")
        return "\n".join(lines)
    by_suit: dict[str, list[str]] = {s: [] for s in SUIT_NAMES}
    for card in draws:
        if len(card) < 2:
            continue
        letter = card[-1].upper()
        for suit in SUIT_NAMES:
            if suit[0].upper() == letter:
                by_suit[suit].append(card)
                break
    for suit in SUIT_NAMES:
        style = SUIT_STYLES[suit]
        cards = by_suit[suit]
        lines.append(f"  {style['symbol']} {suit:<9}  {' '.join(cards) if cards else '—'}")
    return "\n".join(lines)


class SimilarWindow(ctk.CTkToplevel):
    """Browse fingerprint twins: card tables first; screenshots only when requested."""

    def __init__(self, master, store: GameStore | None = None) -> None:
        super().__init__(master)
        self.title("Game Analyzer — Similar")
        self.geometry("1100x780")
        self.store = store or GameStore()
        self._photos: list = []
        self._modal_photos: list = []
        self._exact_only = ctk.BooleanVar(value=False)
        self._clusters: list[SimilarityCluster] = []
        self._shot_modal = None
        self._render_job = None
        self._render_index = 0

        toolbar = ctk.CTkFrame(self, fg_color=UI_PANEL, corner_radius=8)
        toolbar.pack(fill="x", padx=12, pady=(10, 6))
        ctk.CTkButton(toolbar, text="Refresh", width=100, command=self.reload).pack(
            side="left", padx=8, pady=8
        )
        ctk.CTkCheckBox(
            toolbar,
            text="Exact only",
            variable=self._exact_only,
            command=self.reload,
        ).pack(side="left", padx=8)
        self.summary = ctk.CTkLabel(
            toolbar,
            text="Loading similar games…",
            font=("Segoe UI", 12),
            text_color=UI_MUTED,
            anchor="w",
        )
        self.summary.pack(side="left", fill="x", expand=True, padx=12)

        self.body = ctk.CTkScrollableFrame(self, label_text="Similarity clusters")
        self.body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._loading_label = ctk.CTkLabel(
            self.body,
            text="Scanning finished games…",
            text_color=UI_MUTED,
            font=("Segoe UI", 14),
        )
        self._loading_label.pack(anchor="w", padx=8, pady=16)

        # Paint the window first, then load (avoids a frozen blank open).
        self.after(30, self.reload)

    def _cancel_render(self) -> None:
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None

    def reload(self) -> None:
        self._cancel_render()
        self._photos = []
        for child in self.body.winfo_children():
            child.destroy()
        self._loading_label = ctk.CTkLabel(
            self.body,
            text="Scanning finished games…",
            text_color=UI_MUTED,
            font=("Segoe UI", 14),
        )
        self._loading_label.pack(anchor="w", padx=8, pady=16)
        self.summary.configure(text="Loading similar games…")
        self.update_idletasks()
        # Next tick so “Loading…” is visible before the scan.
        self.after(20, self._load_and_start_render)

    def _load_and_start_render(self) -> None:
        exact_only = bool(self._exact_only.get())
        corpus = self.store.similarity_corpus()
        corpus_n = len(corpus)
        self._clusters = self.store.similarity_clusters(exact_only=exact_only)
        exact_n = sum(1 for c in self._clusters if c.exact)
        near_n = sum(1 for c in self._clusters if not c.exact)
        games = {g.game_id for c in self._clusters for g in c.games}
        self.summary.configure(
            text=(
                f"scanned {corpus_n} finished · {len(self._clusters)} clusters · "
                f"{exact_n} exact · {near_n} near · {len(games)} games shown"
            )
        )
        for child in self.body.winfo_children():
            child.destroy()

        if not self._clusters:
            msg = (
                f"Scanned {corpus_n} finished games with full handicap. "
                "No exact twins yet, and no pairs at the near threshold "
                "(≥50% Jaccard / about 8 of 12 handicap cards)."
                if corpus_n
                else "No finished games with full handicap cards yet."
            )
            if exact_only and corpus_n:
                msg = (
                    f"Scanned {corpus_n} finished games — no exact twins yet. "
                    "Uncheck “Exact only” to see near matches."
                )
            ctk.CTkLabel(
                self.body,
                text=msg,
                text_color=UI_MUTED,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=8, pady=12)
            return

        if exact_n == 0 and near_n and not exact_only:
            ctk.CTkLabel(
                self.body,
                text=(
                    f"No exact twins among {corpus_n} finished games yet. "
                    "Showing closest near matches (≥8/12 handicap cards shared)."
                ),
                text_color=UI_WARN,
                wraplength=900,
                justify="left",
            ).pack(anchor="w", padx=8, pady=(8, 4))

        self._render_index = 0
        self._progress = ctk.CTkLabel(
            self.body,
            text=f"Rendering clusters 0/{len(self._clusters)}…",
            text_color=UI_MUTED,
            font=("Segoe UI", 12),
        )
        self._progress.pack(anchor="w", padx=8, pady=(4, 8))
        self._render_job = self.after(1, self._render_next_batch)

    def _render_next_batch(self) -> None:
        self._render_job = None
        if not self.winfo_exists():
            return
        total = len(self._clusters)
        end = min(self._render_index + RENDER_BATCH, total)
        for cluster in self._clusters[self._render_index : end]:
            self._render_cluster(cluster)
        self._render_index = end
        if self._render_index < total:
            if hasattr(self, "_progress") and self._progress.winfo_exists():
                self._progress.configure(
                    text=f"Rendering clusters {self._render_index}/{total}…"
                )
            self._render_job = self.after(1, self._render_next_batch)
            return
        if hasattr(self, "_progress") and self._progress.winfo_exists():
            self._progress.destroy()

    def _render_cluster(self, cluster: SimilarityCluster) -> None:
        box = ctk.CTkFrame(
            self.body,
            fg_color=UI_PANEL,
            corner_radius=8,
            border_width=1,
            border_color=UI_BORDER,
        )
        box.pack(fill="x", padx=4, pady=8)

        kind_color = UI_SUCCESS if cluster.exact else UI_WARN
        ctk.CTkLabel(
            box,
            text=format_cluster_headline(cluster),
            font=("Segoe UI", 13, "bold"),
            text_color=kind_color,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))

        winner_bits = [f"{suit}×{count}" for suit, count in cluster.winner_counts]
        winner_line = " · ".join(winner_bits) if winner_bits else "no winners stored"
        same = cluster.winners_same
        same_note = "same winners" if same else ("mixed winners" if same is False else "")
        ctk.CTkLabel(
            box,
            text=f"Winners: {winner_line}" + (f"  ({same_note})" if same_note else ""),
            font=("Consolas", 12),
            text_color=UI_TEXT if same else UI_MUTED,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 6))

        tables = ctk.CTkFrame(box, fg_color="transparent")
        tables.pack(fill="x", padx=8, pady=(0, 6))
        for i, fp in enumerate(cluster.games):
            self._render_game_table(tables, fp, col=i)

        actions = ctk.CTkFrame(box, fg_color="transparent")
        actions.pack(fill="x", padx=12, pady=(0, 4))
        shots_host = ctk.CTkFrame(box, fg_color="transparent")
        shots_host.pack(fill="x", padx=8, pady=(0, 10))

        game_ids = tuple(fp.game_id for fp in cluster.games)

        def reveal() -> None:
            btn.configure(state="disabled", text="Screenshots loaded")
            self._load_cluster_screenshots(shots_host, game_ids)

        btn = ctk.CTkButton(
            actions,
            text="Show screenshots",
            width=150,
            height=28,
            command=reveal,
        )
        btn.pack(side="left")

    def _render_game_table(self, parent, fp: GameFingerprint, *, col: int) -> None:
        cell = ctk.CTkFrame(
            parent,
            fg_color=UI_PANEL_ALT,
            corner_radius=8,
            border_width=1,
            border_color=UI_BORDER,
        )
        cell.grid(row=col // 2, column=col % 2, padx=6, pady=4, sticky="nsew")
        parent.grid_columnconfigure(col % 2, weight=1)
        ctk.CTkLabel(
            cell,
            text=_format_card_block(fp),
            font=("Consolas", 11),
            text_color=UI_TEXT,
            justify="left",
            anchor="nw",
        ).pack(fill="both", padx=10, pady=8)

    def _load_cluster_screenshots(self, host, game_ids: tuple[str, ...]) -> None:
        for child in host.winfo_children():
            child.destroy()
        row = ctk.CTkFrame(host, fg_color="transparent")
        row.pack(fill="x", pady=(4, 0))
        loaded = 0
        for i, game_id in enumerate(game_ids):
            path = self._best_screenshot_path(game_id)
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.grid(row=0, column=i, padx=6, pady=4, sticky="nw")
            ctk.CTkLabel(
                cell,
                text=f"#{game_id}",
                font=("Consolas", 11),
                text_color=UI_MUTED,
                anchor="w",
            ).pack(anchor="w")
            if path is None:
                ctk.CTkLabel(cell, text="no screenshot", text_color=UI_MUTED).pack(anchor="w")
                continue
            try:
                image = Image.open(path).convert("RGB")
                image.thumbnail(THUMB)
                photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
                self._photos.append(photo)
                btn = ctk.CTkButton(
                    cell,
                    image=photo,
                    text="",
                    width=image.size[0],
                    height=image.size[1],
                    fg_color="transparent",
                    hover_color=UI_BORDER,
                    command=lambda p=path, gid=game_id: self._open_screenshot_modal(gid, p),
                )
                btn.pack(anchor="w", pady=(2, 0))
                loaded += 1
            except OSError:
                ctk.CTkLabel(cell, text="bad image", text_color=UI_MUTED).pack(anchor="w")
        if loaded:
            ctk.CTkLabel(
                host,
                text="Click a screenshot to open a larger view.",
                font=("Segoe UI", 11),
                text_color=UI_MUTED,
                anchor="w",
            ).pack(fill="x", padx=6, pady=(2, 0))

    def _best_screenshot_path(self, game_id: str) -> Path | None:
        # Lightweight path lookup — only the last frame path, not full get_game().
        with self.store._connect(autocommit=True) as con:
            row = con.execute(
                """
                SELECT screenshot_path FROM frames
                WHERE game_id = ?
                ORDER BY seq DESC
                LIMIT 1
                """,
                (game_id,),
            ).fetchone()
        if row is None:
            return None
        raw = row["screenshot_path"]
        path = Path(raw) if Path(raw).is_absolute() else (self.store.root / raw)
        return path if path.exists() else None

    def _open_screenshot_modal(self, game_id: str, path: Path) -> None:
        if self._shot_modal is not None and self._shot_modal.winfo_exists():
            self._shot_modal.destroy()
        try:
            image = Image.open(path).convert("RGB")
        except OSError:
            return
        image.thumbnail(MODAL_MAX)
        photo = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
        self._modal_photos = [photo]

        modal = ctk.CTkToplevel(self)
        modal.title(f"Screenshot — game {game_id}")
        modal.geometry(f"{image.size[0] + 40}x{image.size[1] + 80}")
        modal.transient(self)
        modal.grab_set()
        self._shot_modal = modal

        bar = ctk.CTkFrame(modal, fg_color=UI_PANEL)
        bar.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(
            bar,
            text=f"Game #{game_id}  ·  {path.name}",
            font=("Consolas", 12),
            text_color=UI_TEXT,
            anchor="w",
        ).pack(side="left", padx=8, pady=6)
        ctk.CTkButton(bar, text="Close", width=80, command=modal.destroy).pack(
            side="right", padx=8, pady=6
        )
        ctk.CTkLabel(modal, image=photo, text="").pack(padx=12, pady=(0, 12))
        modal.bind("<Escape>", lambda _e: modal.destroy())
        modal.focus()
