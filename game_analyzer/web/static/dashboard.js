(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  const idle = document.querySelector("[data-idle-hero]");
  const grid = document.querySelector("[data-live-grid]");
  let lastSig = "";

  function setStats(stats) {
    if (!stats) return;
    const g = document.querySelector("[data-guess-stats]");
    const c = document.querySelector("[data-confidence-stats]");
    if (g) g.textContent = stats.guess.text;
    if (c) c.textContent = "Confidence accuracy  ·  " + stats.confidence_text;
  }

  function compactConfidence(conf, guess) {
    if (!conf || !conf.ready) return "— · need 2 rounds";
    const parts = [];
    if (conf.level) {
      parts.push(conf.pct != null ? conf.level + " " + conf.pct + "%" : conf.level);
    }
    const pick = conf.pick || guess;
    if (pick) parts.push(String(pick).charAt(0).toUpperCase() + String(pick).slice(1).toLowerCase());
    return parts.length ? parts.join(" · ") : "—";
  }

  function apply(data) {
    const ready = data && data.ready;
    idle.hidden = !!ready;
    grid.hidden = !ready;
    if (!ready) {
      setStats(data && data.stats);
      return;
    }

    setStats(data.stats);
    document.querySelector("[data-confidence-strip]").textContent = compactConfidence(
      data.confidence,
      data.guess
    );
    document.querySelector("[data-race-state]").textContent = data.in_progress
      ? "In progress / no winner yet"
      : "Race finished (winner highlighted)";
    document.querySelector("[data-locked-guess]").textContent = data.guess_text || "not locked yet";
    document.querySelector("[data-confidence]").textContent =
      (data.confidence && data.confidence.text) || "—";
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

    document.querySelector("[data-win-chance]").innerHTML = cards.winChance(
      data.win_chance,
      data.win_chance_note
    );
    document.querySelector("[data-card-table]").innerHTML = cards.suitTable(data.table);
  }

  live.start(async function () {
    try {
      const data = await live.get("/api/live");
      const sig = JSON.stringify({
        id: data.game_id,
        winner: data.winner,
        frames: data.frames && data.frames.length,
        table: data.table,
        ready: data.ready,
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
