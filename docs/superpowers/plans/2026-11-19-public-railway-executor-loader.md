# Public Railway Deployment & Executor Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Secure the Tap Simulator Reborn TrackStats v2 dashboard for public read-only internet access with an Admin password and Executor Ingest Key, add a 1-line `loadstring` `/loader.lua` endpoint, upgrade the Connector UI, and deploy 24/7 to Railway with a persistent SQLite volume.

**Architecture:** A lightweight HMAC-signed session + header auth layer (`src/auth.py`) gates mutating endpoints behind `TRACKSTATS_ADMIN_PASSWORD` and telemetry/inspector/webhook ingestion behind `TRACKSTATS_INGEST_KEY` while leaving dashboard views & SSE public (`TRACKSTATS_PUBLIC_READ=true`). A reverse-proxy-aware `/loader.lua` endpoint serves `scripts/tap_sim_reborn_tracker.lua` pre-bound to the public HTTPS domain without leaking the key, while the script reads `getgenv().TrackStats.Key` at runtime in the user's executor.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, SQLite, Vanilla HTML/CSS/JS, Roblox Luau (read-only client telemetry), Docker, Railway (Persistent Volume + HTTPS Domain).

**Spec:** `docs/superpowers/specs/2026-11-19-public-railway-executor-loader-design.md`

## Global Constraints

- Preserve backward compatibility when `TRACKSTATS_INGEST_KEY` and `TRACKSTATS_ADMIN_PASSWORD` are empty (all 63 existing v1/v2 tests must pass unchanged).
- Never leak `TRACKSTATS_INGEST_KEY`, `TRACKSTATS_ADMIN_PASSWORD`, or the unmasked Discord Webhook URL to unauthenticated guests or inside `/loader.lua`.
- Keep `scripts/tap_sim_reborn_tracker.lua` strictly read-only (zero gameplay automation, zero remote event firing, zero cookie/token reading).
- Respect reverse-proxy headers (`X-Forwarded-Proto`, `X-Forwarded-Host`, `Host`) and `PUBLIC_BASE_URL` so `/loader.lua` and outbound Discord alerts always emit `https://` URLs on Railway.
- Persist SQLite database on Railway using a mounted volume at `/data/trackstats.db`.

## Review Focus

1. Reverse-proxy HTTPS resolution: `GET /loader.lua` behind `X-Forwarded-Proto: https` and `X-Forwarded-Host: myapp.up.railway.app` must emit `https://myapp.up.railway.app/api/v1/telemetry` and `https://myapp.up.railway.app/api/v1/connector/inspect`.
2. Key non-disclosure: `GET /loader.lua` and unauthenticated `GET /api/v1/connector/config` must never include the configured `TRACKSTATS_INGEST_KEY`.
3. Constant-time auth & query fallback: `POST /api/v1/telemetry` and `POST /api/v1/connector/inspect` must reject missing/wrong `X-TrackStats-Key` with `401`, while `POST /api/v1/webhook/discord?key=<key>` accepts the key via query parameter.
4. Admin session lifecycle: `POST /api/v1/auth/login` sets an `HttpOnly` cookie allowing admin mutations and revealing `ingest_key` in `GET /api/v1/connector/config`; `POST /api/v1/auth/logout` revokes access.
5. Header injection guard on `X-Forwarded-Host`: malicious characters (`"`, `'`, `\n`, `\r`, `\`, whitespace) in `X-Forwarded-Host` must be rejected so `/loader.lua` cannot be tricked into emitting invalid Lua syntax.

---

### Task 1: Environment Configuration & Auth Layer (`src/config.py`, `src/auth.py`, `src/main.py`)

**Files:**
- Modify: `src/config.py:1-19`
- Create: `src/auth.py`
- Modify: `src/main.py`
- Test: `tests/test_public_auth_and_loader.py`

**Interfaces:**
- Consumes: `src.config.settings`
- Produces:
  - `Settings.port`, `Settings.host`, `Settings.public_base_url`, `Settings.ingest_key`, `Settings.admin_password`, `Settings.public_read`
  - `resolve_public_base_url(request: Request) -> str`
  - `require_ingest_key(request: Request) -> None`
  - `require_admin(request: Request) -> None`
  - `require_read_access(request: Request) -> None`
  - `GET /healthz`, `GET /api/v1/auth/status`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/connector/config`

- [ ] **Step 1: Write failing tests for auth, proxy URL resolution, and key masking in `tests/test_public_auth_and_loader.py`**

```python
def test_healthz_always_public(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-admin")
    monkeypatch.setattr(settings, "public_read", False)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_ingest_key_blocks_unauthenticated_telemetry_and_allows_valid_key(client, monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", "ts_live_key_123")
    payload = {"userId": 1001, "currentTaps": 500, "totalTaps": 500}

    res_no_key = client.post("/api/v1/telemetry", json=payload)
    assert res_no_key.status_code == 401

    res_bad_key = client.post("/api/v1/telemetry", json=payload, headers={"X-TrackStats-Key": "wrong"})
    assert res_bad_key.status_code == 401

    res_ok = client.post("/api/v1/telemetry", json=payload, headers={"X-TrackStats-Key": "ts_live_key_123"})
    assert res_ok.status_code == 200
    assert res_ok.json()["user_id"] == 1001


def test_admin_login_cookie_unlocks_mutations_and_connector_key(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "my_admin_pw")
    monkeypatch.setattr(settings, "ingest_key", "ts_secret_999")
    monkeypatch.setattr(settings, "public_read", True)

    # Guest can read overview, but connector config masks ingest_key
    assert client.get("/api/v1/overview").status_code == 200
    cfg_guest = client.get("/api/v1/connector/config").json()
    assert cfg_guest["is_admin"] is False
    assert cfg_guest["ingest_key"] is None

    # Guest cannot mutate alerts or delete accounts
    assert client.post("/api/v1/settings/alerts", json={"enabled": True}).status_code == 401

    # Wrong password rejected
    assert client.post("/api/v1/auth/login", json={"password": "wrong"}).status_code == 401

    # Valid login sets cookie and reveals ingest_key
    login_res = client.post("/api/v1/auth/login", json={"password": "my_admin_pw"})
    assert login_res.status_code == 200
    cfg_admin = client.get("/api/v1/connector/config").json()
    assert cfg_admin["is_admin"] is True
    assert cfg_admin["ingest_key"] == "ts_secret_999"
    assert client.post("/api/v1/settings/alerts", json={"enabled": True}).status_code == 200

    # Logout clears admin session
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/connector/config").json()["ingest_key"] is None
```

- [ ] **Step 2: Run pytest to verify the new tests fail**

Run: `pytest tests/test_public_auth_and_loader.py -v`
Expected: FAIL (`404 Not Found` on `/healthz`, `/api/v1/connector/config`, `/api/v1/auth/login`)

- [ ] **Step 3: Implement env settings in `src/config.py`, auth helpers in `src/auth.py`, and route dependencies in `src/main.py`**

Update `src/config.py` to read `PORT`, `HOST`, `PUBLIC_BASE_URL`, `TRACKSTATS_INGEST_KEY`, `TRACKSTATS_ADMIN_PASSWORD`, and `TRACKSTATS_PUBLIC_READ`. Create `src/auth.py` with `resolve_public_base_url`, `create_admin_session_token`, `verify_admin_session_token`, `is_admin_request`, `require_admin`, `require_read_access`, and `require_ingest_key`. Wire routes and dependencies in `src/main.py`.

- [ ] **Step 4: Run pytest to verify Task 1 tests pass and existing tests remain green**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit Task 1**

```bash
git add src/config.py src/auth.py src/main.py tests/test_public_auth_and_loader.py
git commit -m "feat(auth): add public read-only mode, admin session cookie, and ingest key guard"
```

---

### Task 2: Executor `/loader.lua` & `getgenv().TrackStats` Luau Upgrade (`src/main.py`, `scripts/tap_sim_reborn_tracker.lua`, `tools/telemetry_feeder.py`)

**Files:**
- Modify: `src/main.py` (`/loader.lua` and `/api/v1/connector/script.lua`)
- Modify: `scripts/tap_sim_reborn_tracker.lua:16-180`
- Modify: `tools/telemetry_feeder.py`
- Test: `tests/test_public_auth_and_loader.py`

**Interfaces:**
- Consumes: `resolve_public_base_url(request: Request) -> str`
- Produces:
  - `GET /loader.lua` & `GET /api/v1/connector/script.lua` (auto-injects `https://<host>/api/v1/telemetry` & `/api/v1/connector/inspect` using `resolve_public_base_url`, never embeds `ingest_key`)
  - Luau `getgenv().TrackStats` / `_G.TrackStats` reader + `X-TrackStats-Key` header in `postJson`

- [ ] **Step 1: Add failing tests for `/loader.lua` proxy header rewrite, injection safety, and Luau `getgenv().TrackStats` support in `tests/test_public_auth_and_loader.py`**

```python
def test_loader_lua_uses_forwarded_https_and_never_leaks_key(client, monkeypatch):
    monkeypatch.setattr(settings, "ingest_key", "ts_super_secret_key")
    res = client.get(
        "/loader.lua",
        headers={
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "tapsim-trackstats.up.railway.app",
        },
    )
    assert res.status_code == 200
    body = res.text
    assert 'ENDPOINT_URL = "https://tapsim-trackstats.up.railway.app/api/v1/telemetry"' in body
    assert 'INSPECT_URL = "https://tapsim-trackstats.up.railway.app/api/v1/connector/inspect"' in body
    assert "ts_super_secret_key" not in body
    assert "X-TrackStats-Key" in body
    assert "getgenv" in body
```

- [ ] **Step 2: Run pytest to verify the new test fails**

Run: `pytest tests/test_public_auth_and_loader.py::test_loader_lua_uses_forwarded_https_and_never_leaks_key -v`
Expected: FAIL (`404 Not Found` on `/loader.lua`)

- [ ] **Step 3: Implement `/loader.lua` in `src/main.py`, `getgenv().TrackStats` + `X-TrackStats-Key` in `scripts/tap_sim_reborn_tracker.lua`, and `--key` in `tools/telemetry_feeder.py`**

- [ ] **Step 4: Run pytest to verify all tests pass**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit Task 2**

```bash
git add src/main.py scripts/tap_sim_reborn_tracker.lua tools/telemetry_feeder.py tests/test_public_auth_and_loader.py
git commit -m "feat(connector): add /loader.lua and getgenv().TrackStats key header support"
```

---

### Task 3: Public Read-Only + Admin Unlock + 1-Click Executor Loader UI (`src/static/index.html`, `src/static/js/app.js`, `src/static/css/style.css`)

**Files:**
- Modify: `src/static/index.html`
- Modify: `src/static/js/app.js`
- Modify: `src/static/css/style.css`
- Test: `tests/test_public_auth_and_loader.py`

**Interfaces:**
- Consumes: `GET /api/v1/auth/status`, `POST /api/v1/auth/login`, `POST /api/v1/auth/logout`, `GET /api/v1/connector/config`
- Produces:
  - Navbar `#btnAdminAuth` button & `#adminAuthModal` login dialog
  - Connector tab `#executorLoaderSnippet`, `#btnCopyLoaderSnippet`, `#executorFallbackSnippet`, `#btnCopyFallbackSnippet`, and `#connectorKeyNotice`

- [ ] **Step 1: Add failing UI markup & JS contract test in `tests/test_public_auth_and_loader.py`**

```python
def test_dashboard_html_contains_executor_loader_and_admin_modal(client):
    html = client.get("/").text
    assert 'id="executorLoaderSnippet"' in html
    assert 'id="btnCopyLoaderSnippet"' in html
    assert 'id="btnAdminAuth"' in html
    assert 'id="adminAuthModal"' in html
```

- [ ] **Step 2: Run pytest to verify the UI test fails**

Run: `pytest tests/test_public_auth_and_loader.py::test_dashboard_html_contains_executor_loader_and_admin_modal -v`
Expected: FAIL

- [ ] **Step 3: Update `src/static/index.html`, `src/static/js/app.js`, and `src/static/css/style.css` with Admin Unlock and 1-Click Executor Loader**

- [ ] **Step 4: Run pytest to verify all tests pass**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit Task 3**

```bash
git add src/static/index.html src/static/js/app.js src/static/css/style.css tests/test_public_auth_and_loader.py
git commit -m "feat(ui): add 1-click executor loadstring box and admin unlock modal"
```

---

### Task 4: Railway Production Packaging & Live Cloud Deployment (`Dockerfile`, `.dockerignore`, `railway.toml`, `run.py`, `README.md`)

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `railway.toml`
- Modify: `run.py`
- Modify: `README.md`
- Test: `tests/test_public_auth_and_loader.py`

**Interfaces:**
- Consumes: `src.main:app`, `src.config.settings`
- Produces:
  - Production container image listening on `0.0.0.0:${PORT:-3883}` with `--proxy-headers --forwarded-allow-ips=*`
  - Live Railway deployment with persistent Volume at `/data`, `TRACKSTATS_DB_PATH=/data/trackstats.db`, generated `TRACKSTATS_INGEST_KEY` and `TRACKSTATS_ADMIN_PASSWORD`, `TRACKSTATS_PUBLIC_READ=true`, and public `https://*.up.railway.app` domain.

- [ ] **Step 1: Write failing packaging test verifying `Dockerfile` and `railway.toml` exist and configure `/healthz` + proxy headers**

```python
def test_railway_packaging_files_exist():
    from src.config import BASE_DIR
    dockerfile = (BASE_DIR / "Dockerfile").read_text(encoding="utf-8")
    railway_toml = (BASE_DIR / "railway.toml").read_text(encoding="utf-8")
    assert "--proxy-headers" in dockerfile
    assert "/healthz" in railway_toml
```

- [ ] **Step 2: Run pytest to verify it fails**

Run: `pytest tests/test_public_auth_and_loader.py::test_railway_packaging_files_exist -v`
Expected: FAIL (`FileNotFoundError`)

- [ ] **Step 3: Create `Dockerfile`, `.dockerignore`, `railway.toml`, update `run.py` & `README.md`**

- [ ] **Step 4: Run full pytest suite to verify all tests pass**

Run: `pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit Task 4 and deploy to Railway**

```bash
git add Dockerfile .dockerignore railway.toml run.py README.md tests/test_public_auth_and_loader.py
git commit -m "build(railway): add production Dockerfile and railway.toml config"
```

Then push to private GitHub repo `tuananh8956/tap-simulator-trackstats` (or deploy via Railway CLI/MCP), create Railway project `tap-simulator-trackstats`, attach `/data` persistent volume, configure environment variables (`TRACKSTATS_DB_PATH=/data/trackstats.db`, `TRACKSTATS_INGEST_KEY`, `TRACKSTATS_ADMIN_PASSWORD`, `TRACKSTATS_PUBLIC_READ=true`), generate public `*.up.railway.app` domain, wait for deployment `SUCCESS`, and verify live endpoints (`/healthz`, `/loader.lua`, auth rejection, and authenticated telemetry).
