/**
 * Pro Punter betting assistant — export, confirm, browser alerts.
 * Does NOT place bets; copy slips and open 1xBet for manual placement.
 */
const BetAssistant = (() => {
  let seenAlertIds = new Set(JSON.parse(localStorage.getItem("pp_seen_alerts") || "[]"));
  let notifyEnabled = localStorage.getItem("pp_browser_alerts") !== "false";
  let pollTimer = null;
  let onexbetSite = (localStorage.getItem("pp_onexbet_site") || "https://1xbet.com").replace(/\/$/, "");

  function toast(msg, ms = 2800) {
    const el = document.createElement("div");
    el.className = "ba-toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), ms);
  }

  function fmtMoney(n) {
    return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
  }

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied to clipboard");
      return true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      toast("Copied to clipboard");
      return true;
    }
  }

  function setOnexbetSite(site) {
    if (!site) return;
    onexbetSite = String(site).trim().replace(/\/$/, "");
    if (onexbetSite && !/^https?:\/\//i.test(onexbetSite)) {
      onexbetSite = `https://${onexbetSite}`;
    }
    localStorage.setItem("pp_onexbet_site", onexbetSite);
  }

  function liveFootballUrl() {
    return `${onexbetSite}/en/live/football`;
  }

  function isMobile() {
    return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
      || (navigator.maxTouchPoints > 1 && window.innerWidth < 1024);
  }

  function matchUrl(eventId, leagueId) {
    const gid = parseInt(eventId, 10);
    if (!gid || Number.isNaN(gid)) return liveFootballUrl();
    const lid = parseInt(leagueId, 10);
    if (lid && !Number.isNaN(lid)) {
      return `${onexbetSite}/en/live/football/${lid}/${gid}`;
    }
    return `${onexbetSite}/en/live/football/${gid}`;
  }

  function open1xBet(url) {
    const target = url || liveFootballUrl();
    if (isMobile()) {
      window.location.assign(target);
    } else {
      window.open(target, "_blank", "noopener");
    }
  }

  function bind1xBetLinks(root) {
    (root || document).querySelectorAll("a.ba-1xbet-link").forEach((a) => {
      a.onclick = (e) => {
        if (!isMobile()) return;
        e.preventDefault();
        open1xBet(a.href);
      };
    });
  }

  async function loadOnexbetSite() {
    try {
      const res = await fetch("/api/assistant/config");
      const cfg = await res.json();
      if (cfg.onexbet_site) setOnexbetSite(cfg.onexbet_site);
    } catch { /* ignore */ }
  }

  async function requestNotifyPermission() {
    if (!("Notification" in window)) return false;
    if (Notification.permission === "granted") return true;
    if (Notification.permission !== "denied") {
      const p = await Notification.requestPermission();
      return p === "granted";
    }
    return false;
  }

  async function browserNotify(title, body) {
    if (!notifyEnabled) return;
    const ok = await requestNotifyPermission();
    if (!ok) return;
    try {
      new Notification(title, { body, icon: "/static/favicon.ico" });
    } catch { /* ignore */ }
  }

  function setBrowserAlerts(enabled) {
    notifyEnabled = enabled;
    localStorage.setItem("pp_browser_alerts", enabled ? "true" : "false");
  }

  function fmtModalMinute(leg) {
    const m = Number(leg.minute);
    const pm = Number(leg.period_minute);
    if (leg.half === "sh") {
      const elapsed = !Number.isNaN(pm) && pm > 0 ? pm : Math.max(0, m - 45);
      return !Number.isNaN(m) ? `${m}' · 2H ${elapsed}'` : "—";
    }
    return !Number.isNaN(m) ? `1H ${m}'` : "—";
  }

  function renderLegs(slip) {
    return (slip.legs || []).map((leg, i) => {
      const url = leg.onexbet_url || matchUrl(leg.event_id, leg.league_id);
      const league = leg.league || "Football";
      const clock = leg.minutes_left
        ? `${leg.minute}' · ${leg.minutes_left}' to ${leg.closing_target || "HT/FT"}`
        : fmtModalMinute(leg);
      const odds = leg.estimated_odds ? ` · @ ${Number(leg.estimated_odds).toFixed(2)}` : "";
      return `
      <div class="ba-modal-leg">
        <div class="ba-modal-leg-league">${league}</div>
        <strong>${i + 1}. ${leg.match}</strong><br>
        <span class="ba-modal-leg-meta">${clock} · ${leg.half === "sh" ? "2H" : "1H"} ${leg.period_score || "—"} · FT ${leg.full_score || "—"}</span><br>
        ${leg.selection || leg.market} · ${Number(leg.confidence).toFixed(0)}%${odds}
        ${leg.recommendation ? ` · ${leg.recommendation}` : ""}
        <br><a href="${url}" ${isMobile() ? "" : 'target="_blank" rel="noopener"'} class="ba-leg-link ba-1xbet-link">Open on 1xBet ↗</a>
      </div>`;
    }).join("");
  }

  function closeModal() {
    document.querySelector(".ba-modal-overlay")?.remove();
  }

  function showConfirm(slip, workflow) {
    closeModal();
    const canPlace = workflow?.can_place !== false;
    const warning = !canPlace
      ? `<div class="ba-modal-warning">${workflow?.stop_loss_hit ? "Stop-loss hit (2 losses). Do not place more bets today." : "Max daily slips reached."}</div>`
      : "";

    const overlay = document.createElement("div");
    overlay.className = "ba-modal-overlay";
    overlay.innerHTML = `
      <div class="ba-modal" role="dialog">
        <h3>Confirm manual bet</h3>
        <p class="ba-modal-sub">Review on 1xBet before placing. Pro Punter does not bet for you.</p>
        ${warning}
        <div class="ba-modal-stats">
          <div class="ba-modal-stat"><div class="num">${fmtMoney(slip.stake)}</div><div class="lbl">Stake</div></div>
          <div class="ba-modal-stat"><div class="num">${Number(slip.combined_odds).toFixed(2)}</div><div class="lbl">Odds</div></div>
          <div class="ba-modal-stat"><div class="num">${fmtMoney(slip.potential_profit)}</div><div class="lbl">Profit</div></div>
        </div>
        <div><strong>${slip.title}</strong></div>
        <div class="ba-modal-legs">${renderLegs(slip)}</div>
        <ul class="ba-modal-checklist">${(slip.checklist || []).map((c) => `<li>${c}</li>`).join("")}</ul>
        <div class="ba-modal-actions">
          <button class="ba-btn primary" data-act="copy">Copy slip</button>
          <button class="ba-btn orange" data-act="1xbet">Open 1xBet</button>
          <button class="ba-btn" data-act="placed" ${canPlace ? "" : "disabled"}>Mark placed</button>
          <button class="ba-btn" data-act="close">Close</button>
        </div>
      </div>`;

    overlay.addEventListener("click", (e) => {
      if (e.target === overlay) closeModal();
    });

    overlay.querySelector('[data-act="copy"]').onclick = () => copyText(slip.export_text || "");
    overlay.querySelector('[data-act="1xbet"]').onclick = () => {
      const legs = slip.legs || [];
      if (legs.length <= 1) {
        const leg = legs[0];
        open1xBet(slip.onexbet_url || (leg && (leg.onexbet_url || matchUrl(leg.event_id, leg.league_id))));
      } else if (isMobile()) {
        const leg = legs[0];
        open1xBet(leg.onexbet_url || matchUrl(leg.event_id, leg.league_id));
        toast("Acca: open remaining legs one at a time on 1xBet");
      } else {
        legs.forEach((leg) => open1xBet(leg.onexbet_url || matchUrl(leg.event_id, leg.league_id)));
      }
    };
    overlay.querySelector('[data-act="placed"]').onclick = async () => {
      const res = await fetch("/api/assistant/workflow/placed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          slip_id: slip.id,
          slip_type: slip.slip_type,
          stake: slip.stake,
          title: slip.title,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        toast("Marked as placed — settle win/loss on Assistant page");
        closeModal();
      } else {
        toast(data.error || "Could not record");
      }
    };
    overlay.querySelector('[data-act="close"]').onclick = closeModal;
    document.body.appendChild(overlay);
    bind1xBetLinks(overlay);
  }

  function actionButtons(slip, workflow, compact) {
    const cls = compact ? "ba-actions compact" : "ba-actions";
    return `
      <div class="${cls}">
        <button class="ba-btn primary" type="button" data-ba-copy="${slip.id}">Copy slip</button>
        <button class="ba-btn orange" type="button" data-ba-confirm="${slip.id}">Review & place</button>
        <button class="ba-btn" type="button" data-ba-1xbet="${slip.id}">1xBet ↗</button>
      </div>`;
  }

  const slipCache = new Map();

  function registerSlip(slip) {
    if (slip?.id) slipCache.set(slip.id, slip);
  }

  function bindActions(root, workflow) {
    (root || document).querySelectorAll("[data-ba-copy]").forEach((btn) => {
      btn.onclick = () => {
        const slip = slipCache.get(btn.dataset.baCopy);
        if (slip) copyText(slip.export_text || "");
      };
    });
    (root || document).querySelectorAll("[data-ba-confirm]").forEach((btn) => {
      btn.onclick = () => {
        const slip = slipCache.get(btn.dataset.baConfirm);
        if (slip) showConfirm(slip, workflow);
      };
    });
    (root || document).querySelectorAll("[data-ba-1xbet]").forEach((btn) => {
      btn.onclick = () => {
        const slip = slipCache.get(btn.dataset.ba1xbet);
        open1xBet(slip?.onexbet_url);
      };
    });
  }

  function processAlerts(alerts) {
    if (!alerts?.length) return;
    for (const a of alerts) {
      if (seenAlertIds.has(a.id)) continue;
      seenAlertIds.add(a.id);
      browserNotify(a.title, a.message);
    }
    localStorage.setItem("pp_seen_alerts", JSON.stringify([...seenAlertIds].slice(-200)));
  }

  async function pollAlerts() {
    try {
      const res = await fetch("/api/assistant");
      const data = await res.json();
      processAlerts(data.new_alerts || data.alerts);
      return data;
    } catch {
      return null;
    }
  }

  function startAlertPolling(intervalMs = 30000) {
    if (pollTimer) clearInterval(pollTimer);
    pollAlerts();
    pollTimer = setInterval(pollAlerts, intervalMs);
  }

  function slipFromAcca(acca, stake) {
    const legs = (acca.legs || []).map((leg) => ({
      match: leg.match,
      home_team: leg.home_team,
      away_team: leg.away_team,
      league: leg.league,
      market: leg.market,
      selection: leg.selection,
      minute: leg.minute,
      period_score: leg.period_score || leg.fh_score,
      full_score: leg.full_score,
      confidence: leg.confidence,
      estimated_odds: leg.estimated_odds,
      half: leg.half,
      event_id: leg.event_id,
      league_id: leg.league_id,
      onexbet_url: matchUrl(leg.event_id, leg.league_id),
      recommendation: leg.recommendation,
    }));
    const odds = acca.combined_odds || 1;
    const profit = stake * (odds - 1);
    const lines = [
      "PRO PUNTER · MANUAL BET SLIP",
      `Type: ${acca.name}`,
      `Stake: ${fmtMoney(stake)}`,
      `Combined odds: ${odds.toFixed(2)}`,
      `Potential profit: ${fmtMoney(profit)}`,
      "",
      "LEGS:",
      ...legs.flatMap((l, i) => [
        `${i + 1}. ${l.match} — ${l.selection} — ${l.confidence}%`,
        `   1xBet: ${l.onexbet_url}`,
      ]),
      "",
    ];
    const slip = {
      id: `acca-${acca.id}`,
      slip_type: "accumulator",
      title: acca.name,
      stake,
      combined_odds: odds,
      potential_return: stake * odds,
      potential_profit: profit,
      legs,
      checklist: [
        "Open 1xBet Live Football",
        "Add each leg to bet slip",
        "Verify odds",
        `Stake ${fmtMoney(stake)}`,
        "Place manually",
      ],
      onexbet_url: legs[0]?.onexbet_url || liveFootballUrl(),
      export_text: lines.join("\n"),
    };
    registerSlip(slip);
    return slip;
  }

  function slipFromLock(m, stake) {
    const url = matchUrl(m.event_id, m.league_id);
    const slip = {
      id: `lock-${m.event_id}-${m.half}`,
      slip_type: "goal_lock",
      title: `Goal Lock · ${m.home_team} vs ${m.away_team}`,
      stake,
      combined_odds: 1.05,
      potential_return: stake * 1.05,
      potential_profit: stake * 0.05,
      lock_pct: m.lock_pct,
      legs: [{
        match: `${m.home_team} vs ${m.away_team}`,
        home_team: m.home_team,
        away_team: m.away_team,
        selection: m.lock_label,
        confidence: m.lock_pct,
        period_score: m.period_score,
        minute: m.minute,
        half: m.half,
        event_id: m.event_id,
        league_id: m.league_id,
        onexbet_url: url,
      }],
      checklist: [
        "Open match on 1xBet",
        m.lock_market,
        `Stake ${fmtMoney(stake)}`,
        "Place manually",
      ],
      onexbet_url: url,
      export_text: [
        "PRO PUNTER · GOAL LOCK",
        m.lock_label,
        `${m.home_team} vs ${m.away_team}`,
        `Stake: ${fmtMoney(stake)}`,
        m.lock_market,
        `1xBet: ${url}`,
      ].join("\n"),
    };
    registerSlip(slip);
    return slip;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", loadOnexbetSite);
  } else {
    loadOnexbetSite();
  }

  return {
    copyText,
    matchUrl,
    open1xBet,
    setOnexbetSite,
    bind1xBetLinks,
    isMobile,
    showConfirm,
    actionButtons,
    registerSlip,
    bindActions,
    slipFromAcca,
    slipFromLock,
    toast,
    processAlerts,
    pollAlerts,
    startAlertPolling,
    setBrowserAlerts,
    requestNotifyPermission,
    fmtMoney,
  };
})();