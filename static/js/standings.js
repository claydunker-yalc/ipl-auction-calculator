/**
 * IPL Projected Standings — Frontend
 *
 * Fetches power rankings from the API and renders them with the vintage theme.
 * Two views: Ranks (category rankings 1-12) and Raw Stats (actual projected totals).
 * Two sources: Current Draft and Last Batch Sim.
 */

let standingsData = null;
let currentSource = "draft";  // "draft" or "batch"
let currentView = "ranks";    // "ranks" or "stats"

// Category display names (must match server)
const CAT_DISPLAY = {
  R: "R", RBI: "RBI", HR: "HR", SB: "SB", OPS: "OPS",
  SV_HLD: "SV+HLD", QS: "QS", ERA: "ERA", WHIP: "WHIP", K: "K",
};

const HITTING_CATS = ["R", "RBI", "HR", "SB", "OPS"];
const PITCHING_CATS = ["SV_HLD", "QS", "ERA", "WHIP", "K"];

// ---- Data Fetching ----

async function fetchStandings() {
  const url = currentSource === "batch" ? "/api/standings/batch" : "/api/standings";
  try {
    const res = await fetch(url);
    standingsData = await res.json();
    render();
  } catch (err) {
    console.error("Error fetching standings:", err);
  }
}

// ---- Source & View Toggles ----

function setSource(source) {
  currentSource = source;
  document.getElementById("btn-source-draft").classList.toggle("active", source === "draft");
  document.getElementById("btn-source-batch").classList.toggle("active", source === "batch");
  fetchStandings();
}

function setView(view) {
  currentView = view;
  document.getElementById("btn-view-ranks").classList.toggle("active", view === "ranks");
  document.getElementById("btn-view-stats").classList.toggle("active", view === "stats");
  render();
}

// ---- Rendering ----

function render() {
  if (!standingsData) return;

  const { standings, has_stats, source, picks_made, num_simulations, error } = standingsData;

  // Update status bar
  const statusEl = document.getElementById("standings-source");
  const infoEl = document.getElementById("standings-info");

  if (error) {
    statusEl.textContent = "Error";
    infoEl.textContent = error;
    document.getElementById("no-stats-warning").style.display = "block";
    document.getElementById("rankings-card").style.display = "none";
    return;
  }

  if (source === "batch_sim") {
    statusEl.textContent = "Showing: Batch Sim Average";
    infoEl.textContent = num_simulations ? `(${num_simulations} simulations)` : "";
  } else {
    statusEl.textContent = "Showing: Current Draft";
    infoEl.textContent = picks_made ? `(${picks_made} picks made)` : "(Pre-draft keepers only)";
  }

  // No stats warning
  document.getElementById("no-stats-warning").style.display = has_stats ? "none" : "block";
  document.getElementById("rankings-card").style.display = "block";

  // Render table
  if (currentView === "ranks") {
    renderRanks(standings);
  } else {
    renderStats(standings);
  }
}

function renderRanks(standings) {
  const thead = document.getElementById("rankings-thead");
  const tbody = document.getElementById("rankings-tbody");
  document.getElementById("rankings-title").textContent = "Power Rankings — Category Ranks";

  // Header
  let headerHtml = `<tr>
    <th class="rank-col">#</th>
    <th class="manager-col">Manager</th>`;

  // Hitting categories
  HITTING_CATS.forEach(cat => {
    headerHtml += `<th class="cat-col cat-hitting">${CAT_DISPLAY[cat]}</th>`;
  });

  // Divider
  headerHtml += `<th class="cat-divider"></th>`;

  // Pitching categories
  PITCHING_CATS.forEach(cat => {
    headerHtml += `<th class="cat-col cat-pitching">${CAT_DISPLAY[cat]}</th>`;
  });

  headerHtml += `<th class="total-col">Total</th>
    <th class="roster-col">Roster</th>
  </tr>`;
  thead.innerHTML = headerHtml;

  // Body
  let bodyHtml = "";
  standings.forEach(team => {
    const isMe = team.is_me;
    const rowClass = isMe ? "standings-row standings-me" : "standings-row";

    bodyHtml += `<tr class="${rowClass}" onclick="showTeamDetail('${team.manager}')">
      <td class="rank-col rank-overall rank-overall-${team.overall_rank}">${team.overall_rank}</td>
      <td class="manager-col">${team.manager}${isMe ? " ★" : ""}</td>`;

    HITTING_CATS.forEach(cat => {
      const rank = team.ranks[cat] || 0;
      bodyHtml += `<td class="cat-col ${rankClass(rank, standings.length)}">${rank % 1 === 0 ? rank : rank.toFixed(1)}</td>`;
    });

    bodyHtml += `<td class="cat-divider"></td>`;

    PITCHING_CATS.forEach(cat => {
      const rank = team.ranks[cat] || 0;
      bodyHtml += `<td class="cat-col ${rankClass(rank, standings.length)}">${rank % 1 === 0 ? rank : rank.toFixed(1)}</td>`;
    });

    bodyHtml += `<td class="total-col total-pts">${team.total_points}</td>
      <td class="roster-col">${team.roster_size}</td>
    </tr>`;
  });

  tbody.innerHTML = bodyHtml;
}

function renderStats(standings) {
  const thead = document.getElementById("rankings-thead");
  const tbody = document.getElementById("rankings-tbody");
  document.getElementById("rankings-title").textContent = "Power Rankings — Raw Stat Projections";

  // Header
  let headerHtml = `<tr>
    <th class="rank-col">#</th>
    <th class="manager-col">Manager</th>`;

  HITTING_CATS.forEach(cat => {
    headerHtml += `<th class="cat-col cat-hitting">${CAT_DISPLAY[cat]}</th>`;
  });
  headerHtml += `<th class="cat-divider"></th>`;
  PITCHING_CATS.forEach(cat => {
    headerHtml += `<th class="cat-col cat-pitching">${CAT_DISPLAY[cat]}</th>`;
  });
  headerHtml += `<th class="total-col">Pts</th></tr>`;
  thead.innerHTML = headerHtml;

  // Body
  let bodyHtml = "";
  standings.forEach(team => {
    const isMe = team.is_me;
    const rowClass = isMe ? "standings-row standings-me" : "standings-row";
    const stats = team.stats || {};

    bodyHtml += `<tr class="${rowClass}" onclick="showTeamDetail('${team.manager}')">
      <td class="rank-col rank-overall rank-overall-${team.overall_rank}">${team.overall_rank}</td>
      <td class="manager-col">${team.manager}${isMe ? " ★" : ""}</td>`;

    HITTING_CATS.forEach(cat => {
      let val = stats[cat] || 0;
      if (cat === "OPS") val = val.toFixed(3);
      bodyHtml += `<td class="cat-col stat-val">${val}</td>`;
    });

    bodyHtml += `<td class="cat-divider"></td>`;

    PITCHING_CATS.forEach(cat => {
      let val = stats[cat] || 0;
      if (cat === "ERA") val = val.toFixed(2);
      else if (cat === "WHIP") val = val.toFixed(3);
      bodyHtml += `<td class="cat-col stat-val">${val}</td>`;
    });

    bodyHtml += `<td class="total-col total-pts">${team.total_points}</td></tr>`;
  });

  tbody.innerHTML = bodyHtml;
}

// ---- Rank Color Coding ----

function rankClass(rank, numTeams) {
  // rank 1 = worst, rank numTeams = best
  if (rank >= numTeams - 2) return "rank-elite";     // Top 3 (10-12)
  if (rank >= numTeams - 5) return "rank-good";       // 7-9
  if (rank >= numTeams - 8) return "rank-mid";        // 4-6
  return "rank-low";                                    // 1-3
}

// ---- Team Detail ----

function showTeamDetail(manager) {
  if (!standingsData || !standingsData.standings) return;

  const team = standingsData.standings.find(t => t.manager === manager);
  if (!team || !team.roster) {
    // Need to fetch roster detail
    document.getElementById("team-detail-card").style.display = "none";
    return;
  }

  document.getElementById("team-detail-title").textContent = `${manager} — Full Roster`;
  const body = document.getElementById("team-detail-body");

  // Split into hitters and pitchers
  const hitters = (team.roster || []).filter(p => p.stats && p.stats.type === "Hitter");
  const pitchers = (team.roster || []).filter(p => p.stats && p.stats.type === "Pitcher");
  const noStats = (team.roster || []).filter(p => !p.stats || !p.stats.type);

  let html = "";

  // Hitters table
  if (hitters.length > 0) {
    html += `<h4 class="detail-section-title">Hitters (${hitters.length})</h4>
    <table class="detail-roster-table">
      <thead><tr>
        <th>Player</th><th>Pos</th><th>Source</th><th>$</th>
        <th>R</th><th>RBI</th><th>HR</th><th>SB</th><th>OPS</th>
      </tr></thead><tbody>`;
    hitters.forEach(p => {
      const s = p.stats;
      html += `<tr>
        <td>${p.player}</td><td>${p.position}</td>
        <td class="source-${p.source}">${p.source}</td>
        <td>$${p.price}</td>
        <td>${s.R || 0}</td><td>${s.RBI || 0}</td><td>${s.HR || 0}</td>
        <td>${s.SB || 0}</td><td>${(s.OPS || 0).toFixed(3)}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
  }

  // Pitchers table
  if (pitchers.length > 0) {
    html += `<h4 class="detail-section-title">Pitchers (${pitchers.length})</h4>
    <table class="detail-roster-table">
      <thead><tr>
        <th>Player</th><th>Pos</th><th>Source</th><th>$</th>
        <th>SV+HLD</th><th>QS</th><th>ERA</th><th>WHIP</th><th>K</th>
      </tr></thead><tbody>`;
    pitchers.forEach(p => {
      const s = p.stats;
      html += `<tr>
        <td>${p.player}</td><td>${p.position}</td>
        <td class="source-${p.source}">${p.source}</td>
        <td>$${p.price}</td>
        <td>${s.SV_HLD || 0}</td><td>${s.QS || 0}</td>
        <td>${(s.ERA || 0).toFixed(2)}</td><td>${(s.WHIP || 0).toFixed(3)}</td>
        <td>${s.K || 0}</td>
      </tr>`;
    });
    html += `</tbody></table>`;
  }

  // Players with no stats
  if (noStats.length > 0) {
    html += `<h4 class="detail-section-title" style="color:var(--sage)">No Stats (${noStats.length})</h4>
    <p style="color:var(--sage);font-size:0.85rem">`;
    html += noStats.map(p => p.player).join(", ");
    html += `</p>`;
  }

  body.innerHTML = html;
  document.getElementById("team-detail-card").style.display = "block";
  document.getElementById("team-detail-card").scrollIntoView({ behavior: "smooth" });
}

function closeTeamDetail() {
  document.getElementById("team-detail-card").style.display = "none";
}

// ---- Auto-refresh ----

let refreshInterval = null;

function startAutoRefresh() {
  refreshInterval = setInterval(fetchStandings, 10000);  // Every 10 seconds
}

// ---- Init ----

fetchStandings();
startAutoRefresh();
