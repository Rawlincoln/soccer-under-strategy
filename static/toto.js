const POLL_MS = 30000;
let pollTimer = null;
let lastData = null;
let activeTypeId = 1;

const $ = (id) => document.getElementById(id);

function fmtTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function fmtPrize(kes) {
  if (!kes) return "—";
  if (kes >= 1_000_000) return `KES ${(kes / 1_000_000).toFixed(1)}M`;
  if (kes >= 1_000) return `KES ${(kes / 1_000).toFixed(0)}K`;
  return `KES ${kes.toLocaleString()}`;
}

function pickChip(letter, title) {
  const label = letter === "W" ? "Home" : letter === "D" ? "Draw" : "Away";
  return `<span class="toto-pick-chip ${letter}" title="${title || label}">${letter}</span>`;
}

function openTotoUrl(onex) {
  if (!onex) return "/open/1xbet/toto";
  const slug = onex.slug || "fifteen";
  return `/open/1xbet/toto?slug=${encodeURIComponent(slug)}`;
}

function bindOnexbetLinks(onex) {
  if (!onex) return;
  const href = onex.toto_open_url || openTotoUrl(onex);
  const btn = $("btnOnexbetToto");
  if (btn) {
    btn.href = href;
    btn.textContent = onex.product ? `Open ${onex.product}` : "Open 1xBet";
    btn.title = `Open ${onex.product || "Toto"} on ${onex.site || "1xBet"}`;
  }
  const sub = $("subtitleOnexbetLink");
  if (sub) sub.href = href;
  const note = $("onexbetTotoNote");
  if (note && onex.note) {
    note.textContent = `${onex.note} Tap the green button to open the app.`;
  }
  const title = $("onexbetProductTitle");
  if (title && onex.product) title.textContent = onex.product;
}

function renderProductTabs(products, typeId) {
  const el = $("productTabs");
  if (!el) return;
  const list = (products || []).filter((p) => p.active);
  if (!list.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = list.map((p) => {
    const active = Number(p.type_id) === Number(typeId) ? " active" : "";
    const jp = p.jackpot_kes ? fmtPrize(p.jackpot_kes) : "";
    return `<button type="button" class="toto-product-tab${active}" data-type-id="${p.type_id}" title="${p.game_count} games">
      <span class="tab-icon">${p.icon || "🎰"}</span>
      <span class="tab-label">${p.label}</span>
      <span class="tab-meta">${p.game_count} · ${jp}</span>
    </button>`;
  }).join("");

  el.querySelectorAll(".toto-product-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tid = parseInt(btn.dataset.typeId, 10);
      if (!tid || tid === activeTypeId) return;
      activeTypeId = tid;
      $("totoGrid").innerHTML = '<div class="loading">Loading pool and running 1X2 analysis…</div>';
      fetchData();
    });
  });
}

function renderBaselines(data) {
  const jp = data.jackpot || {};
  const src = data.sources_hit || {};
  const onex = data.onexbet || {};
  $("baselines").innerHTML = `
    <div class="baseline-card"><div class="label">Pool</div><div class="value">${jp.title || onex.product || "1xBet Toto"}</div></div>
    <div class="baseline-card"><div class="label">Draw</div><div class="value">#${jp.draw_number || onex.draw_number || "—"}</div></div>
    <div class="baseline-card"><div class="label">Jackpot</div><div class="value green">${fmtPrize(jp.prize_kes)}</div></div>
    <div class="baseline-card"><div class="label">Pool size</div><div class="value">${fmtPrize(jp.pool_kes)}</div></div>
    <div class="baseline-card"><div class="label">Games</div><div class="value">${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">ProphitBet</div><div class="value">${src.prophitbet || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">SoccerPunter</div><div class="value">${src.soccerpunter || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">FotMob</div><div class="value">${src.fotmob || 0}/${data.match_count || 0}</div></div>
    <div class="baseline-card"><div class="label">Min stake</div><div class="value">KES ${jp.stake_min_kes || jp.stake_kes || 80}</div></div>
    <a class="baseline-card baseline-onexbet" href="${openTotoUrl(onex)}" target="_blank" rel="noopener">
      <div class="label">1xBet</div>
      <div class="value green">${onex.product || "Toto"} →</div>
    </a>
  `;
  bindOnexbetLinks(onex);
}

function renderSets(sets) {
  const el = $("totoSets");
  if (!sets || !sets.length) {
    el.innerHTML = "";
    return;
  }
  el.innerHTML = sets.map((s) => `
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

function marketLine(mkt) {
  if (!mkt || (!mkt.W && !mkt.D && !mkt.L)) return "";
  const w = mkt.W || 0;
  const d = mkt.D || 0;
  const l = mkt.L || 0;
  return `<div class="toto-market">1xBet pool: W ${w}% · D ${d}% · L ${l}%</div>`;
}

function renderMatch(m) {
  const sc = m.scores || {};
  const w = sc.W || 33;
  const d = sc.D || 34;
  const l = sc.L || 33;
  const cov = m.coverage || {};
  const src = (name, ok) => `<span class="toto-src ${ok ? "ok" : ""}">${name}${ok ? " ✓" : ""}</span>`;
  const league = m.league ? `<span class="toto-league">${m.league}</span>` : "";

  return `
    <div class="toto-match-card">
      <div class="toto-match-head">
        <span class="toto-match-num">#${m.num}</span>
        <span class="toto-teams">${m.home_team} <span style="color:var(--muted)">vs</span> ${m.away_team}</span>
        ${league}
        <div class="toto-picks-row">
          <div><div class="toto-pick-label">S1</div>${pickChip(m.pick_primary)}</div>
          <div><div class="toto-pick-label">S2</div>${pickChip(m.pick_value)}</div>
          <div><div class="toto-pick-label">S3</div>${pickChip(m.pick_upset)}</div>
        </div>
      </div>
      ${marketLine(m.market_wdl)}
      <div class="toto-score-bar">
        <span class="w" style="width:${w}%"></span>
        <span class="d" style="width:${d}%"></span>
        <span class="l" style="width:${l}%"></span>
      </div>
      <div class="toto-scores-text">Model W ${w}% · D ${d}% · L ${l}% · top ${(m.confidence_primary || 0).toFixed(0)}%</div>
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
    grid.innerHTML = '<div class="empty">No active games in this pool. Try another product or click Refresh.</div>';
    return;
  }
  grid.innerHTML = matches.map(renderMatch).join("");
}

async function fetchData() {
  try {
    const res = await fetch(`/api/toto?type_id=${activeTypeId}`);
    const data = await res.json();
    if (data.error && !data.matches?.length) throw new Error(data.error);

    lastData = data;
    if (data.type_id) activeTypeId = data.type_id;
    bindOnexbetLinks(data.onexbet);
    renderProductTabs(data.products, activeTypeId);
    $("lastUpdate").textContent = `Updated ${fmtTime(data.updated_at)}`;
    $("matchCount").textContent = `${data.match_count || 0} games`;
    $("connectionStatus").classList.add("live");
    $("connectionStatus").classList.remove("error");

    if (data.loading) {
      $("statusText").textContent = "Analysing jackpot…";
      $("totoGrid").innerHTML = '<div class="loading">Running 1X2 analysis on all pool games (may take 1–2 min first time)…</div>';
      return;
    }

    $("statusText").textContent = `${data.onexbet?.product || "Toto"} · 3 slips · ${data.match_count || 0} games`;
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
  $("totoGrid").innerHTML = '<div class="loading">Refreshing 1xBet pool and re-analysing…</div>';
  await fetch(`/api/toto/refresh?type_id=${activeTypeId}`, { method: "POST" });
  await fetchData();
  $("btnRefresh").disabled = false;
});

function startPolling() {
  fetchData();
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(fetchData, POLL_MS);
}

startPolling();