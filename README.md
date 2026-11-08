# Tap Simulator Reborn – TrackStats System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL%20Mode-003B57.svg)](https://sqlite.org/)
[![Tests](https://img.shields.io/badge/Tests-25%20Passed-10b981.svg)](docs/test-report.md)
[![Zero Exploit](https://img.shields.io/badge/Security-Zero%20Injection%20%2F%20No%20Cookies-00f2fe.svg)](#security--compliance)

A dedicated, legitimate, high-performance **Real-Time Statistics Tracker and Live Dashboard** for the Roblox game **Tap Simulator Reborn** (Place ID: `72858262610964`, Universe ID: `10629695169`), inspired by the user experience and multi-account analytics of [YummyTrack](https://yummytrackstat.com).

This tool is **NOT** an auto-farm bot or an exploit. It is an independent tracking and analytics companion that collects, processes, displays, and stores valid game statistics with zero memory injection, zero Roblox cookies, and zero risk of account moderation.

---

## 1. Features

- **Real-Time Stats Tracking**: Tracks Current Taps, Total Taps, Rebirths, Wins, Currency (Gems/Coins), and Session Playtime.
- **True TPS Calculation**: High-precision sub-second rate engine calculating actual Taps Per Second ($\Delta \text{Taps} / \Delta t$) with automatic **rebirth anomaly protection** (preventing negative spikes when current taps reset).
- **Rolling Growth Windows**: In-memory circular buffers computing rolling 1-minute, 5-minute, and 15-minute growth deltas for Taps and Currency.
- **Pet Showcase**: Real-time tracking of equipped pets with color-coded rarity badges (Mythic, Legendary, Epic, Rare, Common), multipliers, and total Pet Power.
- **Multi-Account Tracking Matrix**: Manage multiple Roblox accounts simultaneously via public User IDs. Includes side-by-side performance comparison, individual pause/resume, and batch "Track All / Pause All".
- **Modern Dark Glassmorphism Dashboard**: Sleek, responsive web interface featuring Chart.js live time-series graphs, pulsing status badges, and instant account switching.
- **Zero-Credential Security**: Does **not** require passwords, session tokens, or `.ROBLOSECURITY` cookies. Public player profiles and avatars are fetched directly from official Roblox Web APIs.
- **Persistent SQLite Storage**: Automatically archives sessions, tracks performance trends, and supports single-click CSV/JSON export and database restore.
- **Ultra-low Resource Footprint**: Asynchronous FastAPI core utilizing < 0.2% CPU at idle and < 35 MB RAM.

---

## 2. Architecture & Data Sources

```
+---------------------------------------------------------------------------------+
|                             USER INTERFACE                                      |
|          Modern Dark Glassmorphism Dashboard (Chart.js & SSE Stream)            |
+----------------------------------------+----------------------------------------+
                                         | REST / Server-Sent Events (SSE)
+----------------------------------------v----------------------------------------+
|                          FASTAPI BACKEND SERVICE                                |
|                                                                                 |
|  +--------------------------------+     +------------------------------------+  |
|  |     Roblox Public Poller       |     |      Telemetry Ingestion API       |  |
|  |   - users.roblox.com           |     |      POST /api/v1/telemetry        |  |
|  |   - presence.roblox.com        |     |      - In-game Taps, Pets, Wins    |  |
|  |   - thumbnails.roblox.com      |     |      - Open REST contract          |  |
|  +----------------+---------------+     +-----------------+------------------+  |
|                   |                                       |                     |
|  +----------------v---------------------------------------v------------------+  |
|  |                       Session & Rate Engine                               |  |
|  |   - Sub-second TPS calculation with Rebirth reset fallback                |  |
|  |   - In-memory rolling circular buffer (1m, 5m, 15m)                       |  |
|  |   - Authoritative heartbeat lifecycle (LIVE -> STALE -> DISCONNECTED)     |  |
|  +--------------------------------+------------------------------------------+  |
|                                   |                                             |
|  +--------------------------------v------------------------------------------+  |
|  |                    SQLite Persistent Storage                              |  |
|  |   - Accounts, Sessions, and Time-Series Snapshots (WAL Mode)              |  |
|  |   - CSV & JSON Exporters / Backup & Restore                               |  |
|  +---------------------------------------------------------------------------+  |
+---------------------------------------------------------------------------------+
```

### Data Source Transparency

1. **Roblox Public Web APIs**:
   - `https://users.roblox.com/v1/users/{userId}`: Fetches username and display name.
   - `https://thumbnails.roblox.com/v1/users/avatar-headshot`: Fetches player avatar headshot.
   - `https://presence.roblox.com/v1/presence/users`: Inspects public game presence (`Place ID 72858262610964`).
   - Rate-limiting: Cached with a 5-second debounce and exponential backoff on HTTP 429.
2. **Local Telemetry Ingestion Bridge**:
   - Internal game stats (Taps, Currency, Rebirths, Pets) are server-authoritative in Roblox and not exposed on public web endpoints.
   - The TrackStats companion provides an open local HTTP endpoint (`http://127.0.0.1:3883/api/v1/telemetry`) that accepts clean JSON payloads from local client tools or the included verification feeder.

---

## 3. Installation & Quick Start

### Prerequisites
- Python 3.10 or higher
- Windows, macOS, or Linux

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Launch the TrackStats Server
```bash
python run.py
```
By default, the server starts on `http://127.0.0.1:3883/`. Open this URL in any web browser to access the Dark UI Dashboard.

### Step 3: Run the Verification Telemetry Feeder
In a separate terminal, launch the interactive telemetry feeder to simulate real-time gameplay telemetry and verify all live calculations:
```bash
python tools/telemetry_feeder.py --user-id 12345678 --rate 35 --interval 1.0
```
Options for the feeder:
- `--rate <float>`: Target Taps Per Second (default: `25.0`).
- `--interval <float>`: Telemetry update interval in seconds (default: `1.0`).
- `--rebirth-interval <float>`: Simulates a rebirth event every N seconds (default: `90.0`).
- `--user-id <int>`: Target Roblox User ID.
- `--count <int>`: Number of updates to send before exiting (`-1` for continuous streaming).

---

## 4. REST API Specification

### Telemetry Ingestion
- **`POST /api/v1/telemetry`**
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
        "name": "Dark Hydra",
        "rarity": "Mythic",
        "multiplier": 500.0,
        "power": 12500.0
      }
    ],
    "petInventoryCount": 42,
    "totalPetPower": 150000.0,
    "timestamp": 1794123456.78
  }
  ```

### Account & Session Management
- **`GET /api/v1/accounts`**: Returns all registered accounts with live status and summaries.
- **`POST /api/v1/accounts`**: Body `{"userId": 12345678}`. Adds an account (auto-fetches profile & avatar from Roblox).
- **`DELETE /api/v1/accounts/{user_id}`**: Deletes an account and purges historical records.
- **`POST /api/v1/accounts/{user_id}/tracking`**: Body `{"is_tracking": true/false}`. Toggles tracking for an account.
- **`POST /api/v1/accounts/tracking/all`**: Body `{"is_tracking": true/false}`. Batch toggles tracking across all accounts.
- **`GET /api/v1/accounts/{user_id}/live`**: Returns consolidated live stats, TPS, and 1m/5m/15m growth windows.
- **`GET /api/v1/accounts/{user_id}/history`**: Retrieves past session records.

### Data Export & Stream
- **`GET /api/v1/export/csv`**: Downloads complete database export as CSV.
- **`GET /api/v1/export/json`**: Downloads complete database export as JSON.
- **`POST /api/v1/restore`**: Restores database state from JSON backup.
- **`GET /api/v1/stream`**: Server-Sent Events (SSE) live push stream for the web dashboard.

---

## 5. Security & Compliance

This project was built strictly adhering to Roblox Terms of Service and clean companion standards:
- **No Cookie Collection**: Never prompts for or stores `.ROBLOSECURITY`.
- **No Password Reading**: Operates completely unauthenticated on the client side.
- **No Memory Tampering**: Does not inject DLLs, inspect process memory, or hook game routines.
- **No Spoofing or Exploit Code**: Built purely as an analytical observer and telemetry consumer.

---

## 6. Testing & Quality Assurance

Run the automated Pytest test suite:
```bash
pytest tests/ -v
```
All 25 test cases cover:
- Sub-second TPS calculation and Rebirth anomaly handling.
- Private Roblox presence tolerance (telemetry-first authoritative lifecycle).
- Multi-account state isolation and concurrency.
- SQLite WAL mode session persistence and snapshot storage.
- JSON/CSV data export and recovery.

See [docs/test-report.md](docs/test-report.md) for the full verification report.
