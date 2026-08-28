(function () {
  const live = window.gameAnalyzerLive;
  const notifs = window.gameAnalyzerNotifs;
  if (!live || !notifs) return;

  const bell = document.querySelector("[data-alert-bell]");
  const panel = document.querySelector("[data-alert-panel]");
  const list = document.querySelector("[data-alert-list]");
  const badge = document.querySelector("[data-alert-badge]");
  const status = document.querySelector("[data-alert-status]");
  const soundBtn = document.querySelector("[data-alert-sound]");
  const markReadBtn = document.querySelector("[data-alert-mark-read]");
  const wrap = document.querySelector("[data-alert-wrap]");
  if (!bell || !panel || !list) return;

  const SOUND_KEY = "ga_alert_sound";
  const LIVE_SEEN_KEY = "ga_live_alert_seen";

  let soundOn = localStorage.getItem(SOUND_KEY) === "1";
  let items = [];
  let open = false;
  let audioCtx = null;
  let lastLiveAlertId = null;
  let livePrimed = false;
  let notifsPrimed = false;

  function syncSoundButton() {
    if (!soundBtn) return;
    soundBtn.textContent = soundOn ? "Sound on" : "Enable sound";
    soundBtn.classList.toggle("is-on", soundOn);
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

  function updateBadge() {
    setBadge(notifs.unreadCount(items));
  }

  function updateStatus() {
    if (!status) return;
    const unread = notifs.unreadCount(items);
    const total = items.length;
    if (!total) {
      status.textContent = "No R3 twins";
      return;
    }
    status.textContent = unread ? unread + " unread · " + total + " total" : total + " notifications";
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

  function escapeAttr(text) {
    return String(text || "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function renderList() {
    if (!items.length) {
      list.innerHTML = '<p class="muted alert-empty">No R3 twin notifications yet.</p>';
      if (markReadBtn) markReadBtn.disabled = true;
      return;
    }
    if (markReadBtn) markReadBtn.disabled = notifs.unreadCount(items) === 0;
    list.innerHTML = items
      .map(function (row) {
        const read = notifs.isRead(row.id);
        const cls = read ? "is-read" : "is-unread";
        return (
          '<article class="alert-item is-twin-r3 is-link ' +
          cls +
          '" data-notif-id="' +
          escapeAttr(row.id) +
          '" data-notif-link="' +
          escapeAttr(row.link || "/similar") +
          '" role="link" tabindex="0">' +
          '<div class="alert-item-top">' +
          '<span class="alert-item-kind">R3 TWIN</span>' +
          (read ? "" : '<span class="alert-item-dot" aria-hidden="true"></span>') +
          "</div>" +
          '<p class="alert-item-title">' +
          escapeAttr(row.title || "R3 twin") +
          "</p>" +
          '<p class="alert-item-msg">' +
          escapeAttr(row.message || "") +
          "</p></article>"
        );
      })
      .join("");

    list.querySelectorAll("[data-notif-id]").forEach(function (el) {
      function go() {
        const id = el.getAttribute("data-notif-id");
        const href = el.getAttribute("data-notif-link");
        notifs.markRead(id);
        updateBadge();
        updateStatus();
        renderList();
        if (href) window.location.href = href;
      }
      el.addEventListener("click", go);
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          go();
        }
      });
    });
  }

  function detectNewItems(nextItems) {
    const ids = nextItems.map(function (row) {
      return row.id;
    });
    if (!notifsPrimed) {
      notifsPrimed = true;
      notifs.saveKnown(ids);
      return;
    }
    const known = notifs.loadKnown();
    let hasNew = false;
    ids.forEach(function (id) {
      if (!known.has(id)) {
        hasNew = true;
        known.add(id);
      }
    });
    notifs.saveKnown(known);
    if (hasNew && soundOn) playAlertBeep();
  }

  function applyItems(nextItems) {
    items = nextItems || [];
    detectNewItems(items);
    updateBadge();
    updateStatus();
    if (open) renderList();
  }

  function placePanel() {
    if (!panel || !bell) return;
    const pad = 12;
    const rect = bell.getBoundingClientRect();
    const vw = window.innerWidth || document.documentElement.clientWidth;
    const vh = window.innerHeight || document.documentElement.clientHeight;
    panel.style.maxWidth = Math.max(200, vw - pad * 2) + "px";
    panel.style.maxHeight = Math.max(160, vh - pad * 2) + "px";
    const pw = panel.offsetWidth || Math.min(360, vw - pad * 2);
    const ph = panel.offsetHeight || 280;
    let left = rect.left;
    let top = rect.bottom + 8;
    if (left + pw > vw - pad) left = vw - pad - pw;
    if (left < pad) left = pad;
    if (top + ph > vh - pad) {
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
      renderList();
      placePanel();
      requestAnimationFrame(placePanel);
    }
  }

  async function refreshNotifications() {
    try {
      const data = await live.get("/api/notifications");
      applyItems(data.items || []);
    } catch (_e) {}
  }

  async function pollLiveAlerts() {
    try {
      const data = await live.get("/api/alerts?limit=5");
      const latest = data && data.latest;
      if (!latest || !latest.id) return;
      const kind = (latest.kind || "").toLowerCase();
      if (kind.indexOf("twin-r") !== 0) return;
      if (!livePrimed) {
        livePrimed = true;
        lastLiveAlertId = latest.id;
        localStorage.setItem(LIVE_SEEN_KEY, latest.id);
        return;
      }
      if (latest.id === lastLiveAlertId) return;
      lastLiveAlertId = latest.id;
      await refreshNotifications();
      if (soundOn) playAlertBeep();
      if (navigator.vibrate) {
        try {
          navigator.vibrate([80, 40, 80]);
        } catch (_e) {}
      }
    } catch (_e) {}
  }

  bell.addEventListener("click", function (e) {
    e.stopPropagation();
    setOpen(!open);
    if (open) refreshNotifications();
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

  window.addEventListener("ganotifs:read", function () {
    updateBadge();
    updateStatus();
    if (open) renderList();
  });

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

  if (markReadBtn) {
    markReadBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      notifs.markAllRead(
        items.map(function (row) {
          return row.id;
        })
      );
      updateBadge();
      updateStatus();
      renderList();
    });
  }

  syncSoundButton();
  refreshNotifications();
  setInterval(refreshNotifications, 5000);
  setInterval(pollLiveAlerts, 2000);
})();
