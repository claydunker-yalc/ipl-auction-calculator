/**
 * IPL Auction Calculator — Dashboard JavaScript
 *
 * Handles:
 * - Data fetching and state management
 * - Player table rendering with sort/filter
 * - Manager grid rendering
 * - Draft modal and drafting flow
 * - Draft log display
 * - Inflation display
 * - Recommendations panel
 * - Profile viewer
 */

// ============================================================
// State
// ============================================================
let appState = null;  // Full state from /api/state
let sortColumn = 'base_projected_value';
let sortDirection = 'desc';
let filters = {
    position: '',
    tier: '',
    type: '',
    search: '',
};
let activeTab = 'recommendations';  // For sidebar tabs
let activeManagerProfile = null;    // Currently expanded manager profile
let inflationHistory = [];          // Track inflation over picks
let autoRunInterval = null;         // For interactive auto-run
let activeView = 'dashboard';       // dashboard | teams
let batchResults = null;            // Store batch sim results

// ============================================================
// Initialization
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    fetchState();
    setupEventListeners();
});

function setupEventListeners() {
    // Mode selector
    document.querySelectorAll('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => setMode(btn.dataset.mode));
    });

    // Filters
    document.getElementById('filter-position')?.addEventListener('change', (e) => {
        filters.position = e.target.value;
        renderPlayerTable();
        renderPositionDemand(filters.position);
    });
    document.getElementById('filter-tier')?.addEventListener('change', (e) => {
        filters.tier = e.target.value;
        renderPlayerTable();
    });
    document.getElementById('filter-type')?.addEventListener('change', (e) => {
        filters.type = e.target.value;
        renderPlayerTable();
    });
    document.getElementById('filter-search')?.addEventListener('input', (e) => {
        filters.search = e.target.value.toLowerCase();
        renderPlayerTable();
    });

    // Sidebar tabs
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            activeTab = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            document.getElementById(`tab-${activeTab}`)?.classList.add('active');
        });
    });

    // Modal close
    document.getElementById('draft-modal-overlay')?.addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeDraftModal();
    });

    // Action buttons
    document.getElementById('btn-undo')?.addEventListener('click', undoLastPick);
    document.getElementById('btn-save')?.addEventListener('click', saveDraft);
    document.getElementById('btn-load')?.addEventListener('click', loadDraft);
    document.getElementById('btn-reset')?.addEventListener('click', () => {
        if (confirm('Reset the entire draft? This cannot be undone.')) resetDraft();
    });
}

// ============================================================
// API Communication
// ============================================================
async function fetchState() {
    try {
        const res = await fetch('/api/state');
        appState = await res.json();
        renderAll();
    } catch (err) {
        console.error('Failed to fetch state:', err);
        showToast('Failed to load data', true);
    }
}

async function draftPlayer(player, manager, price, position) {
    try {
        const res = await fetch('/api/draft', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ player, manager, price: parseInt(price), position }),
        });
        const data = await res.json();
        if (data.success) {
            showToast(`${player} → ${manager} for $${price}`);
            // Track inflation history
            await fetchState();
            if (appState) {
                inflationHistory.push({
                    pick: appState.draft_log.length,
                    global: appState.inflation.global_inflation,
                    hitter: appState.inflation.hitter_inflation,
                    pitcher: appState.inflation.pitcher_inflation,
                });
            }
        } else {
            showToast(data.error || 'Draft failed', true);
        }
    } catch (err) {
        showToast('Draft failed: ' + err.message, true);
    }
}

async function undoLastPick() {
    try {
        const res = await fetch('/api/undraft', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            showToast(`Undid: ${data.removed.player}`);
            inflationHistory.pop();
            await fetchState();
        } else {
            showToast(data.error, true);
        }
    } catch (err) {
        showToast('Undo failed', true);
    }
}

async function saveDraft() {
    const res = await fetch('/api/save_draft', { method: 'POST' });
    const data = await res.json();
    if (data.success) showToast('Draft saved!');
    else showToast('Save failed', true);
}

async function loadDraft() {
    const res = await fetch('/api/load_draft', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
        showToast(`Loaded ${data.picks_loaded} picks`);
        await fetchState();
    } else {
        showToast(data.error || 'Load failed', true);
    }
}

function downloadDraftBackup() {
    window.location.href = '/api/download_draft';
    showToast('Downloading backup...');
}

async function uploadDraftBackup(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (!confirm(`Restore draft from "${file.name}"? This will replace the current draft state.`)) {
        event.target.value = '';
        return;
    }

    const formData = new FormData();
    formData.append('file', file);

    try {
        const res = await fetch('/api/upload_draft', { method: 'POST', body: formData });
        const data = await res.json();
        if (data.success) {
            showToast(`Restored ${data.picks_loaded} picks from backup`);
            await fetchState();
        } else {
            showToast(data.error || 'Restore failed', true);
        }
    } catch (err) {
        showToast('Restore failed', true);
    }
    event.target.value = '';
}

async function resetDraft() {
    const res = await fetch('/api/reset_draft', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
        inflationHistory = [];
        showToast('Draft reset');
        await fetchState();
    }
}

async function setMode(mode) {
    await fetch('/api/set_mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    });
    document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === mode);
    });
    await fetchState();
}

// ============================================================
// Render Everything
// ============================================================
function renderAll() {
    if (!appState) return;
    renderTopBar();
    renderPlayerTable();
    renderManagerGrid();
    renderDraftLog();
    renderRecommendations();
    renderInflationPanel();
    renderProfiles();
    updateAIControls();
    if (activeView === 'teams') renderTeamView();
    // Refresh position demand overlay if it's visible
    if (filters.position) renderPositionDemand(filters.position);
}

// ============================================================
// Draft Active Toggle
// ============================================================
function updateDraftToggle(isActive) {
    const btn = document.getElementById('draft-toggle-btn');
    if (!btn) return;
    const label = btn.querySelector('.draft-toggle-label');
    if (isActive) {
        btn.classList.remove('draft-off');
        btn.classList.add('draft-on');
        label.textContent = 'DRAFT LIVE';
    } else {
        btn.classList.remove('draft-on');
        btn.classList.add('draft-off');
        label.textContent = 'DRAFT OFF';
    }
}

async function toggleDraftActive() {
    try {
        const res = await fetch('/api/toggle_draft', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            updateDraftToggle(data.draft_active);
            if (data.draft_active) {
                showToast('Draft is LIVE — board is updating for everyone');
            } else {
                showToast('Draft is OFF — board is frozen, sim safely');
            }
        } else {
            showToast('Failed to toggle draft', true);
        }
    } catch (err) {
        showToast('Failed to toggle draft: ' + err.message, true);
    }
}

// ============================================================
// Top Bar
// ============================================================
function renderTopBar() {
    const inf = appState.inflation;
    const myTeam = appState.teams.find(t => t.manager === appState.my_manager);

    // Inflation badges — now shows % deviation from predictions (starts at 0%)
    const getClass = (val) => val > 5 ? 'hot' : val < -5 ? 'cold' : 'neutral';
    const fmtInf = (val) => (val >= 0 ? '+' : '') + val.toFixed(1) + '%';

    document.getElementById('inf-global-value').textContent = fmtInf(inf.global_inflation);
    document.getElementById('inf-global-value').className = 'value ' + getClass(inf.global_inflation);

    document.getElementById('inf-hitter-value').textContent = fmtInf(inf.hitter_inflation);
    document.getElementById('inf-hitter-value').className = 'value ' + getClass(inf.hitter_inflation);

    document.getElementById('inf-pitcher-value').textContent = fmtInf(inf.pitcher_inflation);
    document.getElementById('inf-pitcher-value').className = 'value ' + getClass(inf.pitcher_inflation);

    // My team summary
    if (myTeam) {
        document.getElementById('my-budget-remaining').textContent =
            `$${myTeam.budget_remaining} left | Max bid: $${myTeam.max_bid} | ${myTeam.spots_remaining} spots`;
    }

    // Mode buttons
    document.querySelectorAll('.mode-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.mode === appState.mode);
    });

    // Pick counter
    document.getElementById('pick-counter').textContent = `Pick #${appState.draft_log.length}`;

    // Draft active toggle
    updateDraftToggle(appState.draft_active);
}

// ============================================================
// Target / Fade / Steal Classification
// ============================================================
function playerFillsClayNeed(player, clayNeeds) {
    const flexMap = {
        "1B": ["CI", "UTIL"], "3B": ["CI", "UTIL"],
        "2B": ["MI", "UTIL"], "SS": ["MI", "UTIL"],
        "OF": ["UTIL"], "C": ["UTIL"], "DH": ["UTIL"],
        "SP": ["P"], "RP": ["P"],
    };
    const eligibility = player.position_eligibility || [player.position_primary || ""];
    for (const pos of eligibility) {
        if (clayNeeds[pos] > 0) return true;
        const flexes = flexMap[pos] || [];
        for (const flex of flexes) {
            if (clayNeeds[flex] > 0) return true;
        }
    }
    return false;
}

function classifyPlayer(player, clayNeeds, prodFloor) {
    const base = player.base_projected_value || 0;
    const inflAdj = player.inflation_adjusted_value || 0;
    const pred = player.predicted_value || 0;
    const fillsNeed = playerFillsClayNeed(player, clayNeeds);
    const surplus = base - inflAdj;
    const overpay = inflAdj - base;

    // $1 STEAL: predicted $1, projection >= $3, fills need
    // Steals bypass the production floor — that's the whole point of endgame steals
    if (pred === 1 && base >= 3 && fillsNeed) {
        return { category: 'steal', badge: 'STEAL' };
    }
    // TARGET: surplus >= $3 and fills need AND meets production floor
    if (surplus >= 3 && fillsNeed && base >= prodFloor) {
        return { category: 'target', badge: 'TARGET' };
    }
    // FADE: overpay >= $4 (any player)
    if (overpay >= 4) {
        return { category: 'fade', badge: null };
    }
    // VALUE: surplus >= $3 but no need (or below production floor)
    if (surplus >= 3) {
        return { category: 'value', badge: null };
    }
    // OVERPAY: mild $2-3
    if (overpay >= 2) {
        return { category: 'overpay', badge: null };
    }
    return { category: null, badge: null };
}

// ============================================================
// Player Table
// ============================================================
function renderPlayerTable() {
    if (!appState) return;

    let players = [...appState.players];

    // Apply filters
    if (filters.position) {
        players = players.filter(p =>
            p.position_eligibility.includes(filters.position) ||
            p.position_primary === filters.position
        );
    }
    if (filters.tier) {
        players = players.filter(p => p.tier === filters.tier);
    }
    if (filters.type) {
        players = players.filter(p => p.type === filters.type);
    }
    if (filters.search) {
        players = players.filter(p =>
            p.player.toLowerCase().includes(filters.search) ||
            p.mlb_team.toLowerCase().includes(filters.search)
        );
    }

    // Remove already-drafted players
    const draftedNames = new Set(appState.draft_log.map(d => d.player));
    players = players.filter(p => !draftedNames.has(p.player));

    // Sort — null/undefined values always sort to the bottom
    players.sort((a, b) => {
        let aVal = a[sortColumn];
        let bVal = b[sortColumn];

        // Push nulls/undefined to the end regardless of sort direction
        if (aVal == null && bVal == null) return 0;
        if (aVal == null) return 1;
        if (bVal == null) return -1;

        if (typeof aVal === 'string') {
            aVal = aVal.toLowerCase();
            bVal = (bVal || '').toLowerCase();
        }
        if (aVal < bVal) return sortDirection === 'asc' ? -1 : 1;
        if (aVal > bVal) return sortDirection === 'asc' ? 1 : -1;
        return 0;
    });

    // Render
    const tbody = document.getElementById('player-tbody');
    if (!tbody) return;

    // Get Clay's position needs and budget for classification
    const clayTeam = appState.teams.find(t => t.manager === appState.my_manager);
    const clayNeeds = clayTeam?.needs || {};
    const clayBudgetLeft = clayTeam ? clayTeam.budget_remaining : 0;
    const claySpotsLeft = clayTeam ? clayTeam.spots_remaining : 1;
    // Reserve $1 for ~1/3 of remaining spots (endgame filler picks)
    const dollarOneReserve = Math.round(claySpotsLeft / 3);
    const realSpendSpots = Math.max(1, claySpotsLeft - dollarOneReserve);
    const realAvgPerSpot = (clayBudgetLeft - dollarOneReserve) / realSpendSpots;
    // Production floor = 30% of real avg $/spot, minimum $3
    const prodFloor = Math.max(3, Math.round(realAvgPerSpot * 0.3));

    tbody.innerHTML = players.map(p => {
        const cls = classifyPlayer(p, clayNeeds, prodFloor);
        const rowClass = cls.category ? `player-row-${cls.category}` : '';
        const badgeHtml = cls.badge ? `<span class="value-badge badge-${cls.category}">${cls.badge}</span>` : '';
        return `
        <tr class="${rowClass}">
            <td>
                <button class="draft-btn" onclick="openDraftModal('${escapeHtml(p.player)}', '${escapeHtml(p.position_primary)}')">
                    Draft
                </button>
            </td>
            <td><strong class="player-name-link" onclick="showPlayerStats('${escapeHtml(p.player).replace(/'/g, "\\'")}')">${escapeHtml(p.player)}</strong> ${p.scott_white_tag ? `<span class="sw-tag" title="${escapeHtml(p.scott_white_tag)}">${p.scott_white_tag.split(' ')[0]}</span>` : ''} ${p.is_rookie ? '<span class="rookie-badge">R</span>' : ''} ${badgeHtml}</td>
            <td>${escapeHtml(p.position_primary)}</td>
            <td>${escapeHtml(p.mlb_team)}</td>
            <td class="price-cell col-group-value col-group-left">$${p.base_projected_value}</td>
            <td class="price-cell col-group-value col-group-right">$${p.adj_projected_value || p.base_projected_value}</td>
            <td class="price-cell col-group-market col-group-left">$${p.inflation_adjusted_value}</td>
            <td class="price-cell col-group-market col-group-right">$${p.predicted_value || '-'}</td>
            <td><span class="tier-badge tier-${p.tier}">${p.tier}</span></td>
            <td class="${p.type === 'Hitter' ? 'type-hitter' : 'type-pitcher'}">${p.type}</td>
            <td>${p.scarcity_bump_applied > 0 ? '+$' + p.scarcity_bump_applied : ''}</td>
            <td style="font-size:0.7rem;color:var(--text-muted);max-width:120px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(p.notes || '')}</td>
        </tr>`;
    }).join('');

    // Update count
    const countEl = document.getElementById('player-count');
    if (countEl) countEl.textContent = `${players.length} players`;
}

function sortTable(column) {
    if (sortColumn === column) {
        sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
    } else {
        sortColumn = column;
        sortDirection = (column === 'rank' || column === 'player') ? 'asc' : 'desc';
    }
    renderPlayerTable();
}

// ============================================================
// Manager Grid
// ============================================================
function renderManagerGrid() {
    const container = document.getElementById('manager-grid');
    if (!container) return;

    // Put Clay's team first
    const teams = [...appState.teams].sort((a, b) => {
        if (a.manager === appState.my_manager) return -1;
        if (b.manager === appState.my_manager) return 1;
        return a.manager.localeCompare(b.manager);
    });

    container.innerHTML = teams.map(t => {
        const isMe = t.manager === appState.my_manager;
        const needs = t.needs || {};
        const needsList = Object.entries(needs)
            .filter(([k, v]) => !k.startsWith('_') && v > 0)
            .map(([k, v]) => `<span class="need-badge">${k}${v > 1 ? ' x' + v : ''}</span>`)
            .join('');
        const filledList = Object.entries(needs)
            .filter(([k, v]) => !k.startsWith('_') && v <= 0)
            .map(([k]) => `<span class="need-badge filled">${k}</span>`)
            .join('');

        return `
            <div class="manager-card ${isMe ? 'is-me' : ''}" onclick="toggleManagerDetail('${escapeHtml(t.manager)}')">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span class="mgr-name">${isMe ? '⭐ ' : ''}${escapeHtml(t.manager)}</span>
                    <span class="mgr-budget">$${t.budget_remaining}</span>
                </div>
                <div class="mgr-details">
                    Budget: $${t.auction_budget} | Keepers: ${t.keeper_count} | Spots: ${t.spots_remaining} | Max: $${t.max_bid}
                </div>
                <div class="mgr-needs">${needsList}${filledList}</div>
                <div id="mgr-detail-${escapeHtml(t.manager).replace(/\s/g, '_')}" style="display:none;margin-top:8px;padding-top:8px;border-top:1px solid var(--border-light);font-size:0.75rem">
                </div>
            </div>
        `;
    }).join('');
}

function toggleManagerDetail(manager) {
    const id = 'mgr-detail-' + manager.replace(/\s/g, '_');
    const el = document.getElementById(id);
    if (!el) return;

    if (el.style.display === 'none') {
        // Build detail view
        const team = appState.teams.find(t => t.manager === manager);
        const profile = appState.profiles.find(p => p.manager === manager);

        let html = '';

        // Keepers
        if (team && team.keepers && team.keepers.length > 0) {
            html += '<strong>Keepers:</strong><br>';
            html += team.keepers.map(k => `${k.player} (${k.position}) $${k.price}`).join(', ');
            html += '<br><br>';
        }

        // Drafted players
        if (team && team.drafted_players && team.drafted_players.length > 0) {
            html += '<strong>Drafted:</strong><br>';
            html += team.drafted_players.map(d => `${d.player} (${d.position}) $${d.price}`).join(', ');
            html += '<br><br>';
        }

        // Profile summary
        if (profile && profile.classification) {
            const c = profile.classification;
            html += `<strong>AI Profile:</strong> ${c.strategy} | ${c.spend_style} | ${c.predictability}<br>`;
            html += `Age pref: ${c.age_preference} | ${c.filler_style}<br>`;
            if (profile.spending_behavior) {
                const sb = profile.spending_behavior;
                html += `Avg H/P split: ${sb.avg_hitter_spend_pct}/${sb.avg_pitcher_spend_pct} | Avg max bid: $${sb.avg_max_bid}<br>`;
            }
            if (profile.inflation_tolerance) {
                html += `Overpay freq: ${profile.inflation_tolerance.overpay_frequency_pct}% | Avg inflation ratio: ${profile.inflation_tolerance.avg_inflation_ratio}x`;
            }
        }

        el.innerHTML = html;
        el.style.display = 'block';
    } else {
        el.style.display = 'none';
    }
}

// ============================================================
// Draft Log
// ============================================================
function renderDraftLog() {
    const tbody = document.getElementById('draft-log-tbody');
    if (!tbody) return;

    const log = [...appState.draft_log].reverse();  // Most recent first

    tbody.innerHTML = log.map(p => {
        const ouClass = p.over_under > 0 ? 'over-under-positive' : p.over_under < 0 ? 'over-under-negative' : '';
        const ouText = p.over_under > 0 ? `+$${p.over_under}` : p.over_under < 0 ? `-$${Math.abs(p.over_under)}` : '$0';
        return `
            <tr>
                <td>${p.pick_num}</td>
                <td><strong>${escapeHtml(p.player)}</strong></td>
                <td>${p.position}</td>
                <td>${escapeHtml(p.manager)}</td>
                <td class="price-cell">$${p.price}</td>
                <td class="price-cell">$${p.projected_value}</td>
                <td class="${ouClass}">${ouText}</td>
            </tr>
        `;
    }).join('');

    // Summary stats
    const totalSpent = appState.draft_log.reduce((s, p) => s + p.price, 0);
    const totalValue = appState.draft_log.reduce((s, p) => s + p.projected_value, 0);
    const avgOver = appState.draft_log.length > 0
        ? (appState.draft_log.reduce((s, p) => s + p.over_under, 0) / appState.draft_log.length).toFixed(1)
        : 0;

    const summaryEl = document.getElementById('draft-log-summary');
    if (summaryEl) {
        summaryEl.innerHTML = `
            <span>${appState.draft_log.length} picks</span> |
            <span>$${totalSpent} spent</span> |
            <span>$${totalValue.toFixed(0)} in value</span> |
            <span>Avg over/under: $${avgOver}</span>
        `;
    }
}

// ============================================================
// Recommendations Panel
// ============================================================
function renderRecommendations() {
    const recs = appState.recommendations;
    if (!recs) return;

    // Budget summary
    const budgetEl = document.getElementById('rec-budget');
    if (budgetEl && recs.budget_summary) {
        const bs = recs.budget_summary;
        budgetEl.innerHTML = `
            <div class="stats-row">
                <div class="stat-box">
                    <div class="stat-value">$${bs.budget_remaining}</div>
                    <div class="stat-label">Remaining</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">$${bs.max_bid}</div>
                    <div class="stat-label">Max Bid</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value">${bs.spots_remaining}</div>
                    <div class="stat-label">Spots Left</div>
                </div>
            </div>
        `;
    }

    // Best value
    const bestEl = document.getElementById('rec-best-value');
    if (bestEl && recs.best_value) {
        bestEl.innerHTML = recs.best_value.slice(0, 10).map(p => `
            <div class="rec-item">
                <div>
                    <span class="rec-player">${escapeHtml(p.player)}</span>
                    <span class="rec-pos">${p.position_primary} | ${p.mlb_team}</span>
                    ${p.fills_need ? '<span class="need-badge" style="margin-left:4px">NEED</span>' : ''}
                </div>
                <div>
                    <span class="rec-price">$${p.inflation_adjusted_value}</span>
                    <span class="rec-value-good" style="margin-left:6px">${p.value_ratio.toFixed(1)}x</span>
                </div>
            </div>
        `).join('');
    }

    // Position targets
    const posEl = document.getElementById('rec-position-targets');
    if (posEl && recs.position_targets) {
        let html = '';
        for (const [pos, data] of Object.entries(recs.position_targets)) {
            if (data.count_needed <= 0) continue;
            html += `<div style="margin-bottom:10px">`;
            html += `<strong style="color:var(--burgundy)">${pos}</strong>`;
            html += ` <span style="font-size:0.7rem;color:var(--text-muted)">(need ${data.count_needed}, ${data.options_available} available)</span>`;
            html += data.targets.slice(0, 4).map(p => `
                <div class="rec-item">
                    <div>
                        <span class="rec-player">${escapeHtml(p.player)}</span>
                        <span class="rec-pos">${p.mlb_team}</span>
                    </div>
                    <span class="rec-price">$${p.inflation_adjusted_value}</span>
                </div>
            `).join('');
            html += '</div>';
        }
        posEl.innerHTML = html || '<div style="color:var(--text-muted);font-style:italic">All positions filled!</div>';
    }
}

// ============================================================
// Inflation Panel
// ============================================================
function renderInflationPanel() {
    const inf = appState.inflation;

    // Scarcity alerts
    const alertsEl = document.getElementById('scarcity-alerts');
    if (alertsEl && inf.position_scarcity) {
        const scarcePositions = Object.entries(inf.position_scarcity)
            .filter(([, data]) => data.is_scarce)
            .sort((a, b) => b[1].ratio - a[1].ratio);

        alertsEl.innerHTML = scarcePositions.map(([pos, data]) => {
            const level = data.ratio >= 2 ? 'danger' : 'warning';
            return `
                <div class="scarcity-alert ${level}">
                    ⚠️ <strong>${pos}</strong>: Only ${data.supply} available — ${data.demand} teams need one (+$${data.bump_dollars} scarcity bump)
                </div>
            `;
        }).join('');
    }

    // Inflation summary
    const summaryEl = document.getElementById('inflation-summary');
    if (summaryEl) {
        const gi = inf.global_inflation;
        const hotCold = gi > 10 ? 'Expect players to go well over predicted prices' :
                        gi > 5 ? 'Expect players to go slightly over predicted prices' :
                        gi < -10 ? 'Expect players to go well under predicted prices' :
                        gi < -5 ? 'Expect players to go slightly under predicted prices' :
                        'Prices tracking close to predictions';
        const icon = gi > 5 ? '📈' : gi < -5 ? '📉' : '→';

        const spentInfo = inf.picks_made > 0
            ? `<div style="font-size:0.78rem;color:var(--text-secondary);margin-top:4px">
                   Spent: $${inf.total_actual_spent} on ${inf.picks_made} picks |
                   Predicted for those: $${inf.total_predicted_spent}
               </div>`
            : '';

        summaryEl.innerHTML = `
            <div style="font-size:0.85rem;margin-bottom:8px">
                <strong>${icon} ${hotCold}</strong> — ${gi >= 0 ? '+' : ''}${gi.toFixed(1)}% vs predictions
            </div>
            <div style="font-size:0.8rem;color:var(--text-secondary)">
                $${inf.remaining_dollars.toFixed(0)} remaining across all teams |
                $${inf.remaining_predicted_value.toFixed(0)} in remaining predicted value |
                ${inf.remaining_roster_spots} spots to fill
            </div>
            ${spentInfo}
        `;
    }
}

// ============================================================
// Position Demand Overlay
// ============================================================

/**
 * Given a position from the filter dropdown, return all roster slots
 * that could be used to roster a player at that position.
 * E.g. "3B" → ["3B", "CI", "UTIL"] because a 3B can fill CI or UTIL.
 */
function getSlotsThatCanUse(position) {
    const map = {
        'C':    ['C', 'UTIL'],
        '1B':   ['1B', 'CI', 'UTIL'],
        '2B':   ['2B', 'MI', 'UTIL'],
        'SS':   ['SS', 'MI', 'UTIL'],
        '3B':   ['3B', 'CI', 'UTIL'],
        'OF':   ['OF', 'UTIL'],
        'CI':   ['CI', '1B', '3B', 'UTIL'],
        'MI':   ['MI', '2B', 'SS', 'UTIL'],
        'UTIL': ['UTIL', 'C', '1B', '2B', 'SS', '3B', 'CI', 'MI', 'OF'],
        'SP':   ['SP', 'P'],
        'RP':   ['RP', 'P'],
        'P':    ['P', 'SP', 'RP'],
    };
    return map[position] || [position];
}

function renderPositionDemand(position) {
    const overlay = document.getElementById('position-demand-overlay');
    if (!overlay) return;

    if (!position || !appState) {
        overlay.style.display = 'none';
        return;
    }

    const slots = getSlotsThatCanUse(position);
    const titleEl = document.getElementById('demand-title');
    const bodyEl = document.getElementById('demand-body');

    titleEl.innerHTML = `Managers who can bid on <strong>${position}</strong> players`;

    // For each team, check if they have open slots that match
    const demand = [];
    for (const team of appState.teams) {
        const needs = team.needs || {};
        const matchingSlots = [];
        for (const slot of slots) {
            const count = needs[slot] || 0;
            if (count > 0) {
                matchingSlots.push({ slot, count });
            }
        }
        if (matchingSlots.length > 0) {
            demand.push({
                manager: team.manager,
                budget_remaining: team.budget_remaining,
                max_bid: team.max_bid,
                spots_remaining: team.spots_remaining,
                slots: matchingSlots,
                isMe: team.manager === appState.my_manager,
            });
        }
    }

    // Sort priority: direct position need > flex (CI/MI) > UTIL only
    // Within each tier, sort by max bid descending. Clay always first in his tier.
    const flexPositions = new Set(['CI', 'MI', 'P']);
    function demandTier(d) {
        // Check if any slot is the direct position match
        if (d.slots.some(s => s.slot === position)) return 0;  // Direct need
        // Check if any slot is a flex position (CI, MI, P) — not UTIL
        if (d.slots.some(s => flexPositions.has(s.slot))) return 1;  // Flex need
        return 2;  // UTIL only
    }
    demand.sort((a, b) => {
        const tierA = demandTier(a);
        const tierB = demandTier(b);
        if (tierA !== tierB) return tierA - tierB;
        if (a.isMe && !b.isMe) return -1;
        if (!a.isMe && b.isMe) return 1;
        return b.max_bid - a.max_bid;
    });

    if (demand.length === 0) {
        bodyEl.innerHTML = `<div class="demand-empty">No managers currently need a ${position}-eligible player.</div>`;
    } else {
        bodyEl.innerHTML = `
            <div class="demand-summary">${demand.length} manager${demand.length !== 1 ? 's' : ''} can bid — ${demand.reduce((s, d) => s + d.slots.reduce((x, sl) => x + sl.count, 0), 0)} total slots open</div>
            <table class="demand-table">
                <thead>
                    <tr>
                        <th>Manager</th>
                        <th>Open Slots</th>
                        <th>Max Bid</th>
                        <th>Budget</th>
                        <th>Spots Left</th>
                    </tr>
                </thead>
                <tbody>
                    ${demand.map(d => `
                        <tr class="${d.isMe ? 'demand-me' : ''}">
                            <td>${d.isMe ? '⭐ ' : ''}${escapeHtml(d.manager)}</td>
                            <td>${d.slots.map(s =>
                                `<span class="demand-slot ${s.slot === position ? 'demand-slot-direct' : 'demand-slot-flex'}">${s.slot}${s.count > 1 ? ' ×' + s.count : ''}</span>`
                            ).join(' ')}</td>
                            <td class="price-cell">$${d.max_bid}</td>
                            <td class="price-cell">$${d.budget_remaining}</td>
                            <td>${d.spots_remaining}</td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    }

    overlay.style.display = 'block';
}

function closePositionDemand() {
    const overlay = document.getElementById('position-demand-overlay');
    if (overlay) overlay.style.display = 'none';
}

// ============================================================
// Player Stats Popup
// ============================================================
function showPlayerStats(playerName) {
    if (!appState) return;

    // Find the player in the current data
    const player = appState.players.find(p => p.player === playerName);
    if (!player) return;

    const stats = player.stats || {};
    const isHitter = player.type === 'Hitter';

    // Build stat display based on player type
    let statRows = '';
    if (isHitter) {
        const labels = [
            ['AB', 'At Bats'], ['R', 'Runs'], ['HR', 'Home Runs'],
            ['RBI', 'RBI'], ['SB', 'Stolen Bases'], ['OPS', 'OPS']
        ];
        statRows = labels.map(([key, label]) => {
            const val = stats[key];
            if (val === undefined || val === null) return '';
            return `<div class="stat-item">
                <div class="stat-value">${key === 'OPS' ? val.toFixed(3) : val}</div>
                <div class="stat-label">${label}</div>
            </div>`;
        }).join('');
    } else {
        const labels = [
            ['IP', 'Innings'], ['QS', 'Quality Starts'], ['SV_H', 'Saves+Holds'],
            ['K', 'Strikeouts'], ['ERA', 'ERA'], ['WHIP', 'WHIP']
        ];
        statRows = labels.map(([key, label]) => {
            const val = stats[key];
            if (val === undefined || val === null) return '';
            return `<div class="stat-item">
                <div class="stat-value">${(key === 'ERA' || key === 'WHIP') ? val.toFixed(2) : val}</div>
                <div class="stat-label">${label}</div>
            </div>`;
        }).join('');
    }

    // Price summary row
    const priceRow = `
        <div class="stat-prices">
            <span class="stat-price-pair value">Proj $${player.base_projected_value} → Target $${player.adj_projected_value || player.base_projected_value}</span>
            <span class="stat-price-pair market">Adj $${player.inflation_adjusted_value} ← Pred $${player.predicted_value || '-'}</span>
        </div>
    `;

    // Create or reuse popup
    let popup = document.getElementById('player-stats-popup');
    if (!popup) {
        popup = document.createElement('div');
        popup.id = 'player-stats-popup';
        popup.className = 'player-stats-popup';
        document.body.appendChild(popup);
    }

    popup.innerHTML = `
        <div class="stats-popup-header">
            <div>
                <strong class="stats-popup-name">${escapeHtml(player.player)}</strong>
                ${player.is_rookie ? '<span class="rookie-badge">R</span>' : ''}
                <span class="stats-popup-meta">${escapeHtml(player.position_primary)} · ${escapeHtml(player.mlb_team)} · <span class="tier-badge tier-${player.tier}">${player.tier}</span></span>
            </div>
            <button class="stats-popup-close" onclick="closePlayerStats()">✕</button>
        </div>
        <div class="stats-popup-label">${isHitter ? 'Projected Hitting Stats' : 'Projected Pitching Stats'}</div>
        <div class="stats-grid">${statRows}</div>
        ${priceRow}
        ${player.notes ? '<div class="stats-popup-notes">' + escapeHtml(player.notes) + '</div>' : ''}
    `;

    popup.style.display = 'block';

    // Close when clicking outside
    setTimeout(() => {
        document.addEventListener('click', closePlayerStatsOutside);
    }, 10);
}

function closePlayerStats() {
    const popup = document.getElementById('player-stats-popup');
    if (popup) popup.style.display = 'none';
    document.removeEventListener('click', closePlayerStatsOutside);
}

function closePlayerStatsOutside(e) {
    const popup = document.getElementById('player-stats-popup');
    if (popup && !popup.contains(e.target) && !e.target.classList.contains('player-name-link')) {
        closePlayerStats();
    }
}

// ============================================================
// Profiles Tab
// ============================================================
function renderProfiles() {
    const container = document.getElementById('profiles-list');
    if (!container || !appState.profiles) return;

    container.innerHTML = appState.profiles.map(p => {
        const c = p.classification || {};
        const sb = p.spending_behavior || {};
        const hPct = sb.avg_hitter_spend_pct || 50;
        return `
            <div class="profile-card" style="border-bottom:1px solid var(--border-light);padding-bottom:10px;margin-bottom:10px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <strong style="color:var(--navy);font-family:var(--font-display)">${escapeHtml(p.manager)}</strong>
                    <span style="font-size:0.7rem;color:var(--text-muted)">${p.total_drafts} drafts | ${p.data_quality}</span>
                </div>
                <div style="font-size:0.75rem;color:var(--text-secondary);margin:4px 0">
                    ${c.strategy || ''} | ${c.spend_style || ''} | ${c.predictability || ''} | ${c.age_preference || ''}
                </div>
                <div class="profile-bar" title="Hitter/Pitcher split">
                    <div class="profile-bar-fill hitter" style="width:${hPct}%"></div>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--text-muted)">
                    <span>H: ${hPct}%</span>
                    <span>Avg max: $${sb.avg_max_bid || 0}</span>
                    <span>$1 avg: ${sb.avg_dollar_one_count || 0}</span>
                    <span>Overpay: ${(p.inflation_tolerance || {}).overpay_frequency_pct || 0}%</span>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================================
// Draft Modal
// ============================================================
function openDraftModal(playerName, position) {
    const overlay = document.getElementById('draft-modal-overlay');
    if (!overlay) return;

    document.getElementById('modal-player-name').textContent = playerName;
    document.getElementById('modal-position').value = position;

    // Find player data for projected price hint
    const player = appState.players.find(p => p.player === playerName);
    if (player) {
        document.getElementById('modal-price').value = Math.round(player.inflation_adjusted_value);
        document.getElementById('modal-projected-hint').textContent =
            `Proj: $${player.base_projected_value} → Target: $${player.adj_projected_value || player.base_projected_value} | Pred: $${player.predicted_value || 'N/A'} → Adj: $${player.inflation_adjusted_value}`;
    }

    // Populate manager dropdown
    const select = document.getElementById('modal-manager');
    select.innerHTML = appState.teams
        .sort((a, b) => {
            if (a.manager === appState.my_manager) return -1;
            if (b.manager === appState.my_manager) return 1;
            return a.manager.localeCompare(b.manager);
        })
        .map(t => `<option value="${escapeHtml(t.manager)}" ${t.manager === appState.my_manager ? 'selected' : ''}>${escapeHtml(t.manager)} ($${t.budget_remaining})</option>`)
        .join('');

    overlay.classList.add('active');
    document.getElementById('modal-price').focus();
    document.getElementById('modal-price').select();
}

function openManualDraftModal() {
    const overlay = document.getElementById('draft-modal-overlay');
    if (!overlay || !appState) return;

    // Replace the player name with an editable input
    const nameEl = document.getElementById('modal-player-name');
    nameEl.innerHTML = '<input type="text" id="modal-manual-name" placeholder="Type player name..." style="font-family:var(--font-display);font-size:1.1rem;font-weight:700;color:var(--burgundy);border:1px solid var(--border-medium);border-radius:4px;padding:4px 8px;width:100%;background:var(--cream)">';
    document.getElementById('modal-projected-hint').textContent = 'Manual entry — player not in projections ($0 value)';
    document.getElementById('modal-price').value = 1;
    document.getElementById('modal-position').value = 'UTIL';

    // Populate manager dropdown
    const select = document.getElementById('modal-manager');
    select.innerHTML = appState.teams
        .sort((a, b) => {
            if (a.manager === appState.my_manager) return -1;
            if (b.manager === appState.my_manager) return 1;
            return a.manager.localeCompare(b.manager);
        })
        .map(t => `<option value="${escapeHtml(t.manager)}" ${t.manager === appState.my_manager ? 'selected' : ''}>${escapeHtml(t.manager)} ($${t.budget_remaining})</option>`)
        .join('');

    overlay.classList.add('active');
    setTimeout(() => document.getElementById('modal-manual-name')?.focus(), 50);
}

function closeDraftModal() {
    document.getElementById('draft-modal-overlay')?.classList.remove('active');
    // Restore the player name element to plain text (in case it was a manual input)
    const nameEl = document.getElementById('modal-player-name');
    if (nameEl && nameEl.querySelector('input')) {
        nameEl.innerHTML = '';
    }
}

function confirmDraft() {
    // Check if this is a manual entry (input field) or a normal draft (text)
    const manualInput = document.getElementById('modal-manual-name');
    const playerName = manualInput ? manualInput.value.trim() : document.getElementById('modal-player-name').textContent;
    const manager = document.getElementById('modal-manager').value;
    const price = document.getElementById('modal-price').value;
    const position = document.getElementById('modal-position').value;

    if (!playerName || !manager || !price) {
        showToast('Fill in all fields', true);
        return;
    }

    draftPlayer(playerName, manager, price, position);
    closeDraftModal();
}

// ============================================================
// Utilities
// ============================================================
function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(message, isError = false) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = 'toast visible' + (isError ? ' error' : '');
    setTimeout(() => toast.classList.remove('visible'), 3000);
}

// ============================================================
// AI Controls — Mode Switching
// ============================================================
function updateAIControls() {
    if (!appState) return;
    const mode = appState.mode;

    const assistEl = document.getElementById('ai-assist-controls');
    const interEl = document.getElementById('interactive-controls');
    const batchEl = document.getElementById('batch-controls');

    if (assistEl) assistEl.style.display = mode === 'manual' ? 'flex' : 'none';
    if (interEl) interEl.style.display = mode === 'interactive' ? 'flex' : 'none';
    if (batchEl) batchEl.style.display = mode === 'batch' ? 'flex' : 'none';

    // Stop auto-run when switching modes
    if (autoRunInterval && mode !== 'interactive') {
        clearInterval(autoRunInterval);
        autoRunInterval = null;
    }
}

// ============================================================
// AI Assist (Manual Mode)
// ============================================================
async function runAiPicks() {
    const countEl = document.getElementById('ai-pick-count');
    const statusEl = document.getElementById('ai-assist-status');
    const btn = document.getElementById('btn-ai-picks');
    const numPicks = parseInt(countEl?.value || '5');

    btn.disabled = true;
    statusEl.textContent = 'Running...';
    statusEl.className = 'ai-status running';

    try {
        const res = await fetch('/api/ai_picks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ num_picks: numPicks }),
        });
        const data = await res.json();

        if (data.success) {
            statusEl.textContent = `Done! ${data.new_picks.length} picks made`;
            statusEl.className = 'ai-status done';
            showToast(`AI made ${data.new_picks.length} picks`);
            await fetchState();
        } else {
            statusEl.textContent = 'Error: ' + (data.error || 'Unknown');
            statusEl.className = 'ai-status error';
            showToast(data.error || 'AI picks failed', true);
        }
    } catch (err) {
        statusEl.textContent = 'Error: ' + err.message;
        statusEl.className = 'ai-status error';
        showToast('AI picks failed: ' + err.message, true);
    }

    btn.disabled = false;
    setTimeout(() => { statusEl.textContent = ''; }, 5000);
}

// ============================================================
// Interactive Mode
// ============================================================
async function runInteractiveStep() {
    const statusEl = document.getElementById('interactive-status');
    const btn = document.getElementById('btn-next-pick');

    btn.disabled = true;
    statusEl.textContent = 'Picking...';
    statusEl.className = 'ai-status running';

    try {
        const res = await fetch('/api/interactive_step', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
        const data = await res.json();

        if (data.success && data.new_pick) {
            const p = data.new_pick;
            statusEl.textContent = `${p.player} → ${p.manager} for $${p.price}`;
            statusEl.className = 'ai-status done';
            await fetchState();
        } else if (data.success) {
            statusEl.textContent = 'Auction complete!';
            statusEl.className = 'ai-status done';
            stopAutoRun();
        } else {
            statusEl.textContent = 'Error: ' + (data.error || 'Unknown');
            statusEl.className = 'ai-status error';
            stopAutoRun();
        }
    } catch (err) {
        statusEl.textContent = 'Error: ' + err.message;
        statusEl.className = 'ai-status error';
        stopAutoRun();
    }

    btn.disabled = false;
}

function toggleAutoRun() {
    if (autoRunInterval) {
        stopAutoRun();
    } else {
        startAutoRun();
    }
}

function startAutoRun() {
    const speedEl = document.getElementById('auto-speed');
    const speed = parseInt(speedEl?.value || '500');
    const btn = document.getElementById('btn-auto-run');

    btn.textContent = 'Stop';
    btn.classList.add('btn-auto-running');

    autoRunInterval = setInterval(async () => {
        await runInteractiveStep();
        // Check if auction is done
        if (appState && appState.draft_log.length >= 128) {
            stopAutoRun();
            showToast('Auction simulation complete!');
        }
    }, speed);
}

function stopAutoRun() {
    if (autoRunInterval) {
        clearInterval(autoRunInterval);
        autoRunInterval = null;
    }
    const btn = document.getElementById('btn-auto-run');
    if (btn) {
        btn.textContent = 'Auto-Run';
        btn.classList.remove('btn-auto-running');
    }
}

// ============================================================
// Batch Simulation
// ============================================================
function setAnchor(useProjected) {
    document.getElementById('use-projected-anchor').value = useProjected ? 'true' : 'false';
    document.getElementById('anchor-pred').classList.toggle('active', !useProjected);
    document.getElementById('anchor-proj').classList.toggle('active', useProjected);
}

async function runBatchSim() {
    const countEl = document.getElementById('batch-sim-count');
    const statusEl = document.getElementById('batch-status');
    const btn = document.getElementById('btn-run-batch');
    const numSims = parseInt(countEl?.value || '25');

    btn.disabled = true;
    statusEl.textContent = `Running ${numSims} simulations...`;
    statusEl.className = 'ai-status running';

    try {
        const res = await fetch('/api/run_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                num_simulations: numSims,
                forced_picks: window.draftPlan && window.draftPlan.length > 0 ? window.draftPlan : undefined,
                use_projected_anchor: document.getElementById('use-projected-anchor')?.value === 'true',
            }),
        });
        const data = await res.json();

        if (data.success) {
            batchResults = data.results;
            lastRegularBatch = data.results; // Save for throwback comparison
            statusEl.textContent = `Done! ${batchResults.simulation_count} sims completed`;
            statusEl.className = 'ai-status done';
            showToast(`Batch simulation complete (${batchResults.simulation_count} sims)`);
            renderBatchResults();
        } else {
            statusEl.textContent = 'Error: ' + (data.error || 'Unknown');
            statusEl.className = 'ai-status error';
            showToast(data.error || 'Batch sim failed', true);
            console.error('Batch error:', data.traceback);
        }
    } catch (err) {
        statusEl.textContent = 'Error: ' + err.message;
        statusEl.className = 'ai-status error';
        showToast('Batch sim failed: ' + err.message, true);
    }

    btn.disabled = false;
}

function renderBatchResults() {
    if (!batchResults) return;

    const panel = document.getElementById('batch-results-panel');
    panel.style.display = 'block';

    const sa = batchResults.standings_analysis || {};

    // Summary stats row
    const summaryEl = document.getElementById('batch-summary');
    let summaryHTML = `
        <div class="batch-stat">
            <div class="stat-value">${batchResults.simulation_count}</div>
            <div class="stat-label">Simulations</div>
        </div>
        <div class="batch-stat">
            <div class="stat-value">$${batchResults.my_avg_spent}</div>
            <div class="stat-label">My Avg Spent</div>
        </div>
        <div class="batch-stat">
            <div class="stat-value">$${batchResults.my_avg_value}</div>
            <div class="stat-label">My Avg Value</div>
        </div>
    `;

    // Feature 1: Average finish stats
    if (sa.avg_rank) {
        summaryHTML += `
            <div class="batch-stat batch-stat-highlight">
                <div class="stat-value">${formatOrdinal(sa.avg_rank)}</div>
                <div class="stat-label">Avg Finish</div>
            </div>
            <div class="batch-stat">
                <div class="stat-value">${sa.avg_points}</div>
                <div class="stat-label">Avg Points</div>
            </div>
            <div class="batch-stat">
                <div class="stat-value">${formatOrdinal(sa.best_rank)} - ${formatOrdinal(sa.worst_rank)}</div>
                <div class="stat-label">Range</div>
            </div>
        `;
    }

    summaryEl.innerHTML = summaryHTML;

    // Feature 1 & 3: Standings snapshot
    renderStandingsSnapshot(sa);

    // Feature 2: Best/worst outcomes
    renderOutcomes('best-outcomes-container', sa.best_outcomes || [], 'Best');
    renderOutcomes('worst-outcomes-container', sa.worst_outcomes || [], 'Worst');

    // Player prices table
    const playerTbody = document.getElementById('batch-player-tbody');
    playerTbody.innerHTML = batchResults.player_stats.slice(0, 80).map(p => {
        const ouClass = p.avg_over_under > 0 ? 'value-bad' : p.avg_over_under < 0 ? 'value-good' : 'value-neutral';
        return `
            <tr>
                <td><strong>${escapeHtml(p.player)}</strong></td>
                <td>${p.position}</td>
                <td>$${p.projected_value}</td>
                <td>$${p.predicted_value}</td>
                <td class="price-cell"><strong>$${p.avg_price}</strong></td>
                <td>$${p.min_price}</td>
                <td>$${p.max_price}</td>
                <td>${p.std_dev}</td>
                <td class="${ouClass}">${p.avg_over_under > 0 ? '+' : ''}$${p.avg_over_under}</td>
            </tr>
        `;
    }).join('');

    // My team table
    const myTeamTbody = document.getElementById('batch-myteam-tbody');
    myTeamTbody.innerHTML = batchResults.my_avg_team.map(p => `
        <tr>
            <td><strong>${escapeHtml(p.player)}</strong></td>
            <td>${p.position}</td>
            <td><strong>${p.frequency_pct}%</strong></td>
            <td>${p.times_drafted}</td>
            <td>$${p.avg_price}</td>
            <td><span class="tier-badge tier-${p.tier}">${p.tier}</span></td>
        </tr>
    `).join('');

    // Consistent values table
    const valuesTbody = document.getElementById('batch-values-tbody');
    valuesTbody.innerHTML = batchResults.consistent_values.map(p => {
        const savings = (p.projected_value - p.avg_price).toFixed(1);
        return `
            <tr>
                <td><strong>${escapeHtml(p.player)}</strong></td>
                <td>${p.position}</td>
                <td>$${p.projected_value}</td>
                <td>$${p.avg_price}</td>
                <td class="value-good">+$${savings}</td>
                <td>${p.std_dev}</td>
            </tr>
        `;
    }).join('');

    // Volatile players table
    const volatileTbody = document.getElementById('batch-volatile-tbody');
    volatileTbody.innerHTML = batchResults.volatile_players.map(p => `
        <tr>
            <td><strong>${escapeHtml(p.player)}</strong></td>
            <td>${p.position}</td>
            <td>$${p.avg_price}</td>
            <td>$${p.min_price}</td>
            <td>$${p.max_price}</td>
            <td class="value-bad">${p.std_dev}</td>
            <td>$${p.max_price - p.min_price}</td>
        </tr>
    `).join('');

    // Scroll to results
    panel.scrollIntoView({ behavior: 'smooth' });
}

function switchBatchTab(tab) {
    document.querySelectorAll('.batch-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.btab === tab);
    });
    document.querySelectorAll('.batch-tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`btab-${tab}`)?.classList.add('active');
}

function closeBatchResults() {
    document.getElementById('batch-results-panel').style.display = 'none';
}

// ============================================================
// Feature 1 & 3: Standings Snapshot
// ============================================================
function formatOrdinal(n) {
    const num = Math.round(n * 10) / 10;
    const s = String(num);
    const whole = Math.floor(num);
    if (whole === 11 || whole === 12 || whole === 13) return s + 'th';
    const lastDigit = whole % 10;
    if (lastDigit === 1) return s + 'st';
    if (lastDigit === 2) return s + 'nd';
    if (lastDigit === 3) return s + 'rd';
    return s + 'th';
}

const CAT_DISPLAY_NAMES = {
    R: 'R', RBI: 'RBI', HR: 'HR', SB: 'SB', OPS: 'OPS',
    SV_HLD: 'SV+HLD', QS: 'QS', ERA: 'ERA', WHIP: 'WHIP', K: 'K'
};

function renderStandingsSnapshot(sa) {
    const el = document.getElementById('batch-standings-snapshot');
    if (!el || !sa || !sa.avg_rank) {
        if (el) el.innerHTML = '';
        return;
    }

    // Rank distribution bars
    const dist = sa.rank_distribution || [];
    const maxPct = Math.max(...dist.map(d => d.pct), 1);
    const distHTML = dist.map(d => `
        <div class="rank-dist-bar-group">
            <div class="rank-dist-label">${formatOrdinal(d.rank)}</div>
            <div class="rank-dist-bar" style="width:${Math.max(4, (d.pct / maxPct) * 100)}%">
                <span class="rank-dist-pct">${d.pct}%</span>
            </div>
        </div>
    `).join('');

    // Category analysis
    const cats = sa.category_analysis || {};
    const catOrder = ['R','RBI','HR','SB','OPS','SV_HLD','QS','ERA','WHIP','K'];
    const catHTML = catOrder.map(cat => {
        const data = cats[cat];
        if (!data) return '';
        const avgRank = data.avg_rank;
        const colorClass = avgRank >= 10 ? 'rank-elite' : avgRank >= 7 ? 'rank-good' : avgRank >= 4 ? 'rank-mid' : 'rank-low';
        return `
            <div class="cat-rank-cell ${colorClass}">
                <div class="cat-rank-name">${CAT_DISPLAY_NAMES[cat] || cat}</div>
                <div class="cat-rank-value">${avgRank}</div>
            </div>
        `;
    }).join('');

    // Strengths & weaknesses
    const strengthNames = (sa.strengths || []).map(c => CAT_DISPLAY_NAMES[c] || c);
    const weakNames = (sa.weaknesses || []).map(c => CAT_DISPLAY_NAMES[c] || c);

    // Spending profile
    const sp = sa.spending_profile || {};

    // League context
    const leagueAvg = sa.league_avg_points || 0;
    const myAvg = sa.avg_points || 0;
    const ptsDiff = (myAvg - leagueAvg).toFixed(1);
    const ptsSign = ptsDiff >= 0 ? '+' : '';

    el.innerHTML = `
        <div class="standings-snapshot">
            <div class="snapshot-section">
                <div class="snapshot-title">Finish Distribution</div>
                <div class="rank-dist-chart">${distHTML}</div>
            </div>
            <div class="snapshot-section">
                <div class="snapshot-title">Avg Category Ranks</div>
                <div class="cat-rank-grid">${catHTML}</div>
                ${strengthNames.length ? `<div class="snapshot-note"><span class="strength-tag">Strengths:</span> ${strengthNames.join(', ')}</div>` : ''}
                ${weakNames.length ? `<div class="snapshot-note"><span class="weakness-tag">Weaknesses:</span> ${weakNames.join(', ')}</div>` : ''}
            </div>
            <div class="snapshot-section snapshot-section-compact">
                <div class="snapshot-title">Spending Profile</div>
                <div class="spending-row">
                    <span>Hitters: $${sp.avg_hitter_spend || 0}</span>
                    <span>Pitchers: $${sp.avg_pitcher_spend || 0}</span>
                    <span>$1 players: ${sp.avg_dollar_one_count || 0}</span>
                    <span>Top 3: $${sp.avg_top3_spend || 0}</span>
                </div>
                <div class="league-context">
                    Your avg: ${myAvg} pts vs league avg: ${leagueAvg} pts
                    <span class="${ptsDiff >= 0 ? 'value-good' : 'value-bad'}">(${ptsSign}${ptsDiff})</span>
                </div>
            </div>
        </div>
    `;
}

// ============================================================
// Feature 2: Best/Worst Outcomes
// ============================================================
function renderOutcomes(containerId, outcomes, label) {
    const el = document.getElementById(containerId);
    if (!el) return;

    if (!outcomes || outcomes.length === 0) {
        el.innerHTML = `<div class="loading">Run a batch sim with standings analysis to see ${label.toLowerCase()} outcomes.</div>`;
        return;
    }

    el.innerHTML = outcomes.map((sim, idx) => {
        const catRanks = sim.category_ranks || {};
        const catOrder = ['R','RBI','HR','SB','OPS','SV_HLD','QS','ERA','WHIP','K'];
        const catCells = catOrder.map(cat => {
            const val = catRanks[cat] || 0;
            const colorClass = val >= 10 ? 'rank-elite' : val >= 7 ? 'rank-good' : val >= 4 ? 'rank-mid' : 'rank-low';
            return `<td class="${colorClass}">${val}</td>`;
        }).join('');

        const roster = (sim.roster || []).sort((a, b) => b.price - a.price);
        const rosterRows = roster.map(p => `
            <tr>
                <td><strong>${escapeHtml(p.player)}</strong></td>
                <td>${p.position}</td>
                <td>$${p.price}</td>
                <td><span class="tier-badge tier-${p.tier}">${p.tier}</span></td>
                <td class="${p.type === 'Hitter' ? 'type-hitter' : 'type-pitcher'}">${p.type}</td>
            </tr>
        `).join('');

        return `
            <div class="outcome-card ${label.toLowerCase()}-outcome">
                <div class="outcome-header">
                    <div class="outcome-rank">${label} #${idx + 1} — Sim #${sim.sim_num}</div>
                    <div class="outcome-stats">
                        <span class="outcome-finish">${formatOrdinal(sim.overall_rank)} place</span>
                        <span class="outcome-points">${sim.total_points} pts</span>
                        <span>$${sim.total_spent} spent</span>
                        <span>$${sim.total_value} value</span>
                    </div>
                </div>
                <div class="outcome-cats">
                    <table class="batch-table outcome-cat-table">
                        <thead><tr>${catOrder.map(c => `<th>${CAT_DISPLAY_NAMES[c] || c}</th>`).join('')}<th>Total</th></tr></thead>
                        <tbody><tr>${catCells}<td class="total-pts">${sim.total_points}</td></tr></tbody>
                    </table>
                </div>
                <div class="outcome-roster">
                    <table class="batch-table">
                        <thead><tr><th>Player</th><th>Pos</th><th>Price</th><th>Tier</th><th>Type</th></tr></thead>
                        <tbody>${rosterRows}</tbody>
                    </table>
                </div>
            </div>
        `;
    }).join('');
}

// ============================================================
// Feature 4: Keeper Throw-Back Lab
// ============================================================
let throwbackMode = 'single';
let throwbackSelected = new Set();
let throwbackResults = null;
let lastRegularBatch = null; // Store regular batch for comparison

function openThrowbackLab() {
    const panel = document.getElementById('throwback-lab-panel');
    panel.style.display = 'block';
    renderThrowbackKeepers();
    panel.scrollIntoView({ behavior: 'smooth' });
}

function closeThrowbackLab() {
    document.getElementById('throwback-lab-panel').style.display = 'none';
}

function setThrowbackMode(mode) {
    throwbackMode = mode;
    if (mode === 'single') {
        // Keep only the last selected
        const arr = Array.from(throwbackSelected);
        throwbackSelected = arr.length ? new Set([arr[arr.length - 1]]) : new Set();
    }
    document.getElementById('tb-mode-single').classList.toggle('active', mode === 'single');
    document.getElementById('tb-mode-multi').classList.toggle('active', mode === 'multi');
    renderThrowbackKeepers();
}

function renderThrowbackKeepers() {
    const container = document.getElementById('throwback-keepers');
    if (!container || !appState) return;

    // Find Clay's team
    const myTeam = appState.teams.find(t => t.manager === appState.my_manager);
    if (!myTeam || !myTeam.keepers) {
        container.innerHTML = '<div class="loading">No keepers found.</div>';
        return;
    }

    container.innerHTML = myTeam.keepers.map(k => {
        const selected = throwbackSelected.has(k.player);
        return `
            <div class="throwback-keeper-card ${selected ? 'selected' : ''}"
                 onclick="toggleThrowbackKeeper('${escapeHtml(k.player).replace(/'/g, "\\'")}')">
                <div class="tb-keeper-name">${escapeHtml(k.player)}</div>
                <div class="tb-keeper-details">
                    <span class="tb-keeper-pos">${k.position}</span>
                    <span class="tb-keeper-price">$${k.price}</span>
                </div>
                ${selected ? '<div class="tb-selected-badge">THROW BACK</div>' : ''}
            </div>
        `;
    }).join('');
}

function toggleThrowbackKeeper(playerName) {
    if (throwbackMode === 'single') {
        if (throwbackSelected.has(playerName)) {
            throwbackSelected.clear();
        } else {
            throwbackSelected = new Set([playerName]);
        }
    } else {
        if (throwbackSelected.has(playerName)) {
            throwbackSelected.delete(playerName);
        } else {
            throwbackSelected.add(playerName);
        }
    }
    renderThrowbackKeepers();
}

async function runThrowbackSim() {
    if (throwbackSelected.size === 0) {
        showToast('Select at least one keeper to throw back', true);
        return;
    }

    const numSims = parseInt(document.getElementById('throwback-sim-count')?.value || '25');
    const statusEl = document.getElementById('throwback-status');
    const btn = document.getElementById('btn-run-throwback');
    const keeperNames = Array.from(throwbackSelected);

    btn.disabled = true;
    statusEl.textContent = `Simulating without ${keeperNames.join(', ')}...`;
    statusEl.className = 'ai-status running';

    // Save current batch as baseline for comparison
    if (batchResults && !batchResults.is_throwback) {
        lastRegularBatch = batchResults;
    }

    try {
        const res = await fetch('/api/run_batch_throwback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                keepers_to_throw_back: keeperNames,
                num_simulations: numSims,
                forced_picks: window.draftPlan && window.draftPlan.length > 0 ? window.draftPlan : undefined,
                use_projected_anchor: document.getElementById('use-projected-anchor')?.value === 'true',
            }),
        });
        const data = await res.json();

        if (data.success) {
            throwbackResults = data.results;
            statusEl.textContent = 'Done!';
            statusEl.className = 'ai-status done';
            renderThrowbackResults();
            showToast(`Throw-back simulation complete (${throwbackResults.simulation_count} sims)`);
        } else {
            statusEl.textContent = 'Error: ' + (data.error || 'Unknown');
            statusEl.className = 'ai-status error';
            showToast(data.error || 'Throw-back sim failed', true);
        }
    } catch (err) {
        statusEl.textContent = 'Error: ' + err.message;
        statusEl.className = 'ai-status error';
        showToast('Throw-back sim failed: ' + err.message, true);
    }

    btn.disabled = false;
}

function renderThrowbackResults() {
    if (!throwbackResults) return;

    const resultsEl = document.getElementById('throwback-results');
    resultsEl.style.display = 'block';

    const sa = throwbackResults.standings_analysis || {};
    const thrown = throwbackResults.thrown_back || [];
    const thrownNames = thrown.map(t => `${t.player} ($${t.price})`).join(', ');

    // Comparison with regular batch
    const compEl = document.getElementById('throwback-comparison');
    let compHTML = `
        <div class="throwback-comparison-header">
            <strong>Threw back:</strong> ${thrownNames}<br>
            <strong>New budget:</strong> $${throwbackResults.new_auction_budget} |
            <strong>Keepers:</strong> ${throwbackResults.new_keeper_count}
        </div>
    `;

    if (lastRegularBatch && lastRegularBatch.standings_analysis) {
        const regSA = lastRegularBatch.standings_analysis;
        const rankDelta = (sa.avg_rank && regSA.avg_rank) ? (regSA.avg_rank - sa.avg_rank).toFixed(1) : null;
        const ptsDelta = (sa.avg_points && regSA.avg_points) ? (sa.avg_points - regSA.avg_points).toFixed(1) : null;
        const valueDelta = (throwbackResults.my_avg_value - lastRegularBatch.my_avg_value).toFixed(1);

        compHTML += `
            <div class="throwback-deltas">
                ${rankDelta !== null ? `<div class="delta-stat">
                    <div class="delta-label">Avg Finish</div>
                    <div class="delta-values">
                        <span class="delta-old">${formatOrdinal(regSA.avg_rank)}</span>
                        <span class="delta-arrow">&rarr;</span>
                        <span class="delta-new">${formatOrdinal(sa.avg_rank)}</span>
                        <span class="delta-change ${parseFloat(rankDelta) > 0 ? 'value-good' : parseFloat(rankDelta) < 0 ? 'value-bad' : ''}">(${parseFloat(rankDelta) > 0 ? '+' : ''}${rankDelta} places)</span>
                    </div>
                </div>` : ''}
                ${ptsDelta !== null ? `<div class="delta-stat">
                    <div class="delta-label">Avg Points</div>
                    <div class="delta-values">
                        <span class="delta-old">${regSA.avg_points}</span>
                        <span class="delta-arrow">&rarr;</span>
                        <span class="delta-new">${sa.avg_points}</span>
                        <span class="delta-change ${parseFloat(ptsDelta) > 0 ? 'value-good' : parseFloat(ptsDelta) < 0 ? 'value-bad' : ''}">(${parseFloat(ptsDelta) > 0 ? '+' : ''}${ptsDelta})</span>
                    </div>
                </div>` : ''}
                <div class="delta-stat">
                    <div class="delta-label">Avg Value</div>
                    <div class="delta-values">
                        <span class="delta-old">$${lastRegularBatch.my_avg_value}</span>
                        <span class="delta-arrow">&rarr;</span>
                        <span class="delta-new">$${throwbackResults.my_avg_value}</span>
                        <span class="delta-change ${parseFloat(valueDelta) > 0 ? 'value-good' : parseFloat(valueDelta) < 0 ? 'value-bad' : ''}">(${parseFloat(valueDelta) > 0 ? '+$' : '-$'}${Math.abs(valueDelta)})</span>
                    </div>
                </div>
            </div>
        `;
    }

    compEl.innerHTML = compHTML;

    // Summary stats
    const summaryEl = document.getElementById('throwback-batch-summary');
    summaryEl.innerHTML = `
        <div class="batch-stat batch-stat-highlight">
            <div class="stat-value">${sa.avg_rank ? formatOrdinal(sa.avg_rank) : 'N/A'}</div>
            <div class="stat-label">Avg Finish</div>
        </div>
        <div class="batch-stat">
            <div class="stat-value">${sa.avg_points || 'N/A'}</div>
            <div class="stat-label">Avg Points</div>
        </div>
        <div class="batch-stat">
            <div class="stat-value">$${throwbackResults.my_avg_spent}</div>
            <div class="stat-label">Avg Spent</div>
        </div>
        <div class="batch-stat">
            <div class="stat-value">$${throwbackResults.my_avg_value}</div>
            <div class="stat-label">Avg Value</div>
        </div>
    `;

    // My team table
    const myTeamTbody = document.getElementById('tb-myteam-tbody');
    myTeamTbody.innerHTML = (throwbackResults.my_avg_team || []).map(p => `
        <tr>
            <td><strong>${escapeHtml(p.player)}</strong></td>
            <td>${p.position}</td>
            <td><strong>${p.frequency_pct}%</strong></td>
            <td>${p.times_drafted}</td>
            <td>$${p.avg_price}</td>
            <td><span class="tier-badge tier-${p.tier}">${p.tier}</span></td>
        </tr>
    `).join('');

    // Best/worst outcomes
    renderOutcomes('tb-best-outcomes', sa.best_outcomes || [], 'Best');
    renderOutcomes('tb-worst-outcomes', sa.worst_outcomes || [], 'Worst');
}

function switchThrowbackTab(tab) {
    document.querySelectorAll('#throwback-tabs .batch-tab-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.tbtab === tab);
    });
    document.querySelectorAll('.throwback-tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`tbtab-${tab}`)?.classList.add('active');
}

// ============================================================
// View Switching (Dashboard ↔ Team View)
// ============================================================
function switchView(view) {
    activeView = view;

    // Toggle button styles
    document.querySelectorAll('.view-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.view === view);
    });

    // Toggle containers
    const dashboardEl = document.querySelector('.dashboard-container');
    const teamViewEl = document.getElementById('team-view-container');
    const batchEl = document.getElementById('batch-results-panel');

    if (view === 'dashboard') {
        dashboardEl.style.display = '';
        teamViewEl.style.display = 'none';
    } else if (view === 'teams') {
        dashboardEl.style.display = 'none';
        teamViewEl.style.display = '';
        if (batchEl) batchEl.style.display = 'none';
        renderTeamView();
    }
}

// ============================================================
// Team View — Full Roster Display
// ============================================================

/** Roster slot order: hitting positions first, then pitching */
const ROSTER_SLOT_ORDER = [
    { pos: 'C',    count: 1, type: 'hitting' },
    { pos: '1B',   count: 1, type: 'hitting' },
    { pos: '2B',   count: 1, type: 'hitting' },
    { pos: 'SS',   count: 1, type: 'hitting' },
    { pos: '3B',   count: 1, type: 'hitting' },
    { pos: 'CI',   count: 1, type: 'hitting' },
    { pos: 'MI',   count: 1, type: 'hitting' },
    { pos: 'OF',   count: 5, type: 'hitting' },
    { pos: 'UTIL', count: 1, type: 'hitting' },
    { pos: 'SP',   count: 4, type: 'pitching' },
    { pos: 'RP',   count: 3, type: 'pitching' },
    { pos: 'P',    count: 2, type: 'pitching' },
];

function renderTeamView() {
    if (!appState) return;
    const container = document.getElementById('team-view-grid');
    if (!container) return;

    // Sort teams: Clay first, then alphabetical
    const teams = [...appState.teams].sort((a, b) => {
        if (a.manager === appState.my_manager) return -1;
        if (b.manager === appState.my_manager) return 1;
        return a.manager.localeCompare(b.manager);
    });

    container.innerHTML = teams.map(team => renderTeamRosterCard(team)).join('');
}

function renderTeamRosterCard(team) {
    const isMe = team.manager === appState.my_manager;

    // Build a list of all players on the roster (keepers + drafted)
    const keepers = (team.keepers || []).map(k => ({
        player: k.player,
        position: k.position,
        price: k.price,
        source: 'keeper',
        mlb_team: k.mlb_team || '',
    }));

    const drafted = (team.drafted_players || []).map(d => ({
        player: d.player,
        position: d.position,
        price: d.price,
        source: 'drafted',
        mlb_team: d.mlb_team || '',
    }));

    const allPlayers = [...keepers, ...drafted];

    // Fill roster slots
    const filledSlots = fillRosterSlots(allPlayers);
    // Stamp manager name on each slot for move-player UI
    filledSlots.forEach(s => s.manager = team.manager);

    // Build HTML sections
    let hittingRows = '';
    let pitchingRows = '';

    for (const slot of filledSlots) {
        const row = renderRosterSlotRow(slot);
        if (slot.type === 'hitting') {
            hittingRows += row;
        } else {
            pitchingRows += row;
        }
    }

    // Stats for footer
    const totalSpent = allPlayers.reduce((s, p) => s + (p.price || 0), 0);
    const keeperCount = keepers.length;
    const draftedCount = drafted.length;
    const spotsLeft = 22 - allPlayers.length;

    return `
        <div class="team-roster-card ${isMe ? 'is-me' : ''}">
            <div class="team-roster-header">
                <div class="team-roster-name">
                    ${isMe ? '⭐ ' : ''}${escapeHtml(team.manager)}
                    <span class="team-label">${escapeHtml(team.team_name || '')}</span>
                </div>
                <div class="team-roster-budget">
                    <div class="budget-big">$${team.budget_remaining}</div>
                    <div class="budget-detail">Max bid: $${team.max_bid} | ${spotsLeft} open</div>
                </div>
            </div>
            <div class="team-roster-body">
                <div class="roster-section-header">Hitting</div>
                ${hittingRows}
                <div class="roster-section-header">Pitching</div>
                ${pitchingRows}
            </div>
            <div class="team-roster-footer">
                <div class="footer-stat">
                    <div class="footer-label">Keepers</div>
                    <div class="footer-value">${keeperCount}</div>
                </div>
                <div class="footer-stat">
                    <div class="footer-label">Drafted</div>
                    <div class="footer-value">${draftedCount}</div>
                </div>
                <div class="footer-stat">
                    <div class="footer-label">Total Spent</div>
                    <div class="footer-value">$${totalSpent}</div>
                </div>
                <div class="footer-stat">
                    <div class="footer-label">Spots Left</div>
                    <div class="footer-value">${spotsLeft}</div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Assign players to roster slots using the same flex logic as the backend.
 * Returns an array of {pos, type, player, price, source, mlb_team} objects.
 */
function fillRosterSlots(players) {
    // Build empty slot list
    const slots = [];
    for (const def of ROSTER_SLOT_ORDER) {
        for (let i = 0; i < def.count; i++) {
            slots.push({
                pos: def.pos,
                type: def.type,
                player: null,
                price: null,
                source: null,
                mlb_team: null,
            });
        }
    }

    // Track which players have been assigned
    const unassigned = [...players];

    // Pass 1: exact position matches
    for (const slot of slots) {
        if (slot.player) continue;
        const idx = unassigned.findIndex(p => p.position === slot.pos);
        if (idx !== -1) {
            const p = unassigned.splice(idx, 1)[0];
            slot.player = p.player;
            slot.price = p.price;
            slot.source = p.source;
            slot.mlb_team = p.mlb_team;
        }
    }

    // Pass 2: flex position mapping
    const flexMap = {
        'CI': ['1B', '3B'],
        'MI': ['2B', 'SS'],
        'P':  ['SP', 'RP'],
        'UTIL': ['C', '1B', '2B', 'SS', '3B', 'OF', 'CI', 'MI'],
    };

    for (const slot of slots) {
        if (slot.player) continue;
        const eligible = flexMap[slot.pos] || [];
        if (eligible.length === 0) continue;
        const idx = unassigned.findIndex(p => eligible.includes(p.position));
        if (idx !== -1) {
            const p = unassigned.splice(idx, 1)[0];
            slot.player = p.player;
            slot.price = p.price;
            slot.source = p.source;
            slot.mlb_team = p.mlb_team;
        }
    }

    // Pass 3: any remaining unassigned players go to first empty slot of matching type
    for (const p of unassigned) {
        const pType = ['SP', 'RP', 'P'].includes(p.position) ? 'pitching' : 'hitting';
        const emptySlot = slots.find(s => !s.player && s.type === pType);
        if (emptySlot) {
            emptySlot.player = p.player;
            emptySlot.price = p.price;
            emptySlot.source = p.source;
            emptySlot.mlb_team = p.mlb_team;
        }
    }

    return slots;
}

function renderRosterSlotRow(slot) {
    const posClass = slot.type === 'hitting' ? 'pos-hitting' : 'pos-pitching';

    if (!slot.player) {
        return `
            <div class="roster-slot">
                <span class="roster-slot-pos ${posClass}">${slot.pos}</span>
                <span class="roster-slot-player empty-slot">—</span>
                <span class="roster-slot-price"></span>
            </div>
        `;
    }

    const sourceClass = slot.source === 'keeper' ? 'source-keeper' : 'source-drafted';
    const sourceLabel = slot.source === 'keeper' ? 'K' : 'D';
    const mlbTeam = slot.mlb_team ? `<span class="roster-slot-team">${escapeHtml(slot.mlb_team)}</span>` : '';

    // Position badge is clickable to move player
    const safePlayer = escapeHtml(slot.player).replace(/'/g, "\\'");
    const safeManager = escapeHtml(slot.manager || '').replace(/'/g, "\\'");

    // Delete button only for drafted players (not keepers)
    const deleteBtn = slot.source === 'drafted'
        ? `<span class="roster-slot-delete" onclick="confirmDeletePick('${safeManager}', '${safePlayer}', event)" title="Remove draft pick">✕</span>`
        : '';

    return `
        <div class="roster-slot">
            <span class="roster-slot-pos ${posClass} pos-clickable"
                  onclick="openMovePlayer('${safeManager}', '${safePlayer}', '${slot.pos}', this)"
                  title="Click to change position">${slot.pos}</span>
            <span class="roster-slot-player">${escapeHtml(slot.player)}</span>
            ${mlbTeam}
            <span class="roster-slot-source ${sourceClass}">${sourceLabel}</span>
            <span class="roster-slot-price">$${slot.price}</span>
            ${deleteBtn}
        </div>
    `;
}

// ============================================================
// Move Player Position
// ============================================================
const ALL_POSITIONS = ['C','1B','2B','SS','3B','CI','MI','OF','UTIL','SP','RP','P'];
const POS_MAX = { C:1, '1B':1, '2B':1, SS:1, '3B':1, CI:1, MI:1, OF:5, UTIL:1, SP:4, RP:3, P:2 };

// Count how many players a manager has at each position (from current appState)
function getManagerPosCounts(manager) {
    const counts = {};
    ALL_POSITIONS.forEach(p => counts[p] = 0);

    if (!appState) return counts;

    // Count from draft log
    (appState.draft_log || []).forEach(pick => {
        if (pick.manager === manager && counts[pick.position] !== undefined) {
            counts[pick.position]++;
        }
    });

    // Count from keepers
    const team = (appState.teams || []).find(t => t.manager === manager);
    if (team) {
        (team.keepers || []).forEach(k => {
            if (counts[k.position] !== undefined) {
                counts[k.position]++;
            }
        });
    }

    return counts;
}

function openMovePlayer(manager, player, currentPos, el) {
    // Close any existing dropdown
    closeMoveDropdown();

    // Get position counts to show which are full
    const posCounts = getManagerPosCounts(manager);

    const dropdown = document.createElement('div');
    dropdown.id = 'move-pos-dropdown';
    dropdown.className = 'move-pos-dropdown';

    dropdown.innerHTML = `
        <div class="move-pos-title">Move to:</div>
        ${ALL_POSITIONS.map(pos => {
            const isCurrent = pos === currentPos;
            // Subtract 1 from current pos count since this player will be leaving it
            const countAtPos = isCurrent ? posCounts[pos] - 1 : posCounts[pos];
            const maxSlots = POS_MAX[pos] || 1;
            const isFull = countAtPos >= maxSlots && !isCurrent;
            const disabled = isCurrent || isFull;
            const label = isFull ? `${pos} (full)` : pos;
            return `
                <button class="move-pos-option ${isCurrent ? 'current' : ''} ${isFull ? 'full' : ''}"
                        onclick="movePlayer('${manager.replace(/'/g, "\\'")}', '${player.replace(/'/g, "\\'")}', '${pos}')"
                        ${disabled ? 'disabled' : ''}>
                    ${label}
                </button>
            `;
        }).join('')}
    `;

    // Position near the clicked element
    const rect = el.getBoundingClientRect();
    dropdown.style.position = 'fixed';
    dropdown.style.top = (rect.bottom + 4) + 'px';
    dropdown.style.left = rect.left + 'px';
    dropdown.style.zIndex = '3000';

    document.body.appendChild(dropdown);

    // Close on outside click
    setTimeout(() => {
        document.addEventListener('click', closeMoveDropdownOutside);
    }, 10);
}

function closeMoveDropdown() {
    const existing = document.getElementById('move-pos-dropdown');
    if (existing) existing.remove();
    document.removeEventListener('click', closeMoveDropdownOutside);
}

function closeMoveDropdownOutside(e) {
    const dropdown = document.getElementById('move-pos-dropdown');
    if (dropdown && !dropdown.contains(e.target) && !e.target.classList.contains('pos-clickable')) {
        closeMoveDropdown();
    }
}

async function movePlayer(manager, player, newPosition) {
    closeMoveDropdown();
    try {
        const res = await fetch('/api/move_player', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ manager, player, new_position: newPosition }),
        });
        const data = await res.json();
        if (data.success) {
            showToast(`${player}: ${data.old_position} → ${newPosition}`);
            await fetchState();
        } else {
            showToast(data.error || 'Move failed', true);
        }
    } catch (err) {
        showToast('Move failed: ' + err.message, true);
    }
}

// ============================================================
// Delete Draft Pick
// ============================================================
function confirmDeletePick(manager, player, event) {
    event.stopPropagation();

    // Close any open dropdown
    closeMoveDropdown();

    // Create confirmation popup
    const popup = document.createElement('div');
    popup.id = 'delete-pick-confirm';
    popup.className = 'delete-pick-confirm';
    popup.innerHTML = `
        <div class="delete-confirm-text">Remove <strong>${player}</strong> from ${manager}?</div>
        <div class="delete-confirm-sub">Player returns to the available pool. Budget is restored.</div>
        <div class="delete-confirm-buttons">
            <button class="delete-confirm-yes" onclick="deletePick('${manager.replace(/'/g, "\\'")}', '${player.replace(/'/g, "\\'")}')">Yes, Delete</button>
            <button class="delete-confirm-no" onclick="closeDeleteConfirm()">Cancel</button>
        </div>
    `;

    // Position near the clicked element
    const rect = event.target.getBoundingClientRect();
    popup.style.position = 'fixed';
    popup.style.top = (rect.bottom + 4) + 'px';
    popup.style.left = Math.max(10, rect.left - 100) + 'px';
    popup.style.zIndex = '3000';

    // Remove any existing
    closeDeleteConfirm();
    document.body.appendChild(popup);

    setTimeout(() => {
        document.addEventListener('click', closeDeleteConfirmOutside);
    }, 10);
}

function closeDeleteConfirm() {
    const existing = document.getElementById('delete-pick-confirm');
    if (existing) existing.remove();
    document.removeEventListener('click', closeDeleteConfirmOutside);
}

function closeDeleteConfirmOutside(e) {
    const popup = document.getElementById('delete-pick-confirm');
    if (popup && !popup.contains(e.target)) {
        closeDeleteConfirm();
    }
}

async function deletePick(manager, player) {
    closeDeleteConfirm();
    try {
        const res = await fetch('/api/delete_pick', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ manager, player }),
        });
        const data = await res.json();
        if (data.success) {
            showToast(`Removed ${player} from ${manager} ($${data.removed.price} restored)`);
            await fetchState();
        } else {
            showToast(data.error || 'Delete failed', true);
        }
    } catch (err) {
        showToast('Delete failed: ' + err.message, true);
    }
}

// ============================================================
// Draft Plan — Lock in specific picks before batch sim
// ============================================================
window.draftPlan = [];

function toggleDraftPlan() {
    const panel = document.getElementById('draft-plan-panel');
    if (!panel) return;
    const visible = panel.style.display !== 'none';
    panel.style.display = visible ? 'none' : 'block';
    if (!visible) populateDraftPlanAutocomplete();
}

function populateDraftPlanAutocomplete() {
    const datalist = document.getElementById('dp-player-list');
    if (!datalist || !appState.players) return;
    const planned = new Set(window.draftPlan.map(p => p.player));
    datalist.innerHTML = '';
    appState.players.forEach(p => {
        if (!planned.has(p.player)) {
            const opt = document.createElement('option');
            opt.value = p.player;
            datalist.appendChild(opt);
        }
    });
}

function addDraftPlanPick() {
    const nameEl = document.getElementById('dp-player');
    const priceEl = document.getElementById('dp-price');
    const name = nameEl?.value?.trim();
    const price = parseInt(priceEl?.value || '1');

    if (!name) { showToast('Enter a player name', true); return; }

    // Verify player exists in projections
    const player = appState.players?.find(p => p.player.toLowerCase() === name.toLowerCase());
    if (!player) { showToast('Player not found in draft pool', true); return; }

    // Check not already in plan
    if (window.draftPlan.find(p => p.player === player.player)) {
        showToast('Already in draft plan', true); return;
    }

    // Check budget
    const totalPlanned = window.draftPlan.reduce((s, p) => s + p.price, 0);
    const myBudget = appState.my_auction_budget || 71;
    const slotsNeeded = (appState.my_spots_remaining || 9) - window.draftPlan.length;
    const maxBid = myBudget - totalPlanned - (slotsNeeded - 1);
    if (price > maxBid) {
        showToast(`Max bid is $${maxBid} (need $1 for ${slotsNeeded - 1} remaining slots)`, true);
        return;
    }

    window.draftPlan.push({
        player: player.player,
        price: price,
    });

    nameEl.value = '';
    priceEl.value = '1';
    renderDraftPlan();
    populateDraftPlanAutocomplete();
}

function removeDraftPlanPick(index) {
    window.draftPlan.splice(index, 1);
    renderDraftPlan();
    populateDraftPlanAutocomplete();
}

function clearDraftPlan() {
    window.draftPlan = [];
    renderDraftPlan();
    populateDraftPlanAutocomplete();
}

function renderDraftPlan() {
    const container = document.getElementById('dp-picks-list');
    const budgetInfo = document.getElementById('dp-budget-info');
    if (!container) return;

    if (window.draftPlan.length === 0) {
        container.innerHTML = '<div style="color:var(--text-secondary);padding:4px 0">No picks locked in. Add players above, then Run Batch to test your plan.</div>';
        if (budgetInfo) budgetInfo.textContent = '';
        return;
    }

    const totalPlanned = window.draftPlan.reduce((s, p) => s + p.price, 0);
    const myBudget = appState.my_auction_budget || 71;
    const slotsTotal = appState.my_spots_remaining || 9;
    const slotsLeft = slotsTotal - window.draftPlan.length;

    if (budgetInfo) {
        budgetInfo.textContent = `$${totalPlanned} planned / $${myBudget} budget — $${myBudget - totalPlanned} left for ${slotsLeft} open slot${slotsLeft !== 1 ? 's' : ''}`;
    }

    let html = '<div style="display:flex;flex-wrap:wrap;gap:6px">';
    window.draftPlan.forEach((pick, i) => {
        const player = appState.players?.find(p => p.player === pick.player);
        const pos = player?.position_primary || '?';
        const type = player?.type || '?';
        const typeColor = type === 'Pitcher' ? '#c9a959' : '#6b8f71';
        html += `
            <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:4px;padding:4px 8px;display:flex;align-items:center;gap:6px">
                <span style="font-weight:600">${pick.player}</span>
                <span style="color:var(--text-secondary);font-size:0.8rem">${pos}</span>
                <span style="background:${typeColor};color:#fff;font-size:0.7rem;padding:1px 4px;border-radius:2px">${type}</span>
                <span style="font-weight:700;color:var(--accent-gold)">$${pick.price}</span>
                <button onclick="removeDraftPlanPick(${i})" style="background:none;border:none;color:var(--accent-red);cursor:pointer;font-size:1rem;padding:0 2px" title="Remove">×</button>
            </div>
        `;
    });
    html += '</div>';
    container.innerHTML = html;
}
