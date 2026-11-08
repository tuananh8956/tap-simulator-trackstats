# Tap Simulator Reborn – TrackStats Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent, legitimate, high-performance real-time statistics tracker and Dark UI dashboard for Roblox *Tap Simulator Reborn* without cookies, memory injection, or unverified APIs.

**Architecture:** An asynchronous FastAPI backend combines a public Roblox presence poller (for zero-auth profile and game status) with a high-throughput local telemetry ingestion bridge (`POST /api/v1/telemetry`), backed by a rolling circular rate engine, an SQLite time-series database, and a vanilla JS / Chart.js Dark UI served directly by FastAPI.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, SQLite, HTTPX, Pydantic v2, Pytest, Vanilla HTML5/CSS3/JavaScript, Chart.js.

**Spec:** `docs/superpowers/specs/2026-11-08-tap-simulator-reborn-trackstats-design.md`

## Global Constraints

- Never request, read, or store Roblox `.ROBLOSECURITY` cookies, passwords, or session tokens.
- Never inject DLLs, inspect memory, or hook into the Roblox client process.
- In-game stats are strictly accepted via the open `POST /api/v1/telemetry` contract; public presence is gathered via official endpoints (`users.roblox.com`, `presence.roblox.com`, `thumbnails.roblox.com`).
- Telemetry stream is authoritative for in-game session lifecycle; presence serves as non-blocking metadata enrichment.
- Keep CPU idle under 1% and RAM footprint low by using async I/O and zero heavy polling loops.

## Review Focus

1. **Rebirth Anomaly Handling:** When a player rebirths, `currentTaps` drops to 0 or resets. The rate engine must fall back to `totalTaps` delta and not produce a massive negative TPS spike.
2. **Private Roblox Presence:** When a user's Roblox privacy settings hide in-game status, the system must not terminate the tracking session as long as telemetry heartbeats arrive within 15 seconds.
3. **Rapid Telemetry Jitter:** Telemetry arrival intervals can vary (e.g. 50ms to 2000ms). The sub-second TPS calculator must compute $\frac{\Delta \text{Taps}}{\Delta t}$ with high-precision timestamps, guarding against division by zero if $\Delta t < 0.001$.
4. **Multi-Account State Isolation:** When Account A is tracking and Account B is paused, telemetry for Account B must be acknowledged without recording snapshots, and snapshots must never bleed between account sessions.
5. **Database Crash Recovery:** If the application process is terminated unexpectedly during an active session, starting up again must safely recover SQLite state, auto-close dangling open sessions, and remain operational.

---

### Task 1: Project Scaffolding, Configuration, and Data Models

**Files:**
- Create: `requirements.txt`
- Create: `src/__init__.py`
- Create: `src/config.py`
- Create: `src/models.py`
- Test: `tests/__init__.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `Settings`: Application settings dataclass (`db_path: str`, `port: int`, `stale_timeout_sec: float`, `disconnect_timeout_sec: float`).
  - `PetItem`: Pydantic model (`id: str`, `name: str`, `rarity: str`, `multiplier: float`, `power: float`).
  - `TelemetryPayload`: Pydantic model (`userId: int`, `currentTaps: int`, `totalTaps: int`, `currentRebirths: int`, `totalRebirths: int`, `currentWins: int`, `totalWins: int`, `currentCurrency: int`, `equippedPets: list[PetItem]`, `petInventoryCount: int`, `totalPetPower: float`, `timestamp: float`).
  - `AccountInfo`: Model for tracked account profile.
  - `SessionSummary`: Model for session statistics.

- [ ] **Step 1: Write the failing tests for models and configuration**

```python
# tests/test_models.py
import pytest
from src.models import TelemetryPayload, PetItem

def test_telemetry_payload_validation():
    payload_data = {
        "userId": 12345678,
        "currentTaps": 1500,
        "totalTaps": 50000,
        "currentRebirths": 5,
        "totalRebirths": 5,
        "currentWins": 10,
        "totalWins": 10,
        "currentCurrency": 250000,
        "equippedPets": [
            {"id": "p1", "name": "Hydra", "rarity": "Legendary", "multiplier": 150.0, "power": 3000.0}
        ],
        "petInventoryCount": 20,
        "totalPetPower": 15000.0,
        "timestamp": 1700000000.0
    }
    payload = TelemetryPayload(**payload_data)
    assert payload.userId == 12345678
    assert len(payload.equippedPets) == 1
    assert payload.equippedPets[0].name == "Hydra"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.models'`

- [ ] **Step 3: Implement `requirements.txt`, `src/config.py`, and `src/models.py`**

Implement Pydantic models with camelCase / snake_case aliases, default timestamp generation, and settings configuration.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_models.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt src/ tests/
git commit -m "feat: setup models, config and validation tests"
```

---

### Task 2: SQLite Storage Engine, Migrations, and Export/Restore

**Files:**
- Create: `src/database.py`
- Test: `tests/test_database.py`

**Interfaces:**
- Consumes: `src.models` (`TelemetryPayload`, `AccountInfo`)
- Produces:
  - `Database`: Class with methods:
    - `init_db()`
    - `upsert_account(user_id: int, username: str, display_name: str, avatar_url: str) -> None`
    - `set_account_tracking(user_id: int, is_tracking: bool) -> None`
    - `get_accounts() -> list[dict]`
    - `start_session(user_id: int, start_time: float, initial_taps: int, initial_rebirths: int) -> str`
    - `end_session(session_id: str, end_time: float, final_taps: int, final_rebirths: int, max_tps: float, avg_tps: float) -> None`
    - `insert_snapshot(session_id: str, payload: TelemetryPayload, tps: float) -> None`
    - `get_recent_snapshots(user_id: int, limit: int = 100) -> list[dict]`
    - `get_sessions(user_id: int) -> list[dict]`
    - `export_data(format: str) -> str` (CSV or JSON string)
    - `restore_data(json_str: str) -> bool`

- [ ] **Step 1: Write the failing tests for database operations**

```python
# tests/test_database.py
import pytest
from src.database import Database
from src.models import TelemetryPayload

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_trackstats.db"
    db = Database(str(db_file))
    db.init_db()
    return db

def test_account_crud_and_session(test_db):
    test_db.upsert_account(101, "PlayerOne", "P1", "https://avatar/101.png")
    accounts = test_db.get_accounts()
    assert len(accounts) == 1
    assert accounts[0]["user_id"] == 101
    
    session_id = test_db.start_session(101, 1700000000.0, 100, 1)
    assert session_id is not None
    
    test_db.end_session(session_id, 1700000100.0, 200, 2, 5.0, 1.0)
    sessions = test_db.get_sessions(101)
    assert len(sessions) == 1
    assert sessions[0]["taps_gained"] == 100
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.database'`

- [ ] **Step 3: Implement `Database` in `src/database.py`**

Implement connection handling, thread-safe SQLite operations, table initialization, parameterized queries, and JSON/CSV export routines.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_database.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/database.py tests/test_database.py
git commit -m "feat: implement SQLite database storage and session tracking"
```

---

### Task 3: Rate Engine & Rolling Metrics

**Files:**
- Create: `src/rate_engine.py`
- Test: `tests/test_rate_engine.py`

**Interfaces:**
- Consumes: `src.models.TelemetryPayload`
- Produces:
  - `RateEngine`: Class with methods:
    - `add_record(user_id: int, payload: TelemetryPayload) -> dict`: Calculates instant TPS and updates circular buffer.
    - `get_rates(user_id: int) -> dict`: Returns `{"tps": float, "rates": {"1m": {...}, "5m": {...}, "15m": {...}}}`.
    - `reset_account(user_id: int) -> None`

- [ ] **Step 1: Write the failing tests for rate calculations and rebirth anomalies**

```python
# tests/test_rate_engine.py
import pytest
from src.rate_engine import RateEngine
from src.models import TelemetryPayload

def test_tps_calculation_and_rebirth_fallback():
    engine = RateEngine()
    
    # Record 1 at t=0
    p1 = TelemetryPayload(
        userId=1, currentTaps=1000, totalTaps=10000, currentRebirths=1,
        totalRebirths=1, currentWins=0, totalWins=0, currentCurrency=100,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=100.0
    )
    r1 = engine.add_record(1, p1)
    assert r1["tps"] == 0.0
    
    # Record 2 at t=2 (gained 50 taps -> 25 TPS)
    p2 = TelemetryPayload(
        userId=1, currentTaps=1050, totalTaps=10050, currentRebirths=1,
        totalRebirths=1, currentWins=0, totalWins=0, currentCurrency=150,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=102.0
    )
    r2 = engine.add_record(1, p2)
    assert r2["tps"] == 25.0
    
    # Record 3: Player rebirthed (currentTaps drops to 10, totalTaps increases to 10070 at t=3)
    p3 = TelemetryPayload(
        userId=1, currentTaps=10, totalTaps=10070, currentRebirths=2,
        totalRebirths=2, currentWins=0, totalWins=0, currentCurrency=200,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=103.0
    )
    r3 = engine.add_record(1, p3)
    # Should NOT be negative; must fallback to delta totalTaps (20 taps / 1s = 20 TPS)
    assert r3["tps"] == 20.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rate_engine.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.rate_engine'`

- [ ] **Step 3: Implement `RateEngine` in `src/rate_engine.py`**

Implement ring buffer with timestamp window pruning (up to 900 seconds) and delta rate calculations for 1m, 5m, and 15m. Guard against division by zero when $\Delta t < 0.001$.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rate_engine.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/rate_engine.py tests/test_rate_engine.py
git commit -m "feat: implement rate engine with rolling rates and rebirth protection"
```

---

### Task 4: Roblox Public Presence Poller

**Files:**
- Create: `src/roblox_poller.py`
- Test: `tests/test_roblox_poller.py`

**Interfaces:**
- Produces:
  - `RobloxPoller`: Class with methods:
    - `async get_user_info(user_id: int) -> dict`: Returns `{"id": int, "name": str, "displayName": str}`.
    - `async get_user_avatar(user_id: int) -> str`: Returns headshot PNG URL.
    - `async get_user_presence(user_id: int) -> dict`: Returns presence info, `is_in_target_game: bool`.

- [ ] **Step 1: Write the failing tests with mocked HTTP responses**

```python
# tests/test_roblox_poller.py
import pytest
from unittest.mock import AsyncMock, patch
from src.roblox_poller import RobloxPoller, TARGET_PLACE_ID

@pytest.mark.asyncio
async def test_roblox_poller_target_game():
    poller = RobloxPoller()
    
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = AsyncMock(
            status_code=200,
            json=lambda: {
                "userPresences": [
                    {
                        "userId": 12345,
                        "userPresenceType": 2,
                        "lastLocation": "Tap Simulator REBORN",
                        "placeId": TARGET_PLACE_ID,
                        "gameId": "mock-job-id"
                    }
                ]
            }
        )
        presence = await poller.get_user_presence(12345)
        assert presence["is_in_target_game"] is True
        assert presence["status"] == "InGame"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_roblox_poller.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.roblox_poller'`

- [ ] **Step 3: Implement `RobloxPoller` in `src/roblox_poller.py`**

Implement HTTP client with caching, 5-second debouncing per user, HTTP 429 backoff, and graceful handling of private presence.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_roblox_poller.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/roblox_poller.py tests/test_roblox_poller.py
git commit -m "feat: implement roblox public presence poller with rate limiting"
```

---

### Task 5: Session Manager & Lifecycle State Machine

**Files:**
- Create: `src/session_manager.py`
- Test: `tests/test_session_manager.py`

**Interfaces:**
- Consumes: `Database`, `RateEngine`, `RobloxPoller`, `TelemetryPayload`
- Produces:
  - `SessionManager`: Class with methods:
    - `process_telemetry(payload: TelemetryPayload) -> dict`: Ingests payload, updates rate engine, handles session transitions.
    - `check_timeouts() -> None`: Evaluates active accounts for `LIVE` $\rightarrow$ `STALE` $\rightarrow$ `DISCONNECTED` transitions.
    - `get_live_state(user_id: int) -> dict`: Aggregates active status, latest telemetry, TPS, growth rates, session duration.
    - `toggle_tracking(user_id: int, is_tracking: bool) -> bool`

- [ ] **Step 1: Write the failing tests for session transitions and timeout logic**

```python
# tests/test_session_manager.py
import pytest
from src.session_manager import SessionManager
from src.database import Database
from src.rate_engine import RateEngine
from src.models import TelemetryPayload

@pytest.fixture
def manager(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    db.init_db()
    db.upsert_account(101, "TestUser", "Test", "")
    rate_engine = RateEngine()
    return SessionManager(db, rate_engine, poller=None)

def test_session_lifecycle(manager):
    p = TelemetryPayload(
        userId=101, currentTaps=100, totalTaps=1000, currentRebirths=1,
        totalRebirths=1, currentWins=0, totalWins=0, currentCurrency=50,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=1000.0
    )
    res = manager.process_telemetry(p)
    assert res["status"] == "processed"
    state = manager.get_live_state(101)
    assert state["connection_status"] == "LIVE"
    assert state["active_session_id"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_manager.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.session_manager'`

- [ ] **Step 3: Implement `SessionManager` in `src/session_manager.py`**

Implement session auto-creation on initial telemetry, timeout checks (15s for STALE, 60s for DISCONNECTED), and per-account tracking status controls.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_session_manager.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/session_manager.py tests/test_session_manager.py
git commit -m "feat: implement session manager with authoritative telemetry lifecycle"
```

---

### Task 6: FastAPI Application & REST/SSE Endpoints

**Files:**
- Create: `src/main.py`
- Create: `run.py`
- Test: `tests/test_api_endpoints.py`

**Interfaces:**
- Exposes:
  - `POST /api/v1/telemetry`: Accepts `TelemetryPayload`.
  - `GET /api/v1/accounts`: Lists tracked accounts.
  - `POST /api/v1/accounts`: Adds account by `userId`.
  - `DELETE /api/v1/accounts/{user_id}`: Removes account.
  - `POST /api/v1/accounts/{user_id}/tracking`: Sets tracking state.
  - `GET /api/v1/accounts/{user_id}/live`: Gets full live statistics.
  - `GET /api/v1/export/csv`: Downloads CSV export.
  - `GET /api/v1/export/json`: Downloads JSON export.
  - `GET /api/v1/stream`: Server-Sent Events (SSE) broadcasting live updates.

- [ ] **Step 1: Write the failing tests for API endpoints**

```python
# tests/test_api_endpoints.py
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_telemetry_post_and_accounts():
    # 1. Post telemetry
    payload = {
        "userId": 99999,
        "currentTaps": 500,
        "totalTaps": 10000,
        "currentRebirths": 2,
        "totalRebirths": 2,
        "currentWins": 5,
        "totalWins": 5,
        "currentCurrency": 10000,
        "equippedPets": [],
        "petInventoryCount": 5,
        "totalPetPower": 100.0,
        "timestamp": 1700000000.0
    }
    response = client.post("/api/v1/telemetry", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    
    # 2. Get accounts
    acc_resp = client.get("/api/v1/accounts")
    assert acc_resp.status_code == 200
    data = acc_resp.json()
    assert any(a["user_id"] == 99999 for a in data)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_endpoints.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'src.main'`

- [ ] **Step 3: Implement `src/main.py` and `run.py`**

Wire FastAPI router, mount static files directory, implement SSE broadcaster queue, and lifespan background timeout task.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_api_endpoints.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main.py run.py tests/test_api_endpoints.py
git commit -m "feat: implement fastapi application and rest sse endpoints"
```

---

### Task 7: Interactive CLI Telemetry Feeder for Verification

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/telemetry_feeder.py`
- Test: `tests/test_feeder.py`

**Interfaces:**
- Produces:
  - `telemetry_feeder.py`: Executable CLI script with arguments:
    - `--user-id`: Target Roblox User ID (default `12345678`).
    - `--rate`: Target TPS to simulate (default `25`).
    - `--interval`: Telemetry send interval in seconds (default `1.0`).
    - `--rebirth-interval`: Simulates a rebirth reset every N seconds.
    - `--url`: Target endpoint URL (default `http://127.0.0.1:3883/api/v1/telemetry`).
    - `--count`: Number of payloads to send before exiting (or infinite).

- [ ] **Step 1: Write the test verifying the feeder generation logic**

```python
# tests/test_feeder.py
import pytest
from tools.telemetry_feeder import generate_payload

def test_generate_payload_progression():
    state = {
        "current_taps": 1000,
        "total_taps": 5000,
        "rebirths": 1,
        "wins": 2,
        "currency": 10000
    }
    p1 = generate_payload(123, state, delta_taps=50, delta_time=1.0)
    assert p1["currentTaps"] == 1050
    assert p1["totalTaps"] == 5050
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_feeder.py -v`  
Expected: FAIL with `ModuleNotFoundError: No module named 'tools.telemetry_feeder'`

- [ ] **Step 3: Implement `tools/telemetry_feeder.py`**

Implement CLI argument parsing, realistic pet items generator, incremental stats state machine, and interactive terminal dashboard with live status logs.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_feeder.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/ tests/test_feeder.py
git commit -m "feat: implement interactive cli telemetry feeder for verification"
```

---

### Task 8: Modern Dark UI Single-Page Dashboard

**Files:**
- Create: `src/static/index.html`
- Create: `src/static/css/style.css`
- Create: `src/static/js/app.js`

**Interfaces:**
- Consumes: REST endpoints (`/api/v1/accounts`, `/api/v1/accounts/{user_id}/live`, etc.) and SSE stream (`/api/v1/stream`).
- Visual Modules:
  - Header with Account Selector, Add Account Modal, Tracking Toggle, Live Status Indicator, Last Sync.
  - Player Overview Card (Avatar, Username, Presence badge, Playtime counter).
  - Live Stats Grid (Current Taps, Total Taps, Real-time TPS pulse, Rebirths, Wins, Currency).
  - Growth Rates Panel (1m, 5m, 15m deltas with percentage trends).
  - Live Chart.js interactive graph showing TPS history and cumulative taps.
  - Pet Showcase with rarity badges (Common, Rare, Epic, Legendary, Mythic) and multipliers.
  - Multi-Account Comparison view with comparison matrix and batch start/pause.
  - History & Data Management with Session table, CSV export, and JSON export buttons.

- [ ] **Step 1: Write static asset smoke test in Python**

```python
# tests/test_static_ui.py
import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_dashboard_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "Tap Simulator Reborn" in response.text
    assert "Chart.js" in response.text or "chart.js" in response.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_static_ui.py -v`  
Expected: FAIL (404 or missing file)

- [ ] **Step 3: Implement `index.html`, `style.css`, and `app.js`**

Implement ergonomic Dark Glassmorphism theme, SVG/Lucide icons, Chart.js initialization, SSE event listener, and dynamic UI updates without page reloads.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_static_ui.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/static/ tests/test_static_ui.py
git commit -m "feat: implement modern dark ui dashboard with live charts and multi-account view"
```

---

### Task 9: End-to-End Verification, Performance Benchmarks, and Documentation

**Files:**
- Create: `README.md`
- Create: `docs/test-report.md`

- [ ] **Step 1: Run full test suite**

Run: `pytest tests/ -v --durations=10`  
Expected: All tests PASS with 100% green status.

- [ ] **Step 2: Run live end-to-end integration test with `telemetry_feeder.py`**

Launch backend in background, stream 100 telemetry payloads across 2 accounts using `telemetry_feeder.py`, verify SQLite snapshots, verify CSV export, verify TPS accuracy, and confirm CPU usage remains under 1%.

- [ ] **Step 3: Document data sources, installation, and run instructions in `README.md`**

Provide comprehensive documentation covering:
- Architecture diagram & data source transparency.
- Quick start instructions (`pip install -r requirements.txt`, `python run.py`).
- Telemetry API specification and example payloads.
- Multi-account management guide.
- Security and Roblox ToS compliance explanation.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/
git commit -m "docs: add comprehensive readme, data source documentation and test report"
```
