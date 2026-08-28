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

  function apply(data) {
    const ready = !!(data && data.ready && data.game_id);
    showLive(ready);
    setStats(data && data.stats);
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
