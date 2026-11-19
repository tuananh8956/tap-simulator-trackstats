// Tap Simulator Reborn TrackStats v2 - Frontend SPA Application
let activeUserId = null;
let activeTab = "overview";
let accountsList = [];
let secretsPayload = { total_secrets: 0, unique_types: 0, by_variant: {}, by_tier: {}, grouped: [], items: [] };
let petCatalogList = [];
let recentHatchesList = [];
let vaultMode = "owned"; // "owned" | "catalog"
let vaultVariantFilter = "all";
let soundEnabled = false;
let lastSeenHatchId = 0;
let hatchesHydrated = false;

let tpsChart = null;
const maxChartPoints = 40;
const chartTimeLabels = [];
const chartTpsData = [];
let eventSource = null;

// --- XSS & URL Sanitization Helpers ---

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeImageUrl(url, fallback = "/api/v1/pets/icon/secret-pet.svg") {
  if (!url || typeof url !== "string") return fallback;
  const cleaned = url.trim();
  if (!cleaned || /[\s"'<>]/.test(cleaned)) return fallback;
  const lower = cleaned.toLowerCase();
  if (
    lower.startsWith("https://") ||
    lower.startsWith("http://") ||
    lower.startsWith("/static/") ||
    lower.startsWith("/api/")
  ) {
    return cleaned;
  }
  return fallback;
}

function variantThemeClass(variant) {
  const v = (variant || "Normal").toLowerCase();
  if (v.includes("rainbow")) return "variant-rainbow";
  if (v.includes("golden") || v.includes("gold")) return "variant-golden";
  if (v.includes("diamond")) return "variant-diamond";
  if (v.includes("shiny")) return "variant-shiny";
  return "variant-normal";
}

function variantBadgeClass(variant) {
  const v = (variant || "Normal").toLowerCase();
  if (v.includes("rainbow")) return "vb-rainbow";
  if (v.includes("golden") || v.includes("gold")) return "vb-golden";
  if (v.includes("diamond")) return "vb-diamond";
  if (v.includes("shiny")) return "vb-shiny";
  return "vb-normal";
}

function formatNumber(num) {
  if (num === null || num === undefined || Number.isNaN(Number(num))) return "0";
  return Number(num).toLocaleString();
}

function formatCompact(num) {
  const n = Number(num || 0);
  if (Number.isNaN(n)) return "0";
  if (n >= 1e15) return (n / 1e15).toFixed(2) + "Qa";
  if (n >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return Math.round(n).toString();
}

function formatDuration(sec) {
  if (!sec || sec < 0) return "00:00:00";
  const s = Math.floor(sec % 60);
  const m = Math.floor((sec / 60) % 60);
  const h = Math.floor(sec / 3600);
  return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function formatShortTime(tsSec) {
  if (!tsSec) return "--";
  const diff = Math.max(0, Math.floor(Date.now() / 1000 - tsSec));
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return new Date(tsSec * 1000).toLocaleTimeString();
}

function showToast(message, kind = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast ${kind === "secret" ? "secret-toast" : kind === "error" ? "error-toast" : ""}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 250);
  }, 3600);
}

function playSecretChime() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    const ctx = new AudioCtx();
    const notes = [523.25, 659.25, 783.99, 1046.5];
    notes.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, ctx.currentTime + idx * 0.08);
      gain.gain.setValueAtTime(0.001, ctx.currentTime + idx * 0.08);
      gain.gain.exponentialRampToValueAtTime(0.14, ctx.currentTime + idx * 0.08 + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + idx * 0.08 + 0.28);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + idx * 0.08);
      osc.stop(ctx.currentTime + idx * 0.08 + 0.3);
    });
  } catch (_) {}
}

async function apiFetch(endpoint, options = {}) {
  const res = await fetch(endpoint, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API request failed");
  }
  return await res.json();
}

// --- Initialization ---

document.addEventListener("DOMContentLoaded", () => {
  initDynamicEndpoints();
  initChart();
  setupEventListeners();
  Promise.all([loadOverview(), loadAccounts(), loadSecretsVault(), loadPetCatalog(), loadHatches(), loadAlertSettings(), loadInspectorReports()])
    .finally(() => {
      connectSSE();
      if (window.lucide) lucide.createIcons();
    });
});

function initDynamicEndpoints() {
  const origin = window.location.origin;
  const teleUrl = `${origin}/api/v1/telemetry`;
  const whUrl = `${origin}/api/v1/webhook/discord`;
  const elTele = document.getElementById("telemetryEndpointUrl");
  const elWh = document.getElementById("inboundWebhookUrl");
  const dl = document.getElementById("btnDownloadScript");
  if (elTele) elTele.textContent = teleUrl;
  if (elWh) elWh.textContent = whUrl;
  if (dl) dl.href = `/api/v1/connector/script.lua?endpoint=${encodeURIComponent(teleUrl)}`;
}

function switchTab(tabName) {
  activeTab = tabName;
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabName);
  });
  document.querySelectorAll(".view-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `view-${tabName}`);
  });
  if (tabName === "secrets") {
    loadSecretsVault();
  } else if (tabName === "hatches") {
    loadHatches();
  } else if (tabName === "connector") {
    loadInspectorReports();
  } else if (tabName === "history" && activeUserId) {
    loadHistory(activeUserId);
  }
}

// --- Chart ---

function initChart() {
  const canvas = document.getElementById("tpsChart");
  if (!canvas || typeof Chart === "undefined") return;
  const ctx = canvas.getContext("2d");
  const gradient = ctx.createLinearGradient(0, 0, 0, 260);
  gradient.addColorStop(0, "rgba(0, 242, 254, 0.28)");
  gradient.addColorStop(1, "rgba(0, 242, 254, 0.0)");

  tpsChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartTimeLabels,
      datasets: [
        {
          label: "Real-time TPS",
          data: chartTpsData,
          borderColor: "#00f2fe",
          backgroundColor: gradient,
          fill: true,
          tension: 0.35,
          borderWidth: 2.2,
          pointRadius: 1.5,
          pointHoverRadius: 5,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      scales: {
        x: {
          grid: { color: "rgba(255, 255, 255, 0.04)" },
          ticks: { color: "#64748b", font: { size: 10 } },
        },
        y: {
          grid: { color: "rgba(255, 255, 255, 0.05)" },
          ticks: { color: "#94a3b8" },
          suggestedMin: 0,
          suggestedMax: 50,
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0c1220",
          borderColor: "rgba(0, 242, 254, 0.35)",
          borderWidth: 1,
          padding: 10,
        },
      },
    },
  });
}

function updateChart(tps) {
  chartTimeLabels.push(new Date().toLocaleTimeString());
  chartTpsData.push(Number(tps || 0));
  if (chartTimeLabels.length > maxChartPoints) {
    chartTimeLabels.shift();
    chartTpsData.shift();
  }
  if (tpsChart) tpsChart.update();
}

// --- Farm Overview KPI Strip ---

async function loadOverview() {
  try {
    const ov = await apiFetch("/api/v1/overview");
    renderOverview(ov);
  } catch (_) {}
}

function renderOverview(ov) {
  if (!ov) return;
  const elOnline = document.getElementById("farmAccountsOnline");
  const elBreak = document.getElementById("farmAccountsBreakdown");
  const elSec = document.getElementById("farmTotalSecrets");
  const elVarPills = document.getElementById("farmSecretVariants");
  const elTps = document.getElementById("farmTotalTps");
  const elTaps = document.getElementById("farmTotalTaps");
  const elCurr = document.getElementById("farmTotalCurrency");
  const elEggs = document.getElementById("farmTotalEggs");
  const elEggsHr = document.getElementById("farmEggsPerHour");
  const tabSecBadge = document.getElementById("tabSecretBadge");
  const tabAccBadge = document.getElementById("tabAccBadge");

  if (elOnline) elOnline.textContent = `${ov.live_accounts || 0} / ${ov.total_accounts || 0}`;
  if (elBreak) {
    elBreak.textContent = `Stale: ${ov.stale_accounts || 0} • Off: ${ov.disconnected_accounts || 0} • Paused: ${ov.paused_accounts || 0}`;
  }
  if (elSec) elSec.textContent = formatNumber(ov.total_secrets || 0);
  if (tabSecBadge) tabSecBadge.textContent = formatCompact(ov.total_secrets || 0);
  if (tabAccBadge) tabAccBadge.textContent = String(ov.total_accounts || 0);

  if (elVarPills) {
    const entries = Object.entries(ov.by_variant || {});
    if (entries.length === 0) {
      elVarPills.innerHTML = `<span class="mini-pill">${ov.unique_secret_species || 0} types</span>`;
    } else {
      elVarPills.innerHTML = entries
        .slice(0, 4)
        .map(([variant, cnt]) => `<span class="mini-pill">${escapeHtml(variant)}: ${formatNumber(cnt)}</span>`)
        .join("");
    }
  }
  if (elTps) elTps.textContent = Number(ov.total_tps || 0).toFixed(1);
  if (elTaps) elTaps.textContent = formatCompact(ov.total_current_taps || 0);
  if (elCurr) {
    elCurr.textContent = `Currency: ${formatCompact(ov.total_currency || 0)} • Rebirths: ${formatCompact(ov.total_rebirths || 0)}`;
  }
  if (elEggs) elEggs.textContent = formatCompact(ov.total_eggs_hatched || 0);
  if (elEggsHr) elEggsHr.textContent = `${formatCompact(ov.eggs_per_hour || 0)} eggs/hr`;
}

// --- Accounts & Active Dashboard ---

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
  const vaultSelect = document.getElementById("secretAccountFilter");
  if (!select) return;
  select.innerHTML = "";
  if (accounts.length === 0) {
    select.innerHTML = `<option value="">No Accounts Tracked</option>`;
  } else {
    accounts.forEach((acc) => {
      const opt = document.createElement("option");
      opt.value = acc.user_id;
      opt.textContent = `${acc.username} (${acc.user_id})`;
      if (acc.user_id === activeUserId) opt.selected = true;
      select.appendChild(opt);
    });
  }

  if (vaultSelect) {
    const prevVal = vaultSelect.value;
    vaultSelect.innerHTML = `<option value="">All Accounts</option>`;
    accounts.forEach((acc) => {
      const opt = document.createElement("option");
      opt.value = acc.user_id;
      opt.textContent = `${acc.username} (${acc.secret_count || 0} Secrets)`;
      if (String(acc.user_id) === prevVal) opt.selected = true;
      vaultSelect.appendChild(opt);
    });
  }
}

function setActiveAccount(userId) {
  if (!userId) return;
  activeUserId = Number(userId);
  const select = document.getElementById("accountSelect");
  if (select) select.value = String(activeUserId);
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

  const statusLower = String(data.connection_status || "IDLE").toLowerCase();
  const statusBadge = document.getElementById("connectionStatusBadge");
  if (statusBadge) statusBadge.className = `status-badge ${statusLower}`;
  document.getElementById("statusText").textContent = data.connection_status || "IDLE";

  const btnToggle = document.getElementById("btnToggleTracking");
  if (data.is_tracking) {
    btnToggle.className = "btn btn-toggle-tracking active";
    btnToggle.innerHTML = `<i data-lucide="pause" style="width:15px;height:15px;"></i> Pause Tracking`;
  } else {
    btnToggle.className = "btn btn-toggle-tracking paused";
    btnToggle.innerHTML = `<i data-lucide="play" style="width:15px;height:15px;"></i> Resume Tracking`;
  }

  const fallbackAvatar = `https://www.roblox.com/headshot-thumbnail/image?userId=${encodeURIComponent(data.user_id)}&width=150&height=150&format=png`;
  document.getElementById("playerAvatar").src = safeImageUrl(data.avatar_url, fallbackAvatar);
  document.getElementById("playerName").textContent = data.display_name || data.username || `Player_${data.user_id}`;
  document.getElementById("playerUserId").textContent = `@${data.username} (ID: ${data.user_id})`;
  document.getElementById("playerWorld").textContent = data.world || "Unknown";
  document.getElementById("playerClientBadge").textContent = (data.client_source || "telemetry").toUpperCase();
  document.getElementById("sessionDuration").textContent = formatDuration(data.session_duration_sec);

  renderBoosts(data.active_boosts || []);

  document.getElementById("statTps").textContent = Number(data.tps || 0).toFixed(1);
  document.getElementById("statMaxTps").textContent = `Max: ${Number(data.max_tps || 0).toFixed(1)} | Avg: ${Number(data.avg_tps || 0).toFixed(1)}`;
  document.getElementById("statSecrets").textContent = formatNumber(data.secret_count || 0);
  document.getElementById("statSecretsSub").textContent = `${(data.secret_pets || []).length} distinct Secret variants`;
  document.getElementById("statCurrentTaps").textContent = formatNumber(data.current_taps || 0);
  document.getElementById("statTotalTaps").textContent = formatNumber(data.total_taps || 0);
  document.getElementById("statCurrentRebirths").textContent = formatNumber(data.current_rebirths || 0);
  document.getElementById("statWins").textContent = formatNumber(data.current_wins || 0);
  document.getElementById("statCurrency").textContent = formatNumber(data.current_currency || 0);
  document.getElementById("statEggsHatched").textContent = formatNumber(data.eggs_hatched || 0);
  document.getElementById("statEggsRate").textContent = `${formatCompact(data.eggs_per_hour || 0)} eggs/hr`;

  const windows = data.rates || {};
  const w1m = windows["1m"] || { taps_gained: 0, currency_gained: 0, tps: 0 };
  const w5m = windows["5m"] || { taps_gained: 0, currency_gained: 0, tps: 0 };
  const w15m = windows["15m"] || { taps_gained: 0, currency_gained: 0, tps: 0 };

  document.getElementById("growth1mTaps").textContent = `+${formatNumber(w1m.taps_gained)}`;
  document.getElementById("growth1mCurrency").textContent = `+${formatCompact(w1m.currency_gained)}`;
  document.getElementById("growth1mTps").textContent = `${Number(w1m.tps || 0).toFixed(1)} TPS`;

  document.getElementById("growth5mTaps").textContent = `+${formatNumber(w5m.taps_gained)}`;
  document.getElementById("growth5mCurrency").textContent = `+${formatCompact(w5m.currency_gained)}`;
  document.getElementById("growth5mTps").textContent = `${Number(w5m.tps || 0).toFixed(1)} TPS`;

  document.getElementById("growth15mTaps").textContent = `+${formatNumber(w15m.taps_gained)}`;
  document.getElementById("growth15mCurrency").textContent = `+${formatCompact(w15m.currency_gained)}`;
  document.getElementById("growth15mTps").textContent = `${Number(w15m.tps || 0).toFixed(1)} TPS`;

  renderOverviewSecrets(data.secret_pets || []);
  renderPets(data.equipped_pets || [], data.total_pet_power || 0, data.pet_inventory_count || 0);
  updateChart(data.tps || 0);

  if (window.lucide) lucide.createIcons();
}

function renderBoosts(boosts) {
  const container = document.getElementById("activeBoostsList");
  if (!container) return;
  if (!boosts || boosts.length === 0) {
    container.innerHTML = `<span class="boost-empty">No active boosts</span>`;
    return;
  }
  container.innerHTML = boosts
    .map((b) => {
      const rem = b.remainingSec > 0 ? formatDuration(b.remainingSec) : "Active";
      const mult = b.multiplier ? ` (${escapeHtml(b.multiplier)})` : "";
      return `<span class="boost-chip">${escapeHtml(b.name)}${mult} &bull; <span class="mono">${escapeHtml(rem)}</span></span>`;
    })
    .join("");
}

function renderOverviewSecrets(secretPets) {
  const container = document.getElementById("overviewSecretsGrid");
  if (!container) return;
  if (!secretPets || secretPets.length === 0) {
    container.innerHTML = `<div class="empty-state">No Secret pets synced for this account yet. Open Pet Inventory in-game or run telemetry feeder.</div>`;
    return;
  }
  container.innerHTML = secretPets
    .map((sp) => {
      const vClass = variantThemeClass(sp.variant);
      const vbClass = variantBadgeClass(sp.variant);
      const img = safeImageUrl(sp.image_url);
      return `
        <div class="secret-card ${vClass}" data-slug="${escapeHtml(sp.slug)}" data-pet-key="${escapeHtml(sp.pet_key)}">
          <span class="secret-count-pill mono">&times;${formatNumber(sp.count)}</span>
          <div class="secret-card-top">
            <div class="pet-portrait-frame ${vClass}">
              <img src="${escapeHtml(img)}" alt="${escapeHtml(sp.name)}" loading="lazy" />
            </div>
            <div class="secret-info">
              <div class="secret-badges-row">
                <span class="tier-badge">${escapeHtml(sp.tier || "Secret")}</span>
                <span class="variant-badge ${vbClass}">${escapeHtml(sp.variant || "Normal")}</span>
              </div>
              <div class="secret-pet-name">${escapeHtml(sp.name)}</div>
              <div class="secret-egg-sub">${escapeHtml(sp.egg_source || "Secret Pool")}</div>
            </div>
          </div>
          <div class="secret-metrics-row">
            <span>Mult: <strong>${formatCompact(sp.multiplier)}x</strong></span>
            <span>Power: <strong>+${formatCompact(sp.power)}</strong></span>
          </div>
        </div>`;
    })
    .join("");
}

function renderPets(pets, totalPower, invCount) {
  const container = document.getElementById("petsGrid");
  const powerLabel = document.getElementById("totalPetPower");
  if (powerLabel) {
    powerLabel.textContent = `Total Power: ${formatCompact(totalPower)} (${formatNumber(invCount)} stored)`;
  }
  if (!container) return;
  if (!pets || pets.length === 0) {
    container.innerHTML = `<div class="empty-state">No pets equipped</div>`;
    return;
  }
  container.innerHTML = pets
    .map((p) => {
      const rarity = escapeHtml(p.rarity || "Common");
      const img = safeImageUrl(p.image_url);
      return `
        <div class="pet-card">
          <div class="pet-card-head">
            <img class="pet-mini-img" src="${escapeHtml(img)}" alt="${escapeHtml(p.name)}" loading="lazy" />
            <div style="min-width:0;">
              <div class="pet-rarity-badge rarity-${rarity}">${rarity}</div>
              <div class="pet-name">${escapeHtml(p.name || "Unknown Pet")}</div>
            </div>
          </div>
          <div class="pet-stat-row"><span>Variant</span><span>${escapeHtml(p.variant || "Normal")}</span></div>
          <div class="pet-stat-row"><span>Multiplier</span><span>${formatCompact(p.multiplier)}x</span></div>
          <div class="pet-stat-row"><span>Pet Power</span><span>+${formatCompact(p.power)}</span></div>
        </div>`;
    })
    .join("");
}

// --- Secret Vault & Per-Secret Image Gallery ---

async function loadSecretsVault() {
  try {
    const params = new URLSearchParams();
    const accVal = document.getElementById("secretAccountFilter")?.value;
    const tierVal = document.getElementById("secretTierFilter")?.value;
    const qVal = document.getElementById("secretSearchInput")?.value?.trim();
    if (accVal) params.set("user_id", accVal);
    if (vaultVariantFilter && vaultVariantFilter !== "all") params.set("variant", vaultVariantFilter);
    if (tierVal && tierVal !== "all") params.set("tier", tierVal);
    if (qVal) params.set("q", qVal);

    secretsPayload = await apiFetch(`/api/v1/secrets?${params.toString()}`);
    renderSecretVault();
  } catch (e) {
    console.error("Failed to load secrets vault:", e);
  }
}

async function loadPetCatalog() {
  try {
    const allItems = await apiFetch("/api/v1/pets/catalog");
    petCatalogList = (allItems || []).filter((item) => (item.rarity || "Secret").toLowerCase() === "secret");
    const cntEl = document.getElementById("catalogSecretCount");
    if (cntEl) cntEl.textContent = String(petCatalogList.length);
    if (vaultMode === "catalog") renderSecretVault();
  } catch (_) {}
}

function renderSecretVault() {
  const summaryBar = document.getElementById("vaultSummaryBar");
  const grid = document.getElementById("secretVaultGrid");
  if (!grid) return;

  if (summaryBar) {
    const variantsHtml = Object.entries(secretsPayload.by_variant || {})
      .map(([v, c]) => `<div class="vault-summary-chip"><span>${escapeHtml(v)}</span><strong class="mono">${formatNumber(c)}</strong></div>`)
      .join("");
    summaryBar.innerHTML = `
      <div class="vault-summary-chip"><span>Total Secrets</span><strong class="mono highlight-secret">${formatNumber(secretsPayload.total_secrets || 0)}</strong></div>
      <div class="vault-summary-chip"><span>Unique Variants</span><strong class="mono">${formatNumber(secretsPayload.unique_types || 0)}</strong></div>
      ${variantsHtml}`;
  }

  if (vaultMode === "catalog") {
    const q = (document.getElementById("secretSearchInput")?.value || "").trim().toLowerCase();
    const tierVal = (document.getElementById("secretTierFilter")?.value || "all").toLowerCase();
    const ownedBySlug = {};
    (secretsPayload.grouped || []).forEach((g) => {
      ownedBySlug[g.slug] = (ownedBySlug[g.slug] || 0) + g.total_count;
    });

    const filteredCat = petCatalogList.filter((item) => {
      if (tierVal !== "all" && (item.tier || "").toLowerCase() !== tierVal) return false;
      if (q && !`${item.name} ${item.default_egg || ""} ${item.tier || ""}`.toLowerCase().includes(q)) return false;
      return true;
    });

    if (filteredCat.length === 0) {
      grid.innerHTML = `<div class="empty-state">No catalog Secrets match your filter.</div>`;
      return;
    }

    grid.innerHTML = filteredCat
      .map((item) => {
        const owned = ownedBySlug[item.slug] || 0;
        const img = safeImageUrl(item.image_url);
        return `
          <div class="secret-card variant-normal" data-catalog-slug="${escapeHtml(item.slug)}">
            <span class="secret-count-pill mono ${owned === 0 ? "zero" : ""}">&times;${formatNumber(owned)}</span>
            <div class="secret-card-top">
              <div class="pet-portrait-frame variant-normal">
                <img src="${escapeHtml(img)}" alt="${escapeHtml(item.name)}" loading="lazy" />
              </div>
              <div class="secret-info">
                <div class="secret-badges-row">
                  <span class="tier-badge">${escapeHtml(item.tier || "Secret")}</span>
                  <span class="variant-badge vb-normal">${escapeHtml(item.odds || "Rare")}</span>
                </div>
                <div class="secret-pet-name">${escapeHtml(item.name)}</div>
                <div class="secret-egg-sub">${escapeHtml(item.default_egg || "Secret Pool")}</div>
              </div>
            </div>
            <div class="secret-metrics-row">
              <span>Status: <strong>${owned > 0 ? "Owned" : "Not Hatched Yet"}</strong></span>
              <span>Click to customize image</span>
            </div>
          </div>`;
      })
      .join("");
    return;
  }

  let items = [...(secretsPayload.grouped || [])];
  const sortBy = document.getElementById("secretSortSelect")?.value || "count";
  if (sortBy === "power") items.sort((a, b) => (b.max_power || 0) - (a.max_power || 0));
  else if (sortBy === "multiplier") items.sort((a, b) => (b.max_multiplier || 0) - (a.max_multiplier || 0));
  else if (sortBy === "name") items.sort((a, b) => a.name.localeCompare(b.name));
  else items.sort((a, b) => (b.total_count || 0) - (a.total_count || 0));

  if (items.length === 0) {
    grid.innerHTML = `<div class="empty-state">No Secret pets match your filter yet. Switch to "All 18 Catalog Secrets" to browse portraits, or stream telemetry from the game/feeder.</div>`;
    return;
  }

  grid.innerHTML = items
    .map((g) => {
      const vClass = variantThemeClass(g.variant);
      const vbClass = variantBadgeClass(g.variant);
      const img = safeImageUrl(g.image_url);
      const ownersHtml = (g.owners || [])
        .map(
          (o) =>
            `<span class="owner-chip" data-owner-uid="${Number(o.user_id)}">@${escapeHtml(o.username)} &times;${formatNumber(o.count)}</span>`
        )
        .join("");

      return `
        <div class="secret-card ${vClass}" data-slug="${escapeHtml(g.slug)}" data-pet-key="${escapeHtml(g.pet_key)}">
          <span class="secret-count-pill mono">&times;${formatNumber(g.total_count)}</span>
          <div class="secret-card-top">
            <div class="pet-portrait-frame ${vClass}">
              <img src="${escapeHtml(img)}" alt="${escapeHtml(g.name)}" loading="lazy" />
            </div>
            <div class="secret-info">
              <div class="secret-badges-row">
                <span class="tier-badge">${escapeHtml(g.tier || "Secret")}</span>
                <span class="variant-badge ${vbClass}">${escapeHtml(g.variant || "Normal")}</span>
              </div>
              <div class="secret-pet-name">${escapeHtml(g.name)}</div>
              <div class="secret-egg-sub">${escapeHtml(g.egg_source || "Secret Pool")}${g.odds ? ` &bull; ${escapeHtml(g.odds)}` : ""}</div>
            </div>
          </div>
          <div class="secret-metrics-row">
            <span>Mult: <strong>${formatCompact(g.max_multiplier)}x</strong></span>
            <span>Power: <strong>+${formatCompact(g.max_power)}</strong></span>
          </div>
          <div class="secret-owners-row">${ownersHtml}</div>
        </div>`;
    })
    .join("");
}

async function openSecretDetailModal(slug, petKey) {
  const modal = document.getElementById("secretDetailModal");
  if (!modal) return;

  let unfilteredSecrets = secretsPayload;
  try {
    unfilteredSecrets = await apiFetch("/api/v1/secrets");
  } catch (_) {}

  if (!petCatalogList.find((c) => c.slug === slug)) {
    await loadPetCatalog();
  }

  const grouped = (unfilteredSecrets.grouped || []).find((g) => g.pet_key === petKey) ||
    (unfilteredSecrets.grouped || []).find((g) => g.slug === slug);
  const catalogItem = petCatalogList.find((c) => c.slug === slug);

  const name = grouped?.name || catalogItem?.name || slug;
  const variant = grouped?.variant || "Normal";
  const tier = grouped?.tier || catalogItem?.tier || "Secret";
  const egg = grouped?.egg_source || catalogItem?.default_egg || "Secret Pool";
  const odds = grouped?.odds || catalogItem?.odds || "Unknown";
  const imgUrl = safeImageUrl(grouped?.image_url || catalogItem?.image_url);
  const vClass = variantThemeClass(variant);
  const vbClass = variantBadgeClass(variant);

  document.getElementById("secretModalTitle").textContent = `${name} — Secret Pet Profile`;
  const frame = document.getElementById("secretModalAvatarFrame");
  frame.className = `pet-portrait-frame ${vClass} lg`;
  document.getElementById("secretModalImage").src = imgUrl;
  document.getElementById("secretModalBadges").innerHTML = `
    <span class="tier-badge">${escapeHtml(tier)}</span>
    <span class="variant-badge ${vbClass}">${escapeHtml(variant)}</span>`;
  document.getElementById("secretModalStats").innerHTML = `
    <div>Total Owned Across Farm: <strong class="mono">${formatNumber(grouped?.total_count || 0)}</strong></div>
    <div>Egg Source: <strong>${escapeHtml(egg)}</strong> (${escapeHtml(odds)})</div>
    <div>Max Multiplier: <strong class="mono">${formatCompact(grouped?.max_multiplier || 0)}x</strong> &bull; Max Power: <strong class="mono">+${formatCompact(grouped?.max_power || 0)}</strong></div>`;

  const ownersWrap = document.getElementById("secretModalOwners");
  if (grouped && grouped.owners && grouped.owners.length > 0) {
    ownersWrap.innerHTML = grouped.owners
      .map(
        (o) => `
          <div class="owner-row-item">
            <span><strong>@${escapeHtml(o.username)}</strong> (ID: ${Number(o.user_id)}) ${o.is_equipped ? '<span class="mini-pill">Equipped</span>' : ""}</span>
            <strong class="mono highlight-secret">&times;${formatNumber(o.count)}</strong>
          </div>`
      )
      .join("");
  } else {
    ownersWrap.innerHTML = `<div class="empty-state" style="padding:10px;">No tracked account currently holds this Secret.</div>`;
  }

  document.getElementById("overridePetSlug").value = slug;
  document.getElementById("inputCustomImageUrl").value = catalogItem?.custom_image_url || "";
  document.getElementById("inputCustomAssetId").value = catalogItem?.image_asset_id || "";

  modal.classList.add("open");
}

// --- Live Hatch Feed & Discord Settings ---

async function loadHatches() {
  try {
    const rarity = document.getElementById("hatchRarityFilter")?.value || "";
    const qs = rarity ? `?limit=60&rarity=${encodeURIComponent(rarity)}` : "?limit=60";
    const rows = await apiFetch(`/api/v1/hatches${qs}`);
    recentHatchesList = rows;
    if (!hatchesHydrated) {
      lastSeenHatchId = rows.length > 0 ? (rows[0].id || 0) : 0;
      hatchesHydrated = true;
    }
    renderHatchFeeds(rows);
  } catch (_) {}
}

function renderHatchFeeds(rows) {
  const mini = document.getElementById("miniHatchFeed");
  const full = document.getElementById("fullHatchFeedList");
  const renderRows = (list) => {
    if (!list || list.length === 0) {
      return `<div class="empty-state">No hatch events recorded yet.</div>`;
    }
    return list
      .map((h) => {
        const isSec = String(h.rarity || "").toLowerCase() === "secret";
        const vbClass = variantBadgeClass(h.variant);
        const img = safeImageUrl(h.image_url);
        const actor = h.username || h.actor_name || "Unknown";
        return `
          <div class="hatch-row ${isSec ? "is-secret" : ""}">
            <img class="hatch-thumb" src="${escapeHtml(img)}" alt="${escapeHtml(h.pet_name)}" loading="lazy" />
            <div class="hatch-main">
              <div class="hatch-title">
                <span class="pet-rarity-badge rarity-${escapeHtml(h.rarity || "Secret")}">${escapeHtml(h.rarity || "Secret")}</span>
                <span class="variant-badge ${vbClass}">${escapeHtml(h.variant || "Normal")}</span>
                <span>${escapeHtml(h.pet_name)}</span>
              </div>
              <div class="hatch-sub">
                <strong>@${escapeHtml(actor)}</strong>
                ${h.egg_name ? ` &bull; ${escapeHtml(h.egg_name)}` : ""}
                ${h.odds ? ` (${escapeHtml(h.odds)})` : ""}
                &bull; <span style="opacity:0.75;">${escapeHtml(h.source || "telemetry")}</span>
              </div>
            </div>
            <div class="hatch-time mono">${escapeHtml(formatShortTime(h.timestamp))}</div>
          </div>`;
      })
      .join("");
  };
  if (mini) mini.innerHTML = renderRows((rows || []).slice(0, 6));
  if (full) full.innerHTML = renderRows(rows || []);
}

async function loadAlertSettings() {
  try {
    const cfg = await apiFetch("/api/v1/settings/alerts");
    document.getElementById("inputWebhookUrl").value = cfg.webhookUrl || "";
    document.getElementById("chkAlertsEnabled").checked = Boolean(cfg.enabled);
    document.getElementById("chkNotifySecret").checked = Boolean(cfg.notifySecretHatch);
    document.getElementById("chkNotifyDisconnect").checked = Boolean(cfg.notifyDisconnect);
    document.getElementById("chkNotifyStale").checked = Boolean(cfg.notifyStale);
    document.getElementById("chkForwardInbound").checked = Boolean(cfg.forwardInboundWebhook);
    const pill = document.getElementById("webhookStatusPill");
    if (pill) {
      pill.textContent = cfg.hasWebhookUrl ? (cfg.enabled ? "Active" : "Saved (Disabled)") : "Not Configured";
    }
  } catch (_) {}
}

// --- Multi-Account Matrix ---

function renderMultiAccountsTable(accounts) {
  const tbody = document.getElementById("multiAccountsTableBody");
  if (!tbody) return;
  const search = (document.getElementById("accountSearchInput")?.value || "").trim().toLowerCase();
  const statusFilter = document.getElementById("accountStatusFilter")?.value || "all";

  const filtered = (accounts || []).filter((a) => {
    const st = (a.connection_status || "IDLE").toUpperCase();
    if (statusFilter !== "all" && st !== statusFilter) return false;
    if (search) {
      const hay = `${a.username || ""} ${a.display_name || ""} ${a.user_id} ${a.world || ""}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-cell">No matching accounts. Click "+ Add Account" or connect telemetry.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered
    .map((a) => {
      const statusStr = String(a.connection_status || "IDLE");
      const statusClass = statusStr.toLowerCase();
      const avatar = safeImageUrl(
        a.avatar_url,
        `https://www.roblox.com/headshot-thumbnail/image?userId=${encodeURIComponent(a.user_id)}&width=150&height=150&format=png`
      );
      const topSec = (a.top_secrets || a.secret_pets || []).slice(0, 3);
      const miniIcons = topSec
        .map((s) => `<img src="${escapeHtml(safeImageUrl(s.image_url))}" title="${escapeHtml(`${s.variant} ${s.name} x${s.count}`)}" alt="${escapeHtml(s.name)}" />`)
        .join("");

      return `
        <tr>
          <td>
            <div style="display:flex; align-items:center; gap:9px;">
              <img src="${escapeHtml(avatar)}" style="width:30px;height:30px;border-radius:50%;background:#1e293b;object-fit:cover;" alt="" />
              <div>
                <div style="font-weight:700;color:var(--text-main);">${escapeHtml(a.username)}</div>
                <div style="font-size:0.72rem;color:var(--text-dim);">ID: ${Number(a.user_id)}</div>
              </div>
            </div>
          </td>
          <td><span class="status-badge ${escapeHtml(statusClass)}"><span class="status-dot"></span>${escapeHtml(statusStr)}</span></td>
          <td>${escapeHtml(a.world || "--")}</td>
          <td>
            <div class="mini-secret-stack">
              <strong class="mono highlight-secret">${formatNumber(a.secret_count || 0)}</strong>
              <span class="mini-secret-icons">${miniIcons}</span>
            </div>
          </td>
          <td class="mono">${formatCompact(a.current_taps || 0)}</td>
          <td class="mono highlight-green">${Number(a.tps || 0).toFixed(1)}</td>
          <td class="mono">${formatNumber(a.current_rebirths || 0)}</td>
          <td class="mono">${formatCompact(a.eggs_hatched || 0)}</td>
          <td class="mono">${formatDuration(a.session_duration_sec || 0)}</td>
          <td>
            <div style="display:flex;gap:6px;">
              <button class="btn btn-secondary btn-sm" data-action="view" data-uid="${Number(a.user_id)}">View</button>
              <button class="btn btn-danger-ghost btn-sm" data-action="delete" data-uid="${Number(a.user_id)}">Delete</button>
            </div>
          </td>
        </tr>`;
    })
    .join("");
}

// --- Session History & Inspector ---

async function loadHistory(userId) {
  if (!userId) return;
  try {
    const sessions = await apiFetch(`/api/v1/accounts/${userId}/history`);
    const tbody = document.getElementById("historyTableBody");
    if (!tbody) return;
    if (!sessions || sessions.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="empty-cell">No past sessions recorded yet.</td></tr>`;
      return;
    }
    tbody.innerHTML = sessions
      .map((s) => {
        const startStr = new Date(s.start_time * 1000).toLocaleString();
        const dur = s.end_time ? formatDuration(s.end_time - s.start_time) : "Active";
        return `
          <tr>
            <td>${escapeHtml(startStr)}</td>
            <td class="mono">${escapeHtml(dur)}</td>
            <td class="mono">+${formatNumber(s.taps_gained)}</td>
            <td class="mono">+${formatNumber(s.rebirths_gained)}</td>
            <td class="mono">${Number(s.max_tps || 0).toFixed(1)}</td>
            <td class="mono">${Number(s.avg_tps || 0).toFixed(1)}</td>
          </tr>`;
      })
      .join("");
  } catch (_) {}
}

async function loadInspectorReports() {
  const viewer = document.getElementById("inspectorDumpViewer");
  if (!viewer) return;
  try {
    const reports = await apiFetch("/api/v1/connector/inspect?limit=3");
    if (!reports || reports.length === 0) {
      viewer.innerHTML = `<div class="empty-state">No inspector dump received yet. Run the Luau script with INSPECT_ON_START = true to inspect in-game paths.</div>`;
      return;
    }
    const latest = reports[0];
    const header = `// Latest Dump — @${latest.username || latest.user_id} (Place: ${latest.place_id || "?"}) @ ${new Date(latest.created_at * 1000).toLocaleTimeString()}\n`;
    viewer.innerHTML = `<pre>${escapeHtml(header + JSON.stringify(latest.structure, null, 2))}</pre>`;
  } catch (_) {}
}

// --- SSE Live Stream (supports v2 envelope & v1 array) ---

function connectSSE() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/api/v1/stream");

  eventSource.onmessage = (event) => {
    try {
      const payload = JSON.parse(event.data);
      const accounts = Array.isArray(payload) ? payload : payload.accounts || [];
      accountsList = accounts;

      if (!Array.isArray(payload) && payload.overview) {
        renderOverview(payload.overview);
      }

      if (accounts.length > 0 && !activeUserId) {
        setActiveAccount(accounts[0].user_id);
      }
      renderAccountDropdown(accounts);
      renderMultiAccountsTable(accounts);

      const activeData = accounts.find((p) => p.user_id === activeUserId);
      if (activeData) renderDashboard(activeData);

      if (!Array.isArray(payload) && Array.isArray(payload.recent_hatches)) {
        const newest = payload.recent_hatches[0];
        if (!hatchesHydrated) {
          lastSeenHatchId = newest && newest.id ? newest.id : 0;
          hatchesHydrated = true;
        } else if (newest && newest.id && newest.id > lastSeenHatchId) {
          lastSeenHatchId = newest.id;
          if (String(newest.rarity || "").toLowerCase() === "secret") {
            showToast(`✨ SECRET HATCHED: ${newest.variant} ${newest.pet_name} (@${newest.username || "Player"})`, "secret");
            if (soundEnabled) playSecretChime();
            loadSecretsVault();
          }
        }
        recentHatchesList = payload.recent_hatches;
        const rarityFilter = document.getElementById("hatchRarityFilter")?.value || "";
        const filteredHatches = rarityFilter
          ? recentHatchesList.filter((h) => String(h.rarity || "").toLowerCase() === rarityFilter.toLowerCase())
          : recentHatchesList;
        renderHatchFeeds(filteredHatches);
      }
    } catch (e) {
      console.error("SSE parse error:", e);
    }
  };
}

// --- Event Listeners ---

function setupEventListeners() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.getElementById("kpiSecretShortcut")?.addEventListener("click", () => switchTab("secrets"));
  document.getElementById("btnJumpToVault")?.addEventListener("click", () => switchTab("secrets"));
  document.getElementById("btnJumpToHatches")?.addEventListener("click", () => switchTab("hatches"));

  document.getElementById("accountSelect")?.addEventListener("change", (e) => setActiveAccount(e.target.value));

  document.getElementById("btnSoundToggle")?.addEventListener("click", (e) => {
    soundEnabled = !soundEnabled;
    e.currentTarget.classList.toggle("sound-on", soundEnabled);
    showToast(soundEnabled ? "Secret hatch chime enabled" : "Secret hatch chime muted");
    if (soundEnabled) playSecretChime();
  });

  document.getElementById("btnTestSound")?.addEventListener("click", () => {
    playSecretChime();
    showToast("Playing Secret hatch chime!", "secret");
  });

  document.getElementById("btnToggleTracking")?.addEventListener("click", async () => {
    if (!activeUserId) return;
    const acc = accountsList.find((a) => a.user_id === activeUserId);
    const newState = acc ? !acc.is_tracking : false;
    await apiFetch(`/api/v1/accounts/${activeUserId}/tracking`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_tracking: newState }),
    });
    await loadAccounts();
    await loadLiveState(activeUserId);
  });

  // Add Account Modal
  const addModal = document.getElementById("addAccountModal");
  document.getElementById("btnAddAccount")?.addEventListener("click", () => addModal.classList.add("open"));
  document.getElementById("btnCloseAddModal")?.addEventListener("click", () => addModal.classList.remove("open"));
  document.getElementById("btnCancelAddModal")?.addEventListener("click", () => addModal.classList.remove("open"));

  document.getElementById("formAddAccount")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = document.getElementById("inputUserId");
    const uid = Number(input.value.trim());
    if (!uid) return;
    try {
      await apiFetch("/api/v1/accounts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ userId: uid }),
      });
      input.value = "";
      addModal.classList.remove("open");
      await loadAccounts();
      setActiveAccount(uid);
      showToast(`Added Roblox account ${uid}`);
    } catch (err) {
      showToast("Error adding account: " + err.message, "error");
    }
  });

  // Secret Vault filters & mode
  document.getElementById("btnVaultModeOwned")?.addEventListener("click", (e) => {
    vaultMode = "owned";
    e.currentTarget.classList.add("active");
    document.getElementById("btnVaultModeCatalog")?.classList.remove("active");
    renderSecretVault();
  });
  document.getElementById("btnVaultModeCatalog")?.addEventListener("click", (e) => {
    vaultMode = "catalog";
    e.currentTarget.classList.add("active");
    document.getElementById("btnVaultModeOwned")?.classList.remove("active");
    loadPetCatalog().then(renderSecretVault);
  });

  document.querySelectorAll("#variantFilterPills .pill-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#variantFilterPills .pill-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      vaultVariantFilter = btn.dataset.variant || "all";
      loadSecretsVault();
    });
  });

  document.getElementById("secretSearchInput")?.addEventListener("input", () => {
    if (vaultMode === "catalog") renderSecretVault();
    else loadSecretsVault();
  });
  document.getElementById("secretAccountFilter")?.addEventListener("change", () => loadSecretsVault());
  document.getElementById("secretTierFilter")?.addEventListener("change", () => {
    if (vaultMode === "catalog") renderSecretVault();
    else loadSecretsVault();
  });
  document.getElementById("secretSortSelect")?.addEventListener("change", () => renderSecretVault());

  // Click delegation on Secret Cards (both Vault & Overview)
  const handleSecretCardClick = (e) => {
    const ownerChip = e.target.closest(".owner-chip");
    if (ownerChip && ownerChip.dataset.ownerUid) {
      e.stopPropagation();
      setActiveAccount(Number(ownerChip.dataset.ownerUid));
      switchTab("overview");
      return;
    }
    const card = e.target.closest(".secret-card");
    if (!card) return;
    const slug = card.dataset.slug || card.dataset.catalogSlug;
    const petKey = card.dataset.petKey || "";
    if (slug) openSecretDetailModal(slug, petKey);
  };
  document.getElementById("secretVaultGrid")?.addEventListener("click", handleSecretCardClick);
  document.getElementById("overviewSecretsGrid")?.addEventListener("click", handleSecretCardClick);

  // Secret Detail & Custom Image Modal
  const secretModal = document.getElementById("secretDetailModal");
  document.getElementById("btnCloseSecretModal")?.addEventListener("click", () => secretModal.classList.remove("open"));
  secretModal?.addEventListener("click", (e) => {
    if (e.target === secretModal) secretModal.classList.remove("open");
  });

  document.getElementById("formOverridePetImage")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const slug = document.getElementById("overridePetSlug").value;
    const imageUrl = document.getElementById("inputCustomImageUrl").value.trim();
    const assetRaw = document.getElementById("inputCustomAssetId").value.trim();
    const body = {};
    if (imageUrl) body.imageUrl = imageUrl;
    if (assetRaw) body.imageAssetId = assetRaw;
    try {
      const updated = await apiFetch(`/api/v1/pets/catalog/${encodeURIComponent(slug)}/image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      document.getElementById("secretModalImage").src = safeImageUrl(updated.image_url);
      await Promise.all([loadPetCatalog(), loadSecretsVault()]);
      if (activeUserId) await loadLiveState(activeUserId);
      showToast(`Updated image for ${updated.name}`);
    } catch (err) {
      showToast("Failed to update pet image: " + err.message, "error");
    }
  });

  document.getElementById("btnResetPetImage")?.addEventListener("click", async () => {
    const slug = document.getElementById("overridePetSlug").value;
    try {
      const updated = await apiFetch(`/api/v1/pets/catalog/${encodeURIComponent(slug)}/image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ imageUrl: "" }),
      });
      document.getElementById("inputCustomImageUrl").value = "";
      document.getElementById("secretModalImage").src = safeImageUrl(updated.image_url);
      await Promise.all([loadPetCatalog(), loadSecretsVault()]);
      if (activeUserId) await loadLiveState(activeUserId);
      showToast(`Reset ${updated.name} to default portrait`);
    } catch (err) {
      showToast("Reset failed: " + err.message, "error");
    }
  });

  // Hatch feed filter & Discord Settings
  document.getElementById("hatchRarityFilter")?.addEventListener("change", () => loadHatches());

  document.getElementById("discordWebhookForm")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await apiFetch("/api/v1/settings/alerts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          webhookUrl: document.getElementById("inputWebhookUrl").value.trim(),
          enabled: document.getElementById("chkAlertsEnabled").checked,
          notifySecretHatch: document.getElementById("chkNotifySecret").checked,
          notifyDisconnect: document.getElementById("chkNotifyDisconnect").checked,
          notifyStale: document.getElementById("chkNotifyStale").checked,
          forwardInboundWebhook: document.getElementById("chkForwardInbound").checked,
        }),
      });
      document.getElementById("inputWebhookUrl").value = res.webhookUrl || "";
      await loadAlertSettings();
      showToast("Discord alert settings saved");
    } catch (err) {
      showToast("Failed to save alerts: " + err.message, "error");
    }
  });

  document.getElementById("btnTestWebhook")?.addEventListener("click", async () => {
    try {
      const res = await apiFetch("/api/v1/settings/alerts/test", { method: "POST" });
      showToast(res.ok ? "Test alert sent to Discord!" : res.detail || "Webhook test failed", res.ok ? "info" : "error");
    } catch (err) {
      showToast("Webhook test failed: " + err.message, "error");
    }
  });

  document.getElementById("btnClearWebhook")?.addEventListener("click", async () => {
    await apiFetch("/api/v1/settings/alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clearWebhook: true, enabled: false }),
    });
    await loadAlertSettings();
    showToast("Discord Webhook URL cleared");
  });

  // Multi-Account Matrix controls & event delegation
  document.getElementById("accountSearchInput")?.addEventListener("input", () => renderMultiAccountsTable(accountsList));
  document.getElementById("accountStatusFilter")?.addEventListener("change", () => renderMultiAccountsTable(accountsList));

  document.getElementById("multiAccountsTableBody")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const uid = Number(btn.dataset.uid);
    if (btn.dataset.action === "view") {
      setActiveAccount(uid);
      switchTab("overview");
    } else if (btn.dataset.action === "delete") {
      await deleteAccount(uid);
    }
  });

  document.getElementById("btnStartAll")?.addEventListener("click", async () => {
    await apiFetch("/api/v1/accounts/tracking/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_tracking: true }),
    });
    await loadAccounts();
    showToast("Tracking enabled for all accounts");
  });

  document.getElementById("btnPauseAll")?.addEventListener("click", async () => {
    await apiFetch("/api/v1/accounts/tracking/all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_tracking: false }),
    });
    await loadAccounts();
    showToast("Tracking paused for all accounts");
  });

  // Restore JSON Backup
  document.getElementById("inputRestoreJson")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text);
      await apiFetch("/api/v1/restore", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed),
      });
      await Promise.all([loadOverview(), loadAccounts(), loadSecretsVault(), loadHatches()]);
      showToast("Backup restored successfully");
    } catch (err) {
      showToast("Restore failed: " + err.message, "error");
    } finally {
      e.target.value = "";
    }
  });

  // Connector actions
  document.getElementById("btnCopyEndpoint")?.addEventListener("click", async () => {
    const txt = document.getElementById("telemetryEndpointUrl").textContent;
    await navigator.clipboard?.writeText(txt);
    showToast("Telemetry endpoint copied");
  });

  document.getElementById("btnCopyInboundWebhook")?.addEventListener("click", async () => {
    const txt = document.getElementById("inboundWebhookUrl").textContent;
    await navigator.clipboard?.writeText(txt);
    showToast("Inbound Webhook URL copied");
  });

  document.getElementById("btnCopyScript")?.addEventListener("click", async () => {
    try {
      const ep = document.getElementById("telemetryEndpointUrl").textContent;
      const res = await fetch(`/api/v1/connector/script.lua?endpoint=${encodeURIComponent(ep)}`);
      if (!res.ok) throw new Error("Script not available yet");
      const luaText = await res.text();
      await navigator.clipboard?.writeText(luaText);
      showToast("Copied tap_sim_reborn_tracker.lua to clipboard!");
    } catch (err) {
      showToast("Copy failed: " + err.message, "error");
    }
  });

  document.getElementById("btnRefreshInspector")?.addEventListener("click", () => {
    loadInspectorReports().then(() => showToast("Inspector dump refreshed"));
  });
}

async function deleteAccount(userId) {
  if (!confirm(`Are you sure you want to delete account ${userId}?`)) return;
  try {
    await apiFetch(`/api/v1/accounts/${userId}`, { method: "DELETE" });
    if (activeUserId === userId) activeUserId = null;
    await Promise.all([loadAccounts(), loadOverview(), loadSecretsVault()]);
    showToast(`Deleted account ${userId}`);
  } catch (e) {
    showToast("Delete failed: " + e.message, "error");
  }
}
