(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  const historyStatusEl = document.querySelector("[data-streak-history-status]");
  const winnerGridEl = document.querySelector("[data-winner-grid]");
  if (!live || !historyStatusEl || !winnerGridEl) return;

  const PAGE_SIZE = 50;
  const winnerPagerEl = document.querySelector("[data-winner-pager]");
  const winnerPrevBtn = document.querySelector("[data-winner-prev]");
  const winnerNextBtn = document.querySelector("[data-winner-next]");
  const winnerPageLabel = document.querySelector("[data-winner-page-label]");
  const gameModal = document.querySelector("[data-game-modal]");
  const modalTitle = document.querySelector("[data-game-modal-title]");
  const modalWinner = document.querySelector("[data-game-modal-winner]");
  const modalMeta = document.querySelector("[data-game-modal-meta]");
  const modalStreak = document.querySelector("[data-game-modal-streak]");
  const modalTable = document.querySelector("[data-game-modal-table]");
  const modalShots = document.querySelector("[data-game-modal-shots]");
  const modalShotsEmpty = document.querySelector("[data-game-modal-shots-empty]");
  const modalShotsStatus = document.querySelector("[data-game-modal-shots-status]");
  const modalLink = document.querySelector("[data-game-modal-link]");
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  const lightboxStatus = lightbox ? lightbox.querySelector(".lightbox-status") : null;

  let winnerOffset = 0;
  let winnerItemsById = {};
  let lightboxFrames = [];
  let lightboxIndex = 0;
  let modalLoadGen = 0;

  const CODE_TO_SUIT_FALLBACK = {
    "1": "Spades",
    "2": "Hearts",
    "3": "Clubs",
    "4": "Diamonds",
  };

  function readMeta() {
    const node = document.getElementById("winner-suit-meta");
    if (!node) return {};
    try {
      return JSON.parse(node.textContent || "{}");
    } catch (_e) {
      return {};
    }
  }

  const meta = readMeta();

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, "&quot;");
  }

  function formatWhen(at) {
    if (!at) return "";
    try {
      const d = new Date(at);
      if (isNaN(d.getTime())) return at;
      return d.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_e) {
      return at;
    }
  }

  function suitLabel(code) {
    const info = meta[String(code)] || {};
    return info.label || CODE_TO_SUIT_FALLBACK[String(code)] || String(code || "");
  }

  function renderWinnerCell(item) {
    const gameId = String(item.game_id || "?");
    const code = item.actual_winner;
    const info = meta[String(code)] || {};
    const color = info.color || "";
    const label = item.actual_winner_label || suitLabel(code);
    const matched = Boolean(item.matched);
    const classes = ["winner-cell"];
    if (matched) classes.push("is-matched");
    if (item.history_pick_correct === true) classes.push("is-correct");
    if (item.history_pick_correct === false) classes.push("is-wrong");
    return (
      '<button type="button" class="' +
      classes.join(" ") +
      '" data-winner-game="' +
      escapeAttr(gameId) +
      '"' +
      (color ? ' style="--winner-color:' + escapeHtml(color) + '"' : "") +
      ' title="#' +
      escapeAttr(gameId) +
      " · " +
      escapeAttr(label) +
      (matched ? " · streak match" : "") +
      '">' +
      '<span class="winner-cell-code">' +
      escapeHtml(String(code != null ? code : "?")) +
      "</span>" +
      '<span class="winner-cell-id">#' +
      escapeHtml(gameId) +
      "</span>" +
      "</button>"
    );
  }

  function updatePager(data) {
    if (!winnerPagerEl) return;
    const totalGames = data.total_games || 0;
    const offset = data.offset || 0;
    const count = (data.items || []).length;
    const hasOlder = Boolean(data.has_older);
    const hasNewer = Boolean(data.has_newer);
    winnerPagerEl.hidden = totalGames <= PAGE_SIZE && offset === 0;
    if (winnerPrevBtn) winnerPrevBtn.disabled = !hasOlder;
    if (winnerNextBtn) winnerNextBtn.disabled = !hasNewer;
    if (winnerPageLabel) {
      if (!count) {
        winnerPageLabel.textContent = "";
      } else {
        const from = offset + 1;
        const to = offset + count;
        winnerPageLabel.textContent =
          from + "–" + to + " of " + totalGames + " (newest → older)";
      }
    }
  }

  async function refreshHistory() {
    try {
      const data = await live.get(
        "/api/streak-history?limit=" + PAGE_SIZE + "&offset=" + winnerOffset
      );
      const items = data.items || [];
      winnerItemsById = {};
      items.forEach(function (item) {
        if (item.game_id) winnerItemsById[String(item.game_id)] = item;
      });
      if (!items.length) {
        historyStatusEl.textContent =
          winnerOffset > 0 ? "No more older games." : "No finished games yet.";
        winnerGridEl.hidden = true;
        winnerGridEl.innerHTML = "";
        updatePager(data);
        return;
      }
      historyStatusEl.textContent =
        items.length +
        " winner(s) on this page" +
        (data.matched ? " · " + data.matched + " streak match(es)" : "");
      winnerGridEl.innerHTML = items.map(renderWinnerCell).join("");
      winnerGridEl.hidden = false;
      updatePager(data);
    } catch (_e) {
      historyStatusEl.textContent = "Could not load winner history.";
      winnerGridEl.hidden = true;
      if (winnerPagerEl) winnerPagerEl.hidden = true;
    }
  }

  function openLightbox(frames, index) {
    if (!lightbox || !frames.length) return;
    lightboxFrames = frames;
    lightboxIndex = index;
    lightbox.hidden = false;
    syncLightbox();
  }

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.hidden = true;
  }

  function syncLightbox() {
    const frame = lightboxFrames[lightboxIndex];
    if (!frame || !lightboxImg) return;
    lightboxImg.src = frame.url;
    lightboxImg.alt = "Screenshot " + frame.seq;
    if (lightboxStatus) {
      lightboxStatus.textContent =
        lightboxIndex +
        1 +
        " / " +
        lightboxFrames.length +
        "  #" +
        frame.seq +
        " · " +
        frame.phase;
    }
  }

  function closeGameModal() {
    if (!gameModal) return;
    gameModal.hidden = true;
    document.body.classList.remove("no-scroll");
    closeLightbox();
  }

  function renderModalShots(frames) {
    if (!modalShots) return;
    if (!frames || !frames.length) {
      modalShots.innerHTML = "";
      if (modalShotsEmpty) modalShotsEmpty.hidden = false;
      if (modalShotsStatus) modalShotsStatus.hidden = true;
      return;
    }
    if (modalShotsEmpty) modalShotsEmpty.hidden = true;
    if (modalShotsStatus) modalShotsStatus.hidden = true;
    modalShots.innerHTML = frames
      .map(function (frame, i) {
        return (
          '<button type="button" class="shot-thumb" data-shot-index="' +
          i +
          '"><img src="' +
          escapeAttr(frame.url) +
          '" alt="#' +
          escapeAttr(String(frame.seq)) +
          '" loading="lazy" /><span>#' +
          escapeHtml(String(frame.seq)) +
          " · " +
          escapeHtml(frame.phase || "") +
          "</span></button>"
        );
      })
      .join("");
    modalShots.querySelectorAll("[data-shot-index]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openLightbox(frames, Number(btn.getAttribute("data-shot-index")));
      });
    });
  }

  async function openGameModal(gameId) {
    if (!gameModal || !gameId) return;
    const gen = ++modalLoadGen;
    const cached = winnerItemsById[String(gameId)];
    gameModal.hidden = false;
    document.body.classList.add("no-scroll");
    if (modalTitle) modalTitle.textContent = "Game #" + gameId;
    if (modalWinner) {
      modalWinner.textContent = cached
        ? (cached.actual_winner_label || suitLabel(cached.actual_winner)) +
          " (" +
          String(cached.actual_winner) +
          ")"
        : "…";
    }
    if (modalMeta) modalMeta.textContent = "Loading…";
    if (modalStreak) {
      if (cached && cached.matched) {
        modalStreak.hidden = false;
        modalStreak.innerHTML =
          "Streak match before this game: " +
          escapeHtml(String(cached.streak_length || "")) +
          "× " +
          escapeHtml(cached.streak_suit_label || String(cached.streak_suit || "")) +
          " · history favored " +
          escapeHtml(cached.history_best_next_label || String(cached.history_best_next || "")) +
          " (" +
          escapeHtml(String(cached.history_best_count || 0)) +
          "/" +
          escapeHtml(String(cached.history_cases || 0)) +
          ")";
      } else {
        modalStreak.hidden = true;
        modalStreak.textContent = "";
      }
    }
    if (modalTable) modalTable.innerHTML = "";
    if (modalShots) modalShots.innerHTML = "";
    if (modalShotsEmpty) modalShotsEmpty.hidden = true;
    if (modalShotsStatus) {
      modalShotsStatus.hidden = false;
      modalShotsStatus.textContent = "Loading…";
    }
    if (modalLink) modalLink.href = "/game/" + encodeURIComponent(gameId);

    try {
      const [detail, shots] = await Promise.all([
        live.get("/api/history/" + encodeURIComponent(gameId)),
        live.get("/api/history/" + encodeURIComponent(gameId) + "/shots"),
      ]);
      if (gen !== modalLoadGen) return;
      if (modalTitle) modalTitle.textContent = "Game #" + detail.game_id;
      if (modalWinner) modalWinner.textContent = detail.winner || "—";
      if (modalMeta) {
        modalMeta.textContent =
          "Started " +
          formatWhen(detail.started_at) +
          (detail.finished_at ? " · Finished " + formatWhen(detail.finished_at) : "") +
          " · " +
          (detail.draw_note || "") +
          " · " +
          (detail.shot_count || 0) +
          " shots";
      }
      if (modalTable && cards && typeof cards.suitTable === "function") {
        modalTable.innerHTML = cards.suitTable(detail.table || []);
      } else if (modalTable) {
        modalTable.innerHTML = '<p class="muted">Card table unavailable.</p>';
      }
      renderModalShots(shots.frames || []);
    } catch (_e) {
      if (gen !== modalLoadGen) return;
      if (modalMeta) modalMeta.textContent = "Could not load this game.";
      if (modalShotsStatus) {
        modalShotsStatus.hidden = false;
        modalShotsStatus.textContent = "Could not load screenshots.";
      }
    }
  }

  winnerGridEl.addEventListener("click", function (e) {
    const btn = e.target.closest("[data-winner-game]");
    if (!btn) return;
    openGameModal(btn.getAttribute("data-winner-game"));
  });

  if (winnerPrevBtn) {
    winnerPrevBtn.addEventListener("click", function () {
      if (winnerPrevBtn.disabled) return;
      winnerOffset += PAGE_SIZE;
      refreshHistory();
    });
  }
  if (winnerNextBtn) {
    winnerNextBtn.addEventListener("click", function () {
      if (winnerNextBtn.disabled) return;
      winnerOffset = Math.max(0, winnerOffset - PAGE_SIZE);
      refreshHistory();
    });
  }

  if (gameModal) {
    gameModal.querySelectorAll("[data-game-modal-close]").forEach(function (el) {
      el.addEventListener("click", closeGameModal);
    });
  }

  if (lightbox) {
    const closeBtn = lightbox.querySelector(".lightbox-close");
    const prev = lightbox.querySelector(".lightbox-prev");
    const next = lightbox.querySelector(".lightbox-next");
    if (closeBtn) closeBtn.addEventListener("click", closeLightbox);
    if (prev) {
      prev.addEventListener("click", function (e) {
        e.stopPropagation();
        if (!lightboxFrames.length) return;
        lightboxIndex =
          (lightboxIndex - 1 + lightboxFrames.length) % lightboxFrames.length;
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
  }

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (lightbox && !lightbox.hidden) {
      closeLightbox();
      return;
    }
    if (gameModal && !gameModal.hidden) closeGameModal();
  });

  refreshHistory();
  setInterval(function () {
    if (winnerOffset === 0) refreshHistory();
  }, 30000);
})();
