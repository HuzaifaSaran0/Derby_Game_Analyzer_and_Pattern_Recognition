(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  const idle = document.querySelector("[data-idle-hero]");
  const grid = document.querySelector("[data-live-grid]");
  let lastSig = "";

  function setStats(stats) {
    const el = document.querySelector("[data-sim-stats]");
    if (!el || !stats) return;
    el.textContent = stats.late_round_text || "No matching draw history yet";
  }

  function showLive(on) {
    if (idle) {
      idle.hidden = on;
      idle.style.display = on ? "none" : "";
    }
    if (grid) {
      grid.hidden = !on;
      grid.style.display = on ? "" : "none";
    }
  }

  function suitSymbol(code, meta) {
    const key = String(code);
    const info = (meta && meta[key]) || {};
    const sym = info.symbol || key;
    const color = info.color || "";
    return (
      '<span class="winner-hint-suit"' +
      (color ? ' style="color:' + color + '"' : "") +
      ' data-suit="' +
      key +
      '">' +
      sym +
      "</span>"
    );
  }

  function renderTailSymbols(tail, meta) {
    if (!tail || !tail.length) return "";
    return tail.map(function (code) {
      return suitSymbol(code, meta);
    }).join(" ");
  }

  function renderWinnerHints(hints) {
    const panel = document.querySelector("[data-winner-hints-panel]");
    const legend = document.querySelector("[data-winner-hints-legend]");
    const lead = document.querySelector("[data-winner-hints-lead]");
    const rowsEl = document.querySelector("[data-winner-hints-rows]");
    if (!panel || !legend || !lead || !rowsEl) return;

    if (!hints) {
      panel.hidden = true;
      return;
    }

    const meta = hints.suit_meta || {};

    panel.hidden = false;
    legend.innerHTML = (hints.legend || "")
      .split(" · ")
      .map(function (part) {
        const m = part.match(/^(\d)=(.+)$/);
        if (!m) return part;
        return m[1] + "=" + suitSymbol(m[1], meta);
      })
      .join(" · ");
    lead.textContent = hints.lead_summary || "";

    if (!hints.rows || !hints.rows.length) {
      rowsEl.innerHTML = "";
      return;
    }

    rowsEl.innerHTML = hints.rows
      .map(function (row) {
        const counts = row.follow_up_counts || {};
        const chips = ["1", "2", "3", "4"]
          .map(function (code) {
            const n = counts[code] || 0;
            if (!n) return "";
            const pct = row.follow_up_percents ? row.follow_up_percents[code] : 0;
            return (
              '<span class="winner-hint-chip" data-suit="' +
              code +
              '">' +
              suitSymbol(code, meta) +
              " " +
              n +
              (pct ? " (" + pct + "%)" : "") +
              "</span>"
            );
          })
          .filter(Boolean)
          .join("");

        return (
          '<article class="winner-hint-row">' +
          '<div class="winner-hint-head">' +
          '<strong>Last ' +
          row.length +
          "</strong>" +
          '<span class="winner-hint-tail">' +
          renderTailSymbols(row.tail, meta) +
          "</span>" +
          '<span class="winner-hint-matches">' +
          row.match_count +
          " match" +
          (row.match_count === 1 ? "" : "es") +
          "</span>" +
          "</div>" +
          (chips ? '<div class="winner-hint-chips">' + chips + "</div>" : "") +
          '<p class="winner-hint-summary">' +
          (row.summary || "") +
          "</p>" +
          "</article>"
        );
      })
      .join("");
  }

  function apply(data) {
    const ready = !!(data && data.ready && data.game_id);
    showLive(ready);
    setStats(data && data.stats);
    renderWinnerHints(data && data.winner_hints);
    if (!ready) return;

    document.querySelector("[data-race-state]").textContent = data.in_progress
      ? "In progress / no winner yet"
      : "Race finished (winner highlighted)";
    document.querySelector("[data-winner]").textContent = data.winner;
    document.querySelector("[data-phase]").textContent = data.in_progress ? "IN_PLAY" : "FINISHED";
    document.querySelector("[data-game-id]").textContent = data.game_id;
    document.querySelector("[data-session]").textContent =
      "Game " + data.game_id + " · " + (data.frames ? data.frames.length : 0) + " shots";

    const preview = document.querySelector("[data-preview]");
    if (data.preview_url) {
      preview.innerHTML =
        '<img class="preview-img" src="' +
        data.preview_url +
        '" alt="Latest capture" loading="lazy" />';
    } else {
      preview.innerHTML = '<span class="muted">No preview yet</span>';
    }

    document.querySelector("[data-card-table]").innerHTML = cards.suitTable(data.table);
  }

  showLive(false);

  live.start(async function () {
    try {
      const data = await live.get("/api/live");
      const sig = JSON.stringify({
        id: data.game_id,
        winner: data.winner,
        frames: data.frames && data.frames.length,
        table: data.table,
        ready: data.ready,
        preview: data.preview_url,
        in_progress: data.in_progress,
        winner_hints: data.winner_hints,
      });
      live.stamp(true, data.ready ? "game " + data.game_id : "waiting");
      if (sig === lastSig) return;
      lastSig = sig;
      apply(data);
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
