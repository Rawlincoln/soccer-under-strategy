const POLL_MS = 15000;
let pollTimer = null;
let lastData = null;

const $ = (id) => document.getElementById(id);

function link1x(item, label = "1xBet ↗") {
  if (typeof BetAssistant === "undefined") return "";
  return BetAssistant.matchLinkHtml(item?.event_id, item?.league_id, label);
}

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function fmtConf(c) {
  return Number(c).toFixed(1);
}

function halfTag(h) {
  return h === "sh" ? "2H" : "1H";
}

function isHalfTime(item) {
  return !!(item?.is_half_time || item?.half === "ht" || item?.status === "HT");
}

function normalizeMatchMinute(item, raw) {
  const m = Number(raw);
  if (Number.isNaN(m)) return null;
  if (item?.half !== "sh") return m;
  const pm = Number(item?.period_minute);
  if (!Number.isNaN(pm) && pm >= 0) {
    const clock = 45 + pm;
    if (m === clock + 45) return clock;
    if (m > 80 && pm < 45 && m - pm >= 85) return m - 45;
  }
  if (m > 120) return m - 45;
  return m;
}

function matchMinute(item) {
  if (isHalfTime(item)) return 45;
  const raw = item?.minute;
  if (raw == null || raw === "") return null;
  return normalizeMatchMinute(item, raw);
}

function periodMinute(item) {
  const pm = item?.period_minute;
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
  const cls = isHalfTime(item) ? "minute-badge ht" : "minute-badge";
  return `<span class="${cls}">${fmtMinute(item, half)}</span>`;
}

function halfTimeBadge() {
  return '<span class="half-time-badge">HALF TIME</span>';
}

function riskClass(level) {
  return { LOW: "low", MEDIUM: "medium", HIGH: "high" }[level] || "medium";
}

function renderSummary(data) {
  const accas = data.accumulators || [];
  const totalLegs = accas.reduce((s, a) => s + a.leg_count, 0);
  const minConf = data.min_confidence ?? 60;
  $("accaSummary").innerHTML = `
    <div class="baseline-card"><div class="label">60%+ predictions</div><div class="value green">${data.qualified_picks_60_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Acca legs (≥${minConf}%)</div><div class="value">${data.qualified_picks ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Accumulator slips</div><div class="value green">${data.accumulator_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Total acca legs</div><div class="value">${totalLegs}</div></div>
  `;
  $("accaCount").textContent = `${data.accumulator_count ?? 0} acca${data.accumulator_count !== 1 ? "s" : ""}`;
}

function renderPicks60(data) {
  const grid = $("picks60Grid");
  const picks = data.qualified_picks_60 || [];
  const minConf = data.min_confidence ?? 60;

  if (!picks.length) {
    grid.innerHTML = `<div class="insufficient-msg">No live picks at ${minConf}%+ confidence right now.</div>`;
    return;
  }

  grid.innerHTML = picks.map((item) => `
    <div class="pick-60-card">
      <div class="pick-60-top">
        ${isHalfTime(item) ? halfTimeBadge() : `<span class="pick-60-half">${halfTag(item.half)}</span>`}
        ${minuteBadge(item, item.half)}
        <span class="pick-60-conf">${fmtConf(item.confidence)}%</span>
        <span class="rec-badge ${item.recommendation === "BET" ? "bet" : "watch"}">${item.recommendation}</span>
      </div>
      <div class="pick-60-match">${item.match} ${link1x(item)}</div>
      <div class="pick-60-market">${item.market?.replace("First Half Goals", "FH").replace("Second Half Goals", "SH")}</div>
      <div class="pick-60-stats">
        <div class="pick-60-stat"><div class="num">${isHalfTime(item) ? "HT" : `${matchMinute(item) ?? "—"}${matchMinute(item) != null ? "'" : ""}`}</div><div class="lbl">${isHalfTime(item) ? "Break" : item.half === "sh" ? `2H +${periodMinute(item) ?? 0}'` : `${halfTag(item.half)} Min`}</div></div>
        <div class="pick-60-stat"><div class="num">${item.period_score || "—"}</div><div class="lbl">Score</div></div>
      </div>
      <div class="pick-60-meta">${item.fusion_verdict ? item.fusion_verdict : "Live pick"}</div>
    </div>
  `).join("");
  if (typeof BetAssistant !== "undefined") BetAssistant.bind1xBetLinks(grid);
}

function renderAcca(acca, stake) {
  const slip = typeof BetAssistant !== "undefined" ? BetAssistant.slipFromAcca(acca, stake) : null;
  const actions = slip ? BetAssistant.actionButtons(slip, null, true) : "";
  const legsHtml = acca.legs.map((leg, i) => `
    <div class="acca-leg">
      <div class="leg-num">${i + 1}</div>
      <div>
        <div class="leg-match-row">
          <div class="leg-match">${leg.home_team} vs ${leg.away_team} ${link1x(leg)}</div>
          <div style="display:flex;gap:6px;align-items:center">${leg.is_half_time ? halfTimeBadge() : ""}${minuteBadge(leg, leg.half)}</div>
        </div>
        <div class="leg-league">${leg.league} · ${halfTag(leg.half)}</div>
        <div class="leg-stats">
          <div class="leg-stat"><div class="num">${leg.is_half_time ? "HT" : `${leg.minute ?? "—"}${leg.minute != null ? "'" : ""}`}</div><div class="lbl">${leg.is_half_time ? "Break" : leg.half === "sh" ? `2H +${leg.period_minute ?? Math.max(0, (leg.minute || 0) - 45)}'` : `${halfTag(leg.half)} Min`}</div></div>
          <div class="leg-stat"><div class="num">${leg.period_score || leg.fh_score || "—"}</div><div class="lbl">Period</div></div>
          <div class="leg-stat"><div class="num">${leg.full_score || "—"}</div><div class="lbl">FT</div></div>
          <div class="leg-stat"><div class="num">${fmtConf(leg.confidence)}%</div><div class="lbl">Conf</div></div>
        </div>
        <span class="leg-pick">${leg.selection}</span>
        <span class="rec-badge ${leg.recommendation === "BET" ? "bet" : "watch"}">${leg.recommendation}</span>
        <div class="leg-meta">${halfTag(leg.half)} ${leg.period_score || leg.fh_score} · FT ${leg.full_score || "—"} · ${fmtMinute(leg, leg.half)}</div>
        ${leg.fusion_verdict ? `<div class="leg-prophit">${leg.fusion_verdict} · ${leg.fusion_agreement}</div>` : ""}
      </div>
      <div class="leg-odds">
        <div>@ ${leg.estimated_odds.toFixed(2)}</div>
        <div class="leg-conf">${fmtConf(leg.confidence)}%</div>
      </div>
    </div>
  `).join("");

  const potential = (stake * acca.combined_odds).toFixed(2);

  return `
    <div class="acca-slip risk-${riskClass(acca.risk_level)}">
      <div class="acca-header">
        <div class="acca-header-top">
          <span class="acca-name">${acca.name}</span>
          <span class="risk-badge ${riskClass(acca.risk_level)}">${acca.risk_level} RISK</span>
        </div>
        <div class="acca-stats">
          <div class="acca-stat">
            <div class="label">Legs</div>
            <div class="value">${acca.leg_count}</div>
          </div>
          <div class="acca-stat">
            <div class="label">Combined odds</div>
            <div class="value odds">${acca.combined_odds.toFixed(2)}</div>
          </div>
          <div class="acca-stat">
            <div class="label">Win probability</div>
            <div class="value">${acca.combined_probability}%</div>
          </div>
          <div class="acca-stat">
            <div class="label">Avg confidence</div>
            <div class="value">${fmtConf(acca.avg_confidence)}%</div>
          </div>
        </div>
      </div>
      <div class="acca-legs">${legsHtml}</div>
      <div class="acca-footer">
        <span class="total-label">Return on £${stake} stake</span>
        <span class="total-return">£${potential}</span>
      </div>
      ${actions}
    </div>
  `;
}

function renderAccas(data) {
  const container = $("accaContainer");
  const stake = parseFloat($("stakeInput").value) || 10;
  const accas = data.accumulators || [];
  const minConf = data.min_confidence ?? 60;

  if (data.insufficient_picks) {
    container.innerHTML = `
      <div class="insufficient-msg">
        <strong>Not enough picks for an accumulator</strong>
        Found ${data.qualified_picks} match(es) at ${minConf}%+ — need at least ${data.min_legs} for a slip.
        See the 60%+ predictions list above.
      </div>`;
    return;
  }

  if (!accas.length) {
    container.innerHTML = `
      <div class="insufficient-msg">
        <strong>No accumulator slips available</strong>
        No live matches currently qualify at ${minConf}%+. The page will update automatically.
      </div>`;
    return;
  }

  container.innerHTML = `<h2 class="section-title acca-title">Accumulator slips (≥${minConf}% legs)</h2>` +
    accas.map((a) => renderAcca(a, stake)).join("");
  if (typeof BetAssistant !== "undefined") {
    BetAssistant.bindActions(container);
    BetAssistant.bind1xBetLinks(container);
  }
}

async function fetchData() {
  try {
    const res = await fetch("/api/accumulators");
    const data = await res.json();
    if (typeof BetAssistant !== "undefined") BetAssistant.applyOnexbetConfig(data);
    lastData = data;

    $("refreshInterval").textContent = data.refresh_seconds || 30;
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    $("connectionStatus").classList.add("live");
    $("statusText").textContent = `${data.qualified_picks_60_count ?? 0} picks ≥60% · ${data.accumulator_count ?? 0} accas`;

    renderSummary(data);
    renderPicks60(data);
    renderAccas(data);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Connection error";
    console.error(err);
  }
}

$("stakeInput").addEventListener("input", () => {
  if (lastData) renderAccas(lastData);
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