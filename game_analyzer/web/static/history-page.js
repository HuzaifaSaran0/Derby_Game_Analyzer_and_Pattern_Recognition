(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  let gameId = document.body.getAttribute("data-start-id") || "";
  let nav = { prev_id: null, next_id: null, latest_id: null };
  let shotCount = 0;
  let shotsLoadedFor = null;
  let lastSig = "";
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  const lightboxStatus = lightbox ? lightbox.querySelector(".lightbox-status") : null;
  const showBtn = document.querySelector("[data-show-shots]");
  const grid = document.querySelector("[data-shot-grid]");
  const empty = document.querySelector("[data-shots-empty]");
  let lightboxFrames = [];
  let lightboxIndex = 0;

  function setNav(name, id) {
    const el = document.querySelector('[data-nav="' + name + '"]');
    if (!el) return;
    el.disabled = !id;
    el.classList.toggle("disabled", !id);
  }

  function setStats(stats) {
    if (!stats) return;
    const g = document.querySelector("[data-guess-stats]");
    const c = document.querySelector("[data-confidence-stats]");
    if (g) {
      const guess = stats.guess || {};
      g.textContent =
        guess.total > 0
          ? "Acc " + guess.correct + "/" + guess.total + " (" + Math.round(guess.percent) + "%)"
          : "Acc —";
    }
    if (c) {
      const raw = stats.confidence_text || "";
      c.textContent = raw
        .replace(/Confidence accuracy\s*·\s*/i, "")
        .replace(/VERY_HIGH/g, "VH")
        .replace(/HIGH/g, "H");
    }
  }

  function openLightbox(frames, index) {
    if (!lightbox || !frames.length) return;
    lightboxFrames = frames;
    lightboxIndex = index;
    lightbox.hidden = false;
    document.body.classList.add("no-scroll");
    syncLightbox();
  }

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.hidden = true;
    document.body.classList.remove("no-scroll");
  }

  function syncLightbox() {
    const frame = lightboxFrames[lightboxIndex];
    if (!frame || !lightboxImg) return;
    lightboxImg.src = frame.url;
    lightboxImg.alt = "Screenshot " + frame.seq;
    if (lightboxStatus) {
      lightboxStatus.textContent =
        lightboxIndex + 1 + " / " + lightboxFrames.length + "  #" + frame.seq + " · " + frame.phase;
    }
  }

  function resetShotsUi() {
    if (grid) grid.innerHTML = "";
    shotsLoadedFor = null;
    if (!shotCount) {
      if (empty) empty.hidden = false;
      if (showBtn) showBtn.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (showBtn) {
      showBtn.hidden = false;
      showBtn.disabled = false;
      showBtn.textContent = "See screenshots (" + shotCount + ")";
    }
  }

  function renderShots(frames) {
    if (!grid) return;
    if (!frames || !frames.length) {
      grid.innerHTML = "";
      if (empty) empty.hidden = false;
      if (showBtn) showBtn.hidden = true;
      return;
    }
    if (empty) empty.hidden = true;
    if (showBtn) {
      showBtn.hidden = false;
      showBtn.disabled = true;
      showBtn.textContent = "Screenshots loaded";
    }
    grid.innerHTML = frames
      .map(function (frame, i) {
        return (
          '<button type="button" class="shot-thumb" data-shot-index="' +
          i +
          '"><img src="' +
          frame.url +
          '" alt="#' +
          frame.seq +
          '" loading="lazy" /><span>#' +
          frame.seq +
          " · " +
          frame.phase +
          "</span></button>"
        );
      })
      .join("");
    grid.querySelectorAll("[data-shot-index]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openLightbox(frames, Number(btn.getAttribute("data-shot-index")));
      });
    });
  }

  async function loadShots() {
    if (!gameId || !showBtn) return;
    if (shotsLoadedFor === gameId) return;
    showBtn.disabled = true;
    showBtn.textContent = "Loading…";
    try {
      const data = await live.get("/api/history/" + encodeURIComponent(gameId) + "/shots");
      shotsLoadedFor = gameId;
      renderShots(data.frames || []);
    } catch (_e) {
      showBtn.disabled = false;
      showBtn.textContent = "See screenshots (" + shotCount + ")";
    }
  }

  function apply(data) {
    if (!data) return;
    gameId = data.game_id;
    nav = {
      prev_id: data.prev_id || null,
      next_id: data.next_id || null,
      latest_id: data.latest_id || null,
    };
    shotCount = data.shot_count || (data.frames && data.frames.length) || 0;
    document.querySelector("[data-game-pos]").textContent = data.index + " / " + data.total;
    document.querySelector("[data-winner]").textContent = data.winner;
    document.querySelector("[data-guess]").textContent = data.guess_text;
    document.querySelector("[data-conf-r2]").textContent = data.confidence_r2;
    document.querySelector("[data-conf-r3]").textContent = data.confidence_r3;
    document.querySelector("[data-game-meta]").textContent =
      "Started " +
      data.started_at +
      (data.finished_at ? " · Finished " + data.finished_at : "") +
      " · " +
      data.draw_note +
      " · " +
      shotCount +
      " shots";
    setStats(data.stats);
    document.querySelector("[data-card-table]").innerHTML = cards.suitTable(data.table);
    resetShotsUi();
    setNav("prev", nav.prev_id);
    setNav("next", nav.next_id);
    setNav("latest", nav.latest_id && nav.latest_id !== data.game_id ? nav.latest_id : null);
  }

  async function load(id) {
    if (!id) return;
    const data = await live.get("/api/history/" + encodeURIComponent(id));
    apply(data);
    lastSig = JSON.stringify({
      id: data.game_id,
      winner: data.winner,
      shot_count: data.shot_count,
      guess: data.guess_text,
    });
  }

  document.querySelector('[data-nav="prev"]').addEventListener("click", async function () {
    if (!nav.prev_id) return;
    try {
      await load(nav.prev_id);
    } catch (_e) {}
  });
  document.querySelector('[data-nav="next"]').addEventListener("click", async function () {
    if (!nav.next_id) return;
    try {
      await load(nav.next_id);
    } catch (_e) {}
  });
  document.querySelector('[data-nav="latest"]').addEventListener("click", async function () {
    if (!nav.latest_id) return;
    try {
      await load(nav.latest_id);
    } catch (_e) {}
  });

  if (showBtn) showBtn.addEventListener("click", loadShots);

  if (lightbox) {
    lightbox.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
    const prev = lightbox.querySelector(".lightbox-prev");
    const next = lightbox.querySelector(".lightbox-next");
    if (prev) {
      prev.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!lightboxFrames.length) return;
        lightboxIndex = (lightboxIndex - 1 + lightboxFrames.length) % lightboxFrames.length;
        syncLightbox();
      });
    }
    if (next) {
      next.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!lightboxFrames.length) return;
        lightboxIndex = (lightboxIndex + 1) % lightboxFrames.length;
        syncLightbox();
      });
    }
    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox || e.target === lightboxImg) closeLightbox();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && !lightbox.hidden) closeLightbox();
    });
  }

  live.start(async function () {
    try {
      if (!gameId) {
        const list = await live.get("/games.json");
        const games = (list.games || []).filter(function (g) {
          return !!g.winner_suit;
        });
        if (!games.length) {
          live.stamp(true, "no finished games");
          document.querySelector("[data-game-pos]").textContent = "—";
          document.querySelector("[data-winner]").textContent = "none yet";
          document.querySelector("[data-guess]").textContent = "—";
          return;
        }
        gameId = games[0].game_id;
      }
      const data = await live.get("/api/history/" + encodeURIComponent(gameId));
      const sig = JSON.stringify({
        id: data.game_id,
        winner: data.winner,
        shot_count: data.shot_count,
        guess: data.guess_text,
      });
      live.stamp(true, data.index + "/" + data.total);
      if (sig === lastSig) return;
      lastSig = sig;
      apply(data);
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
