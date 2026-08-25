(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  let gameId = document.body.getAttribute("data-start-id") || "";
  let lastSig = "";
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  const lightboxStatus = lightbox ? lightbox.querySelector(".lightbox-status") : null;
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
    if (g) g.textContent = stats.guess.text;
    if (c) c.textContent = "Confidence accuracy  ·  " + stats.confidence_text;
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

  function renderShots(frames) {
    const grid = document.querySelector("[data-shot-grid]");
    const empty = document.querySelector("[data-shots-empty]");
    if (!grid) return;
    if (!frames || !frames.length) {
      grid.innerHTML = "";
      if (empty) empty.hidden = false;
      return;
    }
    if (empty) empty.hidden = true;
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

  function apply(data) {
    if (!data) return;
    gameId = data.game_id;
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
      data.draw_note;
    setStats(data.stats);
    document.querySelector("[data-card-table]").innerHTML = cards.suitTable(data.table);
    renderShots(data.frames);
    setNav("prev", data.prev_id);
    setNav("next", data.next_id);
    setNav("latest", data.latest_id && data.latest_id !== data.game_id ? data.latest_id : null);
  }

  async function load(id) {
    if (!id) return;
    const data = await live.get("/api/history/" + encodeURIComponent(id));
    apply(data);
  }

  document.querySelector('[data-nav="prev"]').addEventListener("click", async function () {
    try {
      const data = await live.get("/api/history/" + encodeURIComponent(gameId));
      if (data.prev_id) await load(data.prev_id);
    } catch (_e) {}
  });
  document.querySelector('[data-nav="next"]').addEventListener("click", async function () {
    try {
      const data = await live.get("/api/history/" + encodeURIComponent(gameId));
      if (data.next_id) await load(data.next_id);
    } catch (_e) {}
  });
  document.querySelector('[data-nav="latest"]').addEventListener("click", async function () {
    try {
      const data = await live.get("/api/history/" + encodeURIComponent(gameId));
      if (data.latest_id) await load(data.latest_id);
    } catch (_e) {}
  });

  if (lightbox) {
    lightbox.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
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
        const games = list.games || [];
        if (!games.length) {
          live.stamp(true, "no games");
          return;
        }
        gameId = games[0].game_id;
      }
      const data = await live.get("/api/history/" + encodeURIComponent(gameId));
      const sig = JSON.stringify({
        id: data.game_id,
        winner: data.winner,
        frames: data.frames,
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
