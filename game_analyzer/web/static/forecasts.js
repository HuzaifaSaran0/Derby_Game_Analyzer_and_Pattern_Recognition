(function () {
  const live = window.gameAnalyzerLive;
  if (!live) return;

  const statusEl = document.querySelector("[data-confidence-status]");
  const listEl = document.querySelector("[data-confidence-list]");
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
    if (!DISPLAY_TIERS[tier] || !item.pick) return false;
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
    const actual = item.actual_winner_label || "";
    const predicted = item.pick_label || "";
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

  function renderItem(item) {
    const tier = String(item.tier || "NONE").toUpperCase();
    const pick = item.pick;
    const pickLabel = item.pick_label || "—";
    const pickColor = (meta[String(pick)] && meta[String(pick)].color) || "#ddd";
    const gameId = String(item.game_id || "");
    const label = tierLabel(tier);
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
      escapeHtml(pickLabel) +
      "</p>" +
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
