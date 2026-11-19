# Tap Simulator Reborn – TrackStats v2 System

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL%20Mode-003B57.svg)](https://sqlite.org/)
[![Zero Credentials](https://img.shields.io/badge/Security-No%20Cookies%20%2F%20Read--Only-00f2fe.svg)](#security--compliance)

A dedicated, high-performance **Real-Time Statistics Tracker, Secret Vault, and Multi-Account Dashboard** for **Tap Simulator Reborn** (Place ID: `72858262610964`, Universe ID: `10629695169`).

---

## 1. Key Features (v2)

- **Secret Vault & Per-Secret Pet Images:**
  - Tracks total Secret count across the entire farm and per account, grouped by **Secret Name** and **Variant** (`Normal`, `Golden`, `Diamond`, `Rainbow`, `Shiny`) plus Tier (`Secret I`, `Secret II`, `Secret III`, `Event`).
  - **5-Step Image Pipeline:** Custom user image override -> safe telemetry URL -> automatic Roblox Asset Thumbnail resolution (`rbxassetid://<id>` via `thumbnails.roblox.com/v1/assets`) -> **66 real in-game Secret pet renders** (`src/static/assets/pets/*.png|.webp|.jpg`, refreshable anytime via `python tools/sync_pet_images.py`) + 18 SVG fallback portraits -> procedural SVG fallback (`/api/v1/pets/icon/{slug}.svg`).
  - Click any Secret card to inspect which accounts hold it and customize its image URL or Roblox Asset ID.
- **Redesigned 6-Tab Dark Cyber-Glass Website UI:**
  - Persistent **Farm Overview KPI Strip** (Online Accounts, Total Secrets + variant breakdown, Farm TPS, Farm Taps/Currency, Total Eggs & Eggs/hr).
  - Instant tabs: **Overview**, **Secret Vault**, **Hatch Feed & Discord Alerts**, **Multi-Account Matrix**, **History & Export/Restore**, and **Game Connector**.
  - World/Island indicator, ticking Active Boosts countdown pills, WebAudio Secret hatch chime, and Chart.js live TPS stream.
- **In-Game Read-Only Luau Telemetry Script (`scripts/tap_sim_reborn_tracker.lua`):**
  - Strictly read-only telemetry observer (zero auto-tap/auto-hatch, zero cookie access).
  - **AFK Closed-Inventory Guard:** Omits `secretPets` when your Pet Inventory UI is closed so AFK hatching never wipes your Secret Vault, while listening to read-only hatch popups/chat to update `recentHatches` & Secret counts live.
  - **Inspector Mode (`INSPECT_ON_START = true`):** Posts discovered `leaderstats`, attributes, and `PlayerGui` paths to the Dashboard's Connector tab so you can tune `CONFIG.PATHS` after game updates.
- **Bidirectional Discord Webhook Integration:**
  - Outbound alerts for Secret Hatches (with pet thumbnail) and state-transition Disconnect (`60s`) / optional Stale (`15s`) alerts, with masked webhook tokens on `GET /api/v1/settings/alerts`.
  - Inbound Discord-compatible bridge (`POST /api/v1/webhook/discord`) with username lookup and 15-second cross-source deduplication.

---

## 2. Quick Start

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Launch the TrackStats Server
```bash
python run.py
```
Open `http://127.0.0.1:3883/` in your browser.

### Step 3: Stream Data (Choose One)
- **Option A — Multi-Account Verification Feeder (Instant Local Demo):**
  ```bash
  python tools/telemetry_feeder.py --multi 3 --rate 45 --hatch-interval 15
  ```
- **Option B — In-Game Luau Telemetry Script:**
  Open the **Connector** tab on the dashboard to copy or download `scripts/tap_sim_reborn_tracker.lua` pre-configured with your server URL.
- **Option C — Inbound Discord Webhook Bridge:**
  POST Discord webhook embeds to `http://127.0.0.1:3883/api/v1/webhook/discord`.

---

## 3. REST API Overview

- `POST /api/v1/telemetry` — Ingest live stats, `secretPets`, `eggsHatched`, `world`, `activeBoosts`, `recentHatches`.
- `GET /api/v1/overview` — Farm-wide aggregate KPIs.
- `GET /api/v1/secrets?user_id=&variant=&tier=&q=` — Aggregated Secret Vault & owner breakdown.
- `GET /api/v1/pets/catalog` & `POST /api/v1/pets/catalog/{slug}/image` — Browse catalog & override pet images.
- `GET /api/v1/pets/icon/{slug}.svg` — Procedural fallback SVG portrait.
- `GET /api/v1/hatches?limit=50&rarity=&user_id=` — Live Hatch Feed history.
- `GET /api/v1/settings/alerts`, `POST /api/v1/settings/alerts`, `POST /api/v1/settings/alerts/test` — Outbound Discord alert settings (URL masked).
- `POST /api/v1/webhook/discord` — Inbound Discord webhook receiver.
- `GET /api/v1/connector/script.lua` — Download/serve configured `tap_sim_reborn_tracker.lua`.
- `POST /api/v1/connector/inspect` & `GET /api/v1/connector/inspect` — Receive/view in-game hierarchy dumps.
- `GET /api/v1/accounts`, `POST /api/v1/accounts`, `DELETE /api/v1/accounts/{user_id}`, `GET /api/v1/accounts/{user_id}/live`, `GET /api/v1/accounts/{user_id}/history`.
- `GET /api/v1/export/csv`, `GET /api/v1/export/json`, `POST /api/v1/restore`, `GET /api/v1/stream` (SSE).

---

## 4. Security & Compliance

- **Zero Credentials:** Never reads, requests, or stores `.ROBLOSECURITY` cookies or passwords.
- **Read-Only Telemetry Only:** Contains zero auto-farm, auto-click, auto-hatch, or remote-event exploit code.
- **Notice on Third-Party Roblox Client Scripts:** Running third-party client scripts inside Roblox violates Roblox Terms of Service and carries account risk; use the included local feeder (`tools/telemetry_feeder.py`), Studio `HttpService` testing, or standard webhook ingestion if you want zero client interaction.

---

## 5. Testing

```bash
pytest tests/ -v
```
