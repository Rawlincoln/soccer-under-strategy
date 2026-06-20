const POLL_MS = 15000;
let lastData = null;

const $ = (id) => document.getElementById(id);

function fmtMoney(n) {
  return BetAssistant.fmtMoney(n);
}

function waveShort(w) {
  if (!w) return "";
  if (w.id === "wave1") return "W1";
  if (w.id === "wave2") return "W2";
  return "W3";
}

function slipMeta(slip) {
  const legs = slip?.legs || [];
  return {
    slip_type: slip?.slip_type || "accumulator",
    stake: slip?.stake || 5000,
    title: slip?.title || "Bet slip",
    wave: slip?.wave || "",
    potential_profit: slip?.potential_profit || 0,
    combined_odds: slip?.combined_odds || 0,
    leg_event_ids: legs.map((l) => String(l.event_id)).filter(Boolean),
  };
}

function renderTracker(wf) {
  if (!wf) return;
  const target = wf.daily_target || 100000;
  const profit = wf.profit_recorded || 0;
  const gap = wf.gap_to_target ?? Math.max(0, target - profit);
  const pct = Math.min(100, Math.round((profit / target) * 100));
  const wins = wf.wins || 0;
  const losses = wf.losses || 0;
  const decided = wins + losses;
  const wlTotal = Math.max(decided, 1);
  const winPct = decided ? Math.round((wins / decided) * 100) : 50;
  const lossPct = decided ? 100 - winPct : 50;

  $("profitRecorded").textContent = fmtMoney(profit);
  $("dailyTarget").textContent = fmtMoney(target);
  $("gapTarget").textContent = fmtMoney(gap);
  $("progressFill").style.width = `${pct}%`;
  $("progressPct").textContent = `${pct}%`;

  const wlWin = $("wlBarWin");
  const wlLoss = $("wlBarLoss");
  const wlLabel = $("wlBarLabel");
  if (wlWin) wlWin.style.width = `${winPct}%`;
  if (wlLoss) wlLoss.style.width = `${lossPct}%`;
  if (wlLabel) {
    wlLabel.textContent = decided
      ? `${wins} W · ${losses} L · ${wf.win_rate_pct ?? 0}% win rate`
      : "No results yet";
  }

  const streak = wf.loss_streak || 0;
  const maxStreak = wf.max_loss_streak || 5;
  const statusEl = $("workflowStatus");
  if (wf.target_reached) {
    statusEl.textContent = "Target reached";
    statusEl.className = "asst-tracker-status ok";
  } else if (streak >= maxStreak - 1 && streak > 0) {
    statusEl.textContent = `${streak} losses in a row`;
    statusEl.className = "asst-tracker-status stop";
  } else if (wf.active_wave?.status === "ACTIVE") {
    statusEl.textContent = wf.active_wave.label?.split("·")[0]?.trim() || "Wave active";
    statusEl.className = "asst-tracker-status ok";
  } else {
    statusEl.textContent = "Waiting for entry window";
    statusEl.className = "asst-tracker-status";
  }

  const chips = $("waveChips");
  if (chips) {
    const waves = wf.waves || [];
    chips.innerHTML = waves.map((w) => {
      const cls = w.status === "ACTIVE" ? "on" : w.status === "STANDBY" ? "standby" : "";
      return `<span class="asst-chip ${cls}" title="${w.action || ""}">${waveShort(w)}</span>`;
    }).join("");
  }

  const netPnl = wf.net_pnl || 0;
  const netCls = netPnl >= 0 ? "win" : "loss";
  const stats = $("trackerStats");
  if (stats) {
    stats.innerHTML = `
      <div class="asst-stat"><span class="num win">${wf.wins || 0}</span><span class="lbl">Wins</span></div>
      <div class="asst-stat"><span class="num loss">${wf.losses || 0}</span><span class="lbl">Losses</span></div>
      <div class="asst-stat"><span class="num">${wf.win_rate_pct ?? 0}%</span><span class="lbl">Win rate</span></div>
      <div class="asst-stat"><span class="num ${netCls}">${netPnl >= 0 ? "+" : ""}${fmtMoney(netPnl)}</span><span class="lbl">Net P/L</span></div>
      <div class="asst-stat"><span class="num win">+${fmtMoney(wf.total_won || 0)}</span><span class="lbl">Won</span></div>
      <div class="asst-stat"><span class="num loss">-${fmtMoney(wf.total_lost || 0)}</span><span class="lbl">Lost</span></div>
      <div class="asst-stat"><span class="num">${streak}</span><span class="lbl">Loss streak</span></div>
      <div class="asst-stat"><span class="num">${wf.pending_count || 0}</span><span class="lbl">Pending</span></div>
    `;
  }

  if ($("manualStake") && !document.activeElement?.isSameNode($("manualStake"))) {
    $("manualStake").value = wf.stake_per_slip || 5000;
  }
}

async function recordOutcome(slipId, won, { profit = 0, legEventId = "", slip = null } = {}) {
  const body = { slip_id: slipId, won, profit };
  if (legEventId) body.leg_event_id = legEventId;
  if (slip) body.slip_meta = slipMeta(slip);
  const res = await fetch("/api/assistant/workflow/result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!data.ok) {
    BetAssistant.toast(data.error || "Could not save result");
    return;
  }
  if (data.session_reset) {
    const msg = data.reset_reason === "target_reached"
      ? "Target reached — day reset"
      : "5-loss streak — day reset";
    BetAssistant.toast(msg, 4200);
  } else if (data.leg_recorded) {
    BetAssistant.toast(won ? "Leg marked W" : "Leg marked L");
  } else {
    BetAssistant.toast(won ? "Win recorded" : "Loss recorded");
  }
  fetchData();
}

async function settleSlip(slipId, won, profit = 0, slip = null) {
  await recordOutcome(slipId, won, { profit, slip });
}

function renderBetJournal(wf) {
  const box = $("betJournal");
  if (!box) return;
  const slips = [...(wf?.placed_slips || [])].reverse();
  if (!slips.length) {
    box.innerHTML = `<div class="asst-empty">No bets logged yet — mark a slip placed or log manually below</div>`;
    return;
  }

  box.innerHTML = slips.map((s) => {
    const settled = s.result != null;
    const time = new Date(s.placed_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const wave = s.wave ? `<span class="asst-bet-wave">${waveShort({ id: s.wave })}</span>` : "";
    const defaultProfit = s.potential_profit || s.stake || wf.stake_per_slip || 5000;

    if (settled) {
      const pnl = Number(s.profit);
      const pnlCls = pnl >= 0 ? "won" : "lost";
      const pnlText = pnl >= 0 ? `+${fmtMoney(pnl)}` : fmtMoney(pnl);
      return `
        <div class="asst-bet-row ${pnlCls}">
          <div class="asst-bet-main">
            ${wave}
            <div class="asst-bet-title">${s.title}</div>
            <div class="asst-bet-meta">${s.type} · Stake ${fmtMoney(s.stake)} · ${time}</div>
          </div>
          <div class="asst-bet-pnl ${pnlCls}">${pnlText}</div>
        </div>`;
    }

    return `
      <div class="asst-bet-row pending">
        <div class="asst-bet-main">
          ${wave}
          <div class="asst-bet-title">${s.title}</div>
          <div class="asst-bet-meta">${s.type} · Stake ${fmtMoney(s.stake)} · ${time}${s.combined_odds ? ` · @ ${Number(s.combined_odds).toFixed(2)}` : ""}</div>
        </div>
        <div class="asst-bet-settle">
          <label class="asst-profit-label">Profit if won</label>
          <input type="number" class="asst-profit-input" data-profit-for="${s.id}" value="${defaultProfit}" min="0" step="100" />
          <button class="ba-btn primary" type="button" data-win="${s.id}">Won</button>
          <button class="ba-btn" type="button" data-loss="${s.id}">Lost</button>
        </div>
      </div>`;
  }).join("");

  box.querySelectorAll("[data-win]").forEach((btn) => {
    btn.onclick = () => {
      const input = box.querySelector(`[data-profit-for="${btn.dataset.win}"]`);
      const profit = parseFloat(input?.value) || 0;
      settleSlip(btn.dataset.win, true, profit);
    };
  });
  box.querySelectorAll("[data-loss]").forEach((btn) => {
    btn.onclick = () => settleSlip(btn.dataset.loss, false);
  });
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

function renderLegWl(leg, slip, settlement) {
  const eid = String(leg.event_id || "");
  const slipSettled = settlement?.result != null;
  const legResult = settlement?.leg_results?.[eid];
  if (slipSettled) {
    const won = settlement.result === "won";
    return `<span class="asst-leg-badge ${won ? "won" : "lost"}">${won ? "W" : "L"}</span>`;
  }
  if (legResult) {
    return `<span class="asst-leg-badge ${legResult === "won" ? "won" : "lost"}">${legResult === "won" ? "W" : "L"}</span>`;
  }
  if (!eid) return "";
  return `
    <div class="asst-leg-wl" data-slip-id="${slip.id}">
      <button type="button" class="asst-wl-btn win" data-leg-win="${eid}" data-slip="${slip.id}" title="Mark win">W</button>
      <button type="button" class="asst-wl-btn loss" data-leg-loss="${eid}" data-slip="${slip.id}" title="Mark loss">L</button>
    </div>`;
}

function renderSlipSettleBar(slip, settlement) {
  if (settlement?.result != null) {
    const won = settlement.result === "won";
    const pnl = Number(settlement.profit);
    const pnlText = won ? `+${fmtMoney(pnl)}` : fmtMoney(pnl);
    return `
      <div class="asst-rec-settle settled ${won ? "won" : "lost"}">
        <span class="asst-settled-label">${won ? "Slip won" : "Slip lost"}</span>
        <span class="asst-settled-pnl">${pnlText}</span>
      </div>`;
  }
  const defaultProfit = slip.potential_profit || slip.stake || 5000;
  const legs = slip.legs || [];
  const legCount = legs.length;
  const marked = settlement?.leg_results ? Object.keys(settlement.leg_results).length : 0;
  const hint = legCount > 1 && marked
    ? `${marked}/${legCount} legs marked — or settle whole slip below`
    : "Or settle the whole slip:";
  return `
    <div class="asst-rec-settle">
      <span class="asst-rec-settle-hint">${hint}</span>
      <label class="asst-profit-label">Profit if won</label>
      <input type="number" class="asst-profit-input" data-slip-profit="${slip.id}" value="${defaultProfit}" min="0" step="100" />
      <button type="button" class="ba-btn primary asst-wl-slip" data-slip-win="${slip.id}">Win slip</button>
      <button type="button" class="ba-btn asst-wl-slip loss" data-slip-loss="${slip.id}">Loss slip</button>
    </div>`;
}

function renderLegDetail(leg, idx, slip, settlement) {
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
  const wlHtml = renderLegWl(leg, slip, settlement);
  return `
    <div class="asst-leg-row${isLock ? " lock" : ""}">
      <div class="asst-leg-num">${idx}</div>
      <div class="asst-leg-body">
        <div class="asst-leg-head">
          <div>
            <div class="asst-leg-league">${league}</div>
            <div class="asst-leg-match">${leg.match || `${leg.home_team} vs ${leg.away_team}`}</div>
          </div>
          <div class="asst-leg-head-right">
            ${wlHtml}
            <span class="asst-leg-clock">${timeBadge}</span>
          </div>
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
    const active = wf?.active_wave;
    const hint = active?.status === "ACTIVE"
      ? "Entry window open — waiting for a 60%+ qualifier that passes filters."
      : "No qualifying slips right now. The assistant only surfaces bets when wave windows and confidence rules match.";
    box.innerHTML = `<div class="asst-empty">${hint}</div>`;
    return;
  }
  const slipCache = new Map();
  box.innerHTML = recs.map((r) => {
    const slip = r.slip;
    const settlement = r.settlement;
    BetAssistant.registerSlip(slip);
    slipCache.set(slip.id, slip);
    const legsHtml = (slip.legs || []).map((l, i) => renderLegDetail(l, i + 1, slip, settlement)).join("");
    const legCount = slip.legs?.length || 0;
    return `
      <div class="asst-rec-card ${r.priority}${settlement?.result ? ` settled-${settlement.result}` : ""}">
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
            ${renderSlipSettleBar(slip, settlement)}
          </div>
        </div>
        ${BetAssistant.actionButtons(slip, wf)}
      </div>`;
  }).join("");
  BetAssistant.bindActions(box, wf);
  BetAssistant.bind1xBetLinks(box);
  bindRecommendationOutcomes(box, slipCache);
}

function bindRecommendationOutcomes(box, slipCache) {
  box.querySelectorAll("[data-leg-win]").forEach((btn) => {
    btn.onclick = () => {
      const slip = slipCache.get(btn.dataset.slip);
      const input = box.querySelector(`[data-slip-profit="${btn.dataset.slip}"]`);
      const profit = parseFloat(input?.value) || slip?.potential_profit || 0;
      recordOutcome(btn.dataset.slip, true, { legEventId: btn.dataset.legWin, profit, slip });
    };
  });
  box.querySelectorAll("[data-leg-loss]").forEach((btn) => {
    btn.onclick = () => {
      const slip = slipCache.get(btn.dataset.slip);
      recordOutcome(btn.dataset.slip, false, { legEventId: btn.dataset.legLoss, slip });
    };
  });
  box.querySelectorAll("[data-slip-win]").forEach((btn) => {
    btn.onclick = () => {
      const slip = slipCache.get(btn.dataset.slipWin);
      const input = box.querySelector(`[data-slip-profit="${btn.dataset.slipWin}"]`);
      const profit = parseFloat(input?.value) || slip?.potential_profit || 0;
      recordOutcome(btn.dataset.slipWin, true, { profit, slip });
    };
  });
  box.querySelectorAll("[data-slip-loss]").forEach((btn) => {
    btn.onclick = () => {
      const slip = slipCache.get(btn.dataset.slipLoss);
      recordOutcome(btn.dataset.slipLoss, false, { slip });
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
    el.textContent = "Telegram: configured — enable and Save";
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
  if ($("targetSetting")) $("targetSetting").value = cfg.daily_target || 100000;
  if ($("onexbetSite")) {
    $("onexbetSite").value = cfg.onexbet_site || "";
    $("onexbetSite").placeholder = cfg.onexbet_site || "https://1xbet.co.ke";
  }
  if (cfg.telegram_chat_id) $("tgChat").value = cfg.telegram_chat_id;
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
    daily_target: parseFloat($("targetSetting")?.value) || 100000,
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
    fetchData();
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
      const n = wf.recommendations?.length || 0;
      $("statusText").textContent = n ? `${n} qualifying slip${n !== 1 ? "s" : ""}` : "Tracking your day";
      $("connectionStatus").classList.add("live");
    }

    renderTracker(wf);
    renderBetJournal(wf);
    renderRecommendations(wf.recommendations, wf);
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
      BetAssistant.toast(data.error || "No chat found — message your bot first");
      return;
    }
    box.hidden = false;
    box.innerHTML = data.chats.map((c) => `
      <button type="button" class="tg-chat-btn" data-chat="${c.chat_id}">
        ${c.name || c.title || c.username || "Chat"} · ID ${c.chat_id}
      </button>
    `).join("");
    box.querySelectorAll(".tg-chat-btn").forEach((btn) => {
      btn.onclick = () => { $("tgChat").value = btn.dataset.chat; };
    });
    if (data.chats.length === 1) $("tgChat").value = data.chats[0].chat_id;
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
      BetAssistant.toast("Test alert sent");
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

$("manualLogForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  const won = btn?.dataset.outcome === "won";
  const stake = parseFloat($("manualStake").value) || 5000;
  const profit = parseFloat($("manualProfit").value) || 0;
  const res = await fetch("/api/assistant/workflow/log", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: $("manualTitle").value.trim(),
      stake,
      won,
      profit: won ? profit : 0,
    }),
  });
  const data = await res.json();
  if (!data.ok) {
    BetAssistant.toast(data.error || "Could not log bet");
    return;
  }
  $("manualTitle").value = "";
  $("manualProfit").value = "";
  if (data.session_reset) {
    BetAssistant.toast(data.reset_reason === "target_reached" ? "Target reached — day reset" : "5-loss streak — day reset", 4200);
  } else {
    BetAssistant.toast(won ? "Win logged" : "Loss logged");
  }
  fetchData();
});

$("btnSaveConfig").addEventListener("click", saveConfig);
$("btnDiscoverChat").addEventListener("click", discoverChat);
$("btnTestTelegram").addEventListener("click", testTelegram);
$("browserAlerts").addEventListener("change", () => {
  BetAssistant.setBrowserAlerts($("browserAlerts").checked);
  if ($("browserAlerts").checked) BetAssistant.requestNotifyPermission();
});

$("btnResetDay").addEventListener("click", async () => {
  if (!confirm("Reset today's counters?")) return;
  await fetch("/api/assistant/workflow/reset", { method: "POST" });
  fetchData();
  BetAssistant.toast("Day reset");
});

async function loadSavedConfig() {
  try {
    const res = await fetch("/api/assistant/config");
    applyConfig(await res.json());
  } catch { /* fetchData will apply config */ }
}

loadSavedConfig();
fetchData();
setInterval(fetchData, POLL_MS);
BetAssistant.startAlertPolling(30000);