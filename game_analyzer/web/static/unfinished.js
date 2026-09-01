(function () {
  const summary = document.querySelector("[data-unfinished-summary]");
  const tableWrap = document.querySelector("[data-unfinished-table]");
  const refreshBtn = document.querySelector("[data-unfinished-refresh]");
  const cleanupBtn = document.querySelector("[data-unfinished-cleanup]");
  if (!summary || !tableWrap) return;

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderTable(items) {
    if (!items.length) {
      tableWrap.innerHTML = '<p class="muted">No unfinished games.</p>';
      return;
    }
    const rows = items
      .map(
        (row) =>
          `<tr>
            <td><a href="${escapeHtml(row.url)}">${escapeHtml(row.game_id)}</a></td>
            <td>${escapeHtml(row.started_at || "—")}</td>
            <td>${escapeHtml(String(row.shot_count))}</td>
          </tr>`
      )
      .join("");
    tableWrap.innerHTML = `<table class="unfinished-table">
      <thead><tr><th>Game ID</th><th>Started</th><th>Shots</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  }

  async function load() {
    summary.textContent = "Loading…";
    try {
      const res = await fetch("/api/unfinished", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      summary.textContent = `${data.total} unfinished game(s)`;
      renderTable(data.items || []);
    } catch (err) {
      summary.textContent = "Failed to load";
      tableWrap.innerHTML = `<p class="muted">Error: ${escapeHtml(err.message || err)}</p>`;
    }
  }

  async function cleanup() {
    if (
      !window.confirm(
        "Delete ALL games without a winner from the database? This cannot be undone."
      )
    ) {
      return;
    }
    cleanupBtn.disabled = true;
    try {
      const res = await fetch("/api/unfinished/cleanup", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      summary.textContent = `Deleted ${data.deleted}; ${data.remaining} remaining`;
      await load();
    } catch (err) {
      summary.textContent = `Cleanup failed: ${err.message || err}`;
    } finally {
      cleanupBtn.disabled = false;
    }
  }

  if (refreshBtn) refreshBtn.addEventListener("click", load);
  if (cleanupBtn) cleanupBtn.addEventListener("click", cleanup);
  load();
})();
