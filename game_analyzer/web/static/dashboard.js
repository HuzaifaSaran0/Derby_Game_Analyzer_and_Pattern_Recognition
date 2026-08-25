(function () {
  const live = window.gameAnalyzerLive;
  const cards = window.gameAnalyzerCards;
  if (!live || !cards) return;

  const idle = document.querySelector("[data-idle-hero]");
  const grid = document.querySelector("[data-live-grid]");
  const strip = document.querySelector("[data-confidence-strip]");
  const alertBanner = document.querySelector("[data-alert-banner]");
  const alertKind = document.querySelector("[data-alert-kind]");
  const alertText = document.querySelector("[data-alert-text]");
  const alertStatus = document.querySelector("[data-alert-status]");
  const soundBtn = document.querySelector("[data-alert-sound]");
  const pushBtn = document.querySelector("[data-alert-push]");

  const SOUND_KEY = "ga_alert_sound";
  const PUSH_KEY = "ga_alert_push";

  let lastSig = "";
  let lastAlertId = null;
  let alertPrimed = false;
  let soundOn = localStorage.getItem(SOUND_KEY) === "1";
  let pushOn = localStorage.getItem(PUSH_KEY) === "1";
  let audioCtx = null;

  function setStats(stats) {
    if (!stats) return;
    const g = document.querySelector("[data-guess-stats]");
    const c = document.querySelector("[data-confidence-stats]");
    if (g) {
      const guess = stats.guess || {};
      g.textContent =
        guess.total > 0
          ? "Acc " + guess.correct + "/" + guess.total + " (" + Math.round(guess.percent) + "%)"
          : "Acc —";
    }
    if (c) {
      const raw = stats.confidence_text || "";
      c.textContent = raw
        .replace(/Confidence accuracy\s*·\s*/i, "")
        .replace(/VERY_HIGH/g, "VH")
        .replace(/HIGH/g, "H");
    }
  }

  function titleCase(value) {
    if (!value) return "";
    return String(value).charAt(0).toUpperCase() + String(value).slice(1).toLowerCase();
  }

  function compactConfidence(conf, guess) {
    if (!conf || !conf.ready) return "— · need 2 rounds";
    const parts = [];
    if (conf.level) {
      parts.push(conf.pct != null ? conf.level + " " + conf.pct + "%" : conf.level);
    }
    const pick = conf.pick || guess;
    if (pick) parts.push(titleCase(pick));
    if (conf.track_gap != null) parts.push("gap +" + conf.track_gap);
    if (conf.mc_pick != null) parts.push("MC " + Math.round(Number(conf.mc_pick) * 100) + "%");
    return parts.length ? parts.join(" · ") : "—";
  }

  function showLive(on) {
    if (idle) {
      idle.hidden = on;
      idle.style.display = on ? "none" : "";
    }
    if (grid) {
      grid.hidden = !on;
      grid.style.display = on ? "" : "none";
    }
  }

  function syncSoundButton() {
    if (!soundBtn) return;
    soundBtn.textContent = soundOn ? "Alert sound on" : "Enable alert sound";
    soundBtn.classList.toggle("is-on", soundOn);
  }

  function syncPushButton() {
    if (!pushBtn) return;
    const supported = "Notification" in window;
    if (!supported) {
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
    pushBtn.textContent = active ? "Phone notify on" : "Enable phone notify";
    pushBtn.classList.toggle("is-on", active);
  }

  function ensureAudio() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    if (audioCtx.state === "suspended") {
      audioCtx.resume();
    }
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
      setTimeout(function () {
        try {
          n.close();
        } catch (_e) {}
      }, 8000);
    } catch (_e) {}
  }

  function updateAlertStatus(alerts) {
    if (!alertStatus) return;
    if (alerts && alerts.enabled === false) {
      alertStatus.textContent = "Desktop alerts are off in config";
      return;
    }
    const bits = [];
    if (soundOn) bits.push("sound on");
    if (pushOn && "Notification" in window && Notification.permission === "granted") {
      bits.push("phone notify on");
    }
    bits.push("watching BET / UPGRADE");
    alertStatus.textContent = bits.join(" · ");
  }

  function renderAlert(alert, isNew) {
    if (!alertBanner || !alert) return;
    if (alertKind) alertKind.textContent = (alert.kind || "alert").toUpperCase();
    if (alertText) alertText.textContent = alert.message || "";
    alertBanner.hidden = false;
    const kind = (alert.kind || "").toLowerCase();
    alertBanner.classList.toggle("is-cancel", kind === "cancel");
    alertBanner.classList.toggle("is-upgrade", kind === "upgrade");
    alertBanner.classList.toggle("is-bet", kind === "bet");
    if (isNew) {
      alertBanner.classList.remove("flash");
      void alertBanner.offsetWidth;
      alertBanner.classList.add("flash");
      if (soundOn) playAlertBeep();
      showBrowserNotify(alert);
      if (navigator.vibrate) {
        try {
          navigator.vibrate([80, 40, 80]);
        } catch (_e) {}
      }
    }
  }

  function handleAlerts(alerts) {
    updateAlertStatus(alerts);
    const latest = alerts && alerts.latest;
    if (!alertPrimed) {
      alertPrimed = true;
      if (latest && latest.id) {
        lastAlertId = latest.id;
        renderAlert(latest, false);
      }
      return;
    }
    if (!latest || !latest.id) return;
    if (latest.id === lastAlertId) return;
    lastAlertId = latest.id;
    renderAlert(latest, true);
  }

  function apply(data) {
    const ready = !!(data && data.ready && data.game_id);
    showLive(ready);
    setStats(data && data.stats);
    handleAlerts(data && data.alerts);
    if (!ready) {
      if (strip) strip.textContent = "—";
      return;
    }

    if (strip) {
      strip.textContent = compactConfidence(data.confidence, data.guess);
      strip.classList.toggle(
        "is-strong",
        !!(data.confidence && (data.confidence.level === "HIGH" || data.confidence.level === "VERY_HIGH"))
      );
    }
    document.querySelector("[data-race-state]").textContent = data.in_progress
      ? "In progress / no winner yet"
      : "Race finished (winner highlighted)";
    document.querySelector("[data-locked-guess]").textContent = data.guess_text || "not locked yet";
    document.querySelector("[data-confidence]").textContent =
      (data.confidence && data.confidence.text) || "—";
    document.querySelector("[data-winner]").textContent = data.winner;
    document.querySelector("[data-phase]").textContent = data.in_progress ? "IN_PLAY" : "FINISHED";
    document.querySelector("[data-game-id]").textContent = data.game_id;
    document.querySelector("[data-session]").textContent =
      "Game " + data.game_id + " · " + (data.frames ? data.frames.length : 0) + " shots";

    const preview = document.querySelector("[data-preview]");
    if (data.preview_url) {
      preview.innerHTML =
        '<img class="preview-img" src="' +
        data.preview_url +
        '" alt="Latest capture" loading="lazy" />';
    } else {
      preview.innerHTML = '<span class="muted">No preview yet</span>';
    }

    document.querySelector("[data-win-chance]").innerHTML = cards.winChance(
      data.win_chance,
      data.win_chance_note
    );
    document.querySelector("[data-card-table]").innerHTML = cards.suitTable(data.table);
  }

  if (soundBtn) {
    soundBtn.addEventListener("click", function () {
      soundOn = !soundOn;
      localStorage.setItem(SOUND_KEY, soundOn ? "1" : "0");
      syncSoundButton();
      updateAlertStatus({ enabled: true });
      if (soundOn) {
        ensureAudio();
        playAlertBeep();
      }
    });
  }

  if (pushBtn) {
    pushBtn.addEventListener("click", async function () {
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
      updateAlertStatus({ enabled: true });
      if (pushOn && Notification.permission === "granted") {
        try {
          new Notification("Game Analyzer", {
            body: "Phone alerts enabled",
            tag: "ga-alert-test",
          });
        } catch (_e) {}
      }
    });
  }

  syncSoundButton();
  syncPushButton();
  showLive(false);

  live.start(async function () {
    try {
      const data = await live.get("/api/live");
      const latestAlert = data.alerts && data.alerts.latest;
      const sig = JSON.stringify({
        id: data.game_id,
        winner: data.winner,
        frames: data.frames && data.frames.length,
        table: data.table,
        ready: data.ready,
        conf: data.confidence,
        guess: data.guess_text,
        alert: latestAlert && latestAlert.id,
      });
      live.stamp(true, data.ready ? "game " + data.game_id : "waiting");
      if (sig === lastSig) return;
      lastSig = sig;
      apply(data);
    } catch (_err) {
      live.stamp(false);
    }
  });
})();
