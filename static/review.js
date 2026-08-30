const $ = (id) => document.getElementById(id);
let lastData = null;
let statusFilter = "all";

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function money(n) {
  const v = Number(n || 0);
  const sign = v > 0 ? "+" : "";
  return `${sign}£${v.toFixed(2)}`;
}

function renderSummary(data) {
  $("stakeNote").textContent = data.assumed_stake ?? 10;
  $("reviewSummary").innerHTML = `
    <div class="baseline-card"><div class="label">Recorded slips</div><div class="value">${(data.snapshots || []).length}</div></div>
    <div class="baseline-card"><div class="label">Pending</div><div class="value">${data.pending_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Won / Lost</div><div class="value green">${data.won_count ?? 0} / ${data.lost_count ?? 0}</div></div>
    <div class="baseline-card"><div class="label">Win rate</div><div class="value">${data.win_rate ?? 0}%</div></div>
    <div class="baseline-card"><div class="label">P/L @ £${data.assumed_stake ?? 10}</div><div class="value ${(data.profit || 0) >= 0 ? "green" : ""}">${money(data.profit)}</div></div>
    <div class="baseline-card"><div class="label">ROI</div><div class="value">${data.roi_pct ?? 0}%</div></div>
  `;
}

function legResult(leg) {
  const r = leg.result;
  if (r === "won") return "WON";
  if (r === "lost") return "LOST";
  return "PENDING";
}

function renderSnap(s) {
  const st = s.status || "pending";
  const profitCls = (s.profit || 0) > 0 ? "profit-up" : (s.profit || 0) < 0 ? "profit-down" : "";
  const legs = (s.legs || []).map((leg, i) => `
    <div class="review-leg ${leg.result || "pending"}">
      <div>${i + 1}</div>
      <div>
        <div><strong>${leg.match}</strong></div>
        <div class="review-leg-sel">${leg.selection} · @${Number(leg.odds || 0).toFixed(2)}</div>
        <div class="review-leg-meta">
          ${leg.location || leg.league || ""}
          · at call ${leg.score_at_call || "—"} (${leg.minute || "—"}')
          · FT then ${leg.full_score_at_call || "—"}
        </div>
      </div>
      <div class="review-leg-result">
        ${legResult(leg)}<br>
        <span style="color:var(--muted)">FH ${leg.final_fh || "—"} · FT ${leg.final_ft || "—"}</span>
      </div>
    </div>
  `).join("");

  let verdict = "Still in play — not settled yet.";
  if (st === "won") {
    verdict = `You would have WON. £${Number(s.stake || 10).toFixed(0)} at ${Number(s.combined_odds).toFixed(2)} returns £${Number(s.payout).toFixed(2)} (profit ${money(s.profit)}).`;
  } else if (st === "lost") {
    verdict = `You would have LOST. Stake £${Number(s.stake || 10).toFixed(0)} is gone (P/L ${money(s.profit)}).`;
  }

  return `
    <article class="review-card status-${st}">
      <div class="review-head">
        <div>
          <div class="review-name">${s.name || "Acca"}</div>
          <div class="review-when">Called ${fmtTime(s.created_at)}${s.settled_at ? ` · settled ${fmtTime(s.settled_at)}` : ""}</div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          <span class="review-badge ${s.band || "core"}">${s.band || "core"}</span>
          <span class="review-badge ${st}">${st}</span>
        </div>
      </div>
      <div class="review-stats">
        <div class="review-stat"><div class="label">Legs</div><div class="value">${s.leg_count}</div></div>
        <div class="review-stat"><div class="label">Combined odds</div><div class="value">${Number(s.combined_odds || 0).toFixed(2)}</div></div>
        <div class="review-stat"><div class="label">Model win %</div><div class="value">${s.combined_probability ?? "—"}%</div></div>
        <div class="review-stat"><div class="label">Avg conf</div><div class="value">${Number(s.avg_confidence || 0).toFixed(0)}%</div></div>
        <div class="review-stat"><div class="label">Payout</div><div class="value">${s.status === "pending" ? "—" : "£" + Number(s.payout || 0).toFixed(2)}</div></div>
        <div class="review-stat"><div class="label">Profit</div><div class="value ${profitCls}">${s.status === "pending" ? "—" : money(s.profit)}</div></div>
      </div>
      ${legs}
      <div class="review-verdict ${st}">${verdict}</div>
    </article>
  `;
}

function renderList(data) {
  const snaps = (data.snapshots || []).filter((s) => statusFilter === "all" || s.status === statusFilter);
  const el = $("reviewList");
  if (!snaps.length) {
    el.innerHTML = `<div class="insufficient-msg">No ${statusFilter === "all" ? "recorded" : statusFilter} accumulators yet. Keep the live acca page running — slips are saved automatically when published.</div>`;
    return;
  }
  el.innerHTML = snaps.map(renderSnap).join("");
}

async function fetchData() {
  try {
    const res = await fetch("/api/acca-review");
    const data = await res.json();
    lastData = data;
    $("connectionStatus").classList.add("live");
    $("statusText").textContent = `${data.settled_count ?? 0} settled · ${data.pending_count ?? 0} pending`;
    renderSummary(data);
    renderList(data);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Ledger error";
    console.error(err);
  }
}

document.querySelectorAll("#statusTabs .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#statusTabs .tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    statusFilter = btn.dataset.status;
    if (lastData) renderList(lastData);
  });
});

$("btnRefresh").addEventListener("click", async () => {
  $("btnRefresh").disabled = true;
  await fetchData();
  $("btnRefresh").disabled = false;
});

fetchData();
setInterval(fetchData, 60000);
