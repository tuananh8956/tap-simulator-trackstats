# Tap Simulator Reborn – TrackStats System Design Document

**Date:** 2026-11-08  
**Status:** Approved by Builder Check – Awaiting User Sign-off  
**Project:** Tap Simulator Reborn TrackStats System  
**Reference Model:** YummyTrack / Yummy Auto (Real-time analytics & multi-account dashboard)

---

## 1. Intent & The Why

Roblox players of *Tap Simulator Reborn* (Place ID: `72858262610964`, Universe ID: `10629695169`) need to monitor their grinding progress, real-time Taps Per Second (TPS), growth rates over time, currency gains, and pet bonuses across single or multiple accounts. Existing unofficial solutions often require sensitive `.ROBLOSECURITY` cookies, inject intrusive memory DLLs, or risk account bans.

The purpose of this project is to build an independent, 100% legitimate, high-performance **Real-Time Game Statistics Tracker** with a modern Dark UI dashboard. It operates strictly without cookies, passwords, or memory injection, adhering to Roblox Terms of Service and clean telemetry standards.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Real-Time Tracking**: Track live player stats (Current Taps, Total Taps, TPS, Rebirths, Wins, Currency, Playtime).
- **Accurate Rate Calculations**: Compute true TPS using sub-second timestamp deltas, plus 1-minute, 5-minute, and 15-minute rolling growth rates.
- **Pet Management**: Display equipped pets (rarity, multiplier, pet power) and total inventory stats.
- **Multi-Account Support**: Manage multiple accounts via public Roblox User IDs; switch active accounts and view side-by-side performance comparisons.
- **Modern Dark UI Dashboard**: Clean, responsive interface featuring live charts, connection indicators, session duration, and instant controls (Start/Stop tracking).
- **Data Persistence & Portability**: SQLite database for persistent session logs; complete export/import capability (CSV and JSON).
- **Extreme Efficiency**: Asynchronous backend with low CPU and RAM consumption (< 1% CPU idle/polling), connection retry mechanisms, and rate-limit safety.
- **Standalone Verification Client**: Include an interactive telemetry feeder CLI (`telemetry_feeder.py`) for live end-to-end verification and testing.

### Non-Goals
- **No Automation/Macro Execution**: The tool will not auto-click, auto-farm, or automate player actions.
- **No Captcha/Credential Bypass**: The tool will not authenticate as the player or bypass login challenges.
- **No In-Game Memory Editing**: No hooking into game memory, DLL injection, or executable modification.

### Anti-Goals
- **Zero Cookie/Password Handling**: Never request, read, or store `.ROBLOSECURITY` or passwords.
- **No Fake Data / Fabricated RemoteEvents**: Never mock unverified internal game events or fabricate game leaderboards without verifiable source signals.

---

## 3. Constraints & Technical Boundaries

1. **Roblox Public Web APIs**:
   - Endpoints: `users.roblox.com`, `presence.roblox.com`, and `thumbnails.roblox.com`.
   - Access: Purely public with zero authentication (only requires Roblox User ID).
   - Rate Limits: Presence endpoints are rate-limited (~60 requests/min per IP); poller uses a 5-second debounce/cache per account with exponential backoff on HTTP 429.
2. **In-Game Stats Isolation**:
   - Roblox DataStores and in-game leaderstats are server-authoritative and not exposed on public web endpoints.
   - In-game stats are delivered to the tracker via an open, lightweight **Local Telemetry Ingestion API** (`http://127.0.0.1:port/api/v1/telemetry`), creating a decoupled and secure companion architecture.
3. **OS & Environment**:
   - Runs cross-platform on Windows/Linux/macOS with Python 3.10+.
   - Self-contained web dashboard (no complex external frontend build required; served directly via FastAPI static files).

---

## 4. Approaches & Selected Strategy

| Approach | Description | Pros | Cons | Decision |
|---|---|---|---|---|
| **Approach 1: Local Ingestion API + Public Poller** | Roblox Public API tracks presence/user data; internal stats are ingested via a local HTTP webhook. | Sub-millisecond latency, 0% ban risk, < 1% CPU/RAM, 100% calculation accuracy. | In-game metrics depend on telemetry payload input. | **SELECTED (User Choice)** |
| **Approach 2: Non-invasive Screen OCR** | Desktop capture scans game HUD values using Tesseract/OpenCV. | Requires no local telemetry input. | High CPU usage, brittle with UI scaling/chat overlays. | Rejected |
| **Approach 3: Hybrid Engine** | Combines Approach 1 and Approach 2. | Most comprehensive. | Adds dependency complexity (Tesseract binaries, OCR models). | User opted for Approach 1 |

---

## 5. System Architecture & Detailed Specifications

```
+-----------------------------------------------------------------------+
|                             USER INTERFACE                            |
|             Modern Dark UI Dashboard (HTML5 / CSS3 / Chart.js)        |
+-----------------------------------+-----------------------------------+
                                    | REST / Server-Sent Events (SSE)
+-----------------------------------v-----------------------------------+
|                         BACKEND SERVICE (FastAPI)                     |
|                                                                       |
|  +-----------------------------+     +-----------------------------+  |
|  |    Roblox Presence Poller   |     |    Local Telemetry Bridge   |  |
|  | (Profile, Avatar, In-Game)  |     |  POST /api/v1/telemetry     |  |
|  +--------------+--------------+     +--------------+--------------+  |
|                 |                                   |                 |
|  +--------------v-----------------------------------v--------------+  |
|  |                 Tracking & Analytics Engine                     |  |
|  |   - Sub-second TPS calculation (Delta Taps / Delta Time)        |  |
|  |   - Rolling Growth Rates (1m, 5m, 15m)                          |  |
|  |   - Heartbeat Monitor (Authoritative Session Lifecycle)         |  |
|  +------------------------------+----------------------------------+  |
|                                 |                                     |
|  +------------------------------v----------------------------------+  |
|  |                    Storage & Persistence                        |  |
|  |   - SQLite Database (accounts, sessions, time_series_snapshots) |  |
|  |   - Exporter (CSV, JSON) & Data Restore                         |  |
|  +-----------------------------------------------------------------+  |
+-----------------------------------------------------------------------+
```

### 5.1 Telemetry Scope & Verification Client (Builder Call #1)
- The core deliverable consists of the complete TrackStats backend, rate engine, SQLite storage, real-time Dark UI, and an interactive CLI Telemetry Feeder (`telemetry_feeder.py`).
- Telemetry ingestion is exposed as a standard REST endpoint (`POST /api/v1/telemetry`).
- Any external tool, script, or companion service can POST JSON payloads to this endpoint. The verification client allows testing realistic production streams without requiring third-party injectors.

### 5.2 Session Lifecycle & Source of Truth (Builder Call #2)
- **Authoritative Source**: The incoming **Telemetry Stream** is the primary source of truth for session recording and active status. This prevents account sessions from being disrupted when users have strict Roblox privacy settings (which return `placeId: null` on public presence endpoints).
- **Session State Machine**:
  - `CONNECTED / LIVE`: Telemetry received within the last 15 seconds.
  - `STALE / WAITING`: No telemetry received for 15–60 seconds.
  - `DISCONNECTED / CLOSED`: No telemetry received for > 60 seconds OR user presence actively confirmed offline. Session metrics are finalized in SQLite.
- **Roblox Presence Role**: Enriches the session with account metadata (Username, Display Name, Avatar Headshot) and public place verification when available.

### 5.3 Multi-Account Tracking Semantics (Builder Call #3)
- Tracking state is maintained **independently per account** (`is_tracking: true / false`).
- The dashboard top toggle reflects and switches the active selected account's status.
- The Multi-Account view provides "Start All" and "Pause All" batch controls.
- When an account's tracking is set to `PAUSED`, incoming telemetry returns HTTP 200 with `status: "paused"`, and snapshots are not recorded to SQLite until resumed.

### 5.4 Backend Service & Telemetry API
- **Framework**: Python 3 with FastAPI and Uvicorn.
- **Endpoint**: `POST /api/v1/telemetry`
- **Payload Schema**:
  ```json
  {
    "userId": 12345678,
    "currentTaps": 1542000,
    "totalTaps": 48200000,
    "currentRebirths": 35,
    "totalRebirths": 35,
    "currentWins": 210,
    "totalWins": 210,
    "currentCurrency": 12500000,
    "equippedPets": [
      {
        "id": "pet_1",
        "name": "Dragon",
        "rarity": "Legendary",
        "multiplier": 250.0,
        "power": 12500
      }
    ],
    "petInventoryCount": 42,
    "totalPetPower": 150000,
    "timestamp": 1794123456.78
  }
  ```

### 5.5 Analytics & Rate Engine
- **TPS (Taps Per Second)**:
  $$\text{TPS} = \frac{\text{CurrentTaps}_t - \text{CurrentTaps}_{t-1}}{t - (t-1)}$$
  If $\Delta \text{Taps} < 0$ (e.g. player rebirthed and current taps reset), fallback to $\Delta \text{TotalTaps} / \Delta t$.
- **Rolling Windows (1 min, 5 min, 15 min)**:
  - In-memory circular buffer storing up to 900 seconds of records per account.
  - Tracks growth for Taps, Currency, and Rebirths.

### 5.6 SQLite Storage Schema
```sql
CREATE TABLE IF NOT EXISTS accounts (
    user_id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    display_name TEXT,
    avatar_url TEXT,
    is_tracking INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    initial_taps INTEGER,
    final_taps INTEGER,
    taps_gained INTEGER,
    initial_rebirths INTEGER,
    final_rebirths INTEGER,
    rebirths_gained INTEGER,
    max_tps REAL DEFAULT 0.0,
    avg_tps REAL DEFAULT 0.0,
    FOREIGN KEY(user_id) REFERENCES accounts(user_id)
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    current_taps INTEGER NOT NULL,
    total_taps INTEGER,
    tps REAL NOT NULL,
    current_rebirths INTEGER,
    current_wins INTEGER,
    current_currency INTEGER,
    total_pet_power REAL,
    equipped_pets_json TEXT,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);
```

### 5.7 Modern Dark UI Dashboard
- Responsive Dark Glassmorphism interface (`#0a0d14` background, `#00f2fe` neon cyan & `#10b981` emerald accents).
- Key views:
  1. **Top Bar**: Active Account dropdown, Add Account modal, Start/Stop Tracking toggle, Live Status badge (`LIVE`, `STALE`, `OFFLINE`).
  2. **Player Overview**: Avatar, Username, UserID, Presence status, Session Timer.
  3. **Live Stats Grid**: Current Taps, Total Taps, Real-time TPS (with green pulse), Rebirths, Wins, Currency.
  4. **Growth Rates Panel**: 1m, 5m, 15m deltas for Taps and Currency.
  5. **Live Chart**: Chart.js time-series graph for TPS and cumulative progression.
  6. **Pet Showcase**: Equipped Pet cards with rarity badges, multipliers, and total pet power.
  7. **Multi-Account View**: Comparison table showing all registered accounts, TPS, total taps, and session stats.
  8. **Data Management**: Session History logs, Export CSV, Export JSON, Backup & Restore.

---

## 6. What's Left to the Builder

- Default port configuration (default `3883`).
- Automatic creation and seeding of database file on launch.
- Packaging as a simple runnable application (`run.py` or `python -m src.main`).
- Full test suite verifying rates, session transitions, and export formats.
