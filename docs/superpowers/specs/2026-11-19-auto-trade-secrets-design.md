# Auto-Trade Secret Consolidation System — Design Specification

- **Date:** 2026-11-19
- **Project:** Tap Simulator Reborn – TrackStats v2 (`tap-simulator-trackstats`)
- **Target Game:** Tap Simulator Reborn (Place ID: `72858262610964`, Universe ID: `10629695169`)

---

## 1. Intent and the Why

The user operates a 40+ account farm in **Tap Simulator Reborn**, tracked in real time by the TrackStats v2 dashboard and the in-game Luau script (`scripts/tap_sim_reborn_tracker.lua`). Across ~25 active clone accounts, 170+ Secret pets accumulate inside `DataController:GetReplica().Data.Pets.Owned`.

Manually joining each clone's server (or bringing each clone into the main account's server), unequipping equipped Secrets, unlocking locked Secrets, opening the trade window, selecting each Secret UUID, and confirming on both accounts is repetitive and interrupts AFK farming.

This feature adds an automated **Secret Consolidation System** so that:
1. Clone accounts holding Secret pets automatically join the Main Account's server one at a time via a backend queue.
2. Once in the Main Account's server, the clone automatically unequips and unlocks all of its Secret pets, trades 100% of them to the Main Account (across multiple trade rounds if necessary), and then hops out to another server so the Main Account's server never fills up.
3. The Main Account (running the same script) automatically reports its current server (`jobId`), accepts trade requests from farm clones, and confirms the trade completely hands-free.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Centralized Web Dashboard Control:** Configure the Main Account (`userId` or `username`), toggle global **Auto-Consolidate Secrets** (`enabled`), trigger a manual **"Collect All Secrets"** queue run, or click **"Trade to Main"** on any individual clone row in the Multi-Account table.
- **Sequential Server-Side Queue Coordinator:** Prevent "Server Full" errors and trade-request collisions by dispatching at most `max_concurrent_clones` (default `1`) to the Main Account's server at a time, with automatic timeout advancing (`120s` lease timeout) if a clone disconnects or stalls.
- **Teleport Persistence (`queue_on_teleport`) & Server Hop Exit:** Automatically re-queue the TrackStats loader script before teleporting into the Main Account's server, and automatically teleport the clone to a different public server once its Secret count reaches `0`.
- **100% Secret Extraction (Auto-Unequip & Auto-Unlock):** Before opening trade, the clone scans `DataController:GetReplica().Data.Pets.Owned` for all Secret pet UUIDs, unequips any that have `Equip == true` (or appear in `EquippedPets`), and unlocks any that have `Locked == true`.
- **Dual-Role Luau Execution (Clone Sender + Main Receiver):** A single unified script (`scripts/tap_sim_reborn_tracker.lua`) acts as Receiver when `LocalPlayer` matches the Main Account and as Sender when `LocalPlayer` is a dispatched clone.
- **Live Queue Visibility:** Display live queue status on the Web Dashboard (Main Account online/server status, currently active clone, queued clones count, and per-account trade state).

### Non-Goals
- Trading non-Secret pets (Common, Rare, Epic, Legendary, Mythical) or non-pet items/potions.
- Multi-hop middleman routing (all clones deliver directly to the single configured Main Account).

### Anti-Goals
- **Never flood the Main Account's server:** Never teleport all 25+ clones simultaneously into `main_job_id`.
- **Never trade Secrets to untrusted players:** A clone must verify the recipient's `UserId` (or exact case-insensitive `Name` when configured by username and resolved to `UserId`) before sending a trade request or confirming an offer. The Main Account must only auto-accept trade requests from UserIds present in the TrackStats farm account registry.
- **Never deadlock the queue:** If a dispatched clone disconnects, fails to teleport within `120s`, or errors out, the backend coordinator must expire its lease and advance to the next eligible clone.

---

## 3. Constraints

- **Single-Line Executor Loader Compatibility:** All 43+ accounts load the script via `loadstring(game:HttpGet("<base_url>/loader.lua"))()` and hot-reload automatically when `script_version` increments in `/api/v1/telemetry`. No per-account local configuration change is required.
- **Executor Environment Support:** Must support standard executor globals (`getgenv`, `request` / `http_request` / `syn.request`, `queue_on_teleport` / `syn.queue_on_teleport` / `fluxus.queue_on_teleport`, `TeleportService:TeleportToPlaceInstance`, `TeleportService:Teleport`).
- **Tap Simulator Reborn Architecture:**
  - Owned pets live in `DataController:GetReplica().Data.Pets.Owned` keyed by UUID (`Id`), with fields `Name`, `Rarity`, `Tier`, `Mutation`, `Equip` (`boolean`), `Locked` (`boolean`), `Power`.
  - Game controllers and network adapters live under `ReplicatedStorage.Controllers.Trading`, `ReplicatedStorage.Shared.Trading`, `ReplicatedStorage.Controllers.Pets` (`PetController`, `InventoryController`), and `ReplicatedStorage.Packages.Comm` (plus `PlayerGui.Trading`).
  - Because Tap Simulator Reborn uses Knit/Comm-style controllers and remotes, the Luau script must dynamically inspect and bind the exact remote/controller methods at runtime (and report `Controllers.Trading`, `Shared.Trading`, and `PlayerGui.Trading` in Inspector snapshots for diagnostics).
- **Admin Security Gate:** Modifying auto-trade settings or triggering trade runs via REST endpoints must require `require_admin` authentication (matching existing Admin password protection), while read-only status is visible in `/api/v1/trade/status` and `/api/v1/stream`.

---

## 4. Approaches Considered

### Approach 1: Centralized Smart Queue Coordinator on TrackStats Backend + Dual-Role Luau Agent (Selected)
- **Description:** The FastAPI backend (`SessionManager` + `Database`) stores the Auto-Trade configuration (`main_user_id`, `main_username`, `enabled`, `keep_equipped=False`) and maintains an ordered queue of clone accounts with `secret_count > 0`. On every `/api/v1/telemetry` heartbeat (every 2 seconds), accounts report `placeId`, `jobId`, and `tradeStatus`, and receive a `trade_directive` object in the JSON response telling the account its role (`MAIN`, `CLONE_ACTIVE`, `CLONE_QUEUED`, or `IDLE`), the target `mainJobId`, and the list of trusted farm `userIds`.
- **Pros:** Guarantees only 1 clone joins the Main Account's server at a time; avoids server-full errors and simultaneous trade request spam; gives real-time dashboard visibility and 1-click web control.
- **Cons:** Requires stateful queue management on the backend in addition to the Luau trade executor.

### Approach 2: Unqueued Direct Teleport from All Clones
- **Description:** The backend broadcasts `mainJobId` to all clones, and every clone with `secret_count > 0` immediately teleports to `mainJobId` and spams trade requests.
- **Pros:** Minimal backend logic.
- **Cons:** Fails when 20+ clones try to join a single Roblox server simultaneously (`Server Full`), and causes trade UI/cooldown deadlocks on the Main Account.

### Approach 3: Manual Per-Account Web Trigger Only
- **Description:** Clones never queue automatically; the user must manually click a button for each clone account on the Web Dashboard.
- **Pros:** Explicit manual control.
- **Cons:** Defeats hands-free AFK consolidation across 43 accounts. (Manual per-account trigger is included as an override action inside Approach 1).

**Decision:** The user selected **Approach 1**.

---

## 5. Detailed Design

### 5.1. Data Model & Persistence (`src/models.py` & `src/database.py`)

1. **Telemetry Payload Extensions (`TelemetryPayload` in `src/models.py`):**
   - `placeId: Optional[int] = None` — Current `game.PlaceId`.
   - `jobId: Optional[str] = None` — Current `game.JobId` (Roblox server instance GUID).
   - `tradeState: Optional[str] = None` — Client-reported trade state (`"IDLE"`, `"TELEPORTING"`, `"PREPARING_PETS"`, `"REQUESTING_TRADE"`, `"TRADING"`, `"COMPLETED"`, `"HOPPING_OUT"`, `"ERROR"`).
   - `tradeMessage: Optional[str] = None` — Human-readable status or last error from the client.
   - `secretInstanceIds: Optional[List[str]] = None` — Optional list of unequipped/equipped Secret UUIDs currently held by the account.

2. **Persistent Auto-Trade Settings (`settings_kv` key `"auto_trade_settings"` in `src/database.py`):**
   ```json
   {
     "enabled": false,
     "mainUserId": null,
     "mainUsername": "",
     "unequipSecrets": true,
     "unlockSecrets": true,
     "hopOutAfterTrade": true,
     "leaseTimeoutSec": 120
   }
   ```

### 5.2. Backend Queue Coordinator (`src/session_manager.py` & `src/main.py`)

1. **Tracking Main Account Server Location:**
   - The Main Account is matched by `user_id == settings.mainUserId` or case-insensitive `username == settings.mainUsername` (once matched by username, `mainUserId` is auto-populated from the account record).
   - Whenever the Main Account sends `/api/v1/telemetry` with a non-empty `jobId` and its connection status is `LIVE`, the coordinator records `main_job_id`, `main_place_id`, and `main_online = True`.

2. **Queue Eligibility & Ordering:**
   - When `enabled == True` (or when specific clone `user_id`s are manually enqueued via the Web UI):
     - Any `LIVE` account where `user_id != main_user_id` and `secret_count > 0` (and not on a temporary post-completion/error cooldown of 15s) is eligible for the queue.
     - Manually triggered accounts (`priority_queue`) are placed ahead of automatic queue accounts; automatic queue accounts are ordered by `secret_count DESC, user_id ASC` so clones with the most Secrets consolidate first.
   - **Active Lease (`active_clone_id`):**
     - Only **1 clone** holds the active lease at any moment.
     - Lease assignment requires `main_online == True` and `main_job_id` to be present.
     - The lease is released and advances to the next queued clone when:
       - The active clone reports `secret_count == 0` (or `tradeState == "COMPLETED"` with `secret_count == 0`), OR
       - The active clone reports `tradeState == "ERROR"` with a terminal reason, OR
       - The active clone exceeds `leaseTimeoutSec` (`120s`) without completing, OR
       - The admin clicks **Skip / Cancel** on the Web Dashboard.

3. **Telemetry Response Directive (`trade_directive` in `POST /api/v1/telemetry` response):**
   Every `/api/v1/telemetry` response includes a `trade_directive` dictionary:
   - **For the Main Account (`role = "MAIN"`):**
     ```json
     {
       "enabled": true,
       "role": "MAIN",
       "action": "AUTO_ACCEPT",
       "activeCloneUserId": 9695124191,
       "activeCloneUsername": "BarryAri3l2007",
       "trustedUserIds": [9695138569, 9695155852, ...]
     }
     ```
   - **For the Currently Dispatched Clone (`role = "CLONE_ACTIVE"`):**
     ```json
     {
       "enabled": true,
       "role": "CLONE_ACTIVE",
       "action": "JOIN_AND_TRADE",
       "mainUserId": 123456789,
       "mainUsername": "YourMainAccount",
       "mainPlaceId": 72858262610964,
       "mainJobId": "a1b2c3d4-...",
       "unequipSecrets": true,
       "unlockSecrets": true,
       "hopOutAfterTrade": true
     }
     ```
   - **For Waiting Clones (`role = "CLONE_QUEUED"`) or Idle (`role = "IDLE"`):**
     ```json
     {
       "enabled": true,
       "role": "CLONE_QUEUED",
       "action": "WAIT",
       "queuePosition": 3
     }
     ```

4. **REST API Endpoints (`src/main.py`):**
   - `GET /api/v1/trade/status` (`require_read_access`) — Returns current auto-trade settings, Main Account online/jobId state, active clone lease details, ordered queue list, and recent trade completion log.
   - `POST /api/v1/trade/settings` (`require_admin`) — Updates `enabled`, `mainUserId`, `mainUsername`, `unequipSecrets`, `unlockSecrets`, `hopOutAfterTrade`.
   - `POST /api/v1/trade/queue/{user_id}` (`require_admin`) — Enqueues a specific clone account immediately to the front of the queue (works even if global auto-mode is toggled off, enabling 1-click single-account consolidation).
   - `POST /api/v1/trade/queue-all` (`require_admin`) — Enqueues all currently online clones with `secret_count > 0` and enables consolidation.
   - `POST /api/v1/trade/skip` (`require_admin`) — Releases the current active clone lease and moves to the next queued clone.

### 5.3. Luau Client Auto-Trade Engine (`scripts/tap_sim_reborn_tracker.lua`)

1. **Inspector & Runtime Controller/Remote Discovery:**
   - Expand `sendInspectorSnapshot()` `probePaths` to also inspect `Controllers.Trading`, `Shared.Trading`, `Packages`, and `PlayerGui.Trading` hierarchy so we have full visibility of every module key and remote signature.
   - Build a resilient **In-Game Action Binder** that locates the game's Pet & Trading functions via three layered strategies:
     1. **Controller Module API:** Require `ReplicatedStorage.Controllers.Trading.*`, `ReplicatedStorage.Shared.Trading.*`, `ReplicatedStorage.Controllers.Pets.InventoryController`, and `ReplicatedStorage.Controllers.Pets.PetController` (plus scanning `getgc(true)` for controller tables exposing `Network:InvokeServer` / `Comm` remote references for `Unequip`, `Lock`/`Unlock`, `RequestTrade`/`SendRequest`, `AcceptRequest`, `AddPet`/`OfferPet`, `Ready`/`Accept`/`Confirm`).
     2. **Comm / RemoteEvent / RemoteFunction Direct Invocation:** Discover `RemoteEvent` / `RemoteFunction` instances under `ReplicatedStorage` (`Packages._Index` / `Comm` / `Remotes` / `Network`) matching pet equip/unequip, lock/unlock, and trade actions.
     3. **PlayerGui UI Automation Fallback (`PlayerGui.Trading` & `Inventory`):** Programmatically fire button signals (`firesignal` / `getconnections(btn.Activated)` / `getconnections(btn.MouseButton1Click)` / `VirtualInputManager`) on the trade request prompt, pet cards inside `PlayerGui.Trading`, and the Ready/Confirm buttons.

2. **Clone Execution State Machine (`role == "CLONE_ACTIVE"` and `action == "JOIN_AND_TRADE"`):**
   - **Step 1 — Server Match & Teleport (`TELEPORTING`):**
     - Check if the Main Account player is currently in `Players:GetPlayers()` (matching `mainUserId` or case-insensitive `mainUsername`).
     - If NOT in the same server and `mainJobId` is valid (`mainJobId ~= ""` and `game.JobId ~= mainJobId`):
       - Queue auto-reload on teleport using `queue_on_teleport` (or `syn.queue_on_teleport` / `fluxus.queue_on_teleport`) with the TrackStats loader snippet (preserving `getgenv().TrackStats`).
       - Call `TeleportService:TeleportToPlaceInstance(mainPlaceId or game.PlaceId, mainJobId, LocalPlayer)` with a 15-second retry cooldown.
   - **Step 2 — Prepare All Secret Pets (`PREPARING_PETS`):**
     - When in the same server as the Main Account:
       - Enumerate all owned Secret pet instances (`UUID` keys) from `DataController:GetReplica().Data.Pets.Owned`.
       - For each Secret pet UUID where `Equip == true` (or present in `EquippedPets`): call the bound **Unequip** action so it can be traded.
       - For each Secret pet UUID where `Locked == true`: call the bound **Unlock** action (`Locked = false`).
   - **Step 3 — Request & Execute Trade (`REQUESTING_TRADE` -> `TRADING`):**
     - Ensure `TradeRequests` setting is enabled if disabled.
     - If no trade session is currently open: send a trade request to the Main Account `Player` instance (debounced every 4 seconds).
     - When the trade window/session opens with the Main Account:
       - Add each Secret pet UUID into the trade offer up to the per-trade slot cap.
       - Wait brief confirmation delay, then trigger **Ready / Confirm** on the trade.
       - Once the trade completes, re-check `DataController:GetReplica().Data.Pets.Owned`. If more Secret pets remain, repeat Step 3 for the next batch.
   - **Step 4 — Completion & Server Hop Out (`COMPLETED` -> `HOPPING_OUT`):**
     - Once 0 Secret pets remain in `repData.Pets.Owned`:
       - Immediately send a telemetry heartbeat with `secretPets = {}`, `tradeState = "COMPLETED"`.
       - If `hopOutAfterTrade == true`: queue `queue_on_teleport` and teleport out to a different server (`TeleportService:Teleport(game.PlaceId, LocalPlayer)` or a non-full server from `games.roblox.com/v1/games/<placeId>/servers/Public`) so the slot in the Main Account's server is freed immediately.

3. **Main Account Receiver State Machine (`role == "MAIN"` and `action == "AUTO_ACCEPT"`):**
   - Ensure `TradeRequests` player setting is enabled.
   - Listen for incoming trade request prompts/events from any player whose `UserId` is in `trustedUserIds` (or matches `activeCloneUserId` / `activeCloneUsername`).
   - Automatically accept the trade request.
   - While in an active trade session with a trusted farm clone:
     - Monitor the trade session state; as soon as the clone has added pets and/or marked Ready, automatically trigger **Ready / Accept / Confirm** until the trade finishes.

### 5.4. Web Dashboard UI (`src/static/index.html`, `src/static/js/app.js`, `src/static/css/style.css`)

- **Auto-Trade Command Banner (on both `Secret Vault` and `Multi-Account` tabs):**
  - **Main Account Selector:** Dropdown populated with known accounts + text input for custom Main Account Username or UserId.
  - **Status Pill:** Shows whether Main Account is `ONLINE (Server Ready)` or `WAIT FOR MAIN ACCOUNT`, current active clone being traded, and number of clones waiting in queue (`Queue: X clones • Y Secrets pending`).
  - **Controls:**
    - Toggle switch / button: **Auto-Trade All Secrets: ON / OFF**
    - Action button: **Queue All Now** (enqueues all clones with Secrets)
    - Action button: **Skip Current** (when a clone is active)
- **Per-Account Action Button in Multi-Account Table:**
  - Next to each clone account holding Secrets (`secret_count > 0`), add a **"Trade to Main"** button (and live badge showing `QUEUED #2`, `TELEPORTING`, `TRADING`, or `DONE`) plus a **"Set as Main"** option.

---

## 6. What Is Left to the Builder

- Exact CSS styling of the Auto-Trade Command Banner within the existing Cyber-Glass theme (`src/static/css/style.css`).
- Internal helper structuring inside `scripts/tap_sim_reborn_tracker.lua` and unit/integration test organization in `tests/test_auto_trade.py`.
