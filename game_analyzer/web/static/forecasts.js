(function () {
  const live = window.gameAnalyzerLive;
  if (!live) return;

  const statusEl = document.querySelector("[data-confidence-status]");
  const listEl = document.querySelector("[data-confidence-list]");
  const accuracyEl = document.querySelector("[data-streak-accuracy]");
  const DISPLAY_TIERS = { MEDIUM: true, HIGH: true };

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
  let initialFocusDone = false;

  function escapeHtml(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/"/g, "&quot;");
  }

  function queryGameId() {
    return new URLSearchParams(window.location.search).get("game") || "";
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

  function tierClass(tier) {
    const t = String(tier || "NONE").toUpperCase();
    if (t === "HIGH") return "is-high";
    if (t === "MEDIUM") return "is-medium";
    return "is-none";
  }

  function tierLabel(tier) {
    const t = String(tier || "").toUpperCase();
    if (t === "HIGH") return "High";
    if (t === "MEDIUM") return "Medium";
    return "";
  }

  function suitCodeBadge(code) {
    const key = String(code);
    const info = meta[key] || {};
    const color = info.color || "";
    return (
      '<span class="winner-hint-suit"' +
      (color ? ' style="color:' + escapeHtml(color) + '"' : "") +
      ">" +
      escapeHtml(key) +
      "</span>"
    );
  }

  function formatTailAsWinners(tail) {
    const text = String(tail || "").trim();
    if (!text) return "—";
    return text.replace(/\s+/g, " ");
  }

  function pickCode(item) {
    if (item.pick != null && item.pick !== "") {
      return String(item.pick);
    }
    return "";
  }

  function winnerCode(item, kind) {
    if (kind === "actual") {
      if (item.actual_winner != null && item.actual_winner !== "") {
        return String(item.actual_winner);
      }
    }
    return pickCode(item);
  }

  function renderPatterns(patterns) {
    if (!patterns || !patterns.length) {
      return "";
    }
    return (
      '<div class="confidence-patterns-block">' +
      '<p class="confidence-meta muted">Pattern(s) that matched in history:</p>' +
      patterns
        .map(function (p) {
          const winners = formatTailAsWinners(p.tail);
          const cases = p.match_count || 0;
          const hits = p.next_count || 0;
          const pct = p.next_pct || 0;
          const caseWord = cases === 1 ? "game" : "games";
          return (
            '<p class="confidence-pattern">' +
            "<strong>Last " +
            escapeHtml(String(p.length)) +
            " winners:</strong> <code>" +
            escapeHtml(winners) +
            "</code><br>" +
            "In " +
            escapeHtml(String(cases)) +
            " similar " +
            caseWord +
            ", next winner was " +
            suitCodeBadge(p.next_code) +
            " " +
            escapeHtml(String(hits)) +
            "/" +
            escapeHtml(String(cases)) +
            " (" +
            escapeHtml(String(pct)) +
            "%)</p>"
          );
        })
        .join("") +
      "</div>"
    );
  }

  function renderAllRows(rows) {
    if (!rows || !rows.length) {
      return "";
    }
    const lines = rows
      .map(function (row) {
        const matches = row.match_count || 0;
        const winners = formatTailAsWinners(row.tail);
        if (!matches) {
          return (
            '<p class="confidence-row-snap muted">' +
            "<strong>Last " +
            escapeHtml(String(row.length)) +
            ":</strong> <code>" +
            escapeHtml(winners) +
            "</code> · no similar games in history</p>"
          );
        }
        const best = row.best_next_code
          ? suitCodeBadge(row.best_next_code) +
            " " +
            escapeHtml(String(row.best_next_count || 0)) +
            "/" +
            escapeHtml(String(matches)) +
            " (" +
            escapeHtml(String(row.best_next_pct || 0)) +
            "%)"
          : "—";
        return (
          '<p class="confidence-row-snap">' +
          "<strong>Last " +
          escapeHtml(String(row.length)) +
          ":</strong> <code>" +
          escapeHtml(winners) +
          "</code> · " +
          escapeHtml(String(matches)) +
          " similar game(s) · best next " +
          best +
          "</p>"
        );
      })
      .join("");
    return (
      '<details class="confidence-details">' +
      "<summary>All history lengths checked (6–10 past winners)</summary>" +
      lines +
      "</details>"
    );
  }

  function hasOutcome(item) {
    return Boolean(
      item.outcome_text || item.actual_winner_label || item.actual_winner != null
    );
  }

  function isRecentForecast(item) {
    if (!item.at) return false;
    const d = new Date(item.at);
    if (isNaN(d.getTime())) return false;
    return Date.now() - d.getTime() < 3 * 60 * 60 * 1000;
  }

  function pendingOutcomeMessage(item) {
    if (isRecentForecast(item)) {
      return "Game still in progress";
    }
    return "Result not recorded";
  }

  function isDisplayable(item) {
    const tier = String(item.tier || "NONE").toUpperCase();
    const pick = item.pick != null && item.pick !== "";
    const streak = item.streak || null;
    const streakTier = String((streak && streak.tier) || "NONE").toUpperCase();
    const streakPick = streak && streak.pick != null && streak.pick !== "";
    if (item.notified && (pick || streakPick)) return true;
    if (DISPLAY_TIERS[tier] && pick) return true;
    if (DISPLAY_TIERS[streakTier] && streakPick) return true;
    if (!pick && !streakPick) return false;
    if (hasOutcome(item)) return true;
    return isRecentForecast(item);
  }

  function findItem(items, gameId) {
    if (!gameId) return null;
    return (
      items.find(function (item) {
        return String(item.game_id || "") === String(gameId);
      }) || null
    );
  }

  function renderEmptyMessage() {
    return (
      '<p class="muted">No forecasts yet. When live play shows a clear historical pattern, it will appear here.</p>'
    );
  }

  function renderNoForecastFocus(gameId, item) {
    let html =
      '<article class="confidence-item is-none is-focused" id="forecast-game-' +
      escapeAttr(gameId) +
      '" data-forecast-game="' +
      escapeAttr(gameId) +
      '">' +
      '<div class="confidence-item-top">' +
      '<span class="confidence-tier">No forecast</span>' +
      (item && item.at
        ? '<span class="confidence-when">' + escapeHtml(formatWhen(item.at)) + "</span>"
        : "") +
      "</div>" +
      '<p class="confidence-game">Live game #' +
      escapeHtml(gameId) +
      "</p>" +
      '<p class="confidence-headline muted">No forecast was made — past games did not show a clear next winner.</p>';
    if (item && (item.outcome_text || item.actual_winner_label)) {
      html +=
        '<p class="confidence-outcome">' + escapeHtml(formatOutcome(item)) + "</p>";
    }
    html += "</article>";
    return html;
  }

  function formatOutcome(item) {
    const actual = winnerCode(item, "actual");
    const predicted = pickCode(item);
    if (!actual && item.outcome_text) {
      return item.outcome_text.replace(/\s*\(\d+\)/g, "");
    }
    if (!actual) return "";
    if (item.pick_correct === true) {
      return "Result: " + actual + " won — forecast was right";
    }
    if (item.pick_correct === false && predicted) {
      return "Result: " + actual + " won — we picked " + predicted;
    }
    return "Result: " + actual + " won";
  }

  function renderStreak(streak) {
    if (!streak || !streak.length) {
      return "";
    }
    const suitCode = streak.suit_code != null ? String(streak.suit_code) : "";
    const tier = String(streak.tier || "NONE").toUpperCase();
    const pick = streak.pick != null && streak.pick !== "" ? String(streak.pick) : "";
    if (!DISPLAY_TIERS[tier] && !streak.notified && !pick) {
      return (
        '<div class="confidence-patterns-block">' +
        '<p class="confidence-meta muted">Streak check: ' +
        escapeHtml(String(streak.length)) +
        "× " +
        escapeHtml(suitCode || "?") +
        " — no strong next-winner signal</p></div>"
      );
    }
    return (
      '<div class="confidence-patterns-block">' +
      '<p class="confidence-meta muted">Same-winner streak:</p>' +
      '<p class="confidence-pattern">' +
      "<strong>" +
      escapeHtml(String(streak.length)) +
      "× " +
      escapeHtml(streak.suit_label || suitCode || "?") +
      " (" +
      escapeHtml(suitCode || "?") +
      ")</strong>" +
      (pick
        ? "<br>Likely next: " +
          suitCodeBadge(pick) +
          " · " +
          escapeHtml(String(streak.confidence_pct || 0)) +
          "% · " +
          escapeHtml(tier)
        : "") +
      (streak.match_count
        ? "<br>" +
          escapeHtml(String(streak.match_count)) +
          " similar streak(s) in history"
        : "") +
      (streak.pick_correct === true
        ? '<br><span class="confidence-outcome is-correct">Streak pick was right</span>'
        : streak.pick_correct === false
          ? '<br><span class="confidence-outcome is-wrong">Streak pick was wrong</span>'
          : "") +
      "</p></div>"
    );
  }

  function renderAccuracy(stats) {
    if (!accuracyEl) return;
    if (!stats || !stats.resolved) {
      accuracyEl.textContent =
        "Streak accuracy: no finished streak forecasts yet (updates after games complete).";
      return;
    }
    const pct = stats.accuracy_pct != null ? String(stats.accuracy_pct) + "%" : "—";
    accuracyEl.innerHTML =
      "<strong>Streak accuracy: " +
      escapeHtml(pct) +
      "</strong> — " +
      escapeHtml(String(stats.correct)) +
      " correct / " +
      escapeHtml(String(stats.resolved)) +
      " resolved" +
      (stats.wrong ? " (" + escapeHtml(String(stats.wrong)) + " wrong)" : "");
  }

  function renderItem(item) {
    const tier = String(item.tier || "NONE").toUpperCase();
    const pick = item.pick;
    const pickCodeText = pick != null && pick !== "" ? String(pick) : "—";
    const pickColor = (meta[String(pick)] && meta[String(pick)].color) || "#ddd";
    const gameId = String(item.game_id || "");
    const label = tierLabel(tier);
    const streak = item.streak || null;
    return (
      '<article class="confidence-item ' +
      tierClass(tier) +
      '" id="forecast-game-' +
      escapeAttr(gameId) +
      '" data-forecast-game="' +
      escapeAttr(gameId) +
      '">' +
      '<div class="confidence-item-top">' +
      (label ? '<span class="confidence-tier">' + escapeHtml(label) + "</span>" : "") +
      (item.notified ? '<span class="confidence-notified">Alert sent</span>' : "") +
      '<span class="confidence-when">' +
      escapeHtml(formatWhen(item.at)) +
      "</span>" +
      "</div>" +
      '<p class="confidence-game">Live game #' +
      escapeHtml(gameId || "?") +
      "</p>" +
      '<p class="confidence-headline" style="color:' +
      escapeHtml(pickColor) +
      '">' +
      "Likely next winner: " +
      escapeHtml(pickCodeText) +
      "</p>" +
      '<p class="confidence-meta muted">' +
      escapeHtml(String(item.confidence_pct || 0)) +
      "% from history · " +
      escapeHtml(String(item.total_cases || 0)) +
      " similar game(s)" +
      (item.has_conflict ? " · mixed signals" : "") +
      "</p>" +
      renderStreak(streak) +
      renderPatterns(item.patterns || []) +
      renderAllRows(item.all_rows || []) +
      (hasOutcome(item)
        ? '<p class="confidence-outcome' +
          (item.pick_correct === true
            ? " is-correct"
            : item.pick_correct === false
              ? " is-wrong"
              : "") +
          '">' +
          escapeHtml(formatOutcome(item)) +
          "</p>"
        : '<p class="confidence-outcome is-pending muted">' +
          escapeHtml(pendingOutcomeMessage(item)) +
          "</p>") +
      "</article>"
    );
  }

  function focusGame(gameId, options) {
    const scroll = !options || options.scroll !== false;
    if (!gameId || !listEl) return false;
    const el = document.getElementById("forecast-game-" + gameId);
    if (!el) return false;
    listEl.querySelectorAll(".confidence-item.is-focused").forEach(function (node) {
      node.classList.remove("is-focused");
    });
    el.classList.add("is-focused");
    if (scroll) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    return true;
  }

  function captureListState() {
    if (!listEl) {
      return { scrollY: window.scrollY, anchor: null };
    }
    const viewportTop = window.scrollY;
    let anchor = null;
    const items = listEl.querySelectorAll(".confidence-item");
    for (let i = 0; i < items.length; i++) {
      const rect = items[i].getBoundingClientRect();
      const top = rect.top + window.scrollY;
      if (top + rect.height > viewportTop + 1) {
        anchor = {
          gameId: items[i].getAttribute("data-forecast-game"),
          offset: viewportTop - top,
        };
        break;
      }
    }
    return {
      scrollY: window.scrollY,
      anchor: anchor,
    };
  }

  function restoreListState(state) {
    if (!state) return;
    if (state.anchor && state.anchor.gameId && listEl) {
      const el = listEl.querySelector('[data-forecast-game="' + state.anchor.gameId + '"]');
      if (el) {
        const top = el.getBoundingClientRect().top + window.scrollY;
        window.scrollTo(0, top + state.anchor.offset);
        return;
      }
    }
    window.scrollTo(0, state.scrollY);
  }

  function renderList(items, focusId) {
    if (!listEl) return;
    const visible = items.filter(isDisplayable);
    const focusRaw = focusId ? findItem(items, focusId) : null;
    const focusVisible = focusId ? findItem(visible, focusId) : null;

    if (!visible.length && !focusRaw) {
      listEl.innerHTML = renderEmptyMessage();
      return;
    }

    let html = visible.map(renderItem).join("");
    if (focusId && focusRaw && !focusVisible) {
      html = renderNoForecastFocus(focusId, focusRaw) + html;
    }
    if (!html) {
      listEl.innerHTML = renderEmptyMessage();
      return;
    }
    listEl.innerHTML = html;
  }

  async function refresh() {
    try {
      const data = await live.get("/api/winner-confidence?limit=200");
      const items = data.items || [];
      renderAccuracy(data.streak_accuracy || null);
      const focusId = queryGameId();
      const visible = items.filter(isDisplayable);
      const willInitialFocus = Boolean(focusId && !initialFocusDone);
      const listState = willInitialFocus ? null : captureListState();
      if (statusEl) {
        if (!visible.length && !(focusId && findItem(items, focusId))) {
          statusEl.textContent = "No forecasts yet";
        } else if (focusId && findItem(items, focusId)) {
          statusEl.textContent = visible.length + " forecast(s) · game #" + focusId;
        } else {
          statusEl.textContent = visible.length + " forecast(s)";
        }
      }
      renderList(items, focusId);
      requestAnimationFrame(function () {
        if (focusId) {
          const scroll = !initialFocusDone;
          if (focusGame(focusId, { scroll: scroll })) {
            initialFocusDone = true;
          } else if (!initialFocusDone && statusEl) {
            statusEl.textContent = "Game #" + focusId + " not found.";
          }
        }
        if (listState) {
          restoreListState(listState);
        }
      });
    } catch (_e) {
      if (statusEl) statusEl.textContent = "Could not load forecasts.";
    }
  }

  refresh();
  setInterval(refresh, 10000);
})();
