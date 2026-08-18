window.gameAnalyzerLive = {
  POLL_MS: 1500,
  async get(path) {
    const url = path + (path.indexOf("?") >= 0 ? "&" : "?") + "_=" + Date.now();
    const response = await fetch(url, {
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        "ngrok-skip-browser-warning": "1",
      },
    });
    if (!response.ok) {
      throw new Error("HTTP " + response.status);
    }
    const type = response.headers.get("content-type") || "";
    if (type.indexOf("application/json") < 0) {
      throw new Error("not json");
    }
    return response.json();
  },
  stamp(ok, detail) {
    const el = document.querySelector("[data-live-status]");
    if (!el) return;
    const time = new Date().toLocaleTimeString();
    el.textContent = (ok ? "Live · " : "Retrying · ") + time + (detail ? " · " + detail : "");
    el.classList.toggle("is-offline", !ok);
  },
  start(tick) {
    const loop = async () => {
      try {
        await tick();
      } finally {
        setTimeout(loop, this.POLL_MS);
      }
    };
    loop();
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) tick();
    });
    window.addEventListener("pageshow", () => tick());
    window.addEventListener("focus", () => tick());
  },
};
