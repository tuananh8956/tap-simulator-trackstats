# Tap Simulator Reborn – TrackStats v2 (Secret Vault, Redesigned Dashboard & In-Game Connector) Design Document

**Date:** 2026-11-19  
**Project:** Tap Simulator Reborn TrackStats System (`tap-simulator-trackstats`)  
**Target Game:** Tap Simulator REBORN (Place ID: `72858262610964`, Universe ID: `10629695169`)  
**Status:** Builder Check Completed – Ready for User Approval

---

## 1. Intent & The Why

The existing v1 implementation in `tap-simulator-trackstats` provides core TPS rate tracking, SQLite session storage, and a single-account dark dashboard, but it only tracks a flat list of `equippedPets` and lacks the primary analytics multi-account *Tap Simulator Reborn* players rely on:

1. **Secret Pet Visibility:** Knowing **how many Secret pets** exist across the entire farm and on each account, and **exactly which Secrets** they are (pet name, Secret tier `I/II/III/Event`, variant `Normal/Golden/Diamond/Rainbow/Shiny`, quantity, multiplier/power, egg source, and **individual Secret pet images**).
2. **Modern Multi-Account Dashboard UI:** A richer dark cyber-glassmorphism SPA layout with a farm-wide overview bar, dedicated Secret Vault gallery, Live Hatch Feed, World & Active Boosts display, multi-account search/filter matrix, and Discord Webhook alerting.
3. **In-Game Telemetry Connector Script:** A ready-to-use, strictly read-only Luau client script (`scripts/tap_sim_reborn_tracker.lua`) with an automated **Inspector / Discovery mode** to collect live stats and Secret inventory from inside the game and push JSON telemetry to the local web server, alongside a Discord Webhook ingestion fallback.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Secret Vault & Per-Secret Images:**
  - Track total Secret count across all accounts and per account.
  - Display every owned Secret pet grouped by `(name, variant)` and per account, with tier tags (`Secret I`, `Secret II`, `Secret III`, `Event`) and variant visual treatments (`Normal`, `Golden`, `Diamond`, `Rainbow`, `Shiny`).
  - Render an image for **every individual Secret pet** via a 3-tier resolution pipeline: custom override URL -> Roblox Asset Thumbnail resolution (`rbxassetid://<id>` via `thumbnails.roblox.com/v1/assets`) -> curated local high-craft SVG portraits (`src/static/assets/pets/*.svg`) + procedural SVG fallback (`/api/v1/pets/icon/{slug}.svg`) so no pet card ever shows a broken image.
- **Redesigned Dark Cyber-Glass Website UI:**
  - Multi-tab SPA inside `src/static/` (zero Node.js build step): **Overview**, **Secret Vault**, **Live Hatch Feed**, **Multi-Account Matrix**, **History & Export**, and **Game Connector**.
  - Farm-wide KPI bar (`Live Accounts`, `Total Farm Secrets`, `Total Farm TPS`, `Total Taps`, `Total Currency`, `Eggs Hatched & Eggs/hr`).
  - World/Island indicator, Active Potions/Boosts countdown pills, browser audio chime on Secret hatch (opt-in toggle), and Secret Detail / Image Customizer modal.
- **In-Game Telemetry Script (`scripts/tap_sim_reborn_tracker.lua`) & Connector:**
  - Pure read-only Luau script reading `LocalPlayer.UserId`, `leaderstats`, `LocalPlayer:GetAttributes()`, and `PlayerGui` UI/pet nodes via configurable `CONFIG.PATHS` + heuristic scanner.
  - Built-in **Inspector mode** (`INSPECT_ON_START = true`) that posts discovered in-game `leaderstats`, attribute keys, and UI Pet/Egg paths to `POST /api/v1/connector/inspect` so the user can inspect and adjust mappings directly in the web Connector tab if the game updates its UI.
  - Served dynamically at `GET /api/v1/connector/script.lua` for one-click copy/download from the dashboard.
- **Bidirectional Discord Webhook Integration:**
  - **Outbound alerts:** Notify a user-configured Discord Webhook on Secret hatches (with pet image) and state-transition account disconnects (`DISCONNECTED` at 60s on by default; optional `STALE` at 15s opt-in toggle).
  - **Inbound bridge (`POST /api/v1/webhook/discord`):** Standard Discord webhook JSON `content`/`embeds` parser (user confirmed no custom third-party hub format is needed) that records hatches into `hatch_events` and optionally forwards to a real Discord webhook.
- **100% Backward Compatibility:**
  - All existing v1 REST endpoints, SQLite tables, and all 28 existing pytest tests must continue to pass without breaking v1 telemetry callers.

### Non-Goals
- **No Gameplay Automation:** No auto-clicking, auto-tapping, auto-hatching, auto-rebirth, auto-craft, or firing game `RemoteEvent`s.
- **No Hosted Cloud Auth / Multi-User Accounts:** Designed as a local/LAN single-operator dashboard.
- **No Complex Frontend Build Chain:** Do not introduce Node.js, npm, React, or Vite build tooling.

### Anti-Goals
- **Zero Credential / Cookie Handling:** Never read, request, or store `.ROBLOSECURITY` cookies, passwords, or auth tokens.
- **No Memory / Binary Tampering:** No DLL injection, memory scanning, or executable patching.
- **No Fabricated Live Data:** Never display mocked or hardcoded farm stats when no telemetry has been sent; offline verification uses `tools/telemetry_feeder.py`.

---

## 3. Constraints & Technical Boundaries

1. **Roblox Public APIs vs. Server-Authoritative Game State:**
   - Public endpoints (`users.roblox.com`, `thumbnails.roblox.com`, `presence.roblox.com`) expose usernames, avatars, asset thumbnails, and presence (when privacy permits), NOT pet inventories or tap stats.
   - Internal stats & Secret inventories arrive via `POST /api/v1/telemetry` (from the Luau script or verification feeder) or `POST /api/v1/webhook/discord`.
2. **Roblox Client UI Hierarchy Uncertainty:**
   - Because *Tap Simulator Reborn* is proprietary and updates frequently, exact internal `PlayerGui` / `ReplicatedStorage` child names cannot be assumed static. The Luau script therefore combines explicit `CONFIG.PATHS`, multi-pattern heuristic discovery (matching keywords like `Tap`, `Rebirth`, `Win`, `Gem`, `Coin`, `Egg`, `Secret`, `Golden`, `Rainbow`, `Diamond`, `Shiny`), and the Inspector dump endpoint so the user can inspect and refine path overrides without guesswork.
3. **Client ToS & Safety Transparency:**
   - Running third-party scripts in a live Roblox client violates Roblox Terms of Service and carries account moderation risk. The provided Luau script is strictly read-only telemetry with zero gameplay modification, and the dashboard functions equally well with `tools/telemetry_feeder.py`, Studio `HttpService` testing, or external Webhook feeds.
4. **XSS & Payload Sanitization:**
   - Any pet name, account name, world name, egg name, or image URL arriving via telemetry or inbound webhooks must be HTML-escaped before DOM rendering, and image URLs must be validated to allow only `http://`, `https://`, `/static/`, or `/api/` schemes.

---

## 4. Approaches Considered & Selected Strategy

| Approach | Summary | Tradeoffs | Decision |
|---|---|---|---|
| **1. Upgrade FastAPI + SQLite + Dark UI + Luau Telemetry & Webhook Bridge** | Extend existing `tap-simulator-trackstats` backend & static SPA; add Secret Vault, 3-tier pet images, Discord webhooks, and read-only Luau script with Inspector mode. | Vanilla JS UI instead of component framework; Luau client paths may require 1-time Inspector check after major game UI updates. | **SELECTED (User Choice)** |
| **2. Separate React + TypeScript + Vite Frontend** | Keep FastAPI API, rewrite UI in React/Tailwind. | Requires Node.js toolchain, duplicates existing working dashboard, slower local setup. | Rejected |
| **3. Webhook-First Receiver Only** | Only listen for Discord-style embeds from existing hubs without a Luau inventory script. | Cannot report full existing Secret inventory, per-second TPS, or active boosts unless hub sends them. | Rejected |

---

## 5. System Architecture

```
+-----------------------------------------------------------------------------+
|                         WEB DASHBOARD (SPA / Static)                        |
|   Overview | Secret Vault (Images) | Hatch Feed | Multi-Acc | Connector     |
+--------------------------------------+--------------------------------------+
                                       | REST JSON + SSE (/api/v1/stream)
+--------------------------------------v--------------------------------------+
|                          FASTAPI BACKEND (Port 3883)                        |
|                                                                             |
|  +-----------------------+  +--------------------+  +--------------------+  |
|  | Ingestion & Connector |  | PetCatalogService  |  | WebhookService     |  |
|  | - POST /telemetry     |  | - Seeded Secrets   |  | - Inbound Parser   |  |
|  | - POST /webhook/disc. |  | - Custom Overrides |  | - Outbound Alerts  |  |
|  | - POST /connector/ins.|  | - Asset Thumbnails |  +--------------------+  |
|  +-----------+-----------+  | - SVG Generator    |                          |
|              |              +---------+----------+                          |
|  +-----------v------------------------v----------------------------------+  |
|  |           SessionManager + RateEngine + RobloxPoller                  |  |
|  |   - Sub-second TPS + Rebirth fallback + Eggs/hr rolling calculation   |  |
|  |   - Secret inventory sync + delta hatch detection + async profile     |  |
|  +-----------------------------------+-----------------------------------+  |
|                                      |                                      |
|  +-----------------------------------v-----------------------------------+  |
|  |                    SQLite Persistence (WAL Mode)                      |  |
|  | accounts | sessions | snapshots | account_secrets | pet_catalog       |  |
|  | hatch_events | settings_kv | inspector_reports                        |  |
|  +-----------------------------------------------------------------------+  |
+--------------------------------------^--------------------------------------+
                                       | HTTP POST JSON
       +-------------------------------+-------------------------------+
       |                                                               |
+------+-------------------------------+     +-------------------------+------+
| In-Game Luau Tracker (Read-Only)     |     | Verification Feeder / External |
| scripts/tap_sim_reborn_tracker.lua   |     | tools/telemetry_feeder.py      |
| - leaderstats / Attributes / UI scan |     | or External Discord Webhook    |
+--------------------------------------+     +--------------------------------+
```

---

## 6. Detailed Component Specifications

### 6.1 Extended Data Models (`src/models.py`)

All new fields are optional with defaults so v1 payloads remain 100% valid:

- **`PetItem` extensions:**
  - Existing: `id: Optional[str] = "pet_default"`, `name: str = "Unknown Pet"`, `rarity: str = "Common"`, `multiplier: float = 1.0`, `power: float = 0.0`
  - New:
    - `variant: str = "Normal"` (canonicalized to `Normal`, `Golden`, `Diamond`, `Rainbow`, `Shiny`, `Golden Shiny`, `Rainbow Shiny`, etc.)
    - `tier: Optional[str] = None` (e.g., `"Secret I"`, `"Secret II"`, `"Secret III"`, `"Event"`)
    - `count: int = 1` (minimum `1` when sanitized)
    - `isEquipped: bool = False`
    - `isLocked: bool = False`
    - `eggSource: Optional[str] = None`
    - `imageAssetId: Optional[int] = None`
    - `imageUrl: Optional[str] = None`
- **`BoostItem`:**
  - `name: str`
  - `multiplier: Optional[str] = None` (e.g., `"2x Luck"`)
  - `remainingSec: float = 0.0`
- **`HatchEventInput`:**
  - `eventId: Optional[str] = None`
  - `petName: str`
  - `rarity: str = "Secret"`
  - `variant: str = "Normal"`
  - `tier: Optional[str] = None`
  - `eggName: Optional[str] = None`
  - `odds: Optional[str] = None`
  - `imageAssetId: Optional[int] = None`
  - `imageUrl: Optional[str] = None`
  - `timestamp: Optional[float] = None`
- **`TelemetryPayload` extensions:**
  - `secretPets: Optional[List[PetItem]] = None`
  - `secretCount: Optional[int] = None`
  - `eggsHatched: int = 0`
  - `world: Optional[str] = None`
  - `activeBoosts: List[BoostItem] = Field(default_factory=list)`
  - `recentHatches: List[HatchEventInput] = Field(default_factory=list)`
  - `clientSource: str = "telemetry"`
- **Additional Request Models:**
  - `CatalogImageOverrideRequest`: `imageUrl: Optional[str] = None`, `imageAssetId: Optional[int] = None`, `tier: Optional[str] = None`, `defaultEgg: Optional[str] = None`, `odds: Optional[str] = None`
  - `AlertSettings`: `webhookUrl: str = ""`, `enabled: bool = False`, `notifySecretHatch: bool = True`, `notifyDisconnect: bool = True` (transition to `DISCONNECTED` at 60s), `notifyStale: bool = False` (opt-in transition to `STALE` at 15s), `forwardInboundWebhook: bool = False`
  - `InspectorReportInput`: `userId: int`, `username: Optional[str] = None`, `placeId: Optional[int] = None`, `structure: Dict[str, Any] = Field(default_factory=dict)`

#### Secret Sync & Count Semantics (Builder Call #1 & #6)
- When `payload.secretPets is not None`:
  - `account_secrets` for `userId` is atomically replaced by aggregating `payload.secretPets` by normalized key `f"{slug(name)}::{normalize_variant(variant)}"` (summing `count` if duplicate entries appear for the same name+variant, preserving `isEquipped = any(...)`, max `multiplier`/`power`).
  - Effective `secret_count` = `payload.secretCount` if explicitly provided and `>= 0`, else `sum(item.count for item in normalized_secrets)`.
  - Records `last_authoritative_secret_sync_ts[userId] = payload.timestamp`.
- When `payload.secretPets is None`:
  - Previously stored `account_secrets` for `userId` are **preserved** (partial telemetry packets or closed Pet Inventory UI during AFK never wipe Secret inventory).
  - If `payload.recentHatches` contains any newly recorded Secret hatch (`rarity.lower() == "secret"`, after deduplication), `SessionManager` automatically increments `(petName, variant)` in `account_secrets` (`count += 1`) and updates `accounts.secret_count` so Farm Overview and Secret Vault reflect AFK hatches immediately; the next authoritative `secretPets` sync reconciles exact counts.
  - Otherwise, if `payload.secretCount is not None`, update numeric `secret_count`; else keep existing `secret_count` or fall back to counting `equippedPets` where `rarity.lower() == "secret"` when no `account_secrets` rows exist yet.

#### Implicit Secret Hatch Detection & Cross-Source Deduplication (Builder Call #2 & #7)
- Before inserting any hatch event (from `recentHatches`, `delta_detected`, or `POST /api/v1/webhook/discord`), `Database` checks for a matching hatch for `(user_id or actor_name, slug(pet_name), normalize_variant(variant))` within the last **15 seconds** (in addition to `event_key` uniqueness). Matching duplicates are skipped so neither the Live Hatch Feed nor outbound Discord alerts double-fire when multiple sources observe the same hatch.
- If `payload.recentHatches` is supplied, each unique event is inserted into `hatch_events` (with `event_key` derived from explicit `eventId` or `sha256(userId|petName|variant|int(ts))`).
- If `payload.secretPets is not None` and this account already had a prior `secretPets` sync in the current session, any Secret `(name, variant)` whose `count` increases by `delta > 0` (and was not already recorded within the 15-second dedup window) automatically emits up to `min(delta, 5)` `hatch_events` with `source="delta_detected"`, ensuring live hatch feed & alerts work even if the client only polls inventory snapshots.

---

### 6.2 SQLite Storage & Safe Migrations (`src/database.py`)

`Database.init_db()` preserves existing `accounts`, `sessions`, and `snapshots` tables and runs idempotent column checks via `PRAGMA table_info(...)` before issuing `ALTER TABLE`:
- `accounts` new columns: `world TEXT`, `eggs_hatched INTEGER DEFAULT 0`, `secret_count INTEGER DEFAULT 0`, `last_client_source TEXT DEFAULT 'telemetry'`
- `snapshots` new columns: `eggs_hatched INTEGER DEFAULT 0`, `secret_count INTEGER DEFAULT 0`, `world TEXT`

New tables:
```sql
CREATE TABLE IF NOT EXISTS account_secrets (
    user_id INTEGER NOT NULL,
    pet_key TEXT NOT NULL,
    name TEXT NOT NULL,
    variant TEXT NOT NULL DEFAULT 'Normal',
    tier TEXT,
    count INTEGER NOT NULL DEFAULT 1,
    multiplier REAL DEFAULT 1.0,
    power REAL DEFAULT 0.0,
    is_equipped INTEGER DEFAULT 0,
    egg_source TEXT,
    image_asset_id INTEGER,
    image_url TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (user_id, pet_key),
    FOREIGN KEY (user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pet_catalog (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rarity TEXT NOT NULL DEFAULT 'Secret',
    tier TEXT,
    default_egg TEXT,
    odds TEXT,
    image_asset_id INTEGER,
    resolved_image_url TEXT,
    custom_image_url TEXT,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS hatch_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT UNIQUE,
    user_id INTEGER NULL,
    actor_name TEXT,
    pet_name TEXT NOT NULL,
    rarity TEXT NOT NULL DEFAULT 'Secret',
    variant TEXT NOT NULL DEFAULT 'Normal',
    tier TEXT,
    egg_name TEXT,
    odds TEXT,
    image_url TEXT,
    source TEXT NOT NULL DEFAULT 'telemetry',
    timestamp REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES accounts(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings_kv (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS inspector_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    username TEXT,
    place_id INTEGER,
    structure_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

- `export_data` & `restore_data` are extended to include `account_secrets`, `pet_catalog`, and `hatch_events` while safely ignoring absent keys when restoring v1 JSON backups.

---

### 6.3 Secret Pet Catalog & Per-Pet Image Pipeline (`src/pet_catalog.py` & `src/static/assets/pets/`)

1. **Seeded Tap Simulator Reborn Secret Catalog (18 Pets):**
   Pre-seeded into `pet_catalog` on `init_db()` with curated SVG assets under `src/static/assets/pets/<slug>.svg`:
   - **Secret I:** `Void Wraith` (Void Egg, `1 in 500K`), `Cinder Eye` (Draconic Egg, `1 in 500K`), `Inferno Dragon` (Volcanic Egg, `1 in 500K`), `Autumn Warden` (Pumpkin Egg, `1 in 500K`), `Oasis Spirit` (Cactus Egg, `1 in 500K`)
   - **Secret II:** `Void Overseer` (Void Egg, `1 in 1M`), `Shinigami` (Void Egg, `1 in 2M`), `Helfire Spirit` (Volcanic Egg, `1 in 2M`), `Infernal Lord` (Draconic Egg, `1 in 2M`), `Chronos` (Chronos Egg, `1 in 2M`)
   - **Secret III & High-Tier Secrets:** `Forsaken Knight` (Void Egg, `1 in 4M`), `Dragon Tamer` (Draconic Egg, `1 in 4M`), `King Of Hell`, `Malevolent Treat`, `Sanguine Heart`, `Peace Keeper`, `Time Paradox`, `Dark Cat`

2. **Image Resolution Order (Strict Precedence):**
   1. `pet_catalog.custom_image_url` (user override set in Secret Vault modal)
   2. Explicit `imageUrl` from incoming telemetry (validated safe scheme: `https://`, `http://`, `/static/`, `/api/`)
   3. `pet_catalog.resolved_image_url` (resolved from `imageAssetId` via `RobloxPoller.get_asset_thumbnail(asset_id)` -> `https://thumbnails.roblox.com/v1/assets?assetIds={id}&returnPolicy=PlaceHolder&size=150x150&format=Png&isCircular=false`)
   4. Local SVG file `/static/assets/pets/{slug}.svg` if present on disk
   5. Dynamic SVG generator `/api/v1/pets/icon/{slug}.svg` (deterministic gradient emblem + stylized pet silhouette + monogram/tier crest derived from `slug` hash, cached with `Cache-Control: public, max-age=3600`)

3. **Asset ID Extraction:**
   - `extract_asset_id(val)` handles integers (`12345678`), `"rbxassetid://12345678"`, `"rbxthumb://type=Asset&id=12345678..."`, and `"https://www.roblox.com/asset/?id=12345678"`.
   - When telemetry introduces a new `imageAssetId` not yet resolved, an async background task resolves the Roblox PNG thumbnail and updates `pet_catalog.resolved_image_url` without blocking `POST /api/v1/telemetry`.

---

### 6.4 Rate Engine, Session Manager & Roblox Enrichment

- **`RateEngine` (`src/rate_engine.py`):**
  - Keeps existing TPS calculation + rebirth fallback (`totalTaps` delta when `currentTaps` drops).
  - Adds egg tracking per record (`eggs_hatched`) to compute `eggs_per_hour` across active window (using `max(10.0, dt)` guard so initial seconds don't spike to millions).
- **`SessionManager` (`src/session_manager.py`):**
  - Exposes `get_overview()` returning farm-wide totals: `total_accounts`, `live_accounts`, `stale_accounts`, `disconnected_accounts`, `paused_accounts`, `idle_accounts`, `total_secrets`, `unique_secret_species`, `total_tps`, `total_current_taps`, `total_taps`, `total_currency`, `total_rebirths`, `total_eggs_hatched`, `eggs_per_hour`.
  - Exposes `get_secrets_summary(user_id=None, variant=None, tier=None, query=None)` combining `account_secrets` + `pet_catalog` + resolved `image_url`, returning both `grouped` (by pet name + variant across farm with `owners[]`) and `items` (per-account breakdown).
  - Adjusts `active_boosts` remaining seconds dynamically based on `max(0.0, remainingSec - elapsed_since_last_seen)`.
  - `get_live_state(user_id)` preserves all v1 keys (`user_id`, `username`, `display_name`, `avatar_url`, `is_tracking`, `connection_status`, `active_session_id`, `session_duration_sec`, `current_taps`, `total_taps`, `current_rebirths`, `total_rebirths`, `current_wins`, `total_wins`, `current_currency`, `equipped_pets`, `pet_inventory_count`, `total_pet_power`, `tps`, `max_tps`, `avg_tps`, `rates`, `last_seen`) and adds: `secret_count`, `secret_pets`, `eggs_hatched`, `eggs_per_hour`, `world`, `active_boosts`, `client_source`.
  - `check_timeouts()` tracks previous state per `user_id` and emits `STALE` / `DISCONNECTED` events strictly on state transitions (`prev_state != new_state`), triggering outbound Discord alerts according to `AlertSettings` (`notifyDisconnect` on `DISCONNECTED`, opt-in `notifyStale` on `STALE`).
- **Async Profile Enrichment (`src/main.py`):**
  - When telemetry arrives for a `userId` not yet resolved from Roblox (e.g., `username == f"Player_{userId}"`), schedule a debounced background lookup via `RobloxPoller.get_user_info` & `get_user_avatar` to populate real Roblox username, display name, and avatar headshot automatically.

---

### 6.5 REST & SSE API Endpoints (`src/main.py`)

All v1 routes remain intact. New & enhanced endpoints:
- `GET /api/v1/overview`: Farm-wide aggregate KPIs.
- `GET /api/v1/accounts`: Preserves v1 fields + adds `secret_count`, `eggs_hatched`, `eggs_per_hour`, `world`, `client_source`.
- `GET /api/v1/secrets`: Query params `user_id`, `variant`, `tier`, `q` -> `{ "total_secrets": int, "unique_types": int, "grouped": [...], "by_variant": {...}, "by_tier": {...} }`.
- `GET /api/v1/pets/catalog`: Lists all seeded & discovered pets with resolved `image_url`.
- `POST /api/v1/pets/catalog/{slug}/image`: Updates custom `imageUrl` or `imageAssetId` (and triggers thumbnail resolution if `imageAssetId` provided).
- `GET /api/v1/pets/icon/{slug}.svg`: Returns fallback procedural SVG artwork (`image/svg+xml`).
- `GET /api/v1/hatches`: Query params `limit` (default 50), `rarity`, `user_id` -> recent hatch events enriched with username, avatar, and resolved pet `image_url`.
- `GET /api/v1/settings/alerts`: Returns alert settings with `webhookUrl` masked (`https://discord.com/api/webhooks/...****`) and `hasWebhookUrl: bool`.
- `POST /api/v1/settings/alerts`: Updates alert settings; preserves stored `webhookUrl` if masked sentinel or empty unchanged placeholder is sent unless explicitly cleared (`clearWebhook: true`).
- `POST /api/v1/settings/alerts/test`: Sends a test Discord embed to verify webhook connectivity.
- `POST /api/v1/webhook/discord`: Standard inbound Discord-compatible webhook receiver (no custom external hub format required). Parses `content` and `embeds[].{title,description,fields}` for player/account (`userId` or `username`), `petName`, `variant`, `rarity`, `eggName`, `odds`. If `username` is found without `userId`, resolves via `RobloxPoller.get_user_by_username(username)` (`POST https://users.roblox.com/v1/usernames/users`) and upserts `accounts`; if unresolvable/absent, inserts `hatch_events` with `user_id = NULL` and `actor_name`. Applies 15s cross-source deduplication, increments `account_secrets` for Secret hatches only if `user_id` is resolved AND no authoritative Luau `secretPets` sync occurred in the last 60 seconds, and optionally forwards to configured outbound webhook.
- `GET /api/v1/connector/script.lua`: Returns `scripts/tap_sim_reborn_tracker.lua` with optional `?endpoint=...` substitution (validated localhost/HTTP(S) URL).
- `POST /api/v1/connector/inspect` & `GET /api/v1/connector/inspect`: Stores and retrieves the latest in-game Luau hierarchy inspection reports (capped at last 10 reports).
- `GET /api/v1/stream` (SSE): Streams JSON array or structured snapshot?
  - **Builder Call #3 (SSE Backward Compatibility):** Keep `GET /api/v1/stream` emitting named SSE event or JSON payload `{ "overview": ..., "accounts": [...], "recent_hatches": [...] }` AND support v1 consumers cleanly in our updated `app.js` (checking `Array.isArray(payload) ? ... : payload.accounts`). Let's verify no existing test asserts array-only on `/api/v1/stream` — confirmed none of the 28 tests hit `/api/v1/stream`. Still, making `app.js` handle both object and array formats ensures zero fragility.

---

### 6.6 Website UI Redesign (`src/static/index.html`, `src/static/css/style.css`, `src/static/js/app.js`)

- **Visual Theme & Aesthetic:**
  - Deep obsidian glassmorphism (`#060911` canvas, translucent `rgba(14, 20, 34, 0.78)` cards with crisp `1px` inner edge highlights, `Inter` / system sans + `JetBrains Mono` / tabular monospace for live numeric counters).
  - Semantic accent hierarchy: Cyan (`#00f2fe`) for taps/navigation, Emerald (`#10b981`) for live TPS & online badges, Violet/Magenta (`#c084fc` / `#ec4899`) for **Secret** indicators, Gold (`#fbbf24`), Diamond (`#38bdf8`), and animated Prismatic gradient (`Rainbow`) for pet variant frames.
- **Navigation Structure:**
  - **Top Command Header:** Brand title (`Tap Simulator Reborn` / `TrackStats`), Quick View Tabs (`Overview`, `Secret Vault`, `Hatch Feed`, `Multi-Account`, `History`, `Connector`), Active Account selector, `+ Add Account`, `Pause/Resume Tracking`, `Sound Alert` toggle, and Connection Status pill (`LIVE` / `STALE` / `DISCONNECTED` / `PAUSED` / `IDLE`).
  - **Persistent Farm Overview Strip:** 5 compact KPI cards visible across views:
    1. `Accounts Online` (`live / total`)
    2. `Total Secrets` (total Secret count across farm + mini breakdown pills `Rainbow`, `Golden`, `Diamond`, `Normal`)
    3. `Farm TPS` (aggregate live taps/sec)
    4. `Farm Taps & Currency`
    5. `Total Eggs` (`eggsHatched` + `eggs/hr`)
- **View 1 — Overview (Live Telemetry Console):**
  - Left column: Active Player Card (Avatar headshot, Display Name, `@username` + `User ID`, World/Island badge, Session Playtime timer, Active Boosts/Potions list with live seconds countdown).
  - Right column: **Live Statistics** grid (Real-time TPS with Max/Avg, Current Taps, Total Taps, Rebirths, Wins, Currency, Secrets Owned, Eggs Hatched) + 1m / 5m / 15m Rolling Growth cards.
  - Full-width **Real-time TPS & Progression Chart** (Chart.js).
  - **Active Account Secret Showcase** (horizontal/grid preview of this account's Secret pets with images) + **Equipped Pets** grid (retaining heading `"Equipped Pets"` for UI clarity & test compatibility) + **Mini Live Hatch Feed**.
- **View 2 — Secret Vault (Kho Secret):**
  - Summary banner showing total Secrets, unique Secret species, and counts by Variant (`Normal`, `Golden`, `Diamond`, `Rainbow`, `Shiny`) & Tier (`Secret I`, `Secret II`, `Secret III`, `Event`).
  - Toolbar: Search input (pet name or owner username), Account dropdown filter, Variant pills (`All`, `Rainbow`, `Golden`, `Diamond`, `Shiny`, `Normal`), Tier filter, Sort selector (`Count`, `Power`, `Multiplier`, `Name`).
  - **Secret Pet Cards Grid:** Each card shows:
    - Dedicated Secret Pet Image (`88x88` framed thumbnail with variant aura & subtle shine animation on Rainbow/Shiny)
    - Tier badge (`Secret III`) + Variant badge (`Rainbow`) + Total Count badge (`×3`)
    - Pet Name, Multiplier (`25,000x`), Max Power (`+120K`), Egg Source (`Void Egg`)
    - Owner breakdown chips (`@Acc_01 ×2`, `@Acc_04 ×1`, clickable to switch active account)
  - Clicking any Secret card opens **Secret Detail & Custom Image Modal**: displays full per-account table and form to set a custom `Image URL` or `Roblox Asset ID` (`POST /api/v1/pets/catalog/{slug}/image`).
- **View 3 — Live Hatch Feed & Discord Alerts:**
  - Live Hatch Feed timeline (pet image, rarity/variant pills, pet name, account avatar + name, egg name, odds, time ago), filterable by `All / Secret Only / Mythic+`, plus a "Simulate/Test Sound" check.
  - Side panel: **Discord Webhook Alert Settings** (enable/disable, Webhook URL input, notify on Secret Hatch / Disconnect at 60s / optional Stale at 15s, Save & Test Alert buttons) + **Inbound Webhook Bridge Box** (copyable URL `http://<host>:3883/api/v1/webhook/discord` for external hubs).
- **View 4 — Multi-Account Matrix:**
  - Search & Status filter (`All / LIVE / STALE / DISCONNECTED / PAUSED`) + `Track All` / `Pause All` batch buttons.
  - Table columns: Account (avatar + name), User ID, Status, World, **Secrets** (count + top 2 mini pet icons), Current Taps, Live TPS, Rebirths, Eggs Hatched, Session Playtime, Actions (`View`, `Pause/Resume`, `Delete`).
- **View 5 — History & Data Export:**
  - Past Session History table for active account + `Export CSV`, `Export JSON`, and `Restore JSON Backup` file picker.
- **View 6 — Game Connector & In-Game Script:**
  - Endpoint summary (`POST /api/v1/telemetry`), one-click **Copy Script** and **Download `tap_sim_reborn_tracker.lua`**, quick **Sample Payload Test** info (`tools/telemetry_feeder.py`), and **Live Inspector Dump Viewer** showing the latest hierarchy JSON posted from inside the game (`GET /api/v1/connector/inspect`) so the user can copy exact `leaderstats` / `PlayerGui` node names into `CONFIG.PATHS`.

---

### 6.7 In-Game Luau Telemetry Script (`scripts/tap_sim_reborn_tracker.lua`)

- **Strict Safety Contract:** Read-only client telemetry observer. Contains zero auto-click/auto-hatch/remote-exploit logic and never accesses cookies or tokens.
- **HTTP Transport Abstraction:** Auto-selects `request` -> `http_request` -> `syn and syn.request` -> `fluxus and fluxus.request` -> `http and http.request` -> fallback `HttpService:RequestAsync` (for Roblox Studio testing).
- **Singleton Lifecycle:** Uses `_G.__TapSimTrackStats_Token` so re-running the script cleanly terminates any prior loop before starting a new one.
- **Configurable `CONFIG` Header:**
  - `ENDPOINT_URL = "http://127.0.0.1:3883/api/v1/telemetry"`
  - `INSPECT_URL = "http://127.0.0.1:3883/api/v1/connector/inspect"`
  - `SEND_INTERVAL = 2.0`
  - `INSPECT_ON_START = true`
  - `DEBUG_LOG = false`
  - `PATHS`: optional explicit overrides for `Taps`, `TotalTaps`, `Rebirths`, `Wins`, `Currency`, `Eggs`, `World`, `PetListGui`, `BoostListGui`.
- **Smart Heuristic Collector + Number Parser:**
  - `parseCompactNumber(str)` converts formatted game text (`"1.54M"`, `"48.2B"`, `"250,000"`, `"x12.5K"`, `"1.2T"`, `"50Qa"`) accurately into numeric values.
  - **Stats Reader:** Checks `CONFIG.PATHS` first, then scans `LocalPlayer.leaderstats` (case-insensitive alias matching for `Taps`/`Clicks`, `TotalTaps`, `Rebirths`, `Wins`, `Gems`/`Coins`/`Currency`, `Eggs`/`Hatched`) and `LocalPlayer:GetAttributes()`, plus optional `PlayerGui` HUD labels if values live in UI text rather than `leaderstats`.
  - **Secret & Equipped Pet Reader (with Closed-UI Guard):** Checks configured `PetListGui` or auto-discovers scrolling pet grids inside `LocalPlayer.PlayerGui` (plus optional read-only client value folders if present). **Crucial AFK guard:** Only populates `payload.secretPets` when the Pet Inventory container is confirmed visible/populated (or a readable client data folder exists); if `PetListGui` is closed (`Visible == false`) or unmounted, `secretPets` is **omitted (`nil`)** so closing the inventory while AFK hatching never wipes the web Secret Vault or causes false delta-hatches on reopen. When readable, extracts `imageAssetId`, `variant`, `tier`, `count` (`x3` stacks or repeated frames), `multiplier`, `power`, and `isEquipped`.
  - **Live Hatch Popup & Chat Listener (AFK Secret Capture):** Listens to `PlayerGui` hatch notification popups and system chat (`TextChatService.MessageReceived` / legacy chat events, read-only) for Secret/Mythic hatch announcements, queuing detected hatches into `payload.recentHatches` so AFK Secret hatches still appear immediately in Live Hatch Feed, Secret Vault, and Discord alerts even while the Pet Inventory window stays closed.
  - **Inspector Mode:** On start (when `INSPECT_ON_START = true`), collects a compact summary of `leaderstats` children, `LocalPlayer:GetAttributes()` keys, and candidate `PlayerGui` Pet/HUD frame paths (max depth 5, bounded size) and sends it to `POST /api/v1/connector/inspect` so the user can inspect the live game layout in the Web Dashboard Connector tab.

---

### 6.8 Upgraded Verification Feeder (`tools/telemetry_feeder.py`)

- Extended CLI arguments (`--accounts` comma-separated or `--multi N`, `--rate`, `--interval`, `--rebirth-interval`, `--hatch-interval`, `--count`, `--url`) so a single command simulates multiple simultaneous *Tap Simulator Reborn* farming accounts with Secret inventories (spanning `Normal`, `Golden`, `Diamond`, `Rainbow`, `Shiny`), periodic Secret/Mythic hatch events, worlds, eggs hatched, and active boosts.

---

## 7. Builder Calls Made During Design

1. **Secret Inventory Partial-Update Preservation (Builder Call #1):** `secretPets` defaults to `None` rather than `[]` in `TelemetryPayload` so a basic v1 telemetry sender (that omits `secretPets`) does not accidentally erase previously synced Secret records for that account. Sending `secretPets: []` explicitly syncs an empty Secret list.
2. **Delta Secret Hatch Detection (Builder Call #2):** If a telemetry client updates `secretPets` without populating `recentHatches`, increases in `(name, variant)` count within an active session automatically create `hatch_events` entries (`source="delta_detected"`) so the Hatch Feed and Discord alerts still fire reliably.
3. **SSE Stream Backward Compatibility (Builder Call #3):** `GET /api/v1/stream` emits a single JSON envelope containing `{ "overview": ..., "accounts": [...], "recent_hatches": [...] }` every 1.0s, and `app.js` defensively accepts either the envelope or a raw list.
4. **Pet Artwork Fallback (Builder Call #4):** Ship 18 bespoke static SVG illustrations for known Tap Simulator Reborn Secrets alongside dynamic Roblox `assetId` thumbnail resolution and a procedural `/api/v1/pets/icon/{slug}.svg` fallback, ensuring every pet renders crisply offline or online without fragile external wiki scraping.
5. **Webhook Secret Masking (Builder Call #5):** `GET /api/v1/settings/alerts` never leaks the raw Discord Webhook secret token back to the browser; it returns a masked string and `hasWebhookUrl: true`, updating the stored URL only when a new non-masked URL or `clearWebhook: true` is submitted.
6. **Luau Closed-Inventory Guard & AFK Hatch Capture (Builder Call #6):** `tap_sim_reborn_tracker.lua` omits `secretPets` (`nil`) whenever the Pet Inventory UI is closed/unmounted so AFK hatching never wipes `account_secrets`, while scraping read-only hatch popups/system chat into `recentHatches`; `SessionManager` increments `account_secrets` from Secret `recentHatches` when `secretPets` is omitted, and reconciles exact inventory counts on the next open-inventory sync.
7. **Nullable Webhook Hatch Actor & Cross-Source Deduplication (Builder Call #7):** `hatch_events.user_id` is nullable with `actor_name` fallback; inbound Discord webhooks resolve Roblox usernames via `users.roblox.com/v1/usernames/users` when possible, use a 15-second deduplication window across `recentHatches` / `delta_detected` / `webhook/discord`, and only mutate `account_secrets` if no authoritative Luau `secretPets` sync occurred within 60 seconds.
8. **State-Transition-Only Outbound Disconnect Alerts (Builder Call #8):** `SessionManager.check_timeouts()` emits `STALE` / `DISCONNECTED` events strictly on state transitions (`prev_state != new_state`), preventing repeated 2-second alert spam. `AlertSettings` defaults `notifyDisconnect = True` (60s) and `notifyStale = False` (15s opt-in toggle in UI).

---

## 8. What's Left to the Builder

- Create the 18 curated SVG files under `src/static/assets/pets/` and implement `src/pet_catalog.py` + procedural SVG endpoint.
- Implement SQLite schema migrations and new CRUD/query methods in `src/database.py`.
- Implement extended Pydantic models, `RateEngine` egg rate, `SessionManager` overview/secrets/boosts/hatch logic, `RobloxPoller` asset thumbnail resolution, and `WebhookService` inbound/outbound handlers.
- Build the redesigned cyber-glass SPA in `src/static/index.html`, `src/static/css/style.css`, and `src/static/js/app.js` with full HTML escaping and URL sanitization.
- Author `scripts/tap_sim_reborn_tracker.lua` with `CONFIG`, multi-executor HTTP wrapper, Inspector mode, compact number parser, and heuristic UI/leaderstats collector.
- Upgrade `tools/telemetry_feeder.py` and write thorough unit + integration + static UI tests in `tests/` verifying all existing 28 tests plus new v2 capabilities (Secret aggregation, variant counts, 3-tier image resolution, delta hatch detection, Discord webhook parser, inspector reports, and script download).
