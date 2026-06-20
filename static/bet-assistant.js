/**
 * Pro Punter betting assistant — export, confirm, browser alerts.
 * Does NOT place bets; copy slips and open 1xBet for manual placement.
 */
const BetAssistant = (() => {
  let seenAlertIds = new Set(JSON.parse(localStorage.getItem("pp_seen_alerts") || "[]"));
  let notifyEnabled = localStorage.getItem("pp_browser_alerts") !== "false";
  let pollTimer = null;
  const KENYA_SITE = "https://1xbet.co.ke";
  const KENYA_ANDROID_PKG = "org.xbet.client.ke_ps";
  let onexbetSite = (localStorage.getItem("pp_onexbet_site") || "").replace(/\/$/, "");
  if (!onexbetSite || onexbetSite === "https://1xbet.com" || onexbetSite === "http://1xbet.com") {
    onexbetSite = KENYA_SITE;
  }
  let onexbetAndroidPackage = localStorage.getItem("pp_onexbet_android_package") || KENYA_ANDROID_PKG;

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

  const ANDROID_PACKAGES = {
    "1xbet.co.ke": "org.xbet.client.ke_ps",
    "1xbet.ng": "org.xbet.client.ng_ps",
    "1xbet.com.zm": "org.xbet.client.zm_ps",
    "1xbet.com.gh": "com.xbet.betafrica.gh",
    "1xbet.ug": "org.xbet.client.ug_ps",
    "1xbet.co.tz": "org.xbet.client.tz_ps",
    "1xbet.co.mz": "org.xbet.client.mz_ps",
  };

  function setOnexbetSite(site) {
    if (!site) return;
    onexbetSite = String(site).trim().replace(/\/$/, "");
    if (onexbetSite && !/^https?:\/\//i.test(onexbetSite)) {
      onexbetSite = `https://${onexbetSite}`;
    }
    localStorage.setItem("pp_onexbet_site", onexbetSite);
    if (!onexbetAndroidPackage) {
      const guessed = guessAndroidPackage(onexbetSite);
      if (guessed) onexbetAndroidPackage = guessed;
    }
  }

  function setOnexbetAndroidPackage(pkg) {
    onexbetAndroidPackage = String(pkg || "").trim();
    localStorage.setItem("pp_onexbet_android_package", onexbetAndroidPackage);
  }

  function siteBase() {
    return onexbetSite || KENYA_SITE;
  }

  function liveFootballUrl() {
    return `${siteBase()}/en/live/football`;
  }

  function isAndroid() {
    return /Android/i.test(navigator.userAgent);
  }

  function isIOS() {
    return /iPhone|iPad|iPod/i.test(navigator.userAgent);
  }

  function isMobile() {
    return isAndroid() || isIOS()
      || (navigator.maxTouchPoints > 1 && window.innerWidth < 1024);
  }

  function guessAndroidPackage(siteUrl) {
    try {
      const host = new URL(siteUrl.startsWith("http") ? siteUrl : `https://${siteUrl}`).hostname.toLowerCase();
      if (ANDROID_PACKAGES[host]) return ANDROID_PACKAGES[host];
      if (host.endsWith(".co.ke")) return "org.xbet.client.ke_ps";
      if (host.endsWith(".co.tz")) return "org.xbet.client.tz_ps";
      if (host.endsWith(".co.mz")) return "org.xbet.client.mz_ps";
      if (host === "1xbet.ng" || host.endsWith(".ng")) return "org.xbet.client.ng_ps";
      if (host.endsWith(".com.zm")) return "org.xbet.client.zm_ps";
      if (host.endsWith(".com.gh")) return "com.xbet.betafrica.gh";
      if (host.endsWith(".ug")) return "org.xbet.client.ug_ps";
    } catch { /* ignore */ }
    return "";
  }

  function normalizeHttpsUrl(url) {
    const raw = url || liveFootballUrl();
    try {
      const u = new URL(raw, siteBase());
      if (onexbetSite) {
        const base = new URL(onexbetSite);
        u.protocol = base.protocol;
        u.host = base.host;
      }
      return u.toString().replace(/\/$/, "");
    } catch {
      return raw;
    }
  }

  function androidPackage() {
    return onexbetAndroidPackage || guessAndroidPackage(siteBase());
  }

  function androidIntentUrl(httpsUrl) {
    try {
      const u = new URL(httpsUrl);
      const path = `${u.host}${u.pathname}${u.search}`;
      return (
        `intent://${path}#Intent;scheme=https;` +
        "action=android.intent.action.VIEW;category=android.intent.category.BROWSABLE;end"
      );
    } catch {
      return httpsUrl;
    }
  }

  function androidAppUrl(httpsUrl) {
    const pkg = onexbetAndroidPackage || guessAndroidPackage(siteBase());
    if (!pkg) return httpsUrl;
    try {
      const u = new URL(httpsUrl);
      return `android-app://${pkg}/https/${u.host}${u.pathname}${u.search}`;
    } catch {
      return httpsUrl;
    }
  }

  function isInAppBrowser() {
    return /Telegram|WhatsApp|FBAN|FBAV|Instagram|Line\//i.test(navigator.userAgent || "");
  }

  function tryOpenApp(httpsUrl) {
    const intent = androidIntentUrl(httpsUrl);
    const appUri = androidAppUrl(httpsUrl);
    if (intent.indexOf("intent://") === 0) {
      const frame = document.createElement("iframe");
      frame.style.display = "none";
      frame.src = intent;
      document.body.appendChild(frame);
      setTimeout(() => frame.remove(), 3000);
      window.location.href = intent;
    }
    if (appUri.indexOf("android-app://") === 0) {
      setTimeout(() => {
        if (document.visibilityState !== "hidden") window.location.href = appUri;
      }, 350);
    }
    setTimeout(() => {
      if (document.visibilityState !== "hidden") {
        toast("If the app did not open: Settings → Apps → 1xBet → Open by default → enable links");
      }
    }, 2200);
  }

  function matchLinkHref(httpsUrl) {
    const normalized = normalizeHttpsUrl(httpsUrl);
    if (!isMobile()) return normalized;
    if (isInAppBrowser()) return openerPageUrl(normalized);
    if (isAndroid() && androidPackage()) {
      const appUri = androidAppUrl(normalized);
      if (appUri.indexOf("android-app://") === 0) return appUri;
    }
    return normalized;
  }

  function mobileOpenUrl(httpsUrl) {
    return matchLinkHref(httpsUrl);
  }

  function matchUrl(eventId, leagueId, sport = "football") {
    const gid = parseInt(eventId, 10);
    if (!gid || Number.isNaN(gid)) return liveFootballUrl();
    const lid = parseInt(leagueId, 10);
    const base = siteBase();
    if (lid && !Number.isNaN(lid)) {
      return `${base}/en/live/${sport}/${lid}/${gid}`;
    }
    return `${base}/en/live/${sport}/${gid}`;
  }

  function openerPageUrl(httpsUrl) {
    try {
      const u = new URL(httpsUrl);
      const parts = u.pathname.split("/").filter(Boolean);
      const gid = parts[parts.length - 1];
      const lid = parts.length >= 2 ? parts[parts.length - 2] : "";
      const sportIdx = parts.indexOf("live");
      const sport = sportIdx >= 0 && parts[sportIdx + 1] ? parts[sportIdx + 1] : "football";
      if (/^\d+$/.test(gid)) {
        const params = new URLSearchParams({ game_id: gid });
        if (/^\d+$/.test(lid)) params.set("league_id", lid);
        if (sport && sport !== "football") params.set("sport", sport);
        return `${window.location.origin}/open/1xbet?${params}`;
      }
    } catch { /* ignore */ }
    return `${window.location.origin}/open/1xbet`;
  }

  function open1xBet(url) {
    const httpsUrl = normalizeHttpsUrl(url || liveFootballUrl());
    if (!isMobile()) {
      window.open(httpsUrl, "_blank", "noopener");
      return;
    }
    if (isInAppBrowser()) {
      window.location.href = openerPageUrl(httpsUrl);
      return;
    }
    if (isAndroid() && androidPackage()) {
      const appUri = androidAppUrl(httpsUrl);
      if (appUri.indexOf("android-app://") === 0) {
        window.location.href = appUri;
        return;
      }
    }
    window.location.href = httpsUrl;
  }

  function oddsForMarket(item) {
    if (!item) return null;
    const pick = String(item.pick || "").toUpperCase();
    const market = String(item.market || item.selection || item.lock_market || "").toLowerCase();
    const gameOdds = item.game_odds || {};
    const q3Odds = item.q3_odds || {};
    const oddsBlock = (market.includes("quarter") || market.includes("q3")) ? q3Odds : gameOdds;
    if (pick === "UNDER" && oddsBlock.under_odds > 1) return oddsBlock.under_odds;
    if (pick === "OVER" && oddsBlock.over_odds > 1) return oddsBlock.over_odds;
    if (oddsBlock.under_odds > 1) return oddsBlock.under_odds;
    if (oddsBlock.over_odds > 1) return oddsBlock.over_odds;

    const mkt = item.market_odds || {};
    if (/under\s*0\.5|u0\.5/.test(market)) return mkt.under_05_odds || null;
    if (/under\s*1\.5|u1\.5/.test(market)) return mkt.under_15_odds || null;
    if (/under\s*2\.5|u2\.5/.test(market)) return mkt.under_25_odds || null;
    const est = Number(item.estimated_odds);
    if (est > 1) return est;
    return mkt.under_15_odds || mkt.under_05_odds || mkt.under_25_odds || null;
  }

  function betLinkHtml(item, opts = {}) {
    const gid = parseInt(item?.event_id, 10);
    if (!gid || Number.isNaN(gid)) return "";
    const sport = opts.sport || "football";
    const label = opts.label || "BET NOW";
    const odds = oddsForMarket(item);
    const text = odds ? `${label} @ ${Number(odds).toFixed(2)}` : label;
    return matchLinkHtml(gid, item.league_id, text, "rec-badge bet ba-1xbet-link", sport);
  }

  function recBadgeHtml(item, opts = {}) {
    const rec = item?.recommendation || opts.rec || "";
    const sport = opts.sport || "football";
    if (rec === "BET" || opts.forceBet) {
      const label = opts.label || (rec === "BET" ? "BET" : "BET NOW");
      return betLinkHtml(item, { label, sport });
    }
    const cls = rec === "WATCH" ? "watch" : rec === "SKIP" ? "skip" : "low";
    return `<span class="rec-badge ${cls}">${rec || opts.fallback || "—"}</span>`;
  }

  function matchLinkHtml(eventId, leagueId, label = "1xBet ↗", className = "ba-match-link ba-1xbet-link", sport = "football") {
    const gid = parseInt(eventId, 10);
    if (!gid || Number.isNaN(gid)) return "";
    const httpsUrl = matchUrl(eventId, leagueId, sport);
    const href = matchLinkHref(httpsUrl);
    const blank = isMobile() ? "" : ' target="_blank" rel="noopener"';
    return `<a href="${href}" data-https-url="${httpsUrl}" class="${className}"${blank}>${label}</a>`;
  }

  function bind1xBetLinks(root) {
    (root || document).querySelectorAll("a.ba-1xbet-link").forEach((a) => {
      if (a.dataset.baBound === "1") return;
      a.dataset.baBound = "1";
      const httpsUrl = a.dataset.httpsUrl || a.getAttribute("href");
      if (httpsUrl && !a.dataset.httpsUrl) a.dataset.httpsUrl = httpsUrl;
      if (isMobile() && httpsUrl && !/^intent:/i.test(a.getAttribute("href") || "")) {
        a.setAttribute("href", matchLinkHref(httpsUrl));
      }
      a.onclick = (e) => {
        e.preventDefault();
        open1xBet(a.dataset.httpsUrl || httpsUrl);
      };
    });
  }

  function applyOnexbetConfig(cfg) {
    if (!cfg) return;
    setOnexbetSite(cfg.onexbet_site || KENYA_SITE);
    setOnexbetAndroidPackage(cfg.onexbet_android_package || KENYA_ANDROID_PKG);
  }

  async function loadOnexbetSite() {
    try {
      const res = await fetch("/api/assistant/config");
      applyOnexbetConfig(await res.json());
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
        <br><a href="${mobileOpenUrl(url)}" data-https-url="${url}" ${isMobile() ? "" : 'target="_blank" rel="noopener"'} class="ba-leg-link ba-1xbet-link">Open on 1xBet ↗</a>
      </div>`;
    }).join("");
  }

  function closeModal() {
    document.querySelector(".ba-modal-overlay")?.remove();
  }

  function showConfirm(slip, workflow) {
    closeModal();
    const streak = workflow?.loss_streak || 0;
    const maxStreak = workflow?.max_loss_streak || 5;
    const warning = streak >= maxStreak - 1 && streak > 0
      ? `<div class="ba-modal-warning">${streak} losses in a row — session resets after ${maxStreak} consecutive losses.</div>`
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
          <button class="ba-btn" data-act="placed">Mark placed</button>
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
          wave: slip.wave || "",
          potential_profit: slip.potential_profit || 0,
          combined_odds: slip.combined_odds || 0,
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
    const leg = slip.legs?.[0];
    const betItem = leg ? {
      ...leg,
      event_id: leg.event_id,
      league_id: leg.league_id,
      market: leg.selection || leg.market,
      market_odds: leg.market_odds,
      estimated_odds: leg.estimated_odds,
    } : null;
    const betLink = betItem ? betLinkHtml(betItem, { label: "Bet now" }) : "";
    return `
      <div class="${cls}">
        <button class="ba-btn primary" type="button" data-ba-copy="${slip.id}">Copy slip</button>
        <button class="ba-btn orange" type="button" data-ba-confirm="${slip.id}">Review & place</button>
        ${betLink || `<button class="ba-btn" type="button" data-ba-1xbet="${slip.id}">1xBet ↗</button>`}
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
        market: m.lock_market,
        lock_market: m.lock_market,
        market_odds: m.market_odds,
        estimated_odds: 1.05,
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
    matchLinkHtml,
    betLinkHtml,
    recBadgeHtml,
    oddsForMarket,
    open1xBet,
    setOnexbetSite,
    setOnexbetAndroidPackage,
    applyOnexbetConfig,
    mobileOpenUrl,
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