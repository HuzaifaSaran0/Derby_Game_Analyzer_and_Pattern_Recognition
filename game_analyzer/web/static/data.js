(function () {
  const live = window.gameAnalyzerLive;
  if (!live) return;

  const statsHost = document.querySelector("[data-data-stats]");
  const exportBtn = document.querySelector("[data-data-export]");
  const exportStatus = document.querySelector("[data-export-status]");
  const fileInput = document.querySelector("[data-data-file]");
  const importBtn = document.querySelector("[data-data-import]");
  const importStatus = document.querySelector("[data-import-status]");

  function formatBytes(n) {
    if (!n && n !== 0) return "—";
    var units = ["B", "KB", "MB", "GB"];
    var v = Number(n);
    var i = 0;
    while (v >= 1024 && i < units.length - 1) {
      v /= 1024;
      i += 1;
    }
    return (i === 0 ? v.toFixed(0) : v.toFixed(1)) + " " + units[i];
  }

  function showStatus(el, text, ok) {
    if (!el) return;
    el.hidden = false;
    el.textContent = text;
    el.classList.remove("auth-error", "auth-success");
    el.classList.add(ok ? "auth-success" : "auth-error");
  }

  function renderStats(data) {
    if (!statsHost) return;
    statsHost.innerHTML =
      '<ul class="data-stat-list">' +
      "<li><strong>" +
      (data.games || 0) +
      "</strong> games · <strong>" +
      (data.frames || 0) +
      "</strong> frames · <strong>" +
      (data.finished_games || 0) +
      "</strong> finished</li>" +
      "<li><strong>" +
      (data.screenshot_files || 0) +
      "</strong> screenshots · " +
      formatBytes(data.screenshot_bytes || 0) +
      "</li>" +
      "<li>Twin cache: " +
      (data.cache_present
        ? "ready (" + (data.trusted_twin_sets || 0) + " sets)"
        : "will build on next Similar visit") +
      (data.cache_built_at ? " · built " + data.cache_built_at : "") +
      "</li></ul>";
  }

  async function loadStats() {
    try {
      const data = await live.get("/api/data/status");
      renderStats(data);
    } catch (_err) {
      if (statsHost) statsHost.innerHTML = '<p class="auth-error">Could not load data summary.</p>';
    }
  }

  async function exportBackup() {
    if (!exportBtn) return;
    exportBtn.disabled = true;
    if (exportStatus) {
      exportStatus.hidden = false;
      exportStatus.textContent = "Preparing backup…";
      exportStatus.className = "data-hint muted";
    }
    try {
      const resp = await fetch("/api/data/export", { credentials: "same-origin" });
      if (!resp.ok) throw new Error("Export failed (" + resp.status + ")");
      const blob = await resp.blob();
      const dispo = resp.headers.get("Content-Disposition") || "";
      var name = "game_analyzer_backup.zip";
      var match = dispo.match(/filename=\"?([^\";]+)/i);
      if (match) name = match[1];
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      showStatus(exportStatus, "Backup downloaded.", true);
    } catch (err) {
      showStatus(exportStatus, err.message || "Export failed.", false);
    } finally {
      exportBtn.disabled = false;
    }
  }

  async function importBackup() {
    if (!fileInput || !fileInput.files || !fileInput.files[0]) return;
    const file = fileInput.files[0];
    importBtn.disabled = true;
    if (exportBtn) exportBtn.disabled = true;
    if (importStatus) {
      importStatus.hidden = false;
      importStatus.textContent = "Uploading and importing…";
      importStatus.className = "data-hint muted";
    }
    try {
      const resp = await fetch("/api/data/import", {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: file,
        credentials: "same-origin",
      });
      const data = await resp.json();
      if (!resp.ok || !data.ok) {
        throw new Error((data && data.message) || "Import failed.");
      }
      showStatus(importStatus, data.message || "Import complete.", true);
      fileInput.value = "";
      importBtn.disabled = true;
      await loadStats();
    } catch (err) {
      showStatus(importStatus, err.message || "Import failed.", false);
    } finally {
      if (exportBtn) exportBtn.disabled = false;
      if (fileInput.files && fileInput.files[0]) importBtn.disabled = false;
    }
  }

  if (fileInput && importBtn) {
    fileInput.addEventListener("change", function () {
      importBtn.disabled = !(fileInput.files && fileInput.files[0]);
    });
    importBtn.addEventListener("click", importBackup);
  }
  if (exportBtn) exportBtn.addEventListener("click", exportBackup);

  loadStats();
})();
