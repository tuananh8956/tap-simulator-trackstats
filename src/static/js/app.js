// Tap Simulator Reborn TrackStats - Frontend Application
let activeUserId = null;
let accountsList = [];
let tpsChart = null;
let maxChartPoints = 40;
let chartTimeLabels = [];
let chartTpsData = [];
let chartTapsData = [];
let eventSource = null;

function formatNumber(num) {
  if (num === null || num === undefined) return "0";
  return Number(num).toLocaleString();
}

function formatCompact(num) {
  if (num === null || num === undefined) return "0";
  if (num >= 1e9) return (num / 1e9).toFixed(2) + "B";
  if (num >= 1e6) return (num / 1e6).toFixed(2) + "M";
  if (num >= 1e3) return (num / 1e3).toFixed(1) + "K";
  return num.toString();
}

function formatDuration(sec) {
  if (!sec || sec < 0) return "00:00:00";
  const s = Math.floor(sec % 60);
  const m = Math.floor((sec / 60) % 60);
  const h = Math.floor(sec / 3600);
  return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

async function apiFetch(endpoint, options = {}) {
  try {
    const res = await fetch(endpoint, options);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "API request failed");
    }
    return await res.json();
  } catch (e) {
    console.error("API error:", e);
    throw e;
  }
}

// Initialize Application
document.addEventListener("DOMContentLoaded", () => {
  initChart();
  loadAccounts().then(() => {
    connectSSE();
  });
  setupEventListeners();
});

function initChart() {
  const ctx = document.getElementById("tpsChart").getContext("2d");
  tpsChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartTimeLabels,
      datasets: [
        {
          label: "Real-time TPS",
          data: chartTpsData,
          borderColor: "#00f2fe",
          backgroundColor: "rgba(0, 242, 254, 0.08)",
          fill: true,
          tension: 0.35,
          borderWidth: 2,
          pointRadius: 1,
          pointHoverRadius: 5,
          yAxisID: "y"
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#64748b", font: { size: 10 } }
        },
        y: {
          position: "left",
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#94a3b8" },
          suggestedMin: 0,
          suggestedMax: 50
        }
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0d111a",
          borderColor: "rgba(0, 242, 254, 0.3)",
          borderWidth: 1,
          padding: 10
        }
      }
    }
  });
}

function updateChart(tps) {
  const nowStr = new Date().toLocaleTimeString();
  chartTimeLabels.push(nowStr);
  chartTpsData.push(tps);

  if (chartTimeLabels.length > maxChartPoints) {
    chartTimeLabels.shift();
    chartTpsData.shift();
  }
  if (tpsChart) {
    tpsChart.update();
  }
}

async function loadAccounts() {
  try {
    const accounts = await apiFetch("/api/v1/accounts");
    accountsList = accounts;
    renderAccountDropdown(accounts);
    renderMultiAccountsTable(accounts);

    if (accounts.length > 0 && !activeUserId) {
      setActiveAccount(accounts[0].user_id);
    }
  } catch (e) {
    console.error("Failed to load accounts:", e);
  }
}

function renderAccountDropdown(accounts) {
  const select = document.getElementById("accountSelect");
  select.innerHTML = "";
  if (accounts.length === 0) {
    select.innerHTML = `<option value="">No Accounts Tracked</option>`;
    return;
  }
  accounts.forEach(acc => {
    const opt = document.createElement("option");
    opt.value = acc.user_id;
    opt.textContent = `${acc.username} (${acc.user_id})`;
    if (acc.user_id === activeUserId) opt.selected = true;
    select.appendChild(opt);
  });
}

function setActiveAccount(userId) {
  activeUserId = Number(userId);
  chartTimeLabels.length = 0;
  chartTpsData.length = 0;
  if (tpsChart) tpsChart.update();
  loadLiveState(activeUserId);
  loadHistory(activeUserId);
}

async function loadLiveState(userId) {
  if (!userId) return;
  try {
    const state = await apiFetch(`/api/v1/accounts/${userId}/live`);
    renderDashboard(state);
  } catch (e) {
    console.error("Failed to fetch live state:", e);
  }
}

function renderDashboard(data) {
  if (!data || data.user_id !== activeUserId) return;

  // Header & Status
  const statusBadge = document.getElementById("connectionStatusBadge");
  statusBadge.className = `status-badge ${data.connection_status.toLowerCase()}`;
  document.getElementById("statusText").textContent = data.connection_status;

  const btnToggle = document.getElementById("btnToggleTracking");
  if (data.is_tracking) {
    btnToggle.className = "btn btn-toggle-tracking active";
    btnToggle.innerHTML = `<i data-lucide="pause"></i> Pause Tracking`;
  } else {
    btnToggle.className = "btn btn-toggle-tracking paused";
    btnToggle.innerHTML = `<i data-lucide="play"></i> Resume Tracking`;
  }

  // Player Overview
  document.getElementById("playerAvatar").src = data.avatar_url || `https://www.roblox.com/headshot-thumbnail/image?userId=${data.user_id}&width=150&height=150&format=png`;
  document.getElementById("playerName").textContent = data.display_name || data.username;
  document.getElementById("playerUserId").textContent = `@${data.username} (ID: ${data.user_id})`;
  document.getElementById("sessionDuration").textContent = formatDuration(data.session_duration_sec);

  // Live Stats Grid
  document.getElementById("statCurrentTaps").textContent = formatNumber(data.current_taps);
  document.getElementById("statTotalTaps").textContent = formatNumber(data.total_taps);
  document.getElementById("statTps").textContent = data.tps.toFixed(1);
  document.getElementById("statMaxTps").textContent = `Max: ${data.max_tps.toFixed(1)} | Avg: ${data.avg_tps.toFixed(1)}`;
  document.getElementById("statCurrentRebirths").textContent = formatNumber(data.current_rebirths);
  document.getElementById("statWins").textContent = formatNumber(data.current_wins);
  document.getElementById("statCurrency").textContent = formatNumber(data.current_currency);

  // Growth Rates Panel
  const windows = data.rates || {};
  const w1m = windows["1m"] || { taps_gained: 0, currency_gained: 0, tps: 0 };
  const w5m = windows["5m"] || { taps_gained: 0, currency_gained: 0, tps: 0 };
  const w15m = windows["15m"] || { taps_gained: 0, currency_gained: 0, tps: 0 };

  document.getElementById("growth1mTaps").textContent = `+${formatNumber(w1m.taps_gained)}`;
  document.getElementById("growth1mCurrency").textContent = `+${formatCompact(w1m.currency_gained)}`;
  document.getElementById("growth1mTps").textContent = `${w1m.tps.toFixed(1)} TPS`;

  document.getElementById("growth5mTaps").textContent = `+${formatNumber(w5m.taps_gained)}`;
  document.getElementById("growth5mCurrency").textContent = `+${formatCompact(w5m.currency_gained)}`;
  document.getElementById("growth5mTps").textContent = `${w5m.tps.toFixed(1)} TPS`;

  document.getElementById("growth15mTaps").textContent = `+${formatNumber(w15m.taps_gained)}`;
  document.getElementById("growth15mCurrency").textContent = `+${formatCompact(w15m.currency_gained)}`;
  document.getElementById("growth15mTps").textContent = `${w15m.tps.toFixed(1)} TPS`;

  // Pet Showcase
  renderPets(data.equipped_pets, data.total_pet_power, data.pet_inventory_count);

  // Chart Update
  updateChart(data.tps);

  // Refresh icons
  if (window.lucide) lucide.createIcons();
}

function renderPets(pets, totalPower, invCount) {
  const container = document.getElementById("petsGrid");
  document.getElementById("totalPetPower").textContent = `Total Power: ${formatCompact(totalPower)} (${invCount} stored)`;

  if (!pets || pets.length === 0) {
    container.innerHTML = `<div style="grid-column: 1/-1; color: var(--text-dim); text-align: center; padding: 20px;">No pets equipped</div>`;
    return;
  }

  container.innerHTML = "";
  pets.forEach(p => {
    const card = document.createElement("div");
    card.className = "pet-card";
    const rarity = p.rarity || "Common";
    card.innerHTML = `
      <div class="pet-rarity-badge rarity-${rarity}">${rarity}</div>
      <div class="pet-name">${p.name || 'Unknown Pet'}</div>
      <div class="pet-stat-row">
        <span>Multiplier</span>
        <span>${p.multiplier}x</span>
      </div>
      <div class="pet-stat-row">
        <span>Pet Power</span>
        <span>+${formatNumber(p.power)}</span>
      </div>
    `;
    container.appendChild(card);
  });
}

function renderMultiAccountsTable(accounts) {
  const tbody = document.getElementById("multiAccountsTableBody");
  if (!tbody) return;
  tbody.innerHTML = "";

  if (accounts.length === 0) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 20px;">No accounts added yet. Click "+ Add Account" to begin.</td></tr>`;
    return;
  }

  accounts.forEach(a => {
    const tr = document.createElement("tr");
    const statusClass = (a.connection_status || 'offline').toLowerCase();
    tr.innerHTML = `
      <td>
        <div style="display:flex; align-items:center; gap:8px;">
          <img src="${a.avatar_url || ''}" style="width:28px; height:28px; border-radius:50%; background:#1e293b;" onerror="this.src=''"/>
          <strong>${a.username}</strong>
        </div>
      </td>
      <td>${a.user_id}</td>
      <td><span class="status-badge ${statusClass}"><span class="status-dot"></span>${a.connection_status || 'OFFLINE'}</span></td>
      <td>${formatNumber(a.current_taps || 0)}</td>
      <td>${(a.tps || 0).toFixed(1)}</td>
      <td>${formatDuration(a.session_duration_sec || 0)}</td>
      <td>
        <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.75rem;" onclick="setActiveAccount(${a.user_id})">View</button>
        <button class="btn btn-secondary" style="padding:4px 10px; font-size:0.75rem; color:#f87171;" onclick="deleteAccount(${a.user_id})">Delete</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
}

async function loadHistory(userId) {
  if (!userId) return;
  try {
    const sessions = await apiFetch(`/api/v1/accounts/${userId}/history`);
    const tbody = document.getElementById("historyTableBody");
    tbody.innerHTML = "";
    if (sessions.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px;">No past sessions recorded yet.</td></tr>`;
      return;
    }
    sessions.forEach(s => {
      const startStr = new Date(s.start_time * 1000).toLocaleString();
      const dur = s.end_time ? formatDuration(s.end_time - s.start_time) : "Active";
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${startStr}</td>
        <td>${dur}</td>
        <td>+${formatNumber(s.taps_gained)}</td>
        <td>+${formatNumber(s.rebirths_gained)}</td>
        <td>${(s.max_tps || 0).toFixed(1)}</td>
        <td>${(s.avg_tps || 0).toFixed(1)}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    console.error("Failed to load history:", e);
  }
}

// Server-Sent Events (SSE) Real-Time Hook
function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/api/v1/stream");

  eventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      if (Array.isArray(payload)) {
        // Update multi-account overview
        renderMultiAccountsTable(payload);

        // Find active account state
        const activeData = payload.find(p => p.user_id === activeUserId);
        if (activeData) {
          renderDashboard(activeData);
        }
      }
    } catch (e) {
      console.error("SSE parse error:", e);
    }
  };

  eventSource.onerror = () => {
    // Reconnect will happen automatically via EventSource
  };
}

function setupEventListeners() {
  document.getElementById("accountSelect").addEventListener("change", (e) => {
    setActiveAccount(e.target.value);
  });

  document.getElementById("btnToggleTracking").addEventListener("click", async () => {
    if (!activeUserId) return;
    const acc = accountsList.find(a => a.user_id === activeUserId);
    const newState = acc ? !acc.is_tracking : false;
    await apiFetch(`/api/v1/accounts/${activeUserId}/tracking`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_tracking: newState })
    });
    await loadAccounts();
    await loadLiveState(activeUserId);
  });

  // Modal handlers
  const addModal = document.getElementById("addAccountModal");
  document.getElementById("btnAddAccount").addEventListener("click", () => addModal.classList.add("open"));
  document.getElementById("btnCloseAddModal").addEventListener("click", () => addModal.classList.remove("open"));

  document.getElementById("formAddAccount").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("inputUserId");
    const uid = Number(input.value.trim());
    if (!uid) return;
    try {
      await apiFetch("/api/v1/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: uid })
      });
      input.value = "";
      addModal.classList.remove("open");
      await loadAccounts();
      setActiveAccount(uid);
    } catch (err) {
      alert("Error adding account: " + err.message);
    }
  });

  // Batch actions
  document.getElementById("btnStartAll").addEventListener("click", async () => {
    await apiFetch("/api/v1/accounts/tracking/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_tracking: true })
    });
    await loadAccounts();
  });

  document.getElementById("btnPauseAll").addEventListener("click", async () => {
    await apiFetch("/api/v1/accounts/tracking/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_tracking: false })
    });
    await loadAccounts();
  });
}

async function deleteAccount(userId) {
  if (!confirm(`Are you sure you want to delete account ${userId}?`)) return;
  try {
    await apiFetch(`/api/v1/accounts/${userId}`, { method: "DELETE" });
    if (activeUserId === userId) activeUserId = null;
    await loadAccounts();
  } catch (e) {
    alert("Delete failed: " + e.message);
  }
}
