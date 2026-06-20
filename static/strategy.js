const DAILY_TARGET = 100000;
const STAKE_PER_SLIP = 5000;
const POLL_MS = 15000;

const $ = (id) => document.getElementById(id);

function fmtMoney(n) {
  return Number(n).toLocaleString(undefined, { maximumFractionDigits: 0 });
}

function profitFromStake(stake, odds) {
  return stake * (odds - 1);
}

function slipsNeededForTarget(stake, odds, target = DAILY_TARGET) {
  const p = profitFromStake(stake, odds);
  if (p <= 0) return "—";
  return Math.ceil(target / p);
}

function renderMath() {
  const examples = [
    { label: "1 winning acca @ 21.0 odds", profit: profitFromStake(STAKE_PER_SLIP, 21) },
    { label: "2 winning accas @ 11.0 odds each", profit: profitFromStake(STAKE_PER_SLIP, 11) * 2 },
    { label: "4 winning accas @ 6.0 odds each", profit: profitFromStake(STAKE_PER_SLIP, 6) * 4 },
    { label: "5 winning accas @ 5.0 odds each", profit: profitFromStake(STAKE_PER_SLIP, 5) * 5 },
  ];
  $("mathRows").innerHTML = examples.map((e) => `
    <div class="math-row">
      <span>${e.label}</span>
      <strong>${fmtMoney(e.profit)} profit</strong>
    </div>
  `).join("");
}

function renderWaves() {
  const third = Math.round(DAILY_TARGET / 3);
  $("wavePlan").innerHTML = `
    <div class="wave-card">
      <div class="wave-time">Wave 1 · 15′–20′ (1H)</div>
      <h3>Anchor slip</h3>
      <p>Place <strong>1× 5,000</strong> on the best 4–6 leg acca (highest fusion + 65%+ avg confidence). Prefer scored-but-under-alive games.</p>
      <div class="wave-target">Target profit: ~${fmtMoney(third)}</div>
    </div>
    <div class="wave-card">
      <div class="wave-time">Wave 2 · 60′–65′ (2H)</div>
      <h3>Booster slip</h3>
      <p>Place <strong>1–2× 5,000</strong> on 2H under accas. Only when entry window + BET signal align. Use second slip if Wave 1 lost.</p>
      <div class="wave-target">Target profit: ~${fmtMoney(third)}</div>
    </div>
    <div class="wave-card">
      <div class="wave-time">Wave 3 · Late window</div>
      <h3>Closer slip(s)</h3>
      <p>Keep placing <strong>5,000</strong> on 60%+ accas until profit target, a 5-loss streak, or midnight resets the day.</p>
      <div class="wave-target">Target profit: ~${fmtMoney(third)}</div>
    </div>
  `;
}

function renderCalculator() {
  const odds = parseFloat($("calcOdds").value) || 4.5;
  const stake = parseFloat($("calcStake").value) || STAKE_PER_SLIP;
  const profit = profitFromStake(stake, odds);
  const returnAmt = stake * odds;
  const needed = slipsNeededForTarget(stake, odds);
  const exposure = stake * needed;

  $("calcResults").innerHTML = `
    <div>Profit if win: <strong>${fmtMoney(profit)}</strong></div>
    <div>Total return: <strong>${fmtMoney(returnAmt)}</strong></div>
    <div>Winning slips needed for ${fmtMoney(DAILY_TARGET)}: <strong>${needed}</strong></div>
    <div>Exposure if all placed: <strong>${fmtMoney(exposure)}</strong></div>
  `;
}

let workflowState = null;

function renderLiveSlips(accas) {
  const box = $("liveSlips");
  if (!accas?.length) {
    box.innerHTML = `
      <div class="insufficient-msg">
        No live accumulator slips right now. Wait for 60%+ picks on the
        <a href="/accumulator">Accumulators</a> page, then refresh.
      </div>`;
    updateProgress(0);
    return;
  }

  let cumulative = 0;
  const cards = accas.map((a, i) => {
    const profit = profitFromStake(STAKE_PER_SLIP, a.combined_odds);
    cumulative += profit;
    const hitsTarget = profit >= DAILY_TARGET;
    const legMins = (a.legs || []).map((l) => `${l.minute ?? "?"}'`).join(", ");
    const slip = typeof BetAssistant !== "undefined" ? BetAssistant.slipFromAcca(a, STAKE_PER_SLIP) : null;
    const actions = slip ? BetAssistant.actionButtons(slip, workflowState, true) : "";
    return `
      <div class="slip-plan ${hitsTarget ? "hit-target" : ""}">
        <div class="slip-plan-header">
          <span class="slip-plan-name">Slip ${i + 1}: ${a.name}</span>
          <span class="slip-plan-odds">@ ${a.combined_odds.toFixed(2)}</span>
        </div>
        <div class="slip-plan-stats">
          <div class="slip-plan-stat"><div class="num">${a.leg_count}</div><div class="lbl">Legs</div></div>
          <div class="slip-plan-stat"><div class="num">${fmtMoney(STAKE_PER_SLIP)}</div><div class="lbl">Stake</div></div>
          <div class="slip-plan-stat"><div class="num">${a.avg_confidence}%</div><div class="lbl">Avg conf</div></div>
        </div>
        <div class="slip-plan-profit">+${fmtMoney(profit)} profit</div>
        <div class="slip-plan-note">${a.risk_level} risk · mins: ${legMins || "—"}</div>
        ${actions}
      </div>
    `;
  }).join("");

  const comboNote = accas.length > 1
    ? `<div class="card-note" style="grid-column:1/-1">If all ${accas.length} slips win @ 5,000 each: <strong style="color:var(--green);font-family:var(--mono)">+${fmtMoney(cumulative)}</strong></div>`
    : "";

  box.innerHTML = comboNote + cards;
  if (typeof BetAssistant !== "undefined") BetAssistant.bindActions(box, workflowState);
  updateProgress(cumulative);
}

function renderWorkflowBanner(wf) {
  const banner = $("workflowBanner");
  if (!banner || !wf) return;
  const streak = wf.loss_streak || 0;
  const maxStreak = wf.max_loss_streak || 5;
  if (streak >= maxStreak - 1 && streak > 0) {
    banner.hidden = false;
    $("wfWave").textContent = `${streak}L STREAK`;
    $("wfAction").textContent = `${streak} losses in a row — session resets after ${maxStreak} consecutive losses.`;
    return;
  }
  const active = wf.active_wave;
  if (active?.status === "ACTIVE") {
    banner.hidden = false;
    $("wfWave").textContent = active.label || active.id;
    $("wfAction").textContent = active.action || "Place slip now @ 5,000";
    return;
  }
  if (wf.recommendations?.length) {
    banner.hidden = false;
    $("wfWave").textContent = "READY";
    $("wfAction").textContent = `${wf.recommendations.length} slip(s) ready — no slip cap today`;
    return;
  }
  banner.hidden = true;
}

function updateProgress(potentialProfit) {
  const pct = Math.min(100, Math.round((potentialProfit / DAILY_TARGET) * 100));
  const gap = Math.max(0, DAILY_TARGET - potentialProfit);
  $("progressFill").style.width = `${pct}%`;
  $("progressPct").textContent = `${pct}%`;
  $("potentialProfit").textContent = fmtMoney(potentialProfit);
  $("gapToTarget").textContent = fmtMoney(gap);
}

async function fetchData() {
  try {
    const [accaRes, asstRes] = await Promise.all([
      fetch("/api/accumulators"),
      fetch("/api/assistant"),
    ]);
    const data = await accaRes.json();
    const asst = await asstRes.json();
    workflowState = asst.workflow || null;
    $("refreshInterval").textContent = data.refresh_seconds || 30;
    $("lastUpdate").textContent = `Updated ${new Date(data.updated_at).toLocaleTimeString()}`;
    $("connectionStatus").classList.add("live");
    const streak = workflowState?.loss_streak || 0;
    const wfNote = streak >= 4 ? ` · ${streak}L streak` : workflowState?.active_wave ? ` · ${workflowState.active_wave.id}` : "";
    $("statusText").textContent = `${data.accumulator_count ?? 0} accas · ${workflowState?.slips_placed ?? 0} slips${wfNote}`;
    renderLiveSlips(data.accumulators || []);
    renderWorkflowBanner(workflowState);
    if (asst.new_alerts?.length && typeof BetAssistant !== "undefined") {
      BetAssistant.processAlerts(asst.new_alerts);
    }
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Connection error";
    console.error(err);
  }
}

function init() {
  $("targetAmount").textContent = fmtMoney(DAILY_TARGET);
  $("stakeDisplay").textContent = fmtMoney(STAKE_PER_SLIP);
  renderMath();
  renderWaves();
  renderCalculator();
  $("calcOdds").addEventListener("input", renderCalculator);
  $("calcStake").addEventListener("input", renderCalculator);
  fetchData();
  setInterval(fetchData, POLL_MS);
}

init();
if (typeof BetAssistant !== "undefined") BetAssistant.startAlertPolling(30000);