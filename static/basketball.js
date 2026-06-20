const POLL_MS = 15000;
let refreshSeconds = 30;
let pollTimer = null;
let lastData = null;

const $ = (id) => document.getElementById(id);

function link1x(item, label = "1xBet ↗") {
  if (typeof BetAssistant === "undefined") return "";
  return BetAssistant.matchLinkHtml(item?.event_id, item?.league_id, label, "ba-match-link ba-1xbet-link", "basketball");
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function recClass(rec) {
  if (rec === "BET") return "bet";
  if (rec === "WATCH") return "watch";
  return "low";
}

function pickClass(pick) {
  if (pick === "OVER") return "over";
  if (pick === "UNDER") return "under";
  return "near";
}

function renderBaselines(data) {
  const minPct = data.min_definite_pct ?? 70;
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Live basketball</div><div class="value orange">${data.total_live ?? 0}</div></div>
    <div class="baseline-card"><div class="label">3rd quarter</div><div class="value orange">${data.match_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">≥${minPct}% definite</div><div class="value orange">${data.definite_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Cyber excluded</div><div class="value">${data.excluded_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">70%+ signals</div><div class="value orange">${data.bet_signal_count ?? 0}</div></div>
  `;
}

function renderBetSignals(signals) {
  const section = $("betSignalsSection");
  const grid = $("betSignals");
  if (!signals?.length) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  grid.innerHTML = signals.map((s) => `
    <div class="signal-card">
      <div style="font-size:0.75rem;color:var(--muted)">${s.league}</div>
      <div style="font-weight:700">${s.match} ${link1x(s)}</div>
      <div style="font-size:0.8rem;color:var(--muted);margin:6px 0">
        ${s.score} · ${s.q3_clock} · ${s.market}
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        <span class="conf-big definite-label">${s.label || `${s.pick} ${s.line} · ${Number(s.confidence).toFixed(0)}%`}</span>
        ${BetAssistant.betLinkHtml({ ...s, recommendation: "BET" }, { label: "BET NOW", sport: "basketball" })}
      </div>
      <ul class="bb-signals">${(s.signals || []).map((x) => `<li>${x}</li>`).join("")}</ul>
    </div>
  `).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

function renderMatchCard(m) {
  const definite = m.definite_pick;
  const hasBet = !!definite || (m.predictions || []).some((p) => p.is_definite);
  const qChips = Object.entries(m.quarters || {}).map(([q, val]) => {
    const active = q === "Q3" ? " active" : "";
    return `<span class="bb-q-chip${active}">${q}: ${val}</span>`;
  }).join("");

  const definiteBanner = definite
    ? `<div class="bb-definite-pick ${pickClass(definite.pick)}">${definite.label}</div>`
    : `<div class="bb-no-definite">No ${lastData?.min_definite_pct ?? 70}%+ pick — see best below</div>`;

  const predsHtml = (m.predictions || []).map((p) => `
    <div class="bb-pred${p.is_definite ? " definite" : ""}">
      <span class="bb-pred-market">${p.market}</span>
      <span class="bb-pred-pick ${pickClass(p.pick)}">${p.label || `${p.pick} ${p.line}`}</span>
      <span class="bb-pred-conf">${Number(p.confidence).toFixed(0)}%</span>
      ${p.is_definite
        ? BetAssistant.betLinkHtml({ ...p, event_id: m.event_id, league_id: m.league_id, game_odds: m.game_odds, q3_odds: m.q3_odds, recommendation: "BET" }, { label: "BET NOW", sport: "basketball" })
        : BetAssistant.recBadgeHtml({ ...p, event_id: m.event_id, league_id: m.league_id, game_odds: m.game_odds, q3_odds: m.q3_odds }, { sport: "basketball" })}
    </div>
    <ul class="bb-signals">${(p.signals || []).slice(0, 5).map((s) => `<li>${s}</li>`).join("")}</ul>
  `).join("");

  const pace = m.pace || {};
  const hist = m.history || {};
  const qs = m.quarter_stats || {};
  const vsHist = (v) => {
    if (v == null || Number.isNaN(v)) return "";
    const cls = v > 2 ? " above" : v < -2 ? " below" : "";
    return `<span class="bb-vs-hist${cls}">${v > 0 ? "+" : ""}${v}</span>`;
  };

  return `
    <div class="basketball-card${hasBet ? " bet-pick" : ""}">
      <div class="bb-header">
        <div>
          <div class="bb-league">${m.league || "Basketball"}</div>
          <div class="bb-teams">${m.home_team} vs ${m.away_team} ${link1x(m)}</div>
        </div>
        <span class="bb-q3-badge">${m.q3_clock || "Q3"} · ${qs.game_pct ?? "—"}% played</span>
      </div>
      <div class="bb-score-row">
        <span class="bb-score">${m.score}</span>
        <span class="bb-total">${m.total_points} pts · 3Q sum ${qs.three_q_total ?? "—"} · proj ${pace.proj_final ?? "—"}</span>
      </div>
      ${definiteBanner}
      <div class="bb-quarters">${qChips}</div>
      <div class="bb-stats-table">
        <div class="bb-stats-row head"><span>Quarter</span><span>Live</span><span>Hist</span><span>vs Hist</span></div>
        <div class="bb-stats-row"><span>Q1</span><span>${qs.q1 ?? "—"}</span><span>${hist.hist_q1 ?? "—"}</span><span>${vsHist(qs.q1_vs_hist)}</span></div>
        <div class="bb-stats-row"><span>Q2</span><span>${qs.q2 ?? "—"}</span><span>${hist.hist_q2 ?? "—"}</span><span>${vsHist(qs.q2_vs_hist)}</span></div>
        <div class="bb-stats-row active"><span>Q3</span><span>${qs.q3_so_far ?? "—"} → ${qs.q3_pace_to_full ?? "—"}</span><span>${hist.hist_q3 ?? "—"}</span><span>${vsHist(qs.q3_vs_hist)}</span></div>
        <div class="bb-stats-row sum"><span>3Q total</span><span>${qs.three_q_total ?? "—"}</span><span>${hist.hist_expected_now ?? "—"}</span><span>${vsHist(qs.three_q_vs_hist)}</span></div>
      </div>
      <div class="bb-pace-grid">
        <div class="bb-pace-item"><div class="num">${qs.three_q_ppm ?? "—"}</div><div class="lbl">3Q ppm</div></div>
        <div class="bb-pace-item"><div class="num">${qs.trajectory ?? "—"}</div><div class="lbl">Trend</div></div>
        <div class="bb-pace-item"><div class="num">${pace.proj_historical ?? "—"}</div><div class="lbl">Hist proj</div></div>
        <div class="bb-pace-item"><div class="num">${hist.hist_bias ?? "—"}</div><div class="lbl">Hist lean</div></div>
      </div>
      <div class="bb-predictions">${predsHtml}</div>
    </div>`;
}

function renderMatches(matches) {
  const grid = $("matchesGrid");
  if (!matches?.length) {
    grid.innerHTML = '<div class="empty">No live 3rd-quarter games right now. Check back during match play.</div>';
    return;
  }
  grid.innerHTML = matches.map(renderMatchCard).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

async function fetchData() {
  try {
    const res = await fetch("/api/basketball");
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    lastData = data;
    if (typeof BetAssistant !== "undefined") BetAssistant.applyOnexbetConfig(data);
    refreshSeconds = data.refresh_seconds || 30;
    $("refreshInterval").textContent = refreshSeconds;
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    $("matchCount").textContent = `${data.match_count ?? 0} Q3 games`;
    $("liveTotal").textContent = `${data.total_live ?? 0} live (${data.excluded_count ?? 0} cyber out)`;

    $("connectionStatus").classList.add("live");
    $("connectionStatus").classList.remove("error");
    const minPct = data.min_definite_pct ?? 70;
    $("statusText").textContent = `≥${minPct}% definite · ${data.definite_count ?? 0}/${data.match_count ?? 0} games · ${data.bet_signal_count} signals`;

    renderBaselines(data);
    renderBetSignals(data.bet_signals);
    renderMatches(data.matches);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("connectionStatus").classList.remove("live");
    $("statusText").textContent = "1xBet connection error";
    console.error(err);
  }
}

$("btnRefresh").addEventListener("click", async () => {
  $("btnRefresh").disabled = true;
  await fetch("/api/basketball/refresh", { method: "POST" });
  await fetchData();
  $("btnRefresh").disabled = false;
});

function startPolling() {
  fetchData();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchData, POLL_MS);
}

startPolling();