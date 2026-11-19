# Tap Simulator Reborn – Public Railway Deployment & Executor Loader Design

**Date:** 2026-11-19
**Project:** `tap-simulator-trackstats`
**Status:** Proposed (Awaiting User Approval)

---

## 1. Intent & Why
Make the Tap Simulator Reborn TrackStats v2 dashboard publicly accessible over HTTPS 24/7 on **Railway**, and provide a short copy-paste **Executor Loader** (`loadstring(game:HttpGet("https://<domain>/loader.lua"))()`) so one or many Roblox accounts (across PCs, emulators, or `autoexec`) can stream live Taps, Rebirths, Eggs, Boosts, Secret Pet inventories, and Secret Hatch alerts directly to the public dashboard without exposing destructive controls or allowing fake telemetry from strangers.

## 2. Goals, Non-Goals & Anti-Goals
- **Goals:**
  - Public 24/7 HTTPS web deployment on Railway with a Persistent Volume (`/data/trackstats.db`) so SQLite data survives redeploys and restarts.
  - Secure write/ingest authentication:
    - **Ingest Key (`TRACKSTATS_INGEST_KEY`)** protects `POST /api/v1/telemetry`, `POST /api/v1/connector/inspect`, and `POST /api/v1/webhook/discord`.
    - **Admin Password (`TRACKSTATS_ADMIN_PASSWORD`)** protects all administrative mutations (`POST/DELETE /api/v1/accounts*`, `POST /api/v1/settings/alerts*`, `POST /api/v1/pets/catalog/{slug}/image`, `POST /api/v1/restore`, `GET /api/v1/export/*`, and viewing/copying the live `Ingest Key` in the UI).
    - Configurable read visibility via `TRACKSTATS_PUBLIC_READ` (default `true`: anyone with the link can view live stats & Secret Vault in read-only mode; setting `false` requires Admin sign-in to view the dashboard & SSE stream as well).
  - Clean 1-line Executor loader (`GET /loader.lua`) + upgraded `scripts/tap_sim_reborn_tracker.lua` reading `getgenv().TrackStats` / `_G.TrackStats` (`Key`, `Interval`, `Inspect`, `Debug`, optional `Endpoint`), sending `X-TrackStats-Key`, supporting all major executor HTTP APIs, and printing clear connection/auth diagnostics.
  - Upgraded **Connector** tab in the web UI with one-click copy for the Executor Loader snippet, `autoexec` instructions, and strict key masking for public guests (real key only shown after Admin Unlock).
  - Zero regression for local development and all 63 existing tests (when `TRACKSTATS_INGEST_KEY` and `TRACKSTATS_ADMIN_PASSWORD` are unset locally, auth stays open for local-only use).
- **Non-Goals:**
  - Multi-tenant public SaaS (user signup / separate isolated databases per stranger).
  - Gameplay automation, auto-tap, auto-hatch, remote event firing, or `.ROBLOSECURITY` / cookie access.
- **Anti-Goals (Failure Conditions):**
  - Leaking `TRACKSTATS_INGEST_KEY`, `TRACKSTATS_ADMIN_PASSWORD`, or the raw Discord Webhook URL to unauthenticated public visitors.
  - Losing SQLite data on Railway redeploys (must mount persistent volume at `/data`).
  - Serving `http://` links in `/loader.lua` when behind Railway's HTTPS reverse proxy.

## 3. Approaches Considered
1. **Approach 1 (Selected): Railway Cloud 24/7 + Auth Keys + Executor `/loader.lua`**
   - *How:* Containerized FastAPI app (`Dockerfile`) deployed to Railway with a `/data` volume, env-configured `INGEST_KEY` + `ADMIN_PASSWORD`, reverse-proxy HTTPS awareness, and `/loader.lua` + Connector UI upgrade.
   - *Trade-off:* Uses Railway hosting account (already installed and signed in as `@tuananh8956`), delivers permanent HTTPS URL + 24/7 uptime.
2. **Approach 2 (Rejected): Local PC + Cloudflare Tunnel**
   - *Trade-off:* Free and zero cloud account, but goes offline whenever the PC sleeps/shuts down and rotates quick-tunnel URLs on restart.
3. **Approach 3 (Rejected): Multi-Tenant Public SaaS**
   - *Trade-off:* Over-engineered for a personal/team multi-account farm; adds unnecessary user-management & abuse-prevention overhead.

## 4. Architecture & Component Design

### 4.1 Configuration & Auth (`src/config.py`, `src/auth.py`, `src/main.py`)
- `src/config.py` reads environment variables:
  - `PORT` (int, default `3883`)
  - `HOST` (str, default `"0.0.0.0"`)
  - `TRACKSTATS_DB_PATH` (default `./trackstats.db`; `/data/trackstats.db` on Railway)
  - `PUBLIC_BASE_URL` (optional override; otherwise derived from `X-Forwarded-Proto` + `X-Forwarded-Host` / `Host`)
  - `TRACKSTATS_INGEST_KEY` (str, default `""`; when non-empty, required for ingest endpoints)
  - `TRACKSTATS_ADMIN_PASSWORD` (str, default `""`; when non-empty, required for admin endpoints & optional read lock)
  - `TRACKSTATS_PUBLIC_READ` (bool, default `true`; when `false` and `TRACKSTATS_ADMIN_PASSWORD` is set, read APIs & `/api/v1/stream` also require an Admin session)
- `src/auth.py`:
  - Constant-time secret comparisons (`hmac.compare_digest`).
  - Signed `HttpOnly; SameSite=Lax` admin session cookie (`ts_admin_session`, `Secure` automatically when request is HTTPS), signed with HMAC-SHA256 derived from `TRACKSTATS_ADMIN_PASSWORD` (no extra dependency needed; survives restarts without losing active sessions).
  - Endpoints:
    - `GET /api/v1/auth/status` -> `{ auth_enabled, public_read, is_admin, ingest_key_required }` (never returns secrets; if `is_admin` is true, `GET /api/v1/connector/config` returns the active `ingest_key`, `loader_url`, and ready-to-paste snippets).
    - `POST /api/v1/auth/login` -> validates `{ password }`, sets `ts_admin_session` cookie.
    - `POST /api/v1/auth/logout` -> clears `ts_admin_session` cookie.
  - FastAPI dependencies:
    - `require_ingest_key`: checks `X-TrackStats-Key` header, or `Authorization: Bearer <key>`, or `?key=<key>` query param (needed for Discord webhooks). Returns `401` on mismatch.
    - `require_admin`: checks valid `ts_admin_session` cookie or `X-Admin-Password` header when `TRACKSTATS_ADMIN_PASSWORD` is configured. Returns `401` on mismatch.
    - `require_read_access`: passes immediately when `TRACKSTATS_PUBLIC_READ=true` or auth disabled; otherwise delegates to `require_admin`.
  - Health endpoint: `GET /healthz` -> `{"status": "ok", "version": "2.0.0"}` (always public for Railway healthchecks).

### 4.2 Executor 1-Line Loader & Read-Only Luau Script (`GET /loader.lua`, `scripts/tap_sim_reborn_tracker.lua`)
- `GET /loader.lua` (and `GET /api/v1/connector/script.lua`):
  - Resolves public HTTPS origin via `PUBLIC_BASE_URL` or `X-Forwarded-Proto` + `Host`.
  - Rewrites `ENDPOINT_URL` and `INSPECT_URL` in the served Luau text to `https://<public-host>/api/v1/telemetry` and `https://<public-host>/api/v1/connector/inspect`.
  - **Never** embeds `TRACKSTATS_INGEST_KEY` in the publicly served `/loader.lua` body.
- `scripts/tap_sim_reborn_tracker.lua`:
  - Reads runtime config from `(getgenv and getgenv().TrackStats) or _G.TrackStats`:
    - `Key` (string): sent in `X-TrackStats-Key` HTTP header on both telemetry and inspector POSTs.
    - `Endpoint` / `BaseUrl` (optional string): overrides default URL if user wants to point elsewhere.
    - `Interval` (number, clamped `>= 1.0`, default `2.0`): telemetry push interval.
    - `Inspect` (boolean, default `true`): one-time UI/leaderstats inspector dump on start.
    - `Debug` (boolean, default `false`): prints response status & payload summary to executor console.
  - Prints one startup banner (`[TrackStats] Started -> https://... (Key: set/missing)`) and surfaces `401 Unauthorized` clearly in `warn(...)` if the key is wrong or missing.
  - Strictly read-only (zero gameplay automation, zero cookie reading).

### 4.3 Web UI Updates (`src/static/index.html`, `src/static/js/app.js`, `src/static/css/style.css`)
- **Navbar Admin Unlock Control:**
  - Shows `Admin Lock` / `Admin Unlocked` pill when `auth_enabled` is true.
  - Clicking opens a clean **Admin Login Modal** (`POST /api/v1/auth/login`).
  - When viewing as a public guest (`auth_enabled && !is_admin`):
    - If `public_read` is `true`: full dashboard, Secret Vault, Hatch Feed, Multi-Account stats, and live SSE stream work seamlessly, while admin-only controls (Add/Delete Account, Pause/Resume Tracking, Discord Webhook save/test, Restore JSON, Customize Pet Image) show a lock badge or prompt Admin Login.
    - If `public_read` is `false`: displays a clean full-screen Password Gate overlay until logged in.
- **Connector Tab Upgrade:**
  - Card 1: **Quick Executor Script (1-Click Copy)**
    - Shows the ready-to-paste `getgenv().TrackStats = { Key = "...", Interval = 2 }` + `loadstring(game:HttpGet("https://<host>/loader.lua"))()` block.
    - Automatically inserts the real `Key` ONLY when `is_admin` is true; shows `"YOUR_TRACKSTATS_KEY"` with an "Unlock Admin to reveal Key" hint for public guests.
    - Includes a collapsible **Fallback Loader** (for executors without `game:HttpGet`) and a short **Autoexec** tip.
  - Card 2: Full `.lua` Download/Copy & Live In-Game Inspector Dump (existing).

### 4.4 Railway Deployment Packaging
- `Dockerfile` (Python 3.12-slim, installs `requirements.txt`, copies app + `scripts/` + `src/static/assets/pets/`, runs `uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-3883} --proxy-headers --forwarded-allow-ips="*"`).
- `.dockerignore` (excludes `trackstats.db*`, `.git`, `__pycache__`, `.pytest_cache`, `tests/`, `docs/`).
- `railway.toml` (`healthcheckPath = "/healthz"`, `restartPolicyType = "ON_FAILURE"`).
- **Railway Provisioning Steps (via Railway MCP + GitHub private repo `tuananh8956/tap-simulator-trackstats`, or `railway up` fallback):**
  1. Create Railway project `tap-simulator-trackstats` in workspace `tuananh8956's Projects`.
  2. Create service `web` and attach a Persistent Volume mounted at `/data`.
  3. Set environment variables: `TRACKSTATS_DB_PATH=/data/trackstats.db`, `TRACKSTATS_INGEST_KEY=<generated>`, `TRACKSTATS_ADMIN_PASSWORD=<user or generated>`, `TRACKSTATS_PUBLIC_READ=<true|false>`.
  4. Connect source repo (or push via CLI) and generate public Railway domain (`https://<name>.up.railway.app`).
  5. Wait for deployment `SUCCESS`, verify `GET /healthz`, `GET /loader.lua`, `401` rejection without key, and `200` ingest with key.

## 5. Verification Plan
- Unit & integration tests (`tests/test_public_auth_and_loader.py`):
  - Ingest endpoints reject missing/wrong `X-TrackStats-Key` with `401` and accept valid key with `200`.
  - Admin endpoints reject unauthenticated requests with `401`, succeed after `POST /api/v1/auth/login` cookie, and reject after logout.
  - `TRACKSTATS_PUBLIC_READ=true` allows guest read + masks ingest key; `TRACKSTATS_PUBLIC_READ=false` blocks guest reads (`401`).
  - `GET /loader.lua` respects `X-Forwarded-Proto: https` and never leaks `TRACKSTATS_INGEST_KEY`.
  - Luau script contains `getgenv`, `TrackStats`, `X-TrackStats-Key`, and zero forbidden automation/cookie APIs.
  - All 63 existing v1+v2 tests continue passing (`pytest tests/ -v`).
- Live Railway production verification after deploy:
  - Confirm Railway deployment reaches `SUCCESS`.
  - Verify live HTTPS URL `/healthz`, `/loader.lua`, auth rejection, authenticated test telemetry, and browser render of the public site.
