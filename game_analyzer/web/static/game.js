(function () {
  const gameId = document.body.getAttribute("data-game-id");
  const carousel = document.querySelector("[data-carousel]");
  const emptyShots = document.querySelector("[data-shots-empty]");
  const tableBox = document.querySelector("[data-table]");
  if (!gameId || !carousel) return;

  const track = carousel.querySelector(".carousel-track");
  const prevBtn = carousel.querySelector(".carousel-prev");
  const nextBtn = carousel.querySelector(".carousel-next");
  const dotsBox = carousel.querySelector(".carousel-dots");
  const status = carousel.querySelector(".carousel-status");
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = lightbox.querySelector("img");
  const lightboxStatus = lightbox.querySelector(".lightbox-status");
  const lightboxPrev = lightbox.querySelector(".lightbox-prev");
  const lightboxNext = lightbox.querySelector(".lightbox-next");
  let index = 0;
  let lightboxOpen = false;
  let swiping = false;
  let lastSig = "";

  function slides() {
    return Array.from(track.children);
  }

  function count() {
    return slides().length;
  }

  function captionAt(i) {
    const slide = slides()[i];
    return slide ? slide.getAttribute("data-caption") || "" : "";
  }

  function srcAt(i) {
    const img = slides()[i] && slides()[i].querySelector("img");
    return img ? img.getAttribute("src") : "";
  }

  function rebuildDots() {
    dotsBox.innerHTML = "";
    slides().forEach((_, i) => {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = "dot";
      dot.setAttribute("aria-label", "Screenshot " + (i + 1));
      dot.addEventListener("click", () => go(i));
      dotsBox.appendChild(dot);
    });
  }

  function go(i) {
    const n = count();
    if (!n) return;
    index = ((i % n) + n) % n;
    track.style.transform = "translateX(-" + index * 100 + "%)";
    Array.from(dotsBox.children).forEach((dot, pos) =>
      dot.classList.toggle("on", pos === index)
    );
    if (status) status.textContent = index + 1 + " / " + n + "  " + captionAt(index);
    if (lightboxOpen) syncLightbox();
  }

  function syncLightbox() {
    lightboxImg.src = srcAt(index);
    const img = slides()[index] && slides()[index].querySelector("img");
    lightboxImg.alt = img ? img.alt : "";
    lightboxStatus.textContent = index + 1 + " / " + count() + "  " + captionAt(index);
  }

  function openLightbox(i) {
    go(i);
    lightboxOpen = true;
    lightbox.hidden = false;
    lightbox.classList.add("open");
    document.body.classList.add("no-scroll");
    syncLightbox();
  }

  function closeLightbox() {
    lightboxOpen = false;
    lightbox.hidden = true;
    lightbox.classList.remove("open");
    document.body.classList.remove("no-scroll");
  }

  function setNav(el, id) {
    if (id) {
      el.setAttribute("href", "/game/" + id);
      el.classList.remove("disabled");
    } else {
      el.removeAttribute("href");
      el.classList.add("disabled");
    }
  }

  function renderTable(rows) {
    if (!rows || !rows.length) {
      tableBox.innerHTML = '<p class="empty">No cards stored.</p>';
      return;
    }
    tableBox.innerHTML =
      '<div class="suit-table">' +
      rows
        .map(function (row) {
          const cards = row.cards && row.cards.length
            ? row.cards
                .map(function (card) {
                  const text = String(card);
                  return (
                    '<div class="mini-card" style="color: ' +
                    row.color +
                    '"><span class="rank">' +
                    text.slice(0, -1) +
                    '</span><span class="pip">' +
                    row.symbol +
                    "</span></div>"
                  );
                })
                .join("")
            : '<span class="dash">—</span>';
          return (
            '<div class="suit-row"><div class="suit-name" style="color: ' +
            row.color +
            '">' +
            row.symbol +
            " " +
            row.name +
            '</div><div class="mini-cards">' +
            cards +
            "</div></div>"
          );
        })
        .join("") +
      "</div>";
  }

  function makeSlide(frame, i) {
    const caption = "#" + frame.seq + " · " + frame.phase + " · " + frame.captured_at;
    const figure = document.createElement("figure");
    figure.className = "shot";
    figure.setAttribute("data-seq", String(frame.seq));
    figure.setAttribute("data-caption", caption);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "shot-open";
    btn.dataset.index = String(i);
    btn.setAttribute("aria-label", "Open screenshot " + frame.seq);
    const img = document.createElement("img");
    img.src = frame.url;
    img.alt = "Round " + frame.seq + " " + frame.phase;
    img.loading = "lazy";
    btn.appendChild(img);
    btn.addEventListener("click", (e) => {
      if (swiping) {
        e.preventDefault();
        return;
      }
      openLightbox(Number(btn.dataset.index));
    });
    figure.appendChild(btn);
    return figure;
  }

  function applyFrames(frames) {
    const wasAtEnd = count() === 0 || index >= count() - 1;
    const currentSeq = count() ? slides()[index].getAttribute("data-seq") : null;
    track.innerHTML = "";
    frames.forEach((frame, i) => track.appendChild(makeSlide(frame, i)));
    const n = frames.length;
    emptyShots.hidden = n > 0;
    carousel.hidden = n === 0;
    prevBtn.hidden = n < 2;
    nextBtn.hidden = n < 2;
    lightboxPrev.hidden = n < 2;
    lightboxNext.hidden = n < 2;
    rebuildDots();
    if (!n) return;
    if (wasAtEnd) go(n - 1);
    else {
      const keep = slides().findIndex((s) => s.getAttribute("data-seq") === currentSeq);
      go(keep >= 0 ? keep : n - 1);
    }
  }

  function apply(data) {
    document.querySelector("[data-winner]").textContent = data.winner;
    const meta = "Started " + data.started_at + (data.finished_at ? " · Finished " + data.finished_at : "");
    document.querySelector("[data-game-meta]").textContent = meta;
    document.querySelector("[data-game-pos]").textContent = data.index + " / " + data.total;
    setNav(document.querySelector('[data-nav="prev"]'), data.prev_id);
    setNav(document.querySelector('[data-nav="next"]'), data.next_id);
    renderTable(data.table);
    applyFrames(data.frames || []);
  }

  prevBtn.addEventListener("click", () => go(index - 1));
  nextBtn.addEventListener("click", () => go(index + 1));
  lightboxPrev.addEventListener("click", (e) => {
    e.stopPropagation();
    go(index - 1);
  });
  lightboxNext.addEventListener("click", (e) => {
    e.stopPropagation();
    go(index + 1);
  });
  lightbox.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
  lightbox.addEventListener("click", (e) => {
    if (e.target === lightbox || e.target === lightboxImg) closeLightbox();
  });

  carousel.querySelectorAll(".shot-open").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (swiping) {
        e.preventDefault();
        return;
      }
      openLightbox(Number(btn.dataset.index));
    });
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && lightboxOpen) closeLightbox();
    else if (e.key === "ArrowLeft") go(index - 1);
    else if (e.key === "ArrowRight") go(index + 1);
  });

  function bindSwipe(el, onLeft, onRight) {
    let x = 0;
    let y = 0;
    el.addEventListener(
      "touchstart",
      (e) => {
        swiping = false;
        x = e.changedTouches[0].clientX;
        y = e.changedTouches[0].clientY;
      },
      { passive: true }
    );
    el.addEventListener(
      "touchend",
      (e) => {
        const dx = e.changedTouches[0].clientX - x;
        const dy = e.changedTouches[0].clientY - y;
        if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return;
        swiping = true;
        if (dx < 0) onLeft();
        else onRight();
      },
      { passive: true }
    );
  }

  bindSwipe(carousel.querySelector(".carousel-viewport"), () => go(index + 1), () => go(index - 1));
  bindSwipe(lightbox, () => go(index + 1), () => go(index - 1));

  rebuildDots();
  if (count()) go(0);

  const live = window.gameAnalyzerLive;
  if (!live) return;

  live.start(async function () {
    try {
      const data = await live.get("/game/" + encodeURIComponent(gameId) + "/live");
      const sig = JSON.stringify({
        winner: data.winner,
        finished_at: data.finished_at,
        table: data.table,
        frames: data.frames,
        total: data.total,
        prev_id: data.prev_id,
        next_id: data.next_id,
      });
      live.stamp(true, (data.frames || []).length + " shot" + ((data.frames || []).length === 1 ? "" : "s"));
      if (sig === lastSig) return;
      apply(data);
      lastSig = sig;
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
