const POLL_MS = 15000;
let refreshSeconds = 30;
let pollTimer = null;
let currentFilter = "bet60";
const MIN_CONF = 60;
let lastData = null;

const $ = (id) => document.getElementById(id);

function link1x(item, label = "1xBet ↗") {
  if (typeof BetAssistant === "undefined") return "";
  return BetAssistant.matchLinkHtml(item?.event_id, item?.league_id, label, "ba-match-link ba-1xbet-link", "football", item?.onexbet_url || "");
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function recClass(rec) {
  if (rec === "BET") return "bet";
  if (rec === "WATCH") return "watch";
  if (rec === "SKIP") return "skip";
  return "low";
}

function confClass(c) {
  if (c >= 70) return "high";
  if (c >= 50) return "mid";
  return "low";
}

function providerLabel(p, countKey) {
  if (!p) return "—";
  if (p.loading || p.loading_index) return "Loading…";
  if (p.error) return "Error";
  const n = p[countKey];
  if (n != null) return String(n);
  return p.loaded ? "OK" : "Pending";
}

function renderBaselines(b, meta, pb, tsdb) {
  if (!b) return;
  const pbLabel = pb?.loaded
    ? `${pb.teams_count ?? 0} teams`
    : pb?.loading ? "Loading…" : "Pending";
  const tsdbLabel = providerLabel(tsdb, "index_events", "loading");
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Live football (1xBet)</div><div class="value">${meta?.total_live ?? 0}</div></div>
    <div class="baseline-card"><div class="label">1st half</div><div class="value green">${meta?.first_half ?? 0}</div></div>
    <div class="baseline-card"><div class="label">2nd half</div><div class="value green">${meta?.second_half ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Half-time</div><div class="value">${meta?.half_time_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Scored · under alive</div><div class="value green">${meta?.scored_filter ?? 0}</div></div>
    <div class="baseline-card"><div class="label">ProphitBet form DB</div><div class="value">${pbLabel}</div></div>
    <div class="baseline-card"><div class="label">TheSportsDB verify</div><div class="value">${tsdbLabel}</div></div>
  `;
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

function normalizeMatchMinute(item, raw) {
  const m = Number(raw);
  if (Number.isNaN(m)) return null;
  const half = item?.half ?? item?.status;
  if (half !== "sh" && half !== "2H") return m;

  const pm = Number(item?.period_minute ?? item?.live_stats?.period_minute);
  if (!Number.isNaN(pm) && pm >= 0) {
    const clock = 45 + pm;
    // Fix legacy double-add bug (45 + total_clock e.g. 45+56=101')
    if (m === clock + 45) return clock;
    if (m > 80 && pm < 45 && m - pm >= 85) return m - 45;
  }
  if (m > 120) return m - 45;
  return m;
}

function matchMinute(item) {
  if (isHalfTime(item)) return 45;
  const raw = item?.minute ?? item?.live_stats?.minute;
  if (raw == null || raw === "") return null;
  return normalizeMatchMinute(item, raw);
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
  if (h === "ht") return "HT";
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

function minuteStatItem(item, half) {
  const m = matchMinute(item);
  const num = m != null && !Number.isNaN(m) ? m : "—";
  const h = half ?? item?.half;
  let lbl = "Minute";
  if (h === "sh" && m != null) {
    const elapsed = periodMinute(item) ?? Math.max(0, m - 45);
    lbl = `2H +${elapsed}'`;
  } else if (h === "fh") {
    lbl = "1H Min";
  } else if (h) {
    lbl = `${halfLabel(h)} Min`;
  }
  return `<div class="stat-item minute-stat"><div class="num">${num}${m != null ? "'" : ""}</div><div class="lbl">${lbl}</div></div>`;
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

function renderFusionAnalysis(m) {
  const f = m.combined_analysis;
  if (!f) return renderProphitStats(m.prophit_stats, m);

  const live = f.live_summary || {};
  const form = f.form_summary || {};
  const sp = f.sp_summary || {};
  const fm = f.fotmob_summary || {};
  const sd = f.sportsdb_summary || m.sportsdb_stats || {};
  const mkt = f.market_odds_summary || m.market_odds || {};
  const prs = f.pressure_summary || {};
  const bd = f.breakdown || {};

  const sdLine = sd.total_shots
    ? `<div class="external-verify">SportsDB: ${sd.total_shots} shots · ${sd.shots_on_target ?? 0} SoT</div>`
    : "";
  const mktLine = mkt.under_15_implied_pct
    ? `<div class="market-odds-line">Market: ${mkt.under_15_implied_pct}% U1.5 @ ${mkt.under_15_odds ?? "—"} <span class="market-src">(${mkt.source || "1xbet"})</span></div>`
    : mkt.under_05_implied_pct
      ? `<div class="market-odds-line">Market: ${mkt.under_05_implied_pct}% U0.5 @ ${mkt.under_05_odds ?? "—"}</div>`
      : "";
  const prsLine = prs.p_under_15
    ? `<div class="pressure-model-line">GAP: ${prs.p_under_15}% U1.5 · fair ${prs.fair_under_odds ?? "—"}${prs.under_edge_pct >= 4 ? ` · <strong>+${prs.under_edge_pct}pp edge</strong>` : ""}</div>`
    : "";

  return `
    <div class="fusion-panel ${fusionClass(f.verdict)}">
      <div class="fusion-header">
        <span class="fusion-verdict">${f.verdict}</span>
        <span class="fusion-conf">${fmtConf(f.confidence)}%</span>
        <span class="fusion-agree ${agreementClass(f.agreement)}">${f.agreement}</span>
      </div>
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
          ${sdLine}${prsLine}${mktLine || '<div class="fusion-profile">No cross-check data yet</div>'}
          ${mkt.market_lean && mkt.market_lean !== "neutral" ? `<div class="fusion-profile market-lean-${mkt.market_lean}">${mkt.market_lean.replace(/_/g, " ")} lean</div>` : ""}
        </div>
      </div>
      <div class="fusion-breakdown">
        <span>Form ${bd.historical ?? 0}</span>
        <span>SP ${bd.soccer_punter ?? 0}</span>
        <span>FM ${bd.fotmob_verify ?? 0}</span>
        <span>Ext ${bd.external_verify ?? 0}</span>
        <span>Mkt ${bd.market_odds ?? 0}</span>
        <span>GAP ${bd.pressure_model ?? 0}</span>
        <span>Live ${bd.live_tempo ?? 0}</span>
        <span>Time ${bd.time_context ?? 0}</span>
        <span>Agree ${bd.agreement > 0 ? "+" : ""}${bd.agreement ?? 0}</span>
        <span class="fusion-total">= ${bd.total ?? 0}</span>
      </div>
      <ul class="signals-list">${(f.fusion_signals || []).slice(0, 6).map((s) => `<li>${s}</li>`).join("")}</ul>
    </div>`;
}

function renderProphitStats(pb, matchCtx) {
  if (!pb?.home && !pb?.away) return "";
  const h = pb.home || {};
  const a = pb.away || {};
  const minLine = matchCtx ? `<div class="prophit-minute">${minuteBadge(matchCtx)}</div>` : "";
  return `
    <div class="prophit-stats">
      ${minLine}
      <div class="prophit-title">ProphitBet form (last ${pb.form_window ?? 3})</div>
      <div class="prophit-teams">
        <span class="prophit-team">${h.matched_name || h.team || "Home"}: ${h.goals_scored ?? "—"}GF ${h.goals_conceded ?? "—"}GA</span>
        <span class="prophit-team">${a.matched_name || a.team || "Away"}: ${a.goals_scored ?? "—"}GF ${a.goals_conceded ?? "—"}GA</span>
      </div>
    </div>`;
}

function renderScoredPicks(sectionId, gridId, items, marketLabel) {
  const section = $(sectionId);
  const grid = $(gridId);
  if (!items?.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  grid.innerHTML = items.map((item) => {
    const p = item.pick;
    const st = item.live_stats || {};
    return `
      <div class="signal-card scored-card">
        <div class="scored-meta">${item.league}</div>
        <div style="font-weight:700;font-size:1.05rem">${item.home_team} vs ${item.away_team} ${link1x(item)}</div>
        <div class="scored-line">
          ${isHalfTime(item) ? halfTimeBadge() : ""}
          <span class="fh-score">${isHalfTime(item) ? "HT" : halfLabel(item.half)}: ${item.period_score || item.fh_score}</span>
          ${minuteBadge(item, item.half)}
        </div>
        <div style="font-size:0.82rem;color:var(--muted);margin:8px 0">${marketLabel}</div>
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
          <span class="conf-big">${fmtConf(p.confidence)}%</span>
          ${BetAssistant.recBadgeHtml({ ...p, event_id: item.event_id, league_id: item.league_id, onexbet_url: item.onexbet_url, market_odds: p.market_odds || item.market_odds })}
        </div>
        <div class="mini-stats">
          <span class="mini-minute">${fmtMinute(item, item.half)}</span>
          <span>Shots ${st.total_shots ?? 0}</span>
          <span>SoT ${st.shots_on_target ?? 0}</span>
          <span>Corners ${st.corners ?? 0}</span>
          <span>Poss ${st.home_possession ?? 50}%</span>
        </div>
        ${renderFusionAnalysis(item)}
        <ul class="signals-list">${(p.signals || []).slice(0, 4).map((s) => `<li>${s}</li>`).join("")}</ul>
      </div>`;
  }).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

function renderBetSignals(signals) {
  const section = $("betSignalsSection");
  const grid = $("betSignals");
  if (!signals?.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  grid.innerHTML = signals.map((p) => `
    <div class="signal-card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:4px">
        <div style="font-weight:700">${p.match} ${link1x(p)}</div>
        <div style="display:flex;gap:6px;align-items:center">${isHalfTime(p) ? halfTimeBadge() : ""}${minuteBadge(p, p.half)}</div>
      </div>
      <div style="font-size:0.8rem;color:var(--muted);margin-bottom:10px">
        ${p.market}${p.period_score ? ` · ${halfLabel(p.half)} ${p.period_score}` : ""}
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        <span class="conf-big">${Math.round(p.confidence)}%</span>
        ${BetAssistant.betLinkHtml({ ...p, onexbet_url: p.onexbet_url }, { label: "BET NOW" })}
      </div>
      <ul class="signals-list">${(p.signals || []).slice(0, 4).map((s) => `<li>${s}</li>`).join("")}</ul>
    </div>
  `).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

function renderMatchCard(m) {
  const stats = m.live_stats;
  const allSignals = [...new Set(m.predictions?.flatMap((p) => p.signals || []) || [])];

  const atHt = isHalfTime(m);
  const hl = atHt ? "HT" : halfLabel(m.half);
  const entryLabel = m.half === "sh" ? "ENTRY 60-65'" : "ENTRY 15-20'";
  const statusBadge = atHt
    ? '<span class="status-badge ht">HALF TIME</span>'
    : m.in_entry_window
      ? `<span class="status-badge window">${entryLabel}</span>`
      : m.scored_filter
        ? '<span class="status-badge scored">SCORED · UNDER ALIVE</span>'
        : `<span class="status-badge live">${hl} LIVE</span>`;

  const statsHtml = stats ? `
    <div class="stats-row">
      ${minuteStatItem({ minute: stats.minute ?? m.minute, half: m.half }, m.half)}
      <div class="stat-item"><div class="num">${stats.total_shots ?? 0}</div><div class="lbl">Shots</div></div>
      <div class="stat-item"><div class="num">${stats.shots_on_target ?? 0}</div><div class="lbl">On Target</div></div>
      <div class="stat-item"><div class="num">${stats.corners ?? 0}</div><div class="lbl">Corners</div></div>
      <div class="stat-item"><div class="num">${stats.dangerous_attacks ?? "—"}</div><div class="lbl">Danger</div></div>
      <div class="stat-item"><div class="num">${stats.home_possession ?? 50}%</div><div class="lbl">Poss</div></div>
    </div>` : "";

  const aliveTags = [
    m.under_15_alive ? '<span class="alive-tag u15">U1.5 alive</span>' : "",
    m.under_25_alive ? '<span class="alive-tag u25">U2.5 alive</span>' : "",
  ].filter(Boolean).join("");

  const predsHtml = (m.predictions || []).map((p) => `
    <div class="pred-row">
      <span class="pred-market">${p.market.replace("First Half Goals", "FH").replace("Second Half Goals", "SH")}</span>
      <div class="confidence-bar-wrap">
        <div class="confidence-bar ${confClass(p.confidence)}" style="width:${p.confidence}%"></div>
      </div>
      <span class="confidence-pct">${fmtConf(p.confidence)}%</span>
      ${BetAssistant.recBadgeHtml({ ...p, event_id: m.event_id, league_id: m.league_id, onexbet_url: m.onexbet_url, market_odds: p.market_odds || m.market_odds })}
    </div>
  `).join("");

  const cardClass = [
    "match-card", "live",
    atHt ? "half-time" : "",
    m.in_entry_window ? "entry-window" : "",
    m.scored_filter ? "scored-alive" : "",
  ].filter(Boolean).join(" ");

  return `
    <div class="${cardClass}" data-scored="${m.scored_filter}" data-window="${m.in_entry_window}">
      <div class="match-header">
        <div class="match-league">${m.league || "Football"} ${atHt ? halfTimeBadge() : `<span class="source-tag">${hl}</span>`} <span class="source-tag">1xBet</span></div>
        <div class="teams-row">
          <div class="team home"><span>${m.home_team}</span></div>
          <div class="score-block">
            <div class="score">${m.score}</div>
            <div class="minute">${fmtMinute(m, m.half)} · ${atHt ? `FH ${m.period_score || m.fh_score}` : `${hl} ${m.period_goals ?? m.fh_goals} goals`} · FT ${m.full_score || "—"}</div>
            ${statusBadge}
            <div class="alive-tags">${aliveTags}</div>
          </div>
          <div class="team away"><span>${m.away_team}</span></div>
        </div>
        <div class="match-1xbet-row">${link1x(m)}</div>
      </div>
      ${statsHtml}
      ${atHt ? '<div class="ht-note">Break between halves — 2nd half picks open at 60′. FH score locked.</div>' : renderFusionAnalysis(m)}
      <div class="predictions">
        ${atHt ? '<div class="empty-ht">No live bets at half-time. Check back for 2H entry (60′–65′).</div>' : predsHtml}
        ${allSignals.length ? `<ul class="signals-list">${allSignals.slice(0, 4).map((s) => `<li>${s}</li>`).join("")}</ul>` : ""}
      </div>
    </div>`;
}

function filterMatches(matches) {
  if (currentFilter === "ht") return matches.filter((m) => isHalfTime(m));
  if (currentFilter === "fh") return matches.filter((m) => m.half === "fh");
  if (currentFilter === "sh") return matches.filter((m) => m.half === "sh");
  if (currentFilter === "scored") return matches.filter((m) => m.scored_filter);
  if (currentFilter === "window") return matches.filter((m) => m.in_entry_window);
  if (currentFilter === "bet60") {
    return matches.filter((m) => (m.predictions || []).length > 0);
  }
  return matches;
}

function renderMatches(matches) {
  const grid = $("matchesGrid");
  const filtered = filterMatches(matches || []);
  if (!filtered.length) {
    grid.innerHTML = '<div class="empty">No matches match this filter. Try "All" or wait for live games.</div>';
    return;
  }
  grid.innerHTML = filtered.map(renderMatchCard).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

async function fetchData() {
  try {
    const res = await fetch("/api/predictions");
    const data = await res.json();
    if (data.error && !lastData?.matches?.length) {
      $("matchesGrid").innerHTML = `<div class="empty">Scan error: ${data.error}</div>`;
      $("statusText").textContent = "Scan error";
      $("connectionStatus").classList.add("error");
      return;
    }
    if (data.error && lastData?.matches?.length) {
      $("statusText").textContent = `Stale data · ${data.error}`;
    }

    lastData = data;
    if (typeof BetAssistant !== "undefined") BetAssistant.applyOnexbetConfig(data);
    refreshSeconds = data.refresh_seconds || 30;
    $("refreshInterval").textContent = refreshSeconds;
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    const fh = data.first_half_count ?? 0;
    const sh = data.second_half_count ?? 0;
    const ht = data.half_time_count ?? 0;
    $("matchCount").textContent = `${fh} FH · ${sh} SH${ht ? ` · ${ht} HT` : ""}`;
    const excluded = data.excluded_count ?? 0;
    $("liveTotal").textContent = `${data.total_live_football ?? 0} live (${excluded} excluded)`;

    $("connectionStatus").classList.add("live");
    $("connectionStatus").classList.remove("error");
    const pb = data.prophitbet;
    const sp = data.soccerpunter;
    const fm = data.fotmob;
    const tsdb = data.thesportsdb;
    const pbNote = pb?.loaded ? ` · PB ${pb.teams_count} teams` : pb?.loading ? " · PB loading" : "";
    const spNote = sp?.index_pairs ? ` · SP ${sp.index_pairs} pairs` : sp?.loading_index ? " · SP loading" : "";
    const fmNote = fm?.index_matches ? ` · FM ${fm.index_matches}` : fm?.loading ? " · FM loading" : "";
    const tsdbNote = tsdb?.index_events ? ` · TSDB ${tsdb.index_events}` : tsdb?.loading ? " · TSDB loading" : "";
    const minC = data.min_confidence ?? MIN_CONF;
    $("statusText").textContent = `≥${minC}% only · ${data.match_count} matches · ${data.bet_signal_count} signals${pbNote}${spNote}${fmNote}${tsdbNote}`;

    if (data.loading && !(data.matches || []).length) {
      $("matchesGrid").innerHTML =
        '<div class="loading">Scanning live matches — first load can take 1–3 min on Render while stats indexes build…</div>';
      $("statusText").textContent = "Initial scan in progress…";
      return;
    }

    renderBaselines(data.baselines, data, data.prophitbet, data.thesportsdb);
    renderScoredPicks("scoredU15Section", "scoredU15", data.scored_under_15, "Under 1.5 First Half");
    renderScoredPicks("scoredU25Section", "scoredU25", data.scored_under_25, "Under 2.5 First Half");
    renderBetSignals(data.bet_signals);
    renderMatches(data.matches);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("connectionStatus").classList.remove("live");
    $("statusText").textContent = "1xBet connection error";
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
if (typeof BetAssistant !== "undefined") BetAssistant.startAlertPolling(30000);