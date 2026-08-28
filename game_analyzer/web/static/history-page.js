(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  let gameId = document.body.getAttribute("data-start-id") || "";
  let nav = { prev_id: null, next_id: null, latest_id: null };
  let shotCount = 0;
  let shotsLoadedFor = null;
  let lastSig = "";
  let loadGen = 0;
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
    const el = document.querySelector("[data-sim-stats]");
    if (!el || !stats) return;
    el.textContent = stats.late_round_text || "No matching draw history yet";
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
    const forId = gameId;
    showBtn.disabled = true;
    showBtn.textContent = "Loading…";
    try {
      const data = await live.get("/api/history/" + encodeURIComponent(forId) + "/shots");
      if (forId !== gameId) return;
      shotsLoadedFor = forId;
      renderShots(data.frames || []);
    } catch (_e) {
      if (forId !== gameId) return;
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

  function sigOf(data) {
    return JSON.stringify({
      id: data.game_id,
      winner: data.winner,
      shot_count: data.shot_count,
      index: data.index,
      total: data.total,
      prev_id: data.prev_id || null,
      next_id: data.next_id || null,
    });
  }

  async function load(id) {
    if (!id) return;
    const gen = ++loadGen;
    // Lock target immediately so the live poll cannot race back to the old game.
    gameId = id;
    setNav("prev", null);
    setNav("next", null);
    setNav("latest", null);
    const data = await live.get("/api/history/" + encodeURIComponent(id));
    if (gen !== loadGen) return;
    apply(data);
    lastSig = sigOf(data);
  }

  async function go(direction) {
    const target =
      direction === "prev"
        ? nav.prev_id
        : direction === "next"
          ? nav.next_id
          : nav.latest_id;
    if (!target || target === gameId) return;
    try {
      await load(target);
    } catch (_e) {}
  }

  document.querySelector('[data-nav="prev"]').addEventListener("click", function () {
    go("prev");
  });
  document.querySelector('[data-nav="next"]').addEventListener("click", function () {
    go("next");
  });
  document.querySelector('[data-nav="latest"]').addEventListener("click", function () {
    go("latest");
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
          return;
        }
        gameId = games[0].game_id;
      }
      const requestedId = gameId;
      const gen = loadGen;
      const data = await live.get("/api/history/" + encodeURIComponent(requestedId));
      // Ignore stale poll responses after Prev/Next/Latest navigation.
      if (gen !== loadGen || requestedId !== gameId) return;
      live.stamp(true, data.index + "/" + data.total);
      const sig = sigOf(data);
      if (sig === lastSig) return;
      lastSig = sig;
      apply(data);
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
