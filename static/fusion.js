const POLL_MS = 15000;
let refreshSeconds = 30;
let pollTimer = null;
let currentFilter = "all";
let lastData = null;

const $ = (id) => document.getElementById(id);

function link1x(item, label = "1xBet ↗") {
  if (typeof BetAssistant === "undefined") return "";
  return BetAssistant.matchLinkHtml(
    item?.event_id,
    item?.league_id,
    label,
    "ba-match-link ba-1xbet-link",
    "football",
    item?.onexbet_url || "",
  );
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtConf(c) {
  return Number(c).toFixed(1);
}

function halfLabel(h) {
  return h === "sh" ? "2H" : "1H";
}

function isHalfTime(item) {
  return !!(item?.is_half_time || item?.half === "ht" || item?.status === "HT");
}

function matchMinute(item) {
  if (isHalfTime(item)) return 45;
  const raw = item?.minute ?? item?.live_stats?.minute;
  const m = Number(raw);
  if (Number.isNaN(m)) return null;
  if (item?.half === "sh") {
    const pm = Number(item?.period_minute ?? item?.live_stats?.period_minute);
    if (!Number.isNaN(pm) && pm >= 0 && m > 80 && pm < 45 && m - pm >= 85) return m - 45;
    if (m > 120) return m - 45;
  }
  return m;
}

function periodMinute(item) {
  const pm = item?.period_minute ?? item?.live_stats?.period_minute;
  if (pm != null && pm !== "") return Number(pm);
  const m = matchMinute(item);
  if (m == null || Number.isNaN(m)) return null;
  if (item?.half === "sh") return Math.max(0, m - 45);
  return m;
}

function fmtMinute(item, half) {
  if (isHalfTime(item)) return "HT";
  const m = matchMinute(item);
  if (m == null || Number.isNaN(m)) return "—";
  const h = half ?? item?.half;
  if (h === "sh") {
    const elapsed = periodMinute(item) ?? Math.max(0, m - 45);
    return `${m}' · 2H ${elapsed}'`;
  }
  return h === "fh" ? `1H ${m}'` : `${m}'`;
}

function minuteBadge(item, half) {
  const text = fmtMinute(item, half);
  const cls = isHalfTime(item) ? "minute-badge ht" : "minute-badge";
  return `<span class="${cls}">${text}</span>`;
}

function halfTimeBadge() {
  return '<span class="half-time-badge">HALF TIME</span>';
}

function fusionClass(verdict) {
  if (verdict === "STRONG BET" || verdict === "BET") return "fusion-bet";
  if (verdict === "CAUTION") return "fusion-caution";
  if (verdict === "WATCH") return "fusion-watch";
  return "fusion-wait";
}

function agreementClass(a) {
  if (a === "CONFIRMED" || a === "ALIGNED") return "agree-yes";
  if (a === "CONFLICT") return "agree-no";
  return "agree-neutral";
}

function marketSnapshot(m, f) {
  return f?.market_odds_summary || m.market_odds || {};
}

function hasStrongUnderLean(m, f) {
  return marketSnapshot(m, f).market_lean === "strong_under";
}

function tierBadge(m) {
  const tier = m.fusion_tier || (m.combined_analysis || {}).agreement || "ALIGNED";
  const cls = {
    CONFIRMED: "tier-confirmed",
    ALIGNED: "tier-aligned",
    STRONG_UNDER: "tier-strong-under",
  }[tier] || "tier-aligned";
  const label = tier === "STRONG_UNDER" ? "STRONG UNDER" : tier;
  return `<span class="fusion-tier-badge ${cls}">${label}</span>`;
}

function sourceChips(f, m) {
  const live = f.live_profile || "";
  const form = f.form_profile || "unknown";
  const sp = f.sp_profile || "unknown";
  const fm = f.fotmob_profile || "unknown";
  const mkt = f.market_odds_summary || m.market_odds || {};
  const slowLive = live === "very_slow" || live === "slow";
  const lowForm = form === "defensive" || form === "low_scoring";
  const lowSp = sp === "defensive" || sp === "low_scoring";
  const fmOk = fm !== "unknown" && !["fast", "high_scoring"].includes(fm);
  const mktLean = mkt.market_lean === "strong_under"
    || (mkt.market_lean && mkt.market_lean !== "neutral");

  const chip = (label, ok, detail, partial) => {
    const cls = ok ? "ok" : partial ? "warn" : "miss";
    const icon = ok ? "✓" : partial ? "~" : "·";
    return `<span class="fusion-source-chip ${cls}" title="${detail}">${icon} ${label}</span>`;
  };

  return [
    chip("1xBet Live", slowLive, `${live.replace(/_/g, " ")} tempo`, live === "average"),
    chip("ProphitBet", lowForm, `${form.replace(/_/g, " ")} form`, form === "balanced"),
    chip("SoccerPunter", lowSp, `${sp.replace(/_/g, " ")} H2H`, sp === "balanced"),
    chip("FotMob", fmOk, `${fm.replace(/_/g, " ")} xG`, fm === "unknown"),
    chip(
      "Market",
      mkt.market_lean === "strong_under" || mktLean,
      mkt.market_lean ? `${mkt.market_lean.replace(/_/g, " ")} lean` : "no lean",
      mkt.market_lean === "under",
    ),
  ].join("");
}

function renderFusionAnalysis(m) {
  const f = m.combined_analysis;
  if (!f) return "";

  const live = f.live_summary || {};
  const form = f.form_summary || {};
  const sp = f.sp_summary || {};
  const fm = f.fotmob_summary || {};
  const sd = f.sportsdb_summary || m.sportsdb_stats || {};
  const mkt = f.market_odds_summary || m.market_odds || {};
  const bd = f.breakdown || {};

  const sdLine = sd.total_shots
    ? `<div class="external-verify">SportsDB: ${sd.total_shots} shots · ${sd.shots_on_target ?? 0} SoT</div>`
    : "";
  const mktLine = mkt.under_15_implied_pct
    ? `<div class="market-odds-line">Market: ${mkt.under_15_implied_pct}% U1.5 @ ${mkt.under_15_odds ?? "—"} <span class="market-src">(${mkt.source || "1xbet"})</span></div>`
    : mkt.under_05_implied_pct
      ? `<div class="market-odds-line">Market: ${mkt.under_05_implied_pct}% U0.5 @ ${mkt.under_05_odds ?? "—"}</div>`
      : "";

  return `
    <div class="fusion-panel ${fusionClass(f.verdict)}">
      <div class="fusion-header">
        <span class="fusion-verdict">${f.verdict}</span>
        <span class="fusion-conf">${fmtConf(f.confidence)}%</span>
        <span class="fusion-agree ${agreementClass(f.agreement)}">${f.agreement}</span>
      </div>
      <div class="fusion-sources">${sourceChips(f, m)}</div>
      <div class="fusion-best">Best pick: <strong>${f.best_market}</strong> · ${f.best_recommendation}</div>
      <div class="fusion-grid">
        <div class="fusion-col">
          <div class="fusion-col-title">1xBet Live @ ${fmtMinute(m, m.half)}</div>
          <div class="mini-stats">
            <span class="mini-minute">${fmtMinute(m, m.half)}</span>
            <span>${live.shots ?? 0} shots</span>
            <span>${live.sot ?? 0} SoT</span>
            <span>${live.corners ?? 0} ck</span>
            <span>${live.dangerous_attacks ?? 0} danger</span>
          </div>
          <div class="fusion-profile">${(f.live_profile || "").replace(/_/g, " ")} tempo</div>
          ${fm.total_xg != null ? `<div class="fotmob-verify">FotMob: ${fm.total_xg} xG · ${fm.shots ?? 0} shots · ${(f.fotmob_profile || "").replace(/_/g, " ")}</div>` : ""}
        </div>
        <div class="fusion-col">
          <div class="fusion-col-title">ProphitBet Form</div>
          <div class="mini-stats">
            <span>U1.5 FH ${form.under_15_fh_pct ?? "—"}%</span>
            <span>U2.5 ${form.under_25_pct ?? "—"}%</span>
            <span>${form.goals_last_n ?? "—"} goals</span>
          </div>
          <div class="fusion-profile">${(f.form_profile || "").replace(/_/g, " ")} teams</div>
        </div>
        <div class="fusion-col">
          <div class="fusion-col-title">SoccerPunter H2H</div>
          <div class="mini-stats">
            <span>H2H ${sp.h2h_avg_goals ?? "—"} avg</span>
            <span>U2.25 ${sp.under_225_pct ?? "—"}%</span>
            <span>FH U0.5 ${sp.fh_under_05_pct ?? "—"}%</span>
          </div>
          <div class="fusion-profile">${(f.sp_profile || "unknown").replace(/_/g, " ")} trend</div>
        </div>
        <div class="fusion-col fusion-col-market">
          <div class="fusion-col-title">External + Market</div>
          ${sdLine}${mktLine || '<div class="fusion-profile">No cross-check data yet</div>'}
          ${mkt.market_lean && mkt.market_lean !== "neutral" ? `<div class="fusion-profile market-lean-${mkt.market_lean}">${mkt.market_lean.replace(/_/g, " ")} lean</div>` : ""}
        </div>
      </div>
      <div class="fusion-breakdown">
        <span>Form ${bd.historical ?? 0}</span>
        <span>SP ${bd.soccer_punter ?? 0}</span>
        <span>FM ${bd.fotmob_verify ?? 0}</span>
        <span>Ext ${bd.external_verify ?? 0}</span>
        <span>Mkt ${bd.market_odds ?? 0}</span>
        <span>Live ${bd.live_tempo ?? 0}</span>
        <span>Time ${bd.time_context ?? 0}</span>
        <span>Agree ${bd.agreement > 0 ? "+" : ""}${bd.agreement ?? 0}</span>
        <span class="fusion-total">= ${bd.total ?? 0}</span>
      </div>
      <ul class="signals-list">${(f.fusion_signals || []).map((s) => `<li>${s}</li>`).join("")}</ul>
    </div>`;
}

function renderFusionCard(m) {
  const f = m.combined_analysis || {};
  const stats = m.live_stats || {};
  const tier = m.fusion_tier || f.agreement || "ALIGNED";
  const mkt = marketSnapshot(m, f);
  const tierCls = {
    CONFIRMED: "tier-confirmed-card",
    STRONG_UNDER: "tier-strong-under-card",
  }[tier] || "";
  const marketTag = mkt.under_15_implied_pct
    ? `<span class="market-lean-tag market-lean-strong_under">${mkt.under_15_implied_pct}% U1.5</span>`
    : "";

  const betItem = {
    event_id: m.event_id,
    league_id: m.league_id,
    onexbet_url: m.onexbet_url,
    market: f.best_market,
    pick: "UNDER",
    recommendation: f.best_recommendation,
    market_odds: m.market_odds,
    estimated_odds: m.market_odds?.under_15_odds || m.market_odds?.under_05_odds,
  };

  return `
    <div class="match-card live fusion-match-card ${tierCls}">
      <div class="match-header">
        <div class="match-league">
          ${m.league || "Football"}
          ${tierBadge(m)}
          ${marketTag}
          <span class="source-tag">${halfLabel(m.half)}</span>
        </div>
        <div class="teams-row">
          <div class="team home"><span>${m.home_team}</span></div>
          <div class="score-block">
            <div class="score">${m.score}</div>
            <div class="minute">${fmtMinute(m, m.half)} · FT ${m.full_score || "—"}</div>
            ${minuteBadge(m, m.half)}
          </div>
          <div class="team away"><span>${m.away_team}</span></div>
        </div>
        <div class="match-1xbet-row">${link1x(m)}</div>
      </div>
      <div class="stats-row">
        <div class="stat-item"><div class="num">${stats.total_shots ?? 0}</div><div class="lbl">Shots</div></div>
        <div class="stat-item"><div class="num">${stats.shots_on_target ?? 0}</div><div class="lbl">On Target</div></div>
        <div class="stat-item"><div class="num">${stats.corners ?? 0}</div><div class="lbl">Corners</div></div>
        <div class="stat-item"><div class="num">${stats.dangerous_attacks ?? "—"}</div><div class="lbl">Danger</div></div>
        <div class="stat-item"><div class="num">${stats.home_possession ?? 50}%</div><div class="lbl">Poss</div></div>
      </div>
      <div class="fusion-pick-row">
        <span class="conf-big">${fmtConf(f.confidence)}%</span>
        <span style="font-size:0.9rem;color:var(--muted)">${f.best_market || "—"}</span>
        ${BetAssistant.recBadgeHtml(betItem, { label: f.best_recommendation === "BET" ? "BET NOW" : "WATCH" })}
      </div>
      ${renderFusionAnalysis(m)}
    </div>`;
}

function filterMatches(matches) {
  return (matches || []).filter((m) => {
    const f = m.combined_analysis || {};
    const tier = m.fusion_tier || f.agreement;
    const rec = f.best_recommendation;
    if (currentFilter === "confirmed") return tier === "CONFIRMED";
    if (currentFilter === "aligned") return tier === "ALIGNED";
    if (currentFilter === "strong_under") {
      return tier === "STRONG_UNDER" || hasStrongUnderLean(m, f);
    }
    if (currentFilter === "bet") return rec === "BET";
    return true;
  });
}

function renderBaselines(data) {
  const pb = data.prophitbet;
  const sp = data.soccerpunter;
  const fm = data.fotmob;
  const tsdb = data.thesportsdb;
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Fusion picks</div><div class="value green">${data.fusion_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Confirmed</div><div class="value" style="color:#d29922">${data.confirmed_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Aligned</div><div class="value green">${data.aligned_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Strong under</div><div class="value green">${data.strong_under_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">BET ready</div><div class="value green">${data.bet_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Live football</div><div class="value">${data.total_live_football ?? 0}</div></div>
    <div class="baseline-card"><div class="label">ProphitBet</div><div class="value">${pb?.loaded ? `${pb.teams_count} teams` : "…"}</div></div>
    <div class="baseline-card"><div class="label">SoccerPunter</div><div class="value">${sp?.index_pairs ?? "…"}</div></div>
    <div class="baseline-card"><div class="label">FotMob</div><div class="value">${fm?.index_matches ?? "…"}</div></div>
    <div class="baseline-card"><div class="label">TheSportsDB</div><div class="value">${tsdb?.index_events ?? "…"}</div></div>
  `;
}

function renderMatches(matches) {
  const grid = $("matchesGrid");
  const filtered = filterMatches(matches);
  if (!filtered.length) {
    const emptyMsg = currentFilter === "strong_under"
      ? "No strong under lean matches right now — 1xBet needs ≥72% implied on Under 1.5 for this half."
      : `No ${currentFilter === "all" ? "fusion" : currentFilter.replace(/_/g, " ")} matches right now. Check back when games are in play.`;
    grid.innerHTML = `<div class="empty">${emptyMsg}</div>`;
    return;
  }
  grid.innerHTML = filtered.map(renderFusionCard).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

async function fetchData() {
  try {
    const res = await fetch("/api/fusion");
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    lastData = data;
    if (typeof BetAssistant !== "undefined") BetAssistant.applyOnexbetConfig(data);
    refreshSeconds = data.refresh_seconds || 30;
    $("refreshInterval").textContent = refreshSeconds;
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    $("matchCount").textContent = `${data.fusion_count ?? 0} fusion · ${data.strong_under_count ?? 0} market`;
    $("liveTotal").textContent = `${data.total_live_football ?? 0} live scanned`;

    $("connectionStatus").classList.add("live");
    $("connectionStatus").classList.remove("error");
    $("statusText").textContent = `${data.fusion_count ?? 0} picks · ${data.bet_count ?? 0} BET`;

    if (data.loading && !(data.matches || []).length && !data.fusion_count) {
      $("matchesGrid").innerHTML =
        '<div class="loading">Waiting for live scan to finish — fusion picks appear after the first 1xBet refresh completes.</div>';
      $("statusText").textContent = "Initial scan in progress…";
      return;
    }

    renderBaselines(data);
    renderMatches(data.matches);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("connectionStatus").classList.remove("live");
    $("statusText").textContent = "Connection error";
    console.error(err);
  }
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    currentFilter = btn.dataset.filter;
    if (lastData) renderMatches(lastData.matches);
  });
});

$("btnRefresh").addEventListener("click", async () => {
  $("btnRefresh").disabled = true;
  await fetch("/api/refresh", { method: "POST" });
  await fetchData();
  $("btnRefresh").disabled = false;
});

function startPolling() {
  fetchData();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchData, POLL_MS);
}

startPolling();

if (typeof FusionAlerts !== "undefined") {
  FusionAlerts.init(POLL_MS);
}