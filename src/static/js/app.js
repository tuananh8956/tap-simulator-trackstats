// Tap Simulator Reborn TrackStats v2 - Streamlined Secret Vault & Multi-Account SPA
let activeUserId = null;
let activeTab = "secrets";
let accountsList = [];
let secretsPayload = { total_secrets: 0, unique_types: 0, by_variant: {}, by_tier: {}, grouped: [], items: [] };
let petCatalogList = [];
let vaultMode = "owned"; // "owned" | "catalog"
let vaultVariantFilter = "all";
let lastSeenHatchId = 0;
let hatchesHydrated = false;
let lastSecretsFingerprint = "";
let authState = { auth_enabled: false, public_read: true, is_admin: true, ingest_key_required: false };
let connectorConfig = null;
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

async function apiFetch(endpoint, options = {}) {
  const res = await fetch(endpoint, options);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    if (res.status === 401 && endpoint !== "/api/v1/auth/login") {
      document.getElementById("adminAuthModal")?.classList.add("open");
    }
    throw new Error(err.detail || "API request failed");
  }
  return await res.json();
}

// --- Initialization ---

async function loadDashboardData() {
  await Promise.all([
    loadConnectorConfig(),
    loadOverview(),
    loadAccounts(),
    loadSecretsVault(),
    loadPetCatalog(),
  ]);
  connectSSE();
}

document.addEventListener("DOMContentLoaded", async () => {
  initDynamicEndpoints();
  setupEventListeners();
  await loadAuthStatus();
  if (authState.auth_enabled && !authState.public_read && !authState.is_admin) {
    const adminModal = document.getElementById("adminAuthModal");
    adminModal?.classList.add("open", "gate-locked");
  } else {
    await loadDashboardData();
  }
  if (window.lucide) lucide.createIcons();
});

function initDynamicEndpoints() {
  const origin = window.location.origin;
  const teleUrl = `${origin}/api/v1/telemetry`;
  const loaderUrl = `${origin}/loader.lua`;
  const dl = document.getElementById("btnDownloadScript");
  if (dl) dl.href = `/api/v1/connector/script.lua?endpoint=${encodeURIComponent(teleUrl)}`;
  renderExecutorLoaderSnippets(loaderUrl, "YOUR_TRACKSTATS_KEY", false, false);
}

function renderExecutorLoaderSnippets(loaderUrl, keyVal, keyRequired, isAdmin) {
  const cleanLoader = loaderUrl || `${window.location.origin}/loader.lua`;
  const effectiveKey = keyRequired ? (keyVal || "YOUR_TRACKSTATS_KEY") : (keyVal || "");
  const snippetEl = document.getElementById("executorLoaderSnippet");
  const fallbackEl = document.getElementById("executorFallbackSnippet");
  const noticeEl = document.getElementById("connectorKeyNotice");
  const noticeText = document.getElementById("connectorKeyNoticeText");
  const unlockBtn = document.getElementById("btnUnlockFromConnector");

  if (snippetEl) {
    if (effectiveKey) {
      snippetEl.textContent =
        `getgenv().TrackStats = {\n` +
        `    Key = "${effectiveKey}",\n` +
        `    Interval = 2,\n` +
        `}\n` +
        `loadstring(game:HttpGet("${cleanLoader}"))()`;
    } else {
      snippetEl.textContent =
        `getgenv().TrackStats = {\n` +
        `    Interval = 2,\n` +
        `}\n` +
        `loadstring(game:HttpGet("${cleanLoader}"))()`;
    }
  }

  if (fallbackEl) {
    const keyPart = effectiveKey ? `Key = "${effectiveKey}", ` : "";
    fallbackEl.textContent =
      `getgenv().TrackStats = { ${keyPart}Interval = 2 }\n` +
      `local req = request or http_request or (syn and syn.request)\n` +
      `loadstring(req({ Url = "${cleanLoader}", Method = "GET" }).Body)()`;
  }

  if (noticeEl && noticeText && unlockBtn) {
    if (keyRequired && !isAdmin) {
      noticeEl.className = "connector-key-banner locked";
      noticeText.textContent = "Public View-Only mode: Key is hidden from guests. Unlock Admin to auto-fill your real Ingest Key.";
      unlockBtn.style.display = "inline-flex";
    } else if (keyRequired && isAdmin && keyVal) {
      noticeEl.className = "connector-key-banner unlocked";
      noticeText.textContent = "Admin Unlocked: Your live Ingest Key is embedded in the script below — ready to copy & paste!";
      unlockBtn.style.display = "none";
    } else {
      noticeEl.className = "connector-key-banner";
      noticeText.textContent = "Copy and paste directly into your executor or autoexec folder.";
      unlockBtn.style.display = "none";
    }
  }
}

async function loadAuthStatus() {
  try {
    authState = await apiFetch("/api/v1/auth/status");
    const btn = document.getElementById("btnAdminAuth");
    const txt = document.getElementById("adminAuthText");
    const logoutBtn = document.getElementById("btnAdminLogout");
    if (btn && txt) {
      if (!authState.auth_enabled) {
        txt.textContent = "Local Admin";
        btn.classList.add("admin-pill-unlocked");
      } else if (authState.is_admin) {
        txt.textContent = "Admin Unlocked";
        btn.classList.add("admin-pill-unlocked");
      } else {
        txt.textContent = "View-Only (Unlock)";
        btn.classList.remove("admin-pill-unlocked");
      }
    }
    if (logoutBtn) {
      logoutBtn.style.display = authState.auth_enabled && authState.is_admin ? "inline-flex" : "none";
    }
    document.body.classList.toggle("guest-readonly", Boolean(authState.auth_enabled && !authState.is_admin));
  } catch (_) {}
}

async function loadConnectorConfig() {
  try {
    const cfg = await apiFetch("/api/v1/connector/config");
    connectorConfig = cfg;
    const dl = document.getElementById("btnDownloadScript");
    if (dl && cfg.telemetry_url) {
      dl.href = `/api/v1/connector/script.lua?endpoint=${encodeURIComponent(cfg.telemetry_url)}`;
    }
    renderExecutorLoaderSnippets(cfg.loader_url, cfg.ingest_key, cfg.ingest_key_required, cfg.is_admin);
  } catch (_) {}
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
  } else if (tabName === "accounts") {
    loadAccounts();
  }
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
  const totalAcc = ov.total_accounts || 0;
  const liveAcc = ov.live_accounts ?? ov.online_accounts ?? 0;
  const staleAcc = ov.stale_accounts || 0;
  const offAcc =
    ov.offline_accounts ??
    (ov.disconnected_accounts || 0) + (ov.idle_accounts || 0);

  const elOnline = document.getElementById("farmAccountsOnline");
  const elBreak = document.getElementById("farmAccountsBreakdown");
  if (elOnline) elOnline.textContent = `${liveAcc} / ${totalAcc}`;
  if (elBreak) elBreak.textContent = `${liveAcc} Live \u2022 ${staleAcc} Stale \u2022 ${offAcc} Offline`;

  const badge = document.getElementById("connectionStatusBadge");
  const stText = document.getElementById("statusText");
  if (badge && stText) {
    const state = liveAcc > 0 ? "LIVE" : staleAcc > 0 ? "STALE" : "IDLE";
    badge.className = `status-badge ${state.toLowerCase()}`;
    stText.textContent = liveAcc > 0 ? `${liveAcc} LIVE` : state;
  }

  const totalSec = ov.total_secrets || 0;
  const elSec = document.getElementById("farmTotalSecrets");
  const elTabSec = document.getElementById("tabSecretBadge");
  const elTabAcc = document.getElementById("tabAccBadge");
  if (elSec) elSec.textContent = formatNumber(totalSec);
  if (elTabSec) elTabSec.textContent = formatNumber(totalSec);
  if (elTabAcc) elTabAcc.textContent = formatNumber(totalAcc);

  const pillsWrap = document.getElementById("farmSecretVariants");
  if (pillsWrap) {
    const variants = ov.by_variant || ov.secrets_by_variant || {};
    const uniqueTypes = ov.unique_secret_species ?? ov.unique_secret_types ?? 0;
    const entries = Object.entries(variants);
    if (entries.length === 0) {
      pillsWrap.innerHTML = `<span class="kpi-sub">${uniqueTypes} unique types</span>`;
    } else {
      pillsWrap.innerHTML = entries
        .map(
          ([v, cnt]) =>
            `<span class="variant-badge ${variantBadgeClass(v)}">${escapeHtml(v)}: ${formatNumber(cnt)}</span>`
        )
        .join(" ");
    }
  }

  const elEggs = document.getElementById("farmTotalEggs");
  const elEggsHr = document.getElementById("farmEggsPerHour");
  const eggsPerHr = ov.eggs_per_hour ?? ov.farm_eggs_per_hour ?? 0;
  if (elEggs) elEggs.textContent = formatCompact(ov.total_eggs_hatched || 0);
  if (elEggsHr) elEggsHr.textContent = `${formatNumber(Math.round(eggsPerHr))} eggs/hr`;

  const elReb = document.getElementById("farmTotalRebirths");
  const elTapsSub = document.getElementById("farmTotalTapsSub");
  if (elReb) elReb.textContent = formatCompact(ov.total_rebirths || 0);
  if (elTapsSub) {
    elTapsSub.textContent =
      (ov.total_taps || 0) > 0
        ? `Total Taps: ${formatCompact(ov.total_taps || 0)}`
        : `${totalAcc} accounts tracked`;
  }
}

// --- Accounts Management ---

async function loadAccounts() {
  try {
    accountsList = await apiFetch("/api/v1/accounts");
    renderAccountFilterDropdown(accountsList);
    renderMultiAccountsTable(accountsList);
  } catch (e) {
    console.error("Failed to load accounts:", e);
  }
}

function renderAccountFilterDropdown(accounts) {
  const secFilter = document.getElementById("secretAccountFilter");
  if (!secFilter) return;
  const prev = secFilter.value;
  secFilter.innerHTML =
    `<option value="">All Accounts (${accounts ? accounts.length : 0})</option>` +
    (accounts || [])
      .map((a) => `<option value="${Number(a.user_id)}">@${escapeHtml(a.username)} (${a.secret_count || 0} Secrets)</option>`)
      .join("");
  secFilter.value = prev;
}

// --- Secret Vault & Catalog ---

async function loadSecretsVault() {
  try {
    const uid = document.getElementById("secretAccountFilter")?.value || "";
    const tier = document.getElementById("secretTierFilter")?.value || "all";
    const q = (document.getElementById("secretSearchInput")?.value || "").trim();
    const params = new URLSearchParams();
    if (uid) params.set("user_id", uid);
    if (vaultVariantFilter && vaultVariantFilter !== "all") params.set("variant", vaultVariantFilter);
    if (tier && tier !== "all") params.set("tier", tier);
    if (q) params.set("q", q);

    secretsPayload = await apiFetch(`/api/v1/secrets?${params.toString()}`);
    renderSecretVault();
  } catch (e) {
    console.error("Failed to load Secret Vault:", e);
  }
}

async function loadPetCatalog() {
  try {
    petCatalogList = await apiFetch("/api/v1/pets/catalog");
    const cntEl = document.getElementById("catalogSecretCount");
    if (cntEl) cntEl.textContent = String(petCatalogList.length);
  } catch (_) {}
}

function renderSecretVault() {
  const grid = document.getElementById("secretVaultGrid");
  const summaryBar = document.getElementById("vaultSummaryBar");
  if (!grid) return;

  if (vaultMode === "catalog") {
    const q = (document.getElementById("secretSearchInput")?.value || "").trim().toLowerCase();
    const tierFilter = document.getElementById("secretTierFilter")?.value || "all";
    const ownedBySlug = {};
    (secretsPayload.grouped || []).forEach((g) => {
      ownedBySlug[g.slug] = (ownedBySlug[g.slug] || 0) + (g.total_count || 0);
    });

    const filtered = petCatalogList.filter((item) => {
      if (tierFilter !== "all" && (item.tier || "") !== tierFilter) return false;
      if (q) {
        const hay = `${item.name} ${item.default_egg || ""} ${item.tier || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (summaryBar) {
      summaryBar.innerHTML = `
        <span class="meta-pill">In-Game Secret Catalog: <strong>${filtered.length}</strong> pets</span>
        <span class="meta-pill">Click any Secret card to view details or customize its image</span>`;
    }

    grid.innerHTML = filtered
      .map((item) => {
        const ownedCount = ownedBySlug[item.slug] || 0;
        const imgUrl = safeImageUrl(item.image_url);
        return `
          <div class="secret-card variant-normal" data-catalog-slug="${escapeHtml(item.slug)}">
            <span class="secret-qty-badge">&times;${formatNumber(ownedCount)}</span>
            <div class="secret-card-top">
              <div class="pet-portrait-frame variant-normal">
                <img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(item.name)}" loading="lazy" />
              </div>
              <div class="secret-card-info">
                <div class="secret-badges-row">
                  <span class="tier-badge">${escapeHtml(item.tier || "Secret")}</span>
                  <span class="variant-badge ${ownedCount > 0 ? "vb-rainbow" : "vb-normal"}">${ownedCount > 0 ? "OWNED" : "CATALOG"}</span>
                </div>
                <div class="secret-card-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
                <div class="secret-card-egg">${escapeHtml(item.default_egg || "Secret Pool")} ${item.odds ? `&bull; ${escapeHtml(item.odds)}` : ""}</div>
              </div>
            </div>
          </div>`;
      })
      .join("");
    return;
  }

  // Owned Secrets mode
  const sortMode = document.getElementById("secretSortSelect")?.value || "count";
  const list = [...(secretsPayload.grouped || [])];
  list.sort((a, b) => {
    if (sortMode === "multiplier") return (b.max_multiplier || 0) - (a.max_multiplier || 0);
    if (sortMode === "name") return String(a.name).localeCompare(String(b.name));
    return (b.total_count || 0) - (a.total_count || 0);
  });

  if (summaryBar) {
    summaryBar.innerHTML = `
      <span class="meta-pill">Total Owned Secrets: <strong class="highlight-secret">${formatNumber(secretsPayload.total_secrets || 0)}</strong></span>
      <span class="meta-pill">Unique Secret Variants: <strong>${formatNumber(secretsPayload.unique_types || 0)}</strong></span>`;
  }

  if (list.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        No Secret pets recorded in inventory yet. Open your Pet Inventory in-game or run the latest Executor Script so it reads your inventory automatically.
      </div>`;
    return;
  }

  grid.innerHTML = list
    .map((item) => {
      const vClass = variantThemeClass(item.variant);
      const vbClass = variantBadgeClass(item.variant);
      const imgUrl = safeImageUrl(item.image_url);
      const ownersHtml = (item.owners || [])
        .map(
          (o) =>
            `<span class="owner-chip" data-owner-uid="${Number(o.user_id)}">@${escapeHtml(o.username)} <strong>&times;${formatNumber(o.count)}</strong></span>`
        )
        .join("");
      return `
        <div class="secret-card ${vClass}" data-pet-key="${escapeHtml(item.pet_key)}" data-slug="${escapeHtml(item.slug)}">
          <span class="secret-qty-badge">&times;${formatNumber(item.total_count)}</span>
          <div class="secret-card-top">
            <div class="pet-portrait-frame ${vClass}">
              <img src="${escapeHtml(imgUrl)}" alt="${escapeHtml(item.name)}" loading="lazy" />
            </div>
            <div class="secret-card-info">
              <div class="secret-badges-row">
                <span class="tier-badge">${escapeHtml(item.tier || "Secret")}</span>
                <span class="variant-badge ${vbClass}">${escapeHtml(item.variant)}</span>
              </div>
              <div class="secret-card-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
              <div class="secret-card-egg">${escapeHtml(item.egg_source || "Secret Pool")} ${item.odds ? `&bull; ${escapeHtml(item.odds)}` : ""}</div>
            </div>
          </div>
          <div class="secret-stats-bar">
            <span>Mult: <strong class="mono">${formatCompact(item.max_multiplier)}x</strong></span>
            <span>Power: <strong class="mono">+${formatCompact(item.max_power)}</strong></span>
          </div>
          <div class="owner-chips">${ownersHtml}</div>
        </div>`;
    })
    .join("");
}

async function openSecretDetailModal(slug, petKey = "") {
  const modal = document.getElementById("secretDetailModal");
  if (!modal) return;

  let freshSecrets = secretsPayload;
  try {
    freshSecrets = await apiFetch("/api/v1/secrets");
  } catch (_) {}

  const grouped =
    (freshSecrets.grouped || []).find((g) => (petKey && g.pet_key === petKey) || g.slug === slug) || null;
  const catalogItem = petCatalogList.find((c) => c.slug === slug) || null;

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
    tbody.innerHTML = `<tr><td colspan="7" class="empty-cell">No matching accounts. Paste the Executor Script in Roblox to connect.</td></tr>`;
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
      const secList = a.secret_pets || a.top_secrets || [];
      const secretPills =
        secList.length > 0
          ? secList
              .map(
                (s) =>
                  `<span class="owner-chip" style="display:inline-flex;align-items:center;gap:5px;margin:2px;">` +
                  `<img src="${escapeHtml(safeImageUrl(s.image_url))}" style="width:20px;height:20px;object-fit:contain;border-radius:4px;" alt="${escapeHtml(s.name)}" />` +
                  `<span>${escapeHtml(s.variant && s.variant !== "Normal" ? `${s.variant} ` : "")}${escapeHtml(s.name)} <strong>&times;${formatNumber(s.count || 1)}</strong></span>` +
                  `</span>`
              )
              .join("")
          : `<span style="color:var(--text-dim);font-size:0.78rem;">0 Secrets</span>`;

      return `
        <tr>
          <td>
            <div style="display:flex; align-items:center; gap:9px;">
              <img src="${escapeHtml(avatar)}" style="width:30px;height:30px;border-radius:50%;background:#1e293b;object-fit:cover;" alt="" />
              <div>
                <div style="font-weight:700;color:var(--text-main);">@${escapeHtml(a.username)}</div>
                <div style="font-size:0.72rem;color:var(--text-dim);">ID: ${Number(a.user_id)}</div>
              </div>
            </div>
          </td>
          <td><span class="status-badge ${escapeHtml(statusClass)}"><span class="status-dot"></span>${escapeHtml(statusStr)}</span></td>
          <td>${escapeHtml(a.world || "--")}</td>
          <td>
            <div style="display:flex;align-items:center;flex-wrap:wrap;gap:4px;">
              <strong class="mono highlight-secret" style="margin-right:6px;">${formatNumber(a.secret_count || 0)}</strong>
              ${secretPills}
            </div>
          </td>
          <td>
            <div class="mono">${formatCompact(a.eggs_hatched || 0)}</div>
            <div style="font-size:0.72rem;color:var(--text-dim);">${formatNumber(Math.round(a.eggs_per_hour || 0))}/hr</div>
          </td>
          <td class="mono">${formatCompact(a.current_rebirths || 0)}</td>
          <td>
            <button class="btn btn-danger-ghost btn-sm" data-action="delete" data-uid="${Number(a.user_id)}">Delete</button>
          </td>
        </tr>`;
    })
    .join("");
}

// --- SSE Live Stream ---

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

      renderAccountFilterDropdown(accounts);
      renderMultiAccountsTable(accounts);

      // Auto-refresh Secret Vault whenever any account's Secret count or variant breakdown changes
      const ov = !Array.isArray(payload) && payload.overview ? payload.overview : {};
      const accSecSummary = accounts.map((a) => `${a.user_id}:${a.secret_count || 0}`).join(",");
      const currentFp = `${ov.total_secrets || 0}:${ov.unique_secret_species || 0}:${JSON.stringify(ov.by_variant || {})}:${accSecSummary}`;
      let vaultRefreshedThisTick = false;

      if (!lastSecretsFingerprint) {
        lastSecretsFingerprint = currentFp;
      } else if (currentFp !== lastSecretsFingerprint) {
        lastSecretsFingerprint = currentFp;
        vaultRefreshedThisTick = true;
        loadSecretsVault();
      }

      if (!Array.isArray(payload) && Array.isArray(payload.recent_hatches)) {
        const newest = payload.recent_hatches[0];
        if (!hatchesHydrated) {
          lastSeenHatchId = newest && newest.id ? newest.id : 0;
          hatchesHydrated = true;
        } else if (newest && newest.id && newest.id > lastSeenHatchId) {
          lastSeenHatchId = newest.id;
          if (String(newest.rarity || "").toLowerCase() === "secret") {
            showToast(`✨ SECRET HATCHED: ${newest.variant} ${newest.pet_name} (@${newest.username || "Player"})`, "secret");
            if (!vaultRefreshedThisTick) {
              loadSecretsVault();
            }
          }
        }
      }
    } catch (e) {
      console.error("SSE parse error:", e);
    }
  };

  eventSource.onerror = () => {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    setTimeout(connectSSE, 3000);
  };
}

// --- Event Listeners ---

function setupEventListeners() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  document.getElementById("kpiSecretShortcut")?.addEventListener("click", () => switchTab("secrets"));
  document.getElementById("kpiAccountsShortcut")?.addEventListener("click", () => switchTab("accounts"));

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

  // Click delegation on Secret Cards
  document.getElementById("secretVaultGrid")?.addEventListener("click", (e) => {
    const ownerChip = e.target.closest(".owner-chip");
    if (ownerChip && ownerChip.dataset.ownerUid) {
      e.stopPropagation();
      const filterEl = document.getElementById("secretAccountFilter");
      if (filterEl) {
        filterEl.value = ownerChip.dataset.ownerUid;
        loadSecretsVault();
      }
      return;
    }
    const card = e.target.closest(".secret-card");
    if (!card) return;
    const slug = card.dataset.slug || card.dataset.catalogSlug;
    const petKey = card.dataset.petKey || "";
    if (slug) openSecretDetailModal(slug, petKey);
  });

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
      showToast(`Reset ${updated.name} to default portrait`);
    } catch (err) {
      showToast("Reset failed: " + err.message, "error");
    }
  });

  // Multi-Account Matrix controls
  document.getElementById("accountSearchInput")?.addEventListener("input", () => renderMultiAccountsTable(accountsList));
  document.getElementById("accountStatusFilter")?.addEventListener("change", () => renderMultiAccountsTable(accountsList));

  document.getElementById("multiAccountsTableBody")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const uid = Number(btn.dataset.uid);
    if (btn.dataset.action === "delete") {
      await deleteAccount(uid);
    }
  });

  // Connector actions
  document.getElementById("btnCopyLoaderSnippet")?.addEventListener("click", async () => {
    const txt = document.getElementById("executorLoaderSnippet")?.textContent || "";
    await navigator.clipboard?.writeText(txt);
    showToast("Copied Executor loadstring script to clipboard!");
  });

  document.getElementById("btnCopyFallbackSnippet")?.addEventListener("click", async () => {
    const txt = document.getElementById("executorFallbackSnippet")?.textContent || "";
    await navigator.clipboard?.writeText(txt);
    showToast("Copied Fallback Executor script to clipboard!");
  });

  document.getElementById("btnCopyScript")?.addEventListener("click", async () => {
    try {
      const res = await fetch("/loader.lua");
      if (!res.ok) throw new Error("Script not available");
      const luaText = await res.text();
      await navigator.clipboard?.writeText(luaText);
      showToast("Copied tap_sim_reborn_tracker.lua to clipboard!");
    } catch (err) {
      showToast("Copy failed: " + err.message, "error");
    }
  });

  // Admin Unlock Modal
  const adminModal = document.getElementById("adminAuthModal");
  const openAdminModal = () => {
    adminModal?.classList.add("open");
    document.getElementById("inputAdminPassword")?.focus();
  };
  document.getElementById("btnAdminAuth")?.addEventListener("click", openAdminModal);
  document.getElementById("btnUnlockFromConnector")?.addEventListener("click", openAdminModal);
  document.getElementById("btnCloseAdminModal")?.addEventListener("click", () => {
    if (!adminModal?.classList.contains("gate-locked")) adminModal?.classList.remove("open");
  });
  document.getElementById("btnCancelAdminModal")?.addEventListener("click", () => {
    if (!adminModal?.classList.contains("gate-locked")) adminModal?.classList.remove("open");
  });

  document.getElementById("formAdminAuth")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const pwInput = document.getElementById("inputAdminPassword");
    const password = (pwInput?.value || "").trim();
    try {
      await apiFetch("/api/v1/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (pwInput) pwInput.value = "";
      adminModal?.classList.remove("open", "gate-locked");
      await loadAuthStatus();
      await loadDashboardData();
      showToast("Admin unlocked! Your real Executor Key is now filled in Executor Script.");
    } catch (err) {
      showToast("Admin login failed: " + err.message, "error");
    }
  });

  document.getElementById("btnAdminLogout")?.addEventListener("click", async () => {
    try {
      await apiFetch("/api/v1/auth/logout", { method: "POST" });
      await loadAuthStatus();
      if (authState.auth_enabled && !authState.public_read) {
        if (eventSource) eventSource.close();
        adminModal?.classList.add("open", "gate-locked");
      } else {
        adminModal?.classList.remove("open");
        await loadConnectorConfig();
      }
      showToast("Admin locked (View-Only mode)");
    } catch (err) {
      showToast("Logout failed: " + err.message, "error");
    }
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
