const POLL_MS = 15000;
let refreshSeconds = 30;
let pollTimer = null;
let lastData = null;

const $ = (id) => document.getElementById(id);

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function halfLabel(h) {
  return h === "sh" ? "2H" : "1H";
}

function renderBaselines(data) {
  const minPct = data.min_lock_pct ?? 95;
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Live football</div><div class="value orange">${data.total_live_football ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Closing window</div><div class="value orange">${data.closing_window_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">≥${minPct}% locks</div><div class="value orange">${data.match_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">FH from 36′</div><div class="value">${data.closing_start?.fh ?? 36}′</div></div>
    <div class="baseline-card"><div class="label">SH from 81′</div><div class="value">${data.closing_start?.sh ?? 81}′</div></div>
  `;
}

function renderMatchCard(m) {
  const stake = 5000;
  const slip = typeof BetAssistant !== "undefined" ? BetAssistant.slipFromLock(m, stake) : null;
  const actions = slip ? BetAssistant.actionButtons(slip, null, true) : "";
  const ls = m.live_stats || {};
  const elapsed = ls.period_minute ?? m.period_minute ?? "—";
  const shotsPm = ls.total_shots && elapsed ? (ls.total_shots / Math.max(elapsed, 1)).toFixed(2) : "—";
  const sotPm = ls.shots_on_target && elapsed ? (ls.shots_on_target / Math.max(elapsed, 1)).toFixed(2) : "—";

  return `
    <div class="closing-card lock-pick">
      <div class="closing-header">
        <div>
          <div class="closing-league">${m.league || "Football"}</div>
          <div class="closing-teams">${m.home_team} vs ${m.away_team}</div>
        </div>
        <span class="closing-clock">${halfLabel(m.half)} ${m.minute}′ · ${m.minutes_left}′ to ${m.closing_target}</span>
      </div>
      <div class="closing-score-row">
        <span class="closing-score">${m.period_score}</span>
        <span class="closing-period">${halfLabel(m.half)} period · full ${m.full_score}</span>
      </div>
      <div class="closing-lock-banner">${m.lock_label || `NO MORE GOALS · ${Number(m.lock_pct).toFixed(0)}%`}</div>
      <div class="closing-market">${m.lock_market || ""}</div>
      <div class="closing-stats-grid">
        <div class="closing-stat"><div class="num">${m.period_goals ?? 0}</div><div class="lbl">${halfLabel(m.half)} goals</div></div>
        <div class="closing-stat"><div class="num">${shotsPm}</div><div class="lbl">Shots/min</div></div>
        <div class="closing-stat"><div class="num">${sotPm}</div><div class="lbl">SoT/min</div></div>
        <div class="closing-stat"><div class="num">${ls.dangerous_attacks ?? "—"}</div><div class="lbl">Danger</div></div>
      </div>
      <ul class="closing-signals">${(m.signals || []).slice(0, 8).map((s) => `<li>${s}</li>`).join("")}</ul>
      ${actions}
    </div>`;
}

function renderMatches(data) {
  const grid = $("matchesGrid");
  const matches = data.matches || [];
  const minPct = data.min_lock_pct ?? 95;

  if (!matches.length) {
    grid.innerHTML = `
      <div class="closing-empty">
        <strong>No ${minPct}%+ goal locks right now</strong>
        Matches in the closing window (FH 36′+ / SH 81′+) appear here only when stats, history and market
        agree there is a ${minPct}%+ chance of no more goals before HT or FT.
      </div>`;
    return;
  }

  grid.innerHTML = matches.map(renderMatchCard).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bindActions(grid);
}

function updateMeta(data) {
  $("lastUpdate").textContent = fmtTime(data.updated_at);
  $("matchCount").textContent = `${data.match_count ?? 0} locks`;
  $("liveTotal").textContent = `${data.closing_window_count ?? 0} in window`;
  refreshSeconds = data.refresh_seconds ?? 30;

  const status = $("connectionStatus");
  const text = $("statusText");
  if (data.error) {
    status.classList.add("error");
    text.textContent = data.error;
  } else {
    status.classList.remove("error");
    text.textContent = "Live";
  }
}

async function fetchData() {
  try {
    const res = await fetch("/api/closing");
    const data = await res.json();
    lastData = data;
    renderBaselines(data);
    renderMatches(data);
    updateMeta(data);
  } catch (err) {
    $("statusText").textContent = "Connection error";
    $("connectionStatus").classList.add("error");
  }
}

function schedulePoll() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchData, POLL_MS);
}

$("btnRefresh")?.addEventListener("click", async () => {
  $("btnRefresh").disabled = true;
  try {
    await fetch("/api/closing/refresh", { method: "POST" });
    await fetchData();
  } finally {
    $("btnRefresh").disabled = false;
  }
});

fetchData();
schedulePoll();
if (typeof BetAssistant !== "undefined") BetAssistant.startAlertPolling(30000);