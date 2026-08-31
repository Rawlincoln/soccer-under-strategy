const POLL_MS = 15000;
let pollTimer = null;
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

function fmtConf(c) {
  return Number(c).toFixed(1);
}

function halfTag(h, scope) {
  const s = (scope || h || "").toLowerCase();
  if (s === "ft" || s === "full") return "FT";
  if (s === "sh" || s === "2h") return "2H";
  if (s === "ht") return "HT";
  return "1H";
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

function money(n) {
  const v = Number(n || 0);
  const sign = v > 0 ? "+" : "";
  return `${sign}£${v.toFixed(2)}`;
}

function renderSummary(data) {
  const shortN = (data.short_accumulators || []).length;
  const longN = (data.long_accumulators || []).length;
  $("accaSummary").innerHTML = `
    <div class="baseline-card"><div class="label">Core 1.30–2.50</div><div class="value green">${data.qualified_picks_60_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Short &lt;1.30</div><div class="value">${data.short_picks_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Longshots &gt;2.50</div><div class="value">${data.long_picks_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Slips</div><div class="value green">${data.accumulator_count ?? 0} · ${shortN} · ${longN}</div></div>
  `;
  $("accaCount").textContent = `${(data.accumulator_count ?? 0) + shortN + longN} accas`;
}

function renderResults(review) {
  const box = $("accaResults");
  if (!box) return;
  if (!review) {
    box.innerHTML = "";
    return;
  }
  const snaps = (review.snapshots || []).filter((s) => s.status === "won" || s.status === "lost").slice(0, 8);
  box.innerHTML = `
    <div class="acca-results-head">
      <h2 class="section-title">Won &amp; lost</h2>
      <a class="acca-results-link" href="/review">Full review →</a>
    </div>
    <div class="acca-results-stats">
      <div class="baseline-card"><div class="label">Won</div><div class="value green">${review.won_count ?? 0}</div></div>
      <div class="baseline-card"><div class="label">Lost</div><div class="value">${review.lost_count ?? 0}</div></div>
      <div class="baseline-card"><div class="label">Pending</div><div class="value">${review.pending_count ?? 0}</div></div>
      <div class="baseline-card"><div class="label">P/L</div><div class="value ${(review.profit || 0) >= 0 ? "green" : ""}">${money(review.profit)}</div></div>
    </div>
    ${snaps.length ? `<div class="acca-results-list">${snaps.map((s) => `
      <div class="acca-result-row ${s.status}">
        <span class="acca-result-name">${s.name || "Acca"}</span>
        <span class="acca-result-meta">${s.leg_count} legs · @${Number(s.combined_odds || 0).toFixed(2)}</span>
        <span class="acca-result-badge">${s.status === "won" ? "WON" : "LOST"} ${money(s.profit)}</span>
      </div>`).join("")}</div>` : `<div class="insufficient-msg">No settled accas yet — results appear here after legs finish or go bust.</div>`}
  `;
}

function renderPicks60(data, gridId = "picks60Grid", picksKey = "qualified_picks_60", emptyMsg = "") {
  const grid = $(gridId);
  if (!grid) return;
  const picks = data[picksKey] || [];
  const minConf = data.min_confidence ?? 60;

  if (!picks.length) {
    grid.innerHTML = `<div class="insufficient-msg">${emptyMsg || `No live picks at ${minConf}%+ in this band.`}</div>`;
    return;
  }

  grid.innerHTML = picks.map((item) => `
    <div class="pick-60-card">
      <div class="pick-60-top">
        ${isHalfTime(item) ? halfTimeBadge() : `<span class="pick-60-half">${halfTag(item.half, item.scope)}</span>`}
        ${minuteBadge(item, item.half)}
        <span class="pick-60-conf">${fmtConf(item.confidence)}%</span>
        ${BetAssistant.recBadgeHtml({
          recommendation: item.recommendation,
          event_id: item.event_id,
          league_id: item.league_id,
          onexbet_url: item.card?.onexbet_url || item.onexbet_url,
          market: item.market,
          market_odds: item.pick?.market_odds || item.card?.market_odds,
        })}
      </div>
      <div class="pick-60-match">${item.match} ${link1x(item)}</div>
      <div class="pick-60-meta">${BetAssistant.locationLabel(item)}</div>
      <div class="pick-60-market">${item.selection || item.market}</div>
      <div class="pick-60-stats">
        <div class="pick-60-stat"><div class="num">${isHalfTime(item) ? "HT" : `${matchMinute(item) ?? "—"}${matchMinute(item) != null ? "'" : ""}`}</div><div class="lbl">${isHalfTime(item) ? "Break" : item.scope === "ft" ? "FT" : item.half === "sh" ? `2H +${periodMinute(item) ?? 0}'` : `${halfTag(item.half, item.scope)} Min`}</div></div>
        <div class="pick-60-stat"><div class="num">${item.period_score || "—"}</div><div class="lbl">Period</div></div>
        <div class="pick-60-stat"><div class="num">${item.full_score || "—"}</div><div class="lbl">FT</div></div>
        <div class="pick-60-stat"><div class="num">${item.tempo || "—"}</div><div class="lbl">Tempo</div></div>
      </div>
      <div class="pick-60-meta">${item.side || ""} ${item.line ?? ""} · @${Number(item.estimated_odds || 0).toFixed(2)} · rem xG ${item.remaining_xg ?? "—"}</div>
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
        <div class="leg-league">${BetAssistant.locationLabel(leg)} · ${halfTag(leg.half, leg.scope)}</div>
        <div class="leg-stats">
          <div class="leg-stat"><div class="num">${leg.is_half_time ? "HT" : `${leg.minute ?? "—"}${leg.minute != null ? "'" : ""}`}</div><div class="lbl">${leg.is_half_time ? "Break" : leg.half === "sh" ? `2H +${leg.period_minute ?? Math.max(0, (leg.minute || 0) - 45)}'` : `${halfTag(leg.half)} Min`}</div></div>
          <div class="leg-stat"><div class="num">${leg.period_score || leg.fh_score || "—"}</div><div class="lbl">Period</div></div>
          <div class="leg-stat"><div class="num">${leg.full_score || "—"}</div><div class="lbl">FT</div></div>
          <div class="leg-stat"><div class="num">${fmtConf(leg.confidence)}%</div><div class="lbl">Conf</div></div>
        </div>
        <span class="leg-pick ${(leg.side || "").toLowerCase()}">${leg.selection}</span>
        ${BetAssistant.recBadgeHtml({
          recommendation: leg.recommendation,
          event_id: leg.event_id,
          league_id: leg.league_id,
          onexbet_url: leg.onexbet_url,
          market: leg.market,
          estimated_odds: leg.estimated_odds,
        })}
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

function renderAccas(data, containerId = "accaContainer", accasKey = "accumulators", title = "") {
  const container = $(containerId);
  if (!container) return;
  const stake = parseFloat($("stakeInput").value) || 10;
  const accas = data[accasKey] || [];
  const minConf = data.min_confidence ?? 60;
  const heading = title || `Core slips · 1.30–2.50 · ≥${minConf}%`;

  if (!accas.length) {
    container.innerHTML = `<h2 class="section-title acca-title">${heading}</h2>
      <div class="insufficient-msg">No slips in this band yet — waiting for ≥${minConf}% picks with matching odds.</div>`;
    return;
  }

  container.innerHTML = `<h2 class="section-title acca-title">${heading} (${accas.length})</h2>` +
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
    $("statusText").textContent = `${data.qualified_picks_60_count ?? 0} core · ${data.short_picks_count ?? 0} short · ${data.long_picks_count ?? 0} long`;

    renderSummary(data);
    try {
      const reviewRes = await fetch("/api/acca-review");
      renderResults(await reviewRes.json());
    } catch {
      renderResults(null);
    }
    renderPicks60(data);
    renderPicks60(data, "picksShortGrid", "short_picks", "No short-price (≥80%, odds under 1.30) picks right now.");
    renderPicks60(data, "picksLongGrid", "long_picks", "No longshot (≥80%, odds over 2.50) picks right now.");
    renderAccas(data);
    renderAccas(data, "accaShortContainer", "short_accumulators", "Short-price slips · odds under 1.30");
    renderAccas(data, "accaLongContainer", "long_accumulators", "Longshot slips · odds over 2.50");
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Connection error";
    console.error(err);
  }
}

$("stakeInput").addEventListener("input", () => {
  if (!lastData) return;
  renderAccas(lastData);
  renderAccas(lastData, "accaShortContainer", "short_accumulators", "Short-price slips · odds under 1.30");
  renderAccas(lastData, "accaLongContainer", "long_accumulators", "Longshot slips · odds over 2.50");
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