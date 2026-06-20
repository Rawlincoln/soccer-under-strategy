const POLL_MS = 15000;
let lastData = null;

const $ = (id) => document.getElementById(id);

function fmtMoney(n) {
  return BetAssistant.fmtMoney(n);
}

function renderWorkflow(wf) {
  if (!wf) return;
  $("profitRecorded").textContent = fmtMoney(wf.profit_recorded || 0);
  $("dailyTarget").textContent = fmtMoney(wf.daily_target || 100000);
  $("gapTarget").textContent = fmtMoney(wf.gap_to_target || 0);
  $("slipsCount").textContent = String(wf.slips_placed || 0);
  $("winsCount").textContent = wf.wins || 0;
  $("lossesCount").textContent = wf.losses || 0;

  const statusEl = $("workflowStatus");
  const card = $("statusCard");
  const streak = wf.loss_streak || 0;
  const maxStreak = wf.max_loss_streak || 5;
  if (wf.target_reached) {
    statusEl.textContent = "TARGET";
    statusEl.className = "asst-hero-value asst-status-ok";
  } else if (streak >= maxStreak - 1 && streak > 0) {
    statusEl.textContent = `${streak}L streak`;
    statusEl.className = "asst-hero-value asst-status-stop";
  } else if (wf.active_wave) {
    statusEl.textContent = wf.active_wave.label?.split("·")[0]?.trim() || "ACTIVE";
    statusEl.className = "asst-hero-value asst-status-ok";
  } else {
    statusEl.textContent = "Ready";
    statusEl.className = "asst-hero-value asst-status-ok";
  }
}

const WAVE_PLAN = {
  wave1: {
    time: "Wave 1 · 15′–20′ (1H)",
    title: "Anchor slip",
    body: (stake) =>
      `Place <strong>1× ${fmtMoney(stake)}</strong> on the best 4–6 leg acca (highest fusion + 65%+ avg confidence). Prefer scored-but-under-alive games.`,
  },
  wave2: {
    time: "Wave 2 · 60′–65′ (2H)",
    title: "Booster slip",
    body: (stake) =>
      `Place <strong>1–2× ${fmtMoney(stake)}</strong> on 2H under accas. Only when entry window + BET signal align. Use second slip if Wave 1 lost.`,
  },
  wave3: {
    time: "Wave 3 · Late window",
    title: "Closer slip(s)",
    body: (stake) =>
      `Keep placing <strong>${fmtMoney(stake)}</strong> on 60%+ accas or goal locks until profit target, a 5-loss streak, or midnight resets the day.`,
  },
};

function renderDailyRules(wf) {
  const stake = fmtMoney(wf?.stake_per_slip || 5000);
  const target = fmtMoney(wf?.daily_target || 100000);
  const box = $("dailyRules");
  if (!box) return;
  box.innerHTML = `
    <li><strong>Only 60%+ picks</strong> from Pro Punter — never force a bet when the app has no qualifier.</li>
    <li><strong>No slip cap</strong> — keep placing ${stake} stakes until profit target or a 5-loss streak ends the day.</li>
    <li><strong>1st half:</strong> enter between <strong>15′–20′</strong> on 1H under markets when fusion says BET / STRONG BET.</li>
    <li><strong>2nd half:</strong> enter between <strong>60′–65′</strong> on 2H under markets with the same filter.</li>
    <li><strong>Skip</strong> red-card games, virtual/esoccer, and student leagues (auto-excluded in app).</li>
    <li><strong>Day resets</strong> at <strong>midnight</strong>, when <strong>${target} profit</strong> is reached, or after <strong>5 losses in a row</strong>.</li>
    <li><strong>Split the target:</strong> aim for 2–4 winning accas, not one miracle longshot.</li>
  `;
}

function renderProgress(wf) {
  const target = wf?.daily_target || 100000;
  const profit = wf?.profit_recorded || 0;
  const gap = wf?.gap_to_target ?? Math.max(0, target - profit);
  const pct = Math.min(100, Math.round((profit / target) * 100));
  if ($("progressFill")) $("progressFill").style.width = `${pct}%`;
  if ($("progressPct")) $("progressPct").textContent = `${pct}%`;
  if ($("progressProfit")) $("progressProfit").textContent = fmtMoney(profit);
  if ($("progressGap")) $("progressGap").textContent = fmtMoney(gap);
}

function renderWaveBanner(wf) {
  const banner = $("waveBanner");
  if (!banner || !wf) return;
  const active = wf.active_wave;
  const streak = wf.loss_streak || 0;
  const maxStreak = wf.max_loss_streak || 5;
  if (streak >= maxStreak - 1 && streak > 0) {
    banner.hidden = false;
    $("waveBannerLabel").textContent = `${streak}L STREAK`;
    $("waveBannerAction").textContent =
      `${streak} losses in a row — session resets after ${maxStreak} consecutive losses.`;
    return;
  }
  if (active?.status === "ACTIVE") {
    banner.hidden = false;
    $("waveBannerLabel").textContent = active.label?.split("·")[0]?.trim() || active.id;
    $("waveBannerAction").textContent = active.action || "Place slip now";
    return;
  }
  if (wf.recommendations?.length) {
    banner.hidden = false;
    $("waveBannerLabel").textContent = "READY";
    $("waveBannerAction").textContent = `${wf.recommendations.length} slip(s) ready — follow daily rules below`;
    return;
  }
  banner.hidden = true;
}

function renderWaves(waves, wf) {
  const grid = $("wavesGrid");
  if (!grid) return;
  const stake = wf?.stake_per_slip || 5000;
  const waveTarget = Math.round((wf?.daily_target || 100000) / 3);
  const fallback = [
    { id: "wave1", status: "WAITING", action: "Wait for 1H matches to hit 15′–20′ entry window", label: "Wave 1 · 1H anchor", start: 15, end: 20 },
    { id: "wave2", status: "WAITING", action: "Wait for 2H matches to hit 60′–65′ entry window", label: "Wave 2 · 2H booster", start: 60, end: 65 },
    { id: "wave3", status: "STANDBY", action: "Use late accas or goal locks if short of target", label: "Wave 3 · Closer / Goal Lock", start: 0, end: 999 },
  ];
  const list = waves?.length ? waves : fallback;
  grid.innerHTML = list.map((w) => {
    const plan = WAVE_PLAN[w.id] || WAVE_PLAN.wave3;
    const badgeCls = w.status === "ACTIVE" ? "active" : w.status === "STANDBY" ? "standby" : "waiting";
    const windowLabel = w.end === 999 ? "Late / Goal Lock" : `${w.start}′–${w.end}′`;
    return `
      <div class="asst-wave-card ${w.status === "ACTIVE" ? "active" : ""}">
        <div class="asst-wave-card-top">
          <div class="asst-wave-time">${plan.time}</div>
          <span class="asst-wave-badge ${badgeCls}">${w.status}</span>
        </div>
        <h3>${plan.title} · ${windowLabel}</h3>
        <p class="asst-wave-body">${plan.body(stake)}</p>
        <div class="asst-wave-live">${w.action || ""}</div>
        <div class="asst-wave-target">Target profit: ~${fmtMoney(waveTarget)}</div>
      </div>`;
  }).join("");
}

function halfTag(h) {
  return h === "sh" ? "2H" : "1H";
}

function fmtLegMinute(leg) {
  const m = Number(leg.minute);
  const pm = Number(leg.period_minute);
  if (leg.half === "sh") {
    const elapsed = !Number.isNaN(pm) && pm > 0 ? pm : Math.max(0, m - 45);
    return !Number.isNaN(m) ? `${m}' · 2H ${elapsed}'` : "—";
  }
  if (!Number.isNaN(m)) return `1H ${m}'`;
  return "—";
}

function leg1xBetUrl(leg) {
  return leg.onexbet_url || BetAssistant.matchUrl(leg.event_id, leg.league_id);
}

function renderLegDetail(leg, idx, slip) {
  const league = leg.league || "Football";
  const clock = fmtLegMinute(leg);
  const timeBadge = leg.minutes_left
    ? `${halfTag(leg.half)} ${leg.minute}' · ${leg.minutes_left}' to ${leg.closing_target || "HT/FT"}`
    : clock;
  const pick = leg.selection || leg.market || "";
  const conf = Number(leg.confidence).toFixed(0);
  const period = leg.period_score || "—";
  const full = leg.full_score || "—";
  const odds = leg.estimated_odds ? `@ ${Number(leg.estimated_odds).toFixed(2)}` : "";
  const url = leg1xBetUrl(leg);
  const isLock = slip?.slip_type === "goal_lock";
  return `
    <div class="asst-leg-row${isLock ? " lock" : ""}">
      <div class="asst-leg-num">${idx}</div>
      <div class="asst-leg-body">
        <div class="asst-leg-head">
          <div>
            <div class="asst-leg-league">${league}</div>
            <div class="asst-leg-match">${leg.match || `${leg.home_team} vs ${leg.away_team}`}</div>
          </div>
          <span class="asst-leg-clock">${timeBadge}</span>
        </div>
        <div class="asst-leg-score-row">
          <span class="asst-leg-period-score">${period}</span>
          <span class="asst-leg-period-label">${halfTag(leg.half)} period · FT ${full}</span>
        </div>
        ${isLock ? `<div class="asst-leg-lock">${pick}</div>` : ""}
        <div class="asst-leg-stats">
          ${!isLock ? `<span class="asst-leg-chip pick">${pick}</span>` : ""}
          <span class="asst-leg-chip conf">${conf}%</span>
          ${odds ? `<span class="asst-leg-chip">${odds}</span>` : ""}
          ${leg.recommendation ? `<span class="asst-leg-chip rec">${leg.recommendation}</span>` : ""}
          <a class="asst-leg-chip link ba-1xbet-link" href="${url}" ${BetAssistant.isMobile() ? "" : 'target="_blank" rel="noopener"'}>1xBet ↗</a>
        </div>
      </div>
    </div>`;
}

function renderRecommendations(recs, wf) {
  const box = $("recommendations");
  if (!recs?.length) {
    box.innerHTML = `<div class="asst-empty">No recommendations right now. Check back during entry windows or when goal locks appear.</div>`;
    return;
  }
  box.innerHTML = recs.map((r) => {
    const slip = r.slip;
    BetAssistant.registerSlip(slip);
    const legsHtml = (slip.legs || []).map((l, i) => renderLegDetail(l, i + 1, slip)).join("");
    const legCount = slip.legs?.length || 0;
    return `
      <div class="asst-rec-card ${r.priority}">
        <div class="asst-rec-top">
          <div style="flex:1;min-width:0">
            <div class="asst-rec-reason">${r.reason}</div>
            <div class="asst-rec-title">${slip.title}</div>
            <div class="asst-rec-meta">
              Stake ${fmtMoney(slip.stake)} · @ ${Number(slip.combined_odds).toFixed(2)} ·
              +${fmtMoney(slip.potential_profit)} profit
              ${slip.lock_pct ? ` · Lock ${slip.lock_pct}%` : ""}
              ${slip.risk_level ? ` · ${slip.risk_level} risk` : ""}
              · ${legCount} leg${legCount !== 1 ? "s" : ""}
            </div>
            <div class="asst-leg-list">${legsHtml}</div>
          </div>
        </div>
        ${BetAssistant.actionButtons(slip, wf)}
      </div>`;
  }).join("");
  BetAssistant.bindActions(box, wf);
  BetAssistant.bind1xBetLinks(box);
}

function renderPlaced(wf) {
  const box = $("placedSlips");
  const slips = wf?.placed_slips || [];
  if (!slips.length) {
    box.innerHTML = `<div class="asst-empty">No slips marked placed today</div>`;
    return;
  }
  box.innerHTML = slips.map((s) => {
    const settled = s.result != null;
    const resultHtml = settled
      ? `<span class="${s.result === "won" ? "asst-rec-reason" : "asst-status-stop"}">${s.result.toUpperCase()}</span>`
      : `<div class="asst-settle">
          <button class="ba-btn primary" data-win="${s.id}" data-profit="0" type="button">Won</button>
          <button class="ba-btn" data-loss="${s.id}" type="button">Lost</button>
        </div>`;
    return `
      <div class="asst-placed-item">
        <div class="title">${s.title}</div>
        <div class="meta">${s.type} · Stake ${fmtMoney(s.stake)} · ${new Date(s.placed_at).toLocaleTimeString()}</div>
        ${resultHtml}
      </div>`;
  }).join("");

  async function settleSlip(slipId, won, profit = 0) {
    const res = await fetch("/api/assistant/workflow/result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slip_id: slipId, won, profit }),
    });
    const data = await res.json();
    if (data.session_reset) {
      const msg = data.reset_reason === "target_reached"
        ? "Profit target reached — new session started"
        : "5-loss streak — new session started";
      BetAssistant.toast(msg, 4200);
    }
    fetchData();
  }

  box.querySelectorAll("[data-win]").forEach((btn) => {
    btn.onclick = async () => {
      const profit = prompt("Profit amount?", String(wf.stake_per_slip || 5000));
      if (profit == null) return;
      await settleSlip(btn.dataset.win, true, parseFloat(profit) || 0);
    };
  });
  box.querySelectorAll("[data-loss]").forEach((btn) => {
    btn.onclick = async () => {
      await settleSlip(btn.dataset.loss, false);
    };
  });
}

function renderAlerts(alerts) {
  const box = $("alertsList");
  if (!alerts?.length) {
    box.innerHTML = `<div class="asst-empty">No alerts yet</div>`;
    return;
  }
  box.innerHTML = alerts.slice(0, 10).map((a) => `
    <div class="asst-alert-item">
      <div class="atitle">${a.title}</div>
      <div class="amsg">${a.message}</div>
    </div>
  `).join("");
}

function updateTgStatus(cfg) {
  const el = $("tgStatus");
  if (!el || !cfg) return;
  if (cfg.telegram_enabled && cfg.telegram_configured) {
    el.textContent = `Telegram: active · chat ${cfg.telegram_chat_id || "—"}`;
    el.className = "tg-status ok";
  } else if (cfg.telegram_enabled && cfg.telegram_token_set) {
    el.textContent = "Telegram: enabled — add chat ID and Save";
    el.className = "tg-status warn";
  } else if (cfg.telegram_configured) {
    el.textContent = "Telegram: configured — enable checkbox and Save";
    el.className = "tg-status warn";
  } else if (cfg.telegram_token_set) {
    el.textContent = "Telegram: token saved — add chat ID";
    el.className = "tg-status warn";
  } else {
    el.textContent = "Telegram: not configured";
    el.className = "tg-status";
  }
}

function applyConfig(cfg) {
  if (!cfg) return;
  $("browserAlerts").checked = cfg.browser_alerts !== false;
  $("telegramEnabled").checked = !!cfg.telegram_enabled;
  $("stakeSetting").value = cfg.stake_per_slip || 5000;
  if ($("onexbetSite")) {
    $("onexbetSite").value = cfg.onexbet_site || "";
    $("onexbetSite").placeholder = cfg.onexbet_site || "https://1xbet.co.ke";
  }
  if (cfg.telegram_chat_id) {
    $("tgChat").value = cfg.telegram_chat_id;
  }
  const tokenEl = $("tgToken");
  if (cfg.telegram_token_set) {
    tokenEl.placeholder = "Token saved on server (leave blank to keep)";
    tokenEl.value = "";
  } else {
    tokenEl.placeholder = "123456789:ABCdefGHI...";
  }
  if (cfg.onexbet_site) BetAssistant.setOnexbetSite(cfg.onexbet_site);
  BetAssistant.setBrowserAlerts(cfg.browser_alerts !== false);
  updateTgStatus(cfg);
}

async function saveConfig() {
  const body = {
    browser_alerts: $("browserAlerts").checked,
    telegram_enabled: $("telegramEnabled").checked,
    stake_per_slip: parseFloat($("stakeSetting").value) || 5000,
    onexbet_site: $("onexbetSite").value.trim(),
  };
  const token = $("tgToken").value.trim();
  const chatId = $("tgChat").value.trim();
  if (token) body.telegram_bot_token = token;
  if (chatId) body.telegram_chat_id = chatId;
  const res = await fetch("/api/assistant/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (data.ok) {
    BetAssistant.toast("Settings saved");
    BetAssistant.setBrowserAlerts(body.browser_alerts);
    if (body.onexbet_site) BetAssistant.setOnexbetSite(body.onexbet_site);
    if (body.browser_alerts) BetAssistant.requestNotifyPermission();
    if (data.config) applyConfig(data.config);
  }
}

async function fetchData() {
  try {
    const res = await fetch("/api/assistant");
    const data = await res.json();
    lastData = data;
    const wf = data.workflow || {};

    $("lastUpdate").textContent = data.updated_at
      ? `Updated ${new Date(data.updated_at).toLocaleTimeString()}`
      : "—";
    if (data.loading) {
      $("statusText").textContent = "Loading live data…";
      $("connectionStatus").classList.remove("error");
    } else {
      $("statusText").textContent = "Ready to assist";
      $("connectionStatus").classList.add("live");
    }

    renderWorkflow(wf);
    renderDailyRules(wf);
    renderProgress(wf);
    renderWaveBanner(wf);
    renderWaves(wf.waves, wf);
    renderRecommendations(wf.recommendations, wf);
    renderPlaced(wf);
    renderAlerts(data.alerts);
    applyConfig(data.config);
    if (data.onexbet_site) BetAssistant.setOnexbetSite(data.onexbet_site);

    if (data.new_alerts?.length) BetAssistant.processAlerts(data.new_alerts);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Connection error";
    console.error(err);
  }
}

async function discoverChat() {
  const token = $("tgToken").value.trim();
  $("btnDiscoverChat").disabled = true;
  try {
    const res = await fetch("/api/assistant/telegram/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(token ? { telegram_bot_token: token } : {}),
    });
    const data = await res.json();
    const box = $("tgChatPick");
    if (!data.ok || !data.chats?.length) {
      box.hidden = true;
      const err = data.error || "No chat found — message your bot first";
      BetAssistant.toast(token ? err : `${err} (or paste your bot token if not saved yet)`);
      return;
    }
    box.hidden = false;
    box.innerHTML = data.chats.map((c) => `
      <button type="button" class="tg-chat-btn" data-chat="${c.chat_id}">
        ${c.name || c.title || c.username || "Chat"} · ID ${c.chat_id} · ${c.type || "private"}
      </button>
    `).join("");
    box.querySelectorAll(".tg-chat-btn").forEach((btn) => {
      btn.onclick = () => {
        $("tgChat").value = btn.dataset.chat;
        BetAssistant.toast(`Chat ID ${btn.dataset.chat} selected`);
      };
    });
    if (data.chats.length === 1) {
      $("tgChat").value = data.chats[0].chat_id;
    }
    BetAssistant.toast(`Found ${data.chats.length} chat(s)`);
  } catch {
    BetAssistant.toast("Could not reach Telegram API");
  } finally {
    $("btnDiscoverChat").disabled = false;
  }
}

async function testTelegram() {
  const body = { telegram_enabled: true };
  const token = $("tgToken").value.trim();
  const chatId = $("tgChat").value.trim();
  if (token) body.telegram_bot_token = token;
  if (chatId) body.telegram_chat_id = chatId;
  $("btnTestTelegram").disabled = true;
  try {
    const res = await fetch("/api/assistant/telegram/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (data.ok) {
      BetAssistant.toast("Test alert sent — check Telegram");
      $("telegramEnabled").checked = true;
      await saveConfig();
    } else {
      BetAssistant.toast(data.error || "Test failed");
    }
  } catch {
    BetAssistant.toast("Test request failed");
  } finally {
    $("btnTestTelegram").disabled = false;
  }
}

$("btnSaveConfig").addEventListener("click", saveConfig);
$("btnDiscoverChat").addEventListener("click", discoverChat);
$("btnTestTelegram").addEventListener("click", testTelegram);
$("browserAlerts").addEventListener("change", () => {
  BetAssistant.setBrowserAlerts($("browserAlerts").checked);
  if ($("browserAlerts").checked) BetAssistant.requestNotifyPermission();
});

$("btnResetDay").addEventListener("click", async () => {
  if (!confirm("Reset today's workflow counters?")) return;
  await fetch("/api/assistant/workflow/reset", { method: "POST" });
  fetchData();
  BetAssistant.toast("Day reset");
});

async function loadSavedConfig() {
  const defaults = { stake_per_slip: 5000, daily_target: 100000 };
  try {
    const res = await fetch("/api/assistant/config");
    const cfg = await res.json();
    applyConfig(cfg);
    defaults.stake_per_slip = cfg.stake_per_slip || 5000;
    defaults.daily_target = cfg.daily_target || 100000;
  } catch {
    /* ignore — fetchData will retry via workflow config */
  }
  renderDailyRules(defaults);
  renderProgress({ ...defaults, profit_recorded: 0, gap_to_target: defaults.daily_target });
  renderWaves(null, defaults);
}

loadSavedConfig();
fetchData();
setInterval(fetchData, POLL_MS);
BetAssistant.startAlertPolling(30000);