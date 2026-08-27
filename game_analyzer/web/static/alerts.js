(function () {
  const live = window.gameAnalyzerLive;
  if (!live) return;

  const bell = document.querySelector("[data-alert-bell]");
  const panel = document.querySelector("[data-alert-panel]");
  const list = document.querySelector("[data-alert-list]");
  const badge = document.querySelector("[data-alert-badge]");
  const status = document.querySelector("[data-alert-status]");
  const soundBtn = document.querySelector("[data-alert-sound]");
  const pushBtn = document.querySelector("[data-alert-push]");
  const wrap = document.querySelector("[data-alert-wrap]");
  if (!bell || !panel || !list) return;

  const SOUND_KEY = "ga_alert_sound";
  const PUSH_KEY = "ga_alert_push";
  const SEEN_KEY = "ga_alert_seen";

  let soundOn = localStorage.getItem(SOUND_KEY) === "1";
  let pushOn = localStorage.getItem(PUSH_KEY) === "1";
  let lastAlertId = null;
  let alertPrimed = false;
  let recent = [];
  let unseen = 0;
  let audioCtx = null;
  let open = false;

  function syncSoundButton() {
    if (!soundBtn) return;
    soundBtn.textContent = soundOn ? "Sound on" : "Enable sound";
    soundBtn.classList.toggle("is-on", soundOn);
  }

  function syncPushButton() {
    if (!pushBtn) return;
    if (!("Notification" in window)) {
      pushBtn.hidden = true;
      return;
    }
    pushBtn.hidden = false;
    const perm = Notification.permission;
    if (perm === "denied") {
      pushBtn.textContent = "Notify blocked";
      pushBtn.disabled = true;
      pushBtn.classList.remove("is-on");
      return;
    }
    pushBtn.disabled = false;
    const active = pushOn && perm === "granted";
    pushBtn.textContent = active ? "Notify on" : "Enable notify";
    pushBtn.classList.toggle("is-on", active);
  }

  function setBadge(count) {
    if (!badge) return;
    if (!count) {
      badge.hidden = true;
      badge.textContent = "";
      bell.classList.remove("has-new");
      return;
    }
    badge.hidden = false;
    badge.textContent = count > 9 ? "9+" : String(count);
    bell.classList.add("has-new");
  }

  function ensureAudio() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }

  function playAlertBeep() {
    const ctx = ensureAudio();
    if (!ctx) return;
    const now = ctx.currentTime;
    [0, 0.18].forEach(function (offset, i) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = i === 0 ? 880 : 1175;
      gain.gain.setValueAtTime(0.0001, now + offset);
      gain.gain.exponentialRampToValueAtTime(0.18, now + offset + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.16);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now + offset);
      osc.stop(now + offset + 0.18);
    });
  }

  function showBrowserNotify(alert) {
    if (!pushOn || !("Notification" in window)) return;
    if (Notification.permission !== "granted") return;
    try {
      const n = new Notification("Game Analyzer — " + (alert.kind || "alert").toUpperCase(), {
        body: alert.message || "New alert",
        tag: alert.id || "ga-alert",
        renotify: true,
      });
      n.onclick = function () {
        window.focus();
        if (alert.link) {
          window.location.href = alert.link;
        } else if ((alert.kind || "").indexOf("twin-r") === 0) {
          window.location.href = "/similar";
        }
        try {
          n.close();
        } catch (_e) {}
      };
      setTimeout(function () {
        try {
          n.close();
        } catch (_e) {}
      }, 8000);
    } catch (_e) {}
  }

  function formatWhen(at) {
    if (!at) return "";
    try {
      const d = new Date(at);
      if (isNaN(d.getTime())) return at;
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    } catch (_e) {
      return at;
    }
  }

  function displayMessage(row) {
    let msg = row.message || "";
    if (row.link && msg.indexOf(" · link=") >= 0) {
      msg = msg.split(" · link=")[0];
    }
    return msg;
  }

  function isSimilarityKind(kind) {
    const k = (kind || "").toLowerCase();
    return k.indexOf("twin-r") === 0;
  }

  function renderList(rows) {
    const twins = (rows || []).filter(function (row) {
      return isSimilarityKind(row.kind);
    });
    if (!twins.length) {
      list.innerHTML = '<p class="muted">No similarity twins yet.</p>';
      return;
    }
    list.innerHTML = twins
      .slice(0, 5)
      .map(function (row) {
        const kind = (row.kind || "twin-r3").toLowerCase();
        const link = row.link || "/similar";
        const clickable = ' data-alert-link="' + link + '" role="link" tabindex="0"';
        return (
          '<article class="alert-item is-' +
          kind +
          ' is-link"' +
          clickable +
          '><span class="alert-item-kind">' +
          (row.kind || "twin").toUpperCase() +
          '</span><span class="alert-item-when">' +
          formatWhen(row.at) +
          '</span><p class="alert-item-msg">' +
          displayMessage(row) +
          '<span class="alert-item-go">Open Similar →</span></p></article>'
        );
      })
      .join("");
    list.querySelectorAll("[data-alert-link]").forEach(function (el) {
      el.addEventListener("click", function () {
        const href = el.getAttribute("data-alert-link");
        if (href) window.location.href = href;
      });
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          const href = el.getAttribute("data-alert-link");
          if (href) window.location.href = href;
        }
      });
    });
  }

  function updateStatus(alerts) {
    if (!status) return;
    const n = ((alerts && alerts.recent) || []).filter(function (row) {
      return isSimilarityKind(row.kind);
    }).length;
    status.textContent = n ? "Latest " + n + " · R3–R5 twins" : "No twins yet";
  }

  function placePanel() {
    if (!panel || !bell) return;
    const pad = 12;
    const rect = bell.getBoundingClientRect();
    const vw = window.innerWidth || document.documentElement.clientWidth;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    panel.style.maxWidth = Math.max(200, vw - pad * 2) + "px";
    panel.style.maxHeight = Math.max(160, vh - pad * 2) + "px";
    // Measure after making visible (caller unhides first).
    const pw = panel.offsetWidth || Math.min(360, vw - pad * 2);
    const ph = panel.offsetHeight || 240;
    let left = rect.left;
    let top = rect.bottom + 8;
    if (left + pw > vw - pad) left = vw - pad - pw;
    if (left < pad) left = pad;
    if (top + ph > vh - pad) {
      // Prefer above the bell when not enough room below.
      const above = rect.top - 8 - ph;
      top = above >= pad ? above : Math.max(pad, vh - pad - ph);
    }
    panel.style.left = Math.round(left) + "px";
    panel.style.top = Math.round(top) + "px";
  }

  function setOpen(next) {
    open = next;
    panel.hidden = !open;
    bell.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) {
      unseen = 0;
      setBadge(0);
      if (lastAlertId) localStorage.setItem(SEEN_KEY, lastAlertId);
      renderList(recent);
      placePanel();
      // Re-measure after list paint (height can grow).
      requestAnimationFrame(placePanel);
    }
  }

  function onNewAlert(alert) {
    if (soundOn) playAlertBeep();
    showBrowserNotify(alert);
    if (navigator.vibrate) {
      try {
        navigator.vibrate([80, 40, 80]);
      } catch (_e) {}
    }
    if (!open) {
      unseen += 1;
      setBadge(unseen);
    }
  }

  function applyAlerts(alerts) {
    recent = ((alerts && alerts.recent) || []).filter(function (row) {
      return isSimilarityKind(row.kind);
    });
    updateStatus({ recent: recent });
    if (open) renderList(recent);
    const latest =
      (alerts && alerts.latest && isSimilarityKind(alerts.latest.kind) && alerts.latest) ||
      recent[0] ||
      null;
    if (!alertPrimed) {
      alertPrimed = true;
      if (latest && latest.id) {
        lastAlertId = latest.id;
        const seen = localStorage.getItem(SEEN_KEY);
        if (seen !== latest.id && !open) {
          unseen = 1;
          setBadge(1);
        }
      }
      return;
    }
    if (!latest || !latest.id || latest.id === lastAlertId) return;
    lastAlertId = latest.id;
    onNewAlert(latest);
  }

  async function refresh() {
    try {
      const data = await live.get("/api/alerts?limit=5");
      applyAlerts(data);
    } catch (_e) {}
  }

  bell.addEventListener("click", function (e) {
    e.stopPropagation();
    setOpen(!open);
    if (open) refresh();
  });

  document.addEventListener("click", function (e) {
    if (!open) return;
    if (wrap && wrap.contains(e.target)) return;
    setOpen(false);
  });

  window.addEventListener("resize", function () {
    if (open) placePanel();
  });
  window.addEventListener(
    "scroll",
    function () {
      if (open) placePanel();
    },
    true
  );

  if (soundBtn) {
    soundBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      soundOn = !soundOn;
      localStorage.setItem(SOUND_KEY, soundOn ? "1" : "0");
      syncSoundButton();
      if (soundOn) {
        ensureAudio();
        playAlertBeep();
      }
    });
  }

  if (pushBtn) {
    pushBtn.addEventListener("click", async function (e) {
      e.stopPropagation();
      if (!("Notification" in window)) return;
      if (Notification.permission === "denied") {
        syncPushButton();
        return;
      }
      if (Notification.permission !== "granted") {
        const perm = await Notification.requestPermission();
        pushOn = perm === "granted";
      } else {
        pushOn = !pushOn;
      }
      localStorage.setItem(PUSH_KEY, pushOn ? "1" : "0");
      syncPushButton();
      if (pushOn && Notification.permission === "granted") {
        try {
          new Notification("Game Analyzer", {
            body: "Similarity twin alerts enabled",
            tag: "ga-alert-test",
          });
        } catch (_e) {}
      }
    });
  }

  syncSoundButton();
  syncPushButton();
  refresh();
  setInterval(refresh, 2000);
})();
