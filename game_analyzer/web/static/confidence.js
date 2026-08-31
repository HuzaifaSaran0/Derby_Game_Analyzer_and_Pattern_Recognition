(function () {
  const live = window.gameAnalyzerLive;
  if (!live) return;

  const statusEl = document.querySelector("[data-confidence-status]");
  const listEl = document.querySelector("[data-confidence-list]");

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

  function suitCode(code) {
    const key = String(code);
    const info = meta[key] || {};
    const color = info.color || "";
    return (
      '<span class="winner-hint-suit"' +
      (color ? ' style="color:' + color + '"' : "") +
      ">" +
      escapeHtml(key) +
      "</span>"
    );
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
    if (t === "LOW") return "is-low";
    return "is-none";
  }

  function renderPatterns(patterns) {
    if (!patterns || !patterns.length) {
      return '<p class="muted">No trusted supporting patterns.</p>';
    }
    return patterns
      .map(function (p) {
        return (
          '<p class="confidence-pattern">' +
          "<strong>Last " +
          escapeHtml(String(p.length)) +
          "</strong> " +
          "<code>" +
          escapeHtml(p.tail || "") +
          "</code> · " +
          escapeHtml(String(p.next_count || 0)) +
          "/" +
          escapeHtml(String(p.match_count || 0)) +
          " history → " +
          suitCode(p.next_code) +
          " (" +
          escapeHtml(String(p.next_pct || 0)) +
          "%)</p>"
        );
      })
      .join("");
  }

  function renderAllRows(rows) {
    if (!rows || !rows.length) return "";
    return (
      '<details class="confidence-details">' +
      "<summary>All lengths 4–10 snapshot</summary>" +
      rows
        .map(function (row) {
          const matches = row.match_count || 0;
          const tail = row.tail || "—";
          const best = row.best_next_code
            ? suitCode(row.best_next_code) +
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
            "</strong> " +
            "<code>" +
            escapeHtml(tail) +
            "</code> · " +
            escapeHtml(String(matches)) +
            " matches · best next " +
            best +
            "</p>"
          );
        })
        .join("") +
      "</details>"
    );
  }

  function renderItem(item) {
    const tier = String(item.tier || "NONE").toUpperCase();
    const pick = item.pick;
    const pickLabel = item.pick_label || "—";
    const pickColor = (meta[String(pick)] && meta[String(pick)].color) || "#ddd";
    const headline = pick
      ? pickLabel + " (" + pick + ") — " + (item.confidence_pct || 0) + "%"
      : "No clear pick";
    return (
      '<article class="confidence-item ' +
      tierClass(tier) +
      '">' +
      '<div class="confidence-item-top">' +
      '<span class="confidence-tier">' +
      escapeHtml(tier) +
      "</span>" +
      (item.notified ? '<span class="confidence-notified">Notified</span>' : "") +
      '<span class="confidence-when">' +
      escapeHtml(formatWhen(item.at)) +
      "</span>" +
      "</div>" +
      '<p class="confidence-game">Live game #' +
      escapeHtml(String(item.game_id || "?")) +
      "</p>" +
      '<p class="confidence-headline" style="color:' +
      escapeHtml(pickColor) +
      '">' +
      escapeHtml(headline) +
      "</p>" +
      '<p class="confidence-meta muted">' +
      escapeHtml(String(item.supporting_count || 0)) +
      " supporting pattern(s) · " +
      escapeHtml(String(item.total_cases || 0)) +
      " historical cases" +
      (item.has_conflict ? " · conflicting signals" : "") +
      "</p>" +
      (item.outcome_text
        ? '<p class="confidence-outcome' +
          (item.pick_correct === true
            ? " is-correct"
            : item.pick_correct === false
              ? " is-wrong"
              : "") +
          '">' +
          escapeHtml(item.outcome_text) +
          "</p>"
        : '<p class="confidence-outcome is-pending muted">Actual winner pending — game not finished yet</p>') +
      (item.skipped_reason && !item.pick
        ? '<p class="confidence-note muted">' + escapeHtml(item.skipped_reason) + "</p>"
        : "") +
      renderPatterns(item.patterns || []) +
      renderAllRows(item.all_rows || []) +
      "</article>"
    );
  }

  function renderList(items) {
    if (!listEl) return;
    if (!items.length) {
      listEl.innerHTML = '<p class="muted">No confidence records yet. Start a live capture to build history.</p>';
      return;
    }
    listEl.innerHTML = items.map(renderItem).join("");
  }

  async function refresh() {
    try {
      const data = await live.get("/api/winner-confidence?limit=200");
      const items = data.items || [];
      if (statusEl) {
        statusEl.textContent = items.length
          ? items.length + " live game record(s)"
          : "No records yet";
      }
      renderList(items);
    } catch (_e) {
      if (statusEl) statusEl.textContent = "Could not load confidence history.";
    }
  }

  refresh();
  setInterval(refresh, 10000);
})();
