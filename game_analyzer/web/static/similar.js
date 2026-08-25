(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  const list = document.querySelector("[data-sim-list]");
  const summary = document.querySelector("[data-sim-summary]");
  const kindBanner = document.querySelector("[data-sim-kind]");
  const loading = document.querySelector("[data-sim-loading]");
  const empty = document.querySelector("[data-sim-empty]");
  const exactOnly = document.querySelector("[data-exact-only]");
  const refreshBtn = document.querySelector("[data-sim-refresh]");
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  const lightboxStatus = lightbox ? lightbox.querySelector(".lightbox-status") : null;

  function openLightbox(url, caption) {
    if (!lightbox || !lightboxImg) return;
    lightboxImg.src = url;
    lightbox.hidden = false;
    document.body.classList.add("no-scroll");
    if (lightboxStatus) lightboxStatus.textContent = caption || "";
  }

  function closeLightbox() {
    if (!lightbox) return;
    lightbox.hidden = true;
    document.body.classList.remove("no-scroll");
  }

  function sharedFromKey(key) {
    if (!key || key.indexOf("shared=") < 0) return null;
    return key.split("shared=").pop();
  }

  function setKindBanner(data) {
    if (!kindBanner) return;
    if (!data.clusters || !data.clusters.length) {
      kindBanner.hidden = true;
      kindBanner.textContent = "";
      return;
    }
    const sharedMin = data.near_shared_min != null ? data.near_shared_min : 9;
    const nearNote =
      "near = ≥" +
      sharedMin +
      "/12 handicap · browse only (not a bet signal)";
    // One page-level line (not repeated per set).
    if (data.exact_n > 0 && data.near_n > 0) {
      kindBanner.textContent =
        "EXACT + NEAR · " +
        data.exact_n +
        " exact · " +
        (data.near_same_n || 0) +
        " near same-winner · " +
        (data.near_mixed_n || 0) +
        " near mixed · " +
        nearNote;
      kindBanner.className = "similar-kind-banner is-mixed";
    } else if (data.exact_n > 0) {
      kindBanner.textContent =
        "EXACT · " + data.exact_n + " twin set(s) with identical fingerprints";
      kindBanner.className = "similar-kind-banner is-exact";
    } else {
      kindBanner.textContent =
        "NEAR only · no exact twins · " +
        (data.near_same_n || 0) +
        " same-winner · " +
        (data.near_mixed_n || 0) +
        " mixed · " +
        nearNote;
      kindBanner.className = "similar-kind-banner is-near";
    }
    kindBanner.hidden = false;
  }

  function clusterDetail(cluster) {
    const bits = [];
    if (cluster.match_pct != null) bits.push(Math.round(cluster.match_pct) + "% match");
    bits.push((cluster.size || cluster.games.length) + " games");
    const shared = sharedFromKey(cluster.key);
    if (shared) bits.push(shared + "/12 cards shared");
    else if (cluster.exact) bits.push("12/12 exact");
    if (cluster.stage) bits.push(cluster.stage);
    return bits.join(" · ");
  }

  function renderCluster(cluster, index) {
    const setNum = index + 1;
    const badgeKind = cluster.badge_kind || (cluster.exact ? "exact" : "near");
    const badge =
      cluster.badge ||
      (cluster.exact
        ? "EXACT"
        : cluster.winners_same
          ? "NEAR · same winners"
          : cluster.winners_same === false
            ? "NEAR · mixed winners · browse only"
            : "NEAR · browse only");
    const winnerBits = (cluster.winner_counts || [])
      .map(function (w) {
        return w[0] + "×" + w[1];
      })
      .join(" · ");

    let gamesHtml = '<div class="similar-games-row">';
    (cluster.games || []).forEach(function (game) {
      gamesHtml += cards.gameCardBlock(game);
    });
    gamesHtml += "</div>";

    const ids = cluster.game_ids || [];
    const hostId = "shots-set-" + setNum + "-" + ids.join("-");

    return (
      '<article class="similar-cluster panel is-' +
      badgeKind +
      '" data-set="' +
      setNum +
      '"><div class="cluster-head"><span class="sim-badge ' +
      badgeKind +
      '">' +
      badge +
      '</span><h3 class="cluster-set">Set ' +
      setNum +
      '</h3></div><p class="cluster-detail">' +
      clusterDetail(cluster) +
      '</p><p class="cluster-winners">Winners: ' +
      (winnerBits || "—") +
      "</p>" +
      gamesHtml +
      '<div class="similar-actions"><button type="button" class="btn btn-sm" data-show-shots="' +
      hostId +
      '" data-game-ids="' +
      ids.join(",") +
      '">Show screenshots</button></div>' +
      '<div class="similar-shots" id="' +
      hostId +
      '" hidden></div></article>'
    );
  }

  async function loadShots(host, gameIds) {
    host.hidden = false;
    host.innerHTML = '<p class="muted">Loading screenshots…</p>';
    const thumbs = [];
    for (const gid of gameIds) {
      try {
        const data = await live.get("/api/game/" + encodeURIComponent(gid));
        const frames = data.frames || [];
        const last = frames.length ? frames[frames.length - 1] : null;
        if (last) {
          thumbs.push({ id: gid, url: last.url, caption: "#" + gid + " · " + last.phase });
        } else {
          thumbs.push({ id: gid, url: null, caption: "#" + gid });
        }
      } catch (_e) {
        thumbs.push({ id: gid, url: null, caption: "#" + gid });
      }
    }
    host.innerHTML =
      '<div class="similar-shot-row">' +
      thumbs
        .map(function (t) {
          if (!t.url) {
            return '<div class="shot-missing">#' + t.id + "<br>no screenshot</div>";
          }
          return (
            '<button type="button" class="shot-thumb" data-shot-url="' +
            t.url +
            '" data-shot-cap="' +
            t.caption +
            '"><img src="' +
            t.url +
            '" alt="' +
            t.caption +
            '" loading="lazy" /><span>' +
            t.caption +
            "</span></button>"
          );
        })
        .join("") +
      '</div><p class="muted">Tap a screenshot for full view.</p>';
    host.querySelectorAll("[data-shot-url]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openLightbox(btn.getAttribute("data-shot-url"), btn.getAttribute("data-shot-cap"));
      });
    });
  }

  function bindList() {
    list.querySelectorAll("[data-show-shots]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        const hostId = btn.getAttribute("data-show-shots");
        const host = document.getElementById(hostId);
        const ids = (btn.getAttribute("data-game-ids") || "")
          .split(",")
          .filter(Boolean);
        btn.disabled = true;
        btn.textContent = "Screenshots loaded";
        await loadShots(host, ids);
      });
    });
  }

  async function refresh() {
    loading.hidden = false;
    empty.hidden = true;
    list.innerHTML = "";
    if (kindBanner) kindBanner.hidden = true;
    summary.textContent = "Loading…";
    try {
      const exact = exactOnly && exactOnly.checked;
      const data = await live.get("/api/similar?exact_only=" + (exact ? "true" : "false"));
      loading.hidden = true;
      summary.textContent =
        "scanned " +
        data.corpus_n +
        " finished · " +
        data.cluster_count +
        " sets · " +
        data.exact_n +
        " exact · " +
        data.near_n +
        " near · " +
        data.games_shown +
        " games";
      live.stamp(true, data.cluster_count + " sets");
      if (!data.clusters || !data.clusters.length) {
        empty.hidden = false;
        empty.textContent =
          "Scanned " +
          data.corpus_n +
          " finished games — no " +
          (exact ? "exact twins" : "similar pairs") +
          " yet.";
        return;
      }
      setKindBanner(data);
      list.innerHTML = data.clusters
        .map(function (cluster, i) {
          return renderCluster(cluster, i);
        })
        .join("");
      bindList();
    } catch (_err) {
      loading.hidden = true;
      summary.textContent = "Failed to load — retrying…";
      live.stamp(false);
    }
  }

  refresh();
  if (refreshBtn)
    refreshBtn.addEventListener("click", function () {
      refresh();
    });
  if (exactOnly)
    exactOnly.addEventListener("change", function () {
      refresh();
    });
  if (lightbox) {
    lightbox.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
    lightbox.addEventListener("click", function (e) {
      if (e.target === lightbox || e.target === lightboxImg) closeLightbox();
    });
  }

  live.start(async function () {
    try {
      await live.get("/api/stats");
      live.stamp(true, summary.textContent.replace(/^scanned /, ""));
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
