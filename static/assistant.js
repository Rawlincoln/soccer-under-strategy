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
  $("slipsCount").textContent = `${wf.slips_placed || 0} / ${wf.max_slips || 5}`;
  $("winsCount").textContent = wf.wins || 0;
  $("lossesCount").textContent = wf.losses || 0;

  const statusEl = $("workflowStatus");
  const card = $("statusCard");
  if (wf.stop_loss_hit) {
    statusEl.textContent = "STOP";
    statusEl.className = "asst-hero-value asst-status-stop";
  } else if (!wf.can_place) {
    statusEl.textContent = "MAX SLIPS";
    statusEl.className = "asst-hero-value asst-status-wait";
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
          <a class="asst-leg-chip link" href="${url}" target="_blank" rel="noopener">1xBet ↗</a>
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

  box.querySelectorAll("[data-win]").forEach((btn) => {
    btn.onclick = async () => {
      const profit = prompt("Profit amount?", String(wf.stake_per_slip || 5000));
      if (profit == null) return;
      await fetch("/api/assistant/workflow/result", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slip_id: btn.dataset.win, won: true, profit: parseFloat(profit) || 0 }),
      });
      fetchData();
    };
  });
  box.querySelectorAll("[data-loss]").forEach((btn) => {
    btn.onclick = async () => {
      await fetch("/api/assistant/workflow/result", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slip_id: btn.dataset.loss, won: false }),
      });
      fetchData();
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

function applyConfig(cfg) {
  if (!cfg) return;
  $("browserAlerts").checked = cfg.browser_alerts !== false;
  $("telegramEnabled").checked = !!cfg.telegram_enabled;
  $("stakeSetting").value = cfg.stake_per_slip || 5000;
  BetAssistant.setBrowserAlerts(cfg.browser_alerts !== false);
}

async function saveConfig() {
  const body = {
    browser_alerts: $("browserAlerts").checked,
    telegram_enabled: $("telegramEnabled").checked,
    telegram_bot_token: $("tgToken").value.trim(),
    telegram_chat_id: $("tgChat").value.trim(),
    stake_per_slip: parseFloat($("stakeSetting").value) || 5000,
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
    if (body.browser_alerts) BetAssistant.requestNotifyPermission();
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
    $("statusText").textContent = wf.can_place ? "Ready to assist" : "Stop / max slips";
    $("connectionStatus").classList.add("live");

    renderWorkflow(wf);
    renderWaves(wf.waves);
    renderRecommendations(wf.recommendations, wf);
    renderPlaced(wf);
    renderAlerts(data.alerts);
    applyConfig(data.config);

    if (data.new_alerts?.length) BetAssistant.processAlerts(data.new_alerts);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Connection error";
    console.error(err);
  }
}

$("btnSaveConfig").addEventListener("click", saveConfig);
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

fetchData();
setInterval(fetchData, POLL_MS);
BetAssistant.startAlertPolling(30000);