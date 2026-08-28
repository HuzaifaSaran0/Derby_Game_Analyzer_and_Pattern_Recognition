(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  const list = document.querySelector("[data-sim-list]");
  const summary = document.querySelector("[data-sim-summary]");
  const kindBanner = document.querySelector("[data-sim-kind]");
  const loading = document.querySelector("[data-sim-loading]");
  const empty = document.querySelector("[data-sim-empty]");
  const refreshBtn = document.querySelector("[data-sim-refresh]");
  const lightbox = document.getElementById("lightbox");
  const lightboxImg = lightbox ? lightbox.querySelector("img") : null;
  const lightboxStatus = lightbox ? lightbox.querySelector(".lightbox-status") : null;
  const lateFocus = document.querySelector("[data-late-focus]");
  const lateStats = document.querySelector("[data-late-stats]");
  const lateStatsGrid = document.querySelector("[data-late-stats-grid]");
  const lateBadge = document.querySelector("[data-late-badge]");
  const lateTitle = document.querySelector("[data-late-title]");
  const lateDetail = document.querySelector("[data-late-detail]");
  const lateWinners = document.querySelector("[data-late-winners]");
  const lateGames = document.querySelector("[data-late-games]");
  const lateShotsBtn = document.querySelector("[data-late-shots]");
  const lateShotsHost = document.querySelector("[data-late-shots-host]");

  let lateFocusIds = [];

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

  function queryParams() {
    return new URLSearchParams(window.location.search || "");
  }

  function setKindBanner(data) {
    if (!kindBanner) return;
    if (!data.clusters || !data.clusters.length) {
      kindBanner.hidden = true;
      kindBanner.textContent = "";
      return;
    }
    kindBanner.textContent =
      "LATE ROUNDS · " +
      data.cluster_count +
      " twin set(s) with identical R3 / R3→R4 / R3→R4→R5 draws";
    kindBanner.className = "similar-kind-banner is-exact";
    kindBanner.hidden = false;
  }

  function lateStageTitle(roundN) {
    if (roundN === 3) return "Round 3";
    if (roundN === 4) return "Rounds 3–4";
    if (roundN === 5) return "Rounds 3–5";
    return "Round " + roundN;
  }

  function renderLateStats(rows) {
    if (!lateStats || !lateStatsGrid) return;
    if (!rows || !rows.length) {
      lateStats.hidden = true;
      lateStatsGrid.innerHTML = "";
      return;
    }
    lateStats.hidden = false;
    lateStatsGrid.innerHTML = rows
      .map(function (row) {
        const title = lateStageTitle(row.round_n);
        const count =
          row.twin_sets > 0
            ? row.twin_sets +
              " matching " +
              (row.twin_sets === 1 ? "group" : "groups") +
              " · " +
              (row.games_in_sets || 0) +
              " games"
            : "No matches yet";
        const same =
          row.same_winner_pct != null
            ? "Same winner " + row.same_winner_pct + "% of the time"
            : "—";
        const mean =
          row.mean_agreement_pct != null
            ? "Winners agreed " + row.mean_agreement_pct + "% on average"
            : "—";
        return (
          '<div class="late-stat-card"><strong>' +
          title +
          "</strong><span>" +
          count +
          "</span><span>" +
          same +
          "</span><span>" +
          mean +
          "</span></div>"
        );
      })
      .join("");
  }

  function sharedRoundsHtml(cluster) {
    const rounds = cluster.round_cards || [];
    if (!rounds.length) return "";
    return (
      '<div class="cluster-shared-rounds">' +
      rounds
        .map(function (row) {
          return (
            '<div class="game-card-section"><strong>Shared R' +
            row.round_n +
            "</strong>" +
            '<div class="mini-cards matched-round-cards">' +
            cards.miniCards(row.cards) +
            "</div></div>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function clusterDetail(cluster) {
    const bits = [];
    bits.push((cluster.size || (cluster.games || []).length) + " games");
    if (cluster.matched_rounds && cluster.matched_rounds.length) {
      bits.push(
        "matched " +
          cluster.matched_rounds
            .map(function (n) {
              return "R" + n;
            })
            .join("+")
      );
    } else if (cluster.stage) {
      bits.push(cluster.stage);
    }
    if (cluster.agreement_pct != null && cluster.majority_winner) {
      bits.push(cluster.agreement_pct + "% agree on " + cluster.majority_winner);
    }
    return bits.join(" · ");
  }

  function trustLabel(cluster) {
    const trust = (cluster.trust || "verified").toLowerCase();
    if (trust === "verified") return "Frame-verified";
    if (trust === "fallback") return "Json/guess fallback";
    return "Unverified";
  }

  function trustClass(cluster) {
    const trust = (cluster.trust || "verified").toLowerCase();
    if (trust === "verified") return "is-verified";
    if (trust === "fallback") return "is-fallback";
    return "is-weak";
  }

  function renderCluster(cluster, index) {
    const setNum = index + 1;
    const badge = cluster.badge || cluster.stage || "R3";
    const trust = trustClass(cluster);
    const trustNote =
      cluster.trust_notes && cluster.trust_notes.length
        ? '<p class="cluster-trust-note muted">' + cluster.trust_notes.join(" · ") + "</p>"
        : "";
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
      '<article class="similar-cluster panel is-exact ' +
      trust +
      '" data-set="' +
      setNum +
      '" data-twin-key="' +
      (cluster.key || "").replace(/"/g, "&quot;") +
      '"><div class="cluster-head"><span class="sim-badge exact">' +
      badge +
      '</span><span class="sim-badge trust ' +
      trust +
      '">' +
      trustLabel(cluster) +
      '</span><h3 class="cluster-set">Set ' +
      setNum +
      '</h3></div><p class="cluster-detail">' +
      clusterDetail(cluster) +
      "</p>" +
      trustNote +
      sharedRoundsHtml(cluster) +
      '<p class="cluster-winners">Winners: ' +
      (winnerBits || "—") +
      "</p>" +
      gamesHtml +
      '<div class="similar-actions"><button type="button" class="btn btn-sm" data-show-shots="' +
      hostId +
      '" data-game-ids="' +
      ids.join(",") +
      '">See screenshots</button></div>' +
      '<div class="similar-shots" id="' +
      hostId +
      '" hidden></div></article>'
    );
  }

  async function loadShots(host, gameIds) {
    host.hidden = false;
    host.innerHTML = '<p class="muted">Loading screenshots…</p>';
    const groups = [];
    for (const gid of gameIds) {
      try {
        const data = await live.get("/api/game/" + encodeURIComponent(gid));
        const frames = data.frames || [];
        groups.push({
          id: gid,
          frames: frames.map(function (f) {
            return {
              url: f.url,
              caption: "#" + gid + " · " + (f.phase || "frame"),
            };
          }),
        });
      } catch (_e) {
        groups.push({ id: gid, frames: [] });
      }
    }
    host.innerHTML =
      groups
        .map(function (g) {
          if (!g.frames.length) {
            return (
              '<div class="similar-shot-game"><h4 class="shot-game-title">#' +
              g.id +
              '</h4><div class="shot-missing">no screenshots</div></div>'
            );
          }
          return (
            '<div class="similar-shot-game"><h4 class="shot-game-title">#' +
            g.id +
            " · " +
            g.frames.length +
            ' shot(s)</h4><div class="similar-shot-row">' +
            g.frames
              .map(function (t) {
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
            "</div></div>"
          );
        })
        .join("") +
      '<p class="muted">Tap a screenshot for full view.</p>';
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

  async function loadLateFocusFromQuery() {
    if (!lateFocus) return;
    const params = queryParams();
    const stage = (params.get("stage") || "").toLowerCase();
    const ids = (params.get("ids") || "")
      .split(",")
      .map(function (s) {
        return s.trim();
      })
      .filter(Boolean);
    const liveId = params.get("live");
    if (!stage || !ids.length) {
      lateFocus.hidden = true;
      return;
    }
    try {
      const data = await live.get(
        "/api/similar/late?stage=" +
          encodeURIComponent(stage) +
          "&ids=" +
          encodeURIComponent(ids.join(",")) +
          (liveId ? "&live=" + encodeURIComponent(liveId) : "")
      );
      if (!data.ready || !data.games || !data.games.length) {
        lateFocus.hidden = true;
        return;
      }
      lateFocusIds = data.game_ids || ids;
      const roundN = data.round_n || 3;
      if (lateBadge) lateBadge.textContent = "TWIN-R" + roundN;
      if (lateTitle) {
        lateTitle.textContent =
          "R" +
          roundN +
          " exact matches" +
          (data.live_game_id ? " · live #" + data.live_game_id : "");
      }
      const roundCards = (data.live_round_cards || []).join(", ") || "—";
      const matched =
        data.matched_rounds && data.matched_rounds.length
          ? data.matched_rounds
              .map(function (n) {
                return "R" + n;
              })
              .join("+")
          : "R" + roundN;
      if (lateDetail) {
        lateDetail.textContent =
          data.match_count +
          " game(s) · " +
          matched +
          " · stage cards [" +
          roundCards +
          "]" +
          (data.agreement_pct != null && data.majority_winner
            ? " · " + data.agreement_pct + "% agree on " + data.majority_winner
            : "");
      }
      const winnerBits = (data.winner_counts || [])
        .map(function (w) {
          return w[0] + "×" + w[1];
        })
        .join(" · ");
      if (lateWinners) lateWinners.textContent = "Winners: " + (winnerBits || "—");
      if (lateGames) {
        lateGames.innerHTML = (data.games || [])
          .map(function (game) {
            return cards.gameCardBlock(game);
          })
          .join("");
      }
      lateFocus.hidden = false;
      if (lateShotsHost) {
        lateShotsHost.hidden = true;
        lateShotsHost.innerHTML = "";
      }
      if (lateShotsBtn) {
        lateShotsBtn.disabled = false;
        lateShotsBtn.textContent = "See screenshots";
      }
      lateFocus.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (_e) {
      lateFocus.hidden = true;
    }
  }

  function focusTwinSetFromQuery() {
    const params = queryParams();
    const setKey = params.get("set");
    if (!setKey) return;
    if (window.gameAnalyzerNotifs) {
      window.gameAnalyzerNotifs.markRead(setKey);
    }
    const el = document.querySelector('[data-twin-key="' + CSS.escape(setKey) + '"]');
    if (!el) return;
    el.classList.add("is-notif-focus");
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function refresh() {
    loading.hidden = false;
    empty.hidden = true;
    list.innerHTML = "";
    if (kindBanner) kindBanner.hidden = true;
    summary.textContent = "Loading…";
    try {
      const data = await live.get("/api/similar");
      loading.hidden = true;
      const r3Sets = data.r3_twin_sets != null ? data.r3_twin_sets : data.cluster_count;
      const r3Games = data.r3_games != null ? data.r3_games : data.games_shown;
      const verified = data.verified_sets != null ? data.verified_sets : 0;
      const fallback = data.fallback_sets != null ? data.fallback_sets : 0;
      const excluded = data.excluded_weak_sets != null ? data.excluded_weak_sets : 0;
      summary.textContent =
        "scanned " +
        data.corpus_n +
        " finished · showing " +
        data.cluster_count +
        " twin sets (" +
        verified +
        " frame-verified" +
        (fallback ? ", " + fallback + " fallback" : "") +
        ")" +
        (excluded ? " · " + excluded + " weak excluded" : "") +
        " · R3 corpus " +
        r3Sets +
        " sets / " +
        r3Games +
        " games";
      live.stamp(true, verified + " verified · " + data.cluster_count + " sets");
      renderLateStats(data.late_round_stats || []);
      await loadLateFocusFromQuery();
      if (!data.clusters || !data.clusters.length) {
        empty.hidden = false;
        empty.textContent =
          "Scanned " +
          data.corpus_n +
          " finished games — no identical R3 / R4 / R5 twin sets yet.";
        return;
      }
      setKindBanner(data);
      list.innerHTML = data.clusters
        .map(function (cluster, i) {
          return renderCluster(cluster, i);
        })
        .join("");
      bindList();
      focusTwinSetFromQuery();
    } catch (_err) {
      loading.hidden = true;
      summary.textContent = "Failed to load — retrying…";
      live.stamp(false);
    }
  }

  if (lateShotsBtn && lateShotsHost) {
    lateShotsBtn.addEventListener("click", async function () {
      lateShotsBtn.disabled = true;
      lateShotsBtn.textContent = "Screenshots loaded";
      await loadShots(lateShotsHost, lateFocusIds);
    });
  }

  refresh();
  if (refreshBtn)
    refreshBtn.addEventListener("click", function () {
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
