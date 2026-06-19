const POLL_MS = 15000;
let refreshSeconds = 30;
let pollTimer = null;
let lastData = null;

const $ = (id) => document.getElementById(id);

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
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Live basketball</div><div class="value orange">${data.total_live ?? 0}</div></div>
    <div class="baseline-card"><div class="label">3rd quarter</div><div class="value orange">${data.match_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Cyber excluded</div><div class="value">${data.excluded_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Other periods</div><div class="value">${data.non_q3_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Signals</div><div class="value orange">${data.bet_signal_count ?? 0}</div></div>
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
      <div style="font-weight:700">${s.match}</div>
      <div style="font-size:0.8rem;color:var(--muted);margin:6px 0">
        ${s.score} · ${s.q3_clock} · ${s.market}
      </div>
      <div style="display:flex;align-items:center;gap:12px">
        <span class="conf-big">${s.pick} ${s.line}</span>
        <span class="rec-badge ${recClass(s.recommendation)}">${s.recommendation}</span>
        <span class="bb-pred-conf">${Number(s.confidence).toFixed(1)}%</span>
      </div>
      <ul class="bb-signals">${(s.signals || []).map((x) => `<li>${x}</li>`).join("")}</ul>
    </div>
  `).join("");
}

function renderMatchCard(m) {
  const hasBet = (m.predictions || []).some((p) => p.recommendation === "BET");
  const qChips = Object.entries(m.quarters || {}).map(([q, val]) => {
    const active = q === "Q3" ? " active" : "";
    return `<span class="bb-q-chip${active}">${q}: ${val}</span>`;
  }).join("");

  const predsHtml = (m.predictions || []).map((p) => `
    <div class="bb-pred">
      <span class="bb-pred-market">${p.market}</span>
      <span class="bb-pred-pick ${pickClass(p.pick)}">${p.pick} ${p.line}</span>
      <span class="bb-pred-conf">${Number(p.confidence).toFixed(1)}%</span>
      <span class="rec-badge ${recClass(p.recommendation)}">${p.recommendation}</span>
    </div>
    <ul class="bb-signals">${(p.signals || []).slice(0, 3).map((s) => `<li>${s}</li>`).join("")}</ul>
  `).join("");

  const pace = m.pace || {};
  const hist = m.history || {};

  return `
    <div class="basketball-card${hasBet ? " bet-pick" : ""}">
      <div class="bb-header">
        <div>
          <div class="bb-league">${m.league || "Basketball"}</div>
          <div class="bb-teams">${m.home_team} vs ${m.away_team}</div>
        </div>
        <span class="bb-q3-badge">${m.q3_clock || "Q3"}</span>
      </div>
      <div class="bb-score-row">
        <span class="bb-score">${m.score}</span>
        <span class="bb-total">${m.total_points} pts · proj ${pace.proj_final ?? "—"}</span>
      </div>
      <div class="bb-quarters">${qChips}</div>
      <div class="bb-pace-grid">
        <div class="bb-pace-item"><div class="num">${pace.h1_pace ?? "—"}</div><div class="lbl">H1 ppm</div></div>
        <div class="bb-pace-item"><div class="num">${pace.q3_pace ?? "—"}</div><div class="lbl">Q3 ppm</div></div>
        <div class="bb-pace-item"><div class="num">${pace.proj_q3 ?? "—"}</div><div class="lbl">Proj Q3</div></div>
        <div class="bb-pace-item"><div class="num">${hist.hist_game ?? "—"}</div><div class="lbl">Hist avg</div></div>
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
}

async function fetchData() {
  try {
    const res = await fetch("/api/basketball");
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    lastData = data;
    refreshSeconds = data.refresh_seconds || 30;
    $("refreshInterval").textContent = refreshSeconds;
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    $("matchCount").textContent = `${data.match_count ?? 0} Q3 games`;
    $("liveTotal").textContent = `${data.total_live ?? 0} live (${data.excluded_count ?? 0} cyber out)`;

    $("connectionStatus").classList.add("live");
    $("connectionStatus").classList.remove("error");
    $("statusText").textContent = `Q3 only · ${data.match_count} games · ${data.bet_signal_count} signals`;

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