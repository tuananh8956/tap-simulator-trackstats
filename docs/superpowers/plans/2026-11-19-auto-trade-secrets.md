# Auto-Trade Secret Consolidation System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an automated Secret Pet consolidation system that queues clone accounts one at a time to join the Main Account's server, unequip and unlock 100% of their Secret pets, trade them to the Main Account (with automatic Main Account acceptance), and hop out to another server upon completion.

**Architecture:** The FastAPI backend (`Database` + `SessionManager` + `main.py`) persists auto-trade configuration, tracks each live account's `placeId`/`jobId`/`tradeState`, and coordinates a sequential 1-clone-at-a-time lease queue returned in `/api/v1/telemetry` responses as `trade_directive`. The unified Luau script (`scripts/tap_sim_reborn_tracker.lua`) inspects and binds `Controllers.Trading` / `Shared.Trading` / `Controllers.Pets` / `PlayerGui.Trading`, executes the Clone (`JOIN_AND_TRADE`) or Main (`AUTO_ACCEPT`) state machine, and persists across teleports via `queue_on_teleport`. The Web Dashboard (`index.html`, `app.js`, `style.css`) exposes a centralized Auto-Trade Command Panel and per-account trade buttons.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLite (WAL mode), Vanilla JS/CSS SPA, Roblox Luau.

**Spec:** `docs/superpowers/specs/2026-11-19-auto-trade-secrets-design.md`

## Global Constraints

- Target Place ID: `72858262610964`, Universe ID: `10629695169`.
- Single-line loader compatibility: All accounts load `/loader.lua` and hot-reload automatically when `script_version` increments (`"2.4.0"`).
- Sequential queue lease: At most `1` clone holds the active `JOIN_AND_TRADE` lease at a time, with a default `120s` lease timeout (`leaseTimeoutSec = 120`).
- Anti-hijack safety: Clones only trade with the configured Main Account (`mainUserId` / `mainUsername`); Main Account only auto-accepts trade requests from `trustedUserIds` in the TrackStats farm registry.
- Security gate: Write endpoints (`/api/v1/trade/settings`, `/api/v1/trade/queue/{user_id}`, `/api/v1/trade/queue-all`, `/api/v1/trade/skip`) require `require_admin`; read status (`/api/v1/trade/status`) uses `require_read_access`.

## Review Focus

1. **Main Account configured by username before its UserId is known:** When `mainUsername` is set (case-insensitively) and `mainUserId` is `None`, the coordinator must resolve `mainUserId` automatically as soon as an account with a matching username exists in `db.get_accounts()` or sends telemetry.
2. **Stalled or disconnected active clone:** If the active clone disconnects (`connection_status != "LIVE"`) or exceeds `leaseTimeoutSec` (`120s`), the coordinator must expire its lease on the next check/heartbeat and assign the next eligible clone with `secret_count > 0`.
3. **Clone completing trade (`secret_count == 0` or `tradeState == "COMPLETED"`):** As soon as the active clone reports `0` secrets (or `tradeState == "COMPLETED"` with `0` secrets), its lease must be released, a 15-second cooldown applied so it isn't immediately re-queued, and the next clone promoted.
4. **Main Account offline or missing `jobId`:** When the Main Account is offline or has not reported a non-empty `jobId`, clones with Secrets must remain in `CLONE_QUEUED` (`action = "WAIT"`) rather than receiving an empty `mainJobId` teleport instruction.
5. **Admin authentication enforcement on trade write endpoints:** When `TRACKSTATS_ADMIN_PASSWORD` is configured, unauthenticated `POST /api/v1/trade/*` requests must return HTTP `401`.

---

### Task 1: Data Models & Persistent Auto-Trade Settings

**Files:**
- Modify: `src/models.py:205-285`
- Modify: `src/database.py:720-780`
- Create: `tests/test_auto_trade.py`

**Interfaces:**
- Consumes: `Database.get_setting(key: str, default: Any)`, `Database.set_setting(key: str, value: Any)` in `src/database.py`
- Produces:
  - Extended `TelemetryPayload` fields in `src/models.py`: `placeId: Optional[int] = None`, `jobId: Optional[str] = None`, `tradeState: Optional[str] = None`, `tradeMessage: Optional[str] = None`, `secretInstanceIds: Optional[List[str]] = None`
  - `AutoTradeSettings` & `AutoTradeSettingsUpdate` Pydantic models in `src/models.py`
  - `Database.get_auto_trade_settings() -> Dict[str, Any]` and `Database.save_auto_trade_settings(settings_dict: Dict[str, Any]) -> Dict[str, Any]` in `src/database.py`

- [ ] **Step 1: Write the failing tests for models and database persistence**

```python
from src.models import TelemetryPayload, AutoTradeSettings, AutoTradeSettingsUpdate
from src.database import Database


def test_telemetry_payload_accepts_trade_and_server_fields():
    p = TelemetryPayload(
        userId=111,
        placeId=72858262610964,
        jobId="job-abc-123",
        tradeState="TRADING",
        tradeMessage="Offering 6 secrets",
        secretInstanceIds=["uuid-1", "uuid-2"],
    )
    assert p.placeId == 72858262610964
    assert p.jobId == "job-abc-123"
    assert p.tradeState == "TRADING"
    assert p.secretInstanceIds == ["uuid-1", "uuid-2"]


def test_database_auto_trade_settings_roundtrip(tmp_path):
    db = Database(str(tmp_path / "trade.db"))
    db.init_db()
    defaults = db.get_auto_trade_settings()
    assert defaults["enabled"] is False
    assert defaults["unequipSecrets"] is True
    assert defaults["unlockSecrets"] is True
    assert defaults["hopOutAfterTrade"] is True
    assert defaults["leaseTimeoutSec"] == 120

    updated = db.save_auto_trade_settings(
        {
            "enabled": True,
            "mainUserId": 99999,
            "mainUsername": "MainBoss",
            "unequipSecrets": True,
            "unlockSecrets": True,
            "hopOutAfterTrade": False,
            "leaseTimeoutSec": 90,
        }
    )
    assert updated["enabled"] is True
    assert updated["mainUserId"] == 99999
    assert updated["mainUsername"] == "MainBoss"
    assert updated["hopOutAfterTrade"] is False
    assert updated["leaseTimeoutSec"] == 90
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_trade.py -v`
Expected: FAIL with `ImportError: cannot import name 'AutoTradeSettings' from 'src.models'`

- [ ] **Step 3: Implement `TelemetryPayload` extensions, `AutoTradeSettings`, `AutoTradeSettingsUpdate` in `src/models.py` and `get_auto_trade_settings` / `save_auto_trade_settings` in `src/database.py`**

In `src/models.py`:
- Add `placeId`, `jobId`, `tradeState`, `tradeMessage`, `secretInstanceIds` to `TelemetryPayload`.
- Define `AutoTradeSettings(BaseModel)` with defaults `enabled=False`, `mainUserId=None`, `mainUsername=""`, `unequipSecrets=True`, `unlockSecrets=True`, `hopOutAfterTrade=True`, `leaseTimeoutSec=120`.
- Define `AutoTradeSettingsUpdate(BaseModel)` with optional fields matching `AutoTradeSettings`.

In `src/database.py`:
- Store and retrieve `"auto_trade_settings"` in `settings_kv` via `get_auto_trade_settings()` and `save_auto_trade_settings(data)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auto_trade.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/models.py src/database.py tests/test_auto_trade.py
git commit -m "feat(models): add auto-trade telemetry fields and persistent settings"
```

---

### Task 2: Backend Queue Coordinator & REST Endpoints

**Files:**
- Modify: `src/session_manager.py:20-360`
- Modify: `src/main.py:238-270,365-435,555-580`
- Test: `tests/test_auto_trade.py`

**Interfaces:**
- Consumes: `TelemetryPayload`, `AutoTradeSettingsUpdate`, `Database.get_auto_trade_settings()`, `Database.save_auto_trade_settings()` from Task 1
- Produces:
  - `SessionManager.get_trade_status(now: Optional[float] = None) -> Dict[str, Any]`
  - `SessionManager.update_trade_settings(req: AutoTradeSettingsUpdate) -> Dict[str, Any]`
  - `SessionManager.enqueue_clone_for_trade(user_id: int) -> Dict[str, Any]`
  - `SessionManager.enqueue_all_clones_for_trade() -> Dict[str, Any]`
  - `SessionManager.skip_active_trade_clone() -> Dict[str, Any]`
  - `trade_directive` included in `SessionManager.process_telemetry(payload)` and returned by `POST /api/v1/telemetry`
  - REST endpoints in `src/main.py`: `GET /api/v1/trade/status`, `POST /api/v1/trade/settings`, `POST /api/v1/trade/queue/{user_id}`, `POST /api/v1/trade/queue-all`, `POST /api/v1/trade/skip`, plus `trade_status` in `GET /api/v1/stream` and per-account `job_id`/`trade_state`/`trade_role` in `GET /api/v1/accounts`

- [ ] **Step 1: Write the failing tests for queue coordination, lease timeout, username resolution, and REST endpoints**

```python
from fastapi.testclient import TestClient
from src.main import app, session_manager, db
from src.models import PetItem


def test_coordinator_assigns_one_clone_at_a_time_and_advances_on_completion(tmp_path):
    client = TestClient(app)
    # Register Main Account (userId 1000) and two Clones (2001 with 3 secrets, 2002 with 8 secrets)
    db.upsert_account(1000, "MainAcc", "MainAcc", "")
    db.upsert_account(2001, "CloneA", "CloneA", "")
    db.upsert_account(2002, "CloneB", "CloneB", "")

    # Configure Auto-Trade by username only to verify Review Focus #1
    res_cfg = client.post(
        "/api/v1/trade/settings",
        json={"enabled": True, "mainUsername": "mainacc"},
    )
    assert res_cfg.status_code == 200
    assert res_cfg.json()["settings"]["mainUserId"] == 1000

    # CloneA and CloneB report Secrets while Main is still offline (Review Focus #4)
    r_a = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2001,
            "placeId": 72858262610964,
            "jobId": "job-clone-a",
            "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 3}],
        },
    ).json()
    assert r_a["trade_directive"]["role"] == "CLONE_QUEUED"
    assert r_a["trade_directive"]["action"] == "WAIT"

    r_b = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2002,
            "placeId": 72858262610964,
            "jobId": "job-clone-b",
            "secretPets": [{"name": "Operating System", "rarity": "Secret", "count": 8}],
        },
    ).json()

    # Main Account comes online with jobId "job-main-server"
    r_main = client.post(
        "/api/v1/telemetry",
        json={"userId": 1000, "placeId": 72858262610964, "jobId": "job-main-server"},
    ).json()
    assert r_main["trade_directive"]["role"] == "MAIN"
    assert r_main["trade_directive"]["action"] == "AUTO_ACCEPT"
    # CloneB (8 secrets > 3 secrets) should be selected first!
    assert r_main["trade_directive"]["activeCloneUserId"] == 2002

    # CloneB heartbeat receives CLONE_ACTIVE with mainJobId
    r_b2 = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2002,
            "placeId": 72858262610964,
            "jobId": "job-main-server",
            "tradeState": "TRADING",
            "secretPets": [{"name": "Operating System", "rarity": "Secret", "count": 8}],
        },
    ).json()
    assert r_b2["trade_directive"]["role"] == "CLONE_ACTIVE"
    assert r_b2["trade_directive"]["action"] == "JOIN_AND_TRADE"
    assert r_b2["trade_directive"]["mainJobId"] == "job-main-server"

    # While CloneB is active, CloneA remains CLONE_QUEUED
    r_a2 = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2001,
            "placeId": 72858262610964,
            "jobId": "job-clone-a",
            "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 3}],
        },
    ).json()
    assert r_a2["trade_directive"]["role"] == "CLONE_QUEUED"

    # CloneB finishes trading all secrets (secretPets = [], tradeState = COMPLETED) -> advances to CloneA (Review Focus #3)
    r_b_done = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2002,
            "placeId": 72858262610964,
            "jobId": "job-main-server",
            "tradeState": "COMPLETED",
            "secretPets": [],
        },
    ).json()
    assert r_b_done["trade_directive"]["role"] == "IDLE"

    # Next heartbeat for CloneA promotes CloneA to CLONE_ACTIVE
    r_a3 = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2001,
            "placeId": 72858262610964,
            "jobId": "job-clone-a",
            "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 3}],
        },
    ).json()
    assert r_a3["trade_directive"]["role"] == "CLONE_ACTIVE"
    assert r_a3["trade_directive"]["mainJobId"] == "job-main-server"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_trade.py::test_coordinator_assigns_one_clone_at_a_time_and_advances_on_completion -v`
Expected: FAIL with `404 Not Found` on `/api/v1/trade/settings`

- [ ] **Step 3: Implement queue coordinator in `src/session_manager.py` and REST endpoints in `src/main.py`**

In `src/session_manager.py`:
- Track `_place_id: Dict[int, Optional[int]]`, `_job_id: Dict[int, Optional[str]]`, `_trade_state: Dict[int, str]`, `_trade_message: Dict[int, Optional[str]]`, `_priority_trade_queue: List[int]`, `_active_trade_clone: Optional[int]`, `_active_trade_leased_at: float`, `_trade_cooldown_until: Dict[int, float]`, and `_recent_trade_completions: List[Dict[str, Any]]`.
- Resolve `mainUserId` from `mainUsername` case-insensitively whenever `mainUsername` matches a known account.
- Compute queue ordering: priority queue accounts (with `secret_count > 0` and `LIVE`) first, then when `enabled == True` all `LIVE` accounts with `secret_count > 0` and `user_id != main_user_id` sorted by `(-secret_count, user_id)`.
- Expire `_active_trade_clone` if its `connection_status != "LIVE"`, or `now - _active_trade_leased_at >= leaseTimeoutSec`, or `secret_count == 0`, or `tradeState == "COMPLETED"` with `secret_count == 0`.
- Build `trade_directive` for `user_id` during `process_telemetry` and include `job_id`, `place_id`, `trade_state`, `trade_message`, and `trade_role` in `get_live_state(user_id)`.
- Add tests for lease timeout advancing (`Review Focus #2`), manual per-account queueing (`/api/v1/trade/queue/{user_id}`), skip (`/api/v1/trade/skip`), and admin auth gate (`Review Focus #5`).

In `src/main.py`:
- Expose `GET /api/v1/trade/status`, `POST /api/v1/trade/settings`, `POST /api/v1/trade/queue/{user_id}`, `POST /api/v1/trade/queue-all`, `POST /api/v1/trade/skip`.
- Include `trade_directive` in `POST /api/v1/telemetry` response, increment `script_version` to `"2.4.0"`, and include `trade_status` in `GET /api/v1/stream`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_auto_trade.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/session_manager.py src/main.py tests/test_auto_trade.py
git commit -m "feat(backend): add sequential auto-trade queue coordinator and REST API"
```

---

### Task 3: Luau Dual-Role Auto-Trade Engine & Trading Inspector

**Files:**
- Modify: `scripts/tap_sim_reborn_tracker.lua:16-100,1640-1905`
- Test: `tests/test_auto_trade.py`

**Interfaces:**
- Consumes: `trade_directive` from `POST /api/v1/telemetry` response (`role`, `action`, `mainUserId`, `mainUsername`, `mainPlaceId`, `mainJobId`, `unequipSecrets`, `unlockSecrets`, `hopOutAfterTrade`, `trustedUserIds`, `activeCloneUserId`)
- Produces:
  - `SCRIPT_VERSION = "2.4.0"` in `scripts/tap_sim_reborn_tracker.lua`
  - Extended Inspector probe paths (`Controllers.Trading`, `Shared.Trading`, `Packages`, `PlayerGui.Trading` hierarchy)
  - Telemetry fields `placeId`, `jobId`, `tradeState`, `tradeMessage`, `secretInstanceIds` sent in every heartbeat
  - `queueTeleportLoader()` helper supporting `queue_on_teleport`, `syn.queue_on_teleport`, `fluxus.queue_on_teleport`
  - Dynamic Pet Action & Trading Binder (`unequipSecretPet(uuid)`, `unlockSecretPet(uuid)`, `ensureTradeRequestsEnabled()`, `requestTradeWithPlayer(targetPlayer)`, `acceptIncomingTrade(trustedSet)`, `offerSecretPetsAndConfirm(secretUuids, targetPlayer)`, `confirmReceiveTrade(trustedSet)`, `hopToAnotherServer()`)

- [ ] **Step 1: Write the failing test verifying Luau script v2.4.0 auto-trade engine structure**

```python
from pathlib import Path


def test_luau_script_contains_v240_auto_trade_engine():
    lua_path = Path(__file__).resolve().parent.parent / "scripts" / "tap_sim_reborn_tracker.lua"
    src = lua_path.read_text(encoding="utf-8")
    assert 'local SCRIPT_VERSION = "2.4.0"' in src
    assert "Controllers.Trading" in src
    assert "Shared.Trading" in src
    assert "TeleportToPlaceInstance" in src
    assert "queue_on_teleport" in src
    assert "trade_directive" in src
    assert "JOIN_AND_TRADE" in src
    assert "AUTO_ACCEPT" in src
    assert "unequipSecretPets" in src
    assert "unlockSecretPets" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_trade.py::test_luau_script_contains_v240_auto_trade_engine -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Implement Dual-Role Auto-Trade Engine & Trading Inspector in `scripts/tap_sim_reborn_tracker.lua`**

In `scripts/tap_sim_reborn_tracker.lua`:
1. Bump `SCRIPT_VERSION = "2.4.0"`.
2. Add `Controllers.Trading` and `Shared.Trading` to `sendInspectorSnapshot()` `probePaths`, plus a dedicated `dump.tradingGuiDetails` scan of `PlayerGui:FindFirstChild("Trading")` (listing frames, buttons, and remote/controller methods).
3. Collect exact `secretInstanceIds` (all UUIDs from `DataController:GetReplica().Data.Pets.Owned` that are Secret pets, along with their `Equip` and `Locked` flags).
4. Implement multi-strategy Pet & Trading action executor:
   - **Discover Trading & Pet Controllers/Remotes:** Inspect `ReplicatedStorage.Controllers.Trading`, `ReplicatedStorage.Shared.Trading`, `ReplicatedStorage.Controllers.Pets.InventoryController`, `ReplicatedStorage.Controllers.Pets.PetController`, `getgc(true)` tables with `Network` / `InvokeServer` / `FireServer`, and all `RemoteEvent` / `RemoteFunction` instances in `ReplicatedStorage`.
   - **Auto-Unequip & Auto-Unlock (`unequipSecretPets` & `unlockSecretPets`):** For every Secret UUID in `repData.Pets.Owned`, if `Equip == true` (or in `EquippedPets`), call controller/remote unequip (and UI unequip button fallback via `InventoryController:SelectPet(uuid)` + `GetUnequipButton()`); if `Locked == true`, call controller/remote unlock (`Lock` / `ToggleLock` / `SetLocked(uuid, false)`).
   - **Clone Active Flow (`JOIN_AND_TRADE`):**
     - Check if Main Account is in `Players:GetPlayers()`. If not, and `mainJobId` differs from `game.JobId`, register `queue_on_teleport` with the loader snippet and call `TeleportService:TeleportToPlaceInstance(mainPlaceId, mainJobId, LocalPlayer)`.
     - Once Main Account is in the server: unequip & unlock all Secret UUIDs -> send trade request to Main Account player -> when trade session is active with Main Account, add Secret UUIDs (via controller/remote + `PlayerGui.Trading` pet card buttons) -> trigger Ready/Confirm/Accept.
     - When `0` Secret pets remain in `repData.Pets.Owned`, set `tradeState = "COMPLETED"`, post telemetry immediately, and if `hopOutAfterTrade == true`, register `queue_on_teleport` and hop to another server (`TeleportService:Teleport(game.PlaceId, LocalPlayer)`).
   - **Main Account Flow (`AUTO_ACCEPT`):**
     - Listen for incoming trade request prompts/signals from `trustedUserIds` (or `activeCloneUserId`) -> automatically invoke Accept on controller/remote and `PlayerGui` prompt buttons -> in active trade with trusted clone, once clone offers pets or marks ready, automatically invoke Ready/Accept/Confirm.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_auto_trade.py::test_luau_script_contains_v240_auto_trade_engine -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/tap_sim_reborn_tracker.lua tests/test_auto_trade.py
git commit -m "feat(luau): add v2.4.0 dual-role auto-trade engine and trading inspector"
```

---

### Task 4: Web Dashboard Auto-Trade Command Center & Per-Account Controls

**Files:**
- Modify: `src/static/index.html:85-195`
- Modify: `src/static/js/app.js:100-750`
- Modify: `src/static/css/style.css:600-880`
- Test: `tests/test_auto_trade.py`

**Interfaces:**
- Consumes: `GET /api/v1/trade/status`, `POST /api/v1/trade/settings`, `POST /api/v1/trade/queue/{user_id}`, `POST /api/v1/trade/queue-all`, `POST /api/v1/trade/skip`, SSE `trade_status`
- Produces:
  - Auto-Trade Consolidation Command Card (`#autoTradeCard`) in `src/static/index.html` with Main Account selector/input (`#tradeMainAccountInput`, `#tradeMainAccountSelect`), toggle button (`#btnToggleAutoTrade`), **"Gom Tất Cả (Queue All)"** button (`#btnQueueAllTrades`), **"Bỏ Qua Acc Kẹt (Skip)"** button (`#btnSkipActiveTrade`), and live queue status banner (`#autoTradeStatusBanner`).
  - Per-account **"Trade to Main"** & **"Set Main"** buttons and live trade state badge in `#multiAccountsTableBody` (`src/static/js/app.js`).

- [ ] **Step 1: Write the failing UI test verifying Auto-Trade controls in `index.html` and `app.js`**

```python
from fastapi.testclient import TestClient
from src.main import app


def test_dashboard_includes_auto_trade_command_center():
    client = TestClient(app)
    html = client.get("/").text
    assert 'id="autoTradeCard"' in html
    assert 'id="tradeMainAccountInput"' in html
    assert 'id="btnToggleAutoTrade"' in html
    assert 'id="btnQueueAllTrades"' in html
    assert 'id="btnSkipActiveTrade"' in html

    js = client.get("/static/js/app.js").text
    assert "/api/v1/trade/status" in js
    assert "/api/v1/trade/settings" in js
    assert "/api/v1/trade/queue/" in js
    assert "queueAccountTrade" in js
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_auto_trade.py::test_dashboard_includes_auto_trade_command_center -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Implement Auto-Trade Command Center in `src/static/index.html`, `src/static/js/app.js`, and `src/static/css/style.css`**

In `src/static/index.html`:
- Add `#autoTradeCard` above the Secret Vault / Multi-Account view panels so it is accessible from both tabs.
- Include `#tradeMainAccountSelect` (dropdown of tracked accounts) + `#tradeMainAccountInput` (Username or UserId input), `#btnSaveMainAccount`, `#btnToggleAutoTrade`, `#btnQueueAllTrades`, `#btnSkipActiveTrade`, and `#autoTradeStatusBanner`.

In `src/static/js/app.js`:
- Fetch `/api/v1/trade/status` on startup and update live via SSE (`data.trade_status`).
- Render Main Account online/server status (`LIVE in Server ...` vs `Offline / Waiting for Main Account`), currently active clone (`CLONE_ACTIVE` + `trade_state`), and waiting queue pills.
- Wire `saveTradeSettings()`, `toggleAutoTrade()`, `queueAllClonesTrade()`, `skipActiveTrade()`, `queueAccountTrade(userId)`, and `setAsMainAccount(username, userId)`.
- In `renderMultiAccountsTable()`, display a live trade status badge (`MAIN ACC`, `TRADING`, `TELEPORTING`, `QUEUED #N`) and a 1-click **"Trade to Main"** button for any clone with `secret_count > 0`.

In `src/static/css/style.css`:
- Add cyber-glass styling for `.auto-trade-card`, `.trade-queue-strip`, and `.trade-badge-*` pills.

- [ ] **Step 4: Run the entire test suite to verify all tests pass**

Run: `pytest tests/ -v`
Expected: PASS (100% pass across all existing and new tests)

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html src/static/js/app.js src/static/css/style.css tests/test_auto_trade.py
git commit -m "feat(ui): add Auto-Trade Secret Consolidation command center and per-account controls"
```
