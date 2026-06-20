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

function renderWaves(waves) {
  const grid = $("wavesGrid");
  if (!waves?.length) {
    grid.innerHTML = "";
    return;
  }
  grid.innerHTML = waves.map((w) => {
    const badgeCls = w.status === "ACTIVE" ? "active" : w.status === "STANDBY" ? "standby" : "waiting";
    return `
      <div class="asst-wave ${w.status === "ACTIVE" ? "active" : ""}">
        <div class="asst-wave-time">${w.label || w.id}</div>
        <h3>${w.start}′–${w.end === 999 ? "late" : w.end + "′"}</h3>
        <p>${w.action || ""}</p>
        <span class="asst-wave-badge ${badgeCls}">${w.status}</span>
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
  } else if (cfg.telegram_configured) {
    el.textContent = "Telegram: configured — enable checkbox and Save";
    el.className = "tg-status warn";
  } else if (cfg.telegram_token_set) {
    el.textContent = "Telegram: token set — add chat ID";
    el.className = "tg-status warn";
  } else {
    el.textContent = "Telegram: not configured";
    el.className = "tg-status";
  }
  if (cfg.telegram_chat_id && !$("tgChat").value) {
    $("tgChat").placeholder = `Saved: ${cfg.telegram_chat_id}`;
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
  if (cfg.onexbet_site) BetAssistant.setOnexbetSite(cfg.onexbet_site);
  BetAssistant.setBrowserAlerts(cfg.browser_alerts !== false);
  updateTgStatus(cfg);
}

async function saveConfig() {
  const body = {
    browser_alerts: $("browserAlerts").checked,
    telegram_enabled: $("telegramEnabled").checked,
    telegram_bot_token: $("tgToken").value.trim(),
    telegram_chat_id: $("tgChat").value.trim(),
    stake_per_slip: parseFloat($("stakeSetting").value) || 5000,
    onexbet_site: $("onexbetSite").value.trim(),
  };
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
    renderWaves(wf.waves);
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
  if (!token) {
    BetAssistant.toast("Paste your bot token first");
    return;
  }
  $("btnDiscoverChat").disabled = true;
  try {
    const res = await fetch("/api/assistant/telegram/discover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ telegram_bot_token: token }),
    });
    const data = await res.json();
    const box = $("tgChatPick");
    if (!data.ok || !data.chats?.length) {
      box.hidden = true;
      BetAssistant.toast(data.error || "No chat found — message your bot first");
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
  const body = {
    telegram_bot_token: $("tgToken").value.trim(),
    telegram_chat_id: $("tgChat").value.trim(),
    telegram_enabled: true,
  };
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
  if (!confirm("Reset session counters and start fresh?")) return;
  await fetch("/api/assistant/workflow/reset", { method: "POST" });
  fetchData();
  BetAssistant.toast("Session reset");
});

fetchData();
setInterval(fetchData, POLL_MS);
BetAssistant.startAlertPolling(30000);