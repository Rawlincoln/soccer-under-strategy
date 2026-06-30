const POLL_MS = 30000;
let pollTimer = null;
let lastData = null;

const $ = (id) => document.getElementById(id);

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtPrize(kes) {
  if (!kes) return "—";
  if (kes >= 1_000_000) return `KES ${(kes / 1_000_000).toFixed(0)}M`;
  return `KES ${kes.toLocaleString()}`;
}

function pickChip(letter, title) {
  const label = letter === "W" ? "Home" : letter === "D" ? "Draw" : "Away";
  return `<span class="toto-pick-chip ${letter}" title="${title || label}">${letter}</span>`;
}

function renderBaselines(data) {
  const jp = data.jackpot || {};
  const src = data.sources_hit || {};
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Jackpot</div><div class="value">${jp.title || "Mega JP 17"}</div></div>
    <div class="baseline-card"><div class="label">Prize</div><div class="value green">${fmtPrize(jp.prize_kes)}</div></div>
    <div class="baseline-card"><div class="label">Games</div><div class="value">${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">ProphitBet</div><div class="value">${src.prophitbet || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">SoccerPunter</div><div class="value">${src.soccerpunter || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">FotMob</div><div class="value">${src.fotmob || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">SportsDB</div><div class="value">${src.sportsdb || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">Stake</div><div class="value">KES ${jp.stake_kes || 99}</div></div>
  `;
}

function renderSets(sets) {
  const el = $("totoSets");
  if (!sets || !sets.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = sets.map((s, idx) => `
    <div class="toto-set-card">
      <h3>${s.label}</h3>
      <p>${s.description}</p>
      <div class="toto-slip">${s.slip}</div>
      <div class="toto-slip-picks">${(s.picks || []).map((p, i) => pickChip(p, `Game ${i + 1}`)).join("")}</div>
      <button type="button" class="btn-copy" data-slip="${s.slip}">Copy slip</button>
    </div>
  `).join("");

  el.querySelectorAll(".btn-copy").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const slip = btn.dataset.slip || "";
      try {
        await navigator.clipboard.writeText(slip);
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy slip"; }, 1500);
      } catch {
        btn.textContent = "Copy failed";
      }
    });
  });
}

function renderMatch(m) {
  const sc = m.scores || {};
  const w = sc.W || 33;
  const d = sc.D || 34;
  const l = sc.L || 33;
  const cov = m.coverage || {};
  const src = (name, ok) => `<span class="toto-src ${ok ? "ok" : ""}">${name}${ok ? " ✓" : ""}</span>`;

  return `
    <div class="toto-match-card">
      <div class="toto-match-head">
        <span class="toto-match-num">#${m.num}</span>
        <span class="toto-teams">${m.home_team} <span style="color:var(--muted)">vs</span> ${m.away_team}</span>
        <div class="toto-picks-row">
          <div><div class="toto-pick-label">S1</div>${pickChip(m.pick_primary)}</div>
          <div><div class="toto-pick-label">S2</div>${pickChip(m.pick_value)}</div>
          <div><div class="toto-pick-label">S3</div>${pickChip(m.pick_upset)}</div>
        </div>
      </div>
      <div class="toto-score-bar">
        <span class="w" style="width:${w}%"></span>
        <span class="d" style="width:${d}%"></span>
        <span class="l" style="width:${l}%"></span>
      </div>
      <div class="toto-scores-text">W ${w}% · D ${d}% · L ${l}% · top ${(m.confidence_primary || 0).toFixed(0)}%</div>
      <div class="toto-coverage">
        ${src("ProphitBet", cov.prophitbet)}
        ${src("SoccerPunter", cov.soccerpunter)}
        ${src("FotMob", cov.fotmob)}
        ${src("SportsDB", cov.sportsdb)}
      </div>
      <ul class="toto-signals">${(m.signals || []).map((s) => `<li>${s}</li>`).join("")}</ul>
    </div>`;
}

function renderMatches(matches) {
  const grid = $("totoGrid");
  if (!matches || !matches.length) {
    grid.innerHTML = '<div class="empty">No jackpot matches found. Click Refresh or update data/toto_jackpot.json.</div>';
    return;
  }
  grid.innerHTML = matches.map(renderMatch).join("");
}

async function fetchData() {
  try {
    const res = await fetch("/api/toto");
    const data = await res.json();
    if (data.error && !data.matches?.length) throw new Error(data.error);

    lastData = data;
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    $("matchCount").textContent = `${data.match_count || 0} games`;
    $("connectionStatus").classList.add("live");
    $("connectionStatus").classList.remove("error");

    if (data.loading) {
      $("statusText").textContent = "Analysing jackpot…";
      $("totoGrid").innerHTML = '<div class="loading">Running 1X2 analysis on all jackpot games (may take 1–2 min first time)…</div>';
      return;
    }

    $("statusText").textContent = `3 slips · ${data.match_count || 0} games`;
    renderBaselines(data);
    renderSets(data.sets);
    renderMatches(data.matches);
  } catch (err) {
    $("connectionStatus").classList.add("error");
    $("statusText").textContent = "Toto error";
    $("totoGrid").innerHTML = `<div class="empty">${err.message}</div>`;
    console.error(err);
  }
}

$("btnRefresh").addEventListener("click", async () => {
  $("btnRefresh").disabled = true;
  $("totoGrid").innerHTML = '<div class="loading">Refreshing jackpot list and re-analysing…</div>';
  await fetch("/api/toto/refresh", { method: "POST" });
  await fetchData();
  $("btnRefresh").disabled = false;
});

function startPolling() {
  fetchData();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchData, POLL_MS);
}

startPolling();