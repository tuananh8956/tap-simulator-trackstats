# Tap Simulator Reborn TrackStats v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade `tap-simulator-trackstats` into a multi-account *Tap Simulator Reborn* TrackStats v2 system featuring a Secret Vault with per-Secret pet images, a redesigned 6-tab dark cyber-glass website UI, bidirectional Discord webhooks, and a strictly read-only Luau in-game telemetry script with Inspector mode.

**Architecture:** Extend the existing FastAPI + SQLite (WAL) single-server backend with idempotent schema migrations, a `PetCatalogService` implementing a 5-step image resolution pipeline (custom override -> safe URL -> Roblox Asset Thumbnail -> 18 bespoke local SVGs -> procedural SVG endpoint), an enhanced `SessionManager`/`RateEngine` for farm-wide aggregation and AFK-safe Secret syncing, and a `WebhookService` for inbound/outbound Discord integration. Keep the frontend zero-build inside `src/static/` using SSE and Chart.js, paired with `scripts/tap_sim_reborn_tracker.lua` and an upgraded `tools/telemetry_feeder.py`.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, Pydantic v2, SQLite (WAL), httpx, Vanilla HTML5/CSS3/JS, Chart.js 4, Lucide Icons, Luau (client telemetry script), Pytest.

**Spec:** [docs/superpowers/specs/2026-11-19-tap-simulator-reborn-v2-secrets-ui-design.md](../specs/2026-11-19-tap-simulator-reborn-v2-secrets-ui-design.md)

## Global Constraints

- Target Roblox game: **Tap Simulator REBORN**, Place ID `72858262610964`, Universe ID `10629695169`, default port `3883`.
- Zero Node.js / npm / Vite frontend build tooling — all web UI lives directly in `src/static/`.
- Zero `.ROBLOSECURITY` cookies, passwords, auth tokens, DLL injection, memory tampering, or gameplay automation (`auto-tap`, `auto-hatch`, `auto-rebirth`, firing game remotes).
- 100% backward compatibility with all existing v1 REST endpoints, SQLite tables, and all 28 existing pytest tests (including v1 UI text checks in `tests/test_static_ui.py`: `"Tap Simulator Reborn"`, `"TrackStats"`, `"Chart"`, `"Live Statistics"`, `"Equipped Pets"`, `"Multi-Account"`).
- All user/game-supplied strings rendered in the web UI must be HTML-escaped, and all pet `imageUrl` values must be sanitized to allow only `http://`, `https://`, `/static/`, or `/api/` schemes.
- Never fabricate live telemetry when no client or feeder has posted data.

## Review Focus

1. **XSS / Unsafe URL Scheme Injection (Tasks 1, 3, 8):** Telemetry or inbound Discord webhooks containing `<img src=x onerror=alert(1)>` in pet/account/world names or `javascript:alert(1)` in `imageUrl` must be rejected/escaped cleanly and fall back to catalog SVG artwork.
2. **AFK Closed-Inventory Secret Wipe & False Hatch Flood (Tasks 5, 9):** Omitting `secretPets` (`None`) when the in-game Pet UI is closed must preserve existing `account_secrets`; receiving a Secret via `recentHatches` while `secretPets` is omitted must increment `account_secrets` by 1 without generating duplicate hatch alerts when the inventory later syncs.
3. **Cross-Source Hatch Duplication & Secret Double-Counting (Tasks 2, 5, 6):** Receiving the same Secret hatch from `recentHatches`, `delta_detected`, and `/api/v1/webhook/discord` within 15 seconds must persist only one `hatch_events` row, trigger at most one outbound alert, and avoid mutating `account_secrets` from inbound webhooks if an authoritative Luau `secretPets` sync occurred within 60 seconds.
4. **Masked Discord Webhook Overwrite & Repeated Timeout Spam (Tasks 5, 6):** Submitting `POST /api/v1/settings/alerts` with the masked placeholder URL returned by `GET /api/v1/settings/alerts` must preserve the stored secret webhook URL; and `SessionManager.check_timeouts()` called repeatedly every 2s must emit `STALE` / `DISCONNECTED` transition events only once per state change.
5. **Legacy v1 SQLite Database & v1 Backup Upgrade (Task 2):** Opening a pre-v2 SQLite DB lacking new columns/tables or calling `restore_data()` with a v1 JSON export must migrate and restore cleanly without losing existing accounts/sessions/snapshots or violating foreign keys.

---

## File Structure Overview

- **Modify:** `src/models.py` — v2 Pydantic models + normalization/sanitization helpers (`slugify_pet_name`, `normalize_variant`, `sanitize_image_url`, `extract_asset_id`).
- **Modify:** `src/database.py` — idempotent v2 schema migrations, `account_secrets`, `pet_catalog`, `hatch_events` (nullable `user_id` + `actor_name`), `settings_kv`, `inspector_reports`, 15s dedup hatch recording, v2 export/restore.
- **Create:** `src/pet_catalog.py` & 18 SVGs in `src/static/assets/pets/*.svg` — seeded Secret catalog, 5-step image resolution, custom image overrides, procedural fallback SVG generator.
- **Modify:** `src/roblox_poller.py` — `get_asset_thumbnail(asset_id)` and `get_user_by_username(username)` with caching and 429 backoff.
- **Modify:** `src/rate_engine.py` & `src/session_manager.py` — `eggs_per_hour`, AFK-safe Secret syncing, delta hatch detection, farm-wide `get_overview()`, `get_secrets_summary()`, live boost countdowns, transition-only `check_timeouts()`.
- **Create:** `src/webhook_service.py` — masked alert settings, outbound Discord Secret/status embeds, inbound Discord webhook parser + account resolution + dedup + optional forwarding.
- **Modify:** `src/main.py` — all v2 REST endpoints, SSE JSON envelope, async Roblox profile & asset thumbnail enrichment, transition alert dispatch, dynamic `.lua` script serving.
- **Modify:** `src/static/index.html`, `src/static/css/style.css`, `src/static/js/app.js` — redesigned 6-tab cyber-glass SPA with Farm Overview strip, Secret Vault gallery & custom image modal, Live Hatch Feed & Discord Settings, Multi-Account Matrix Pro, History & Restore, and Game Connector/Inspector.
- **Create:** `scripts/tap_sim_reborn_tracker.lua` — strictly read-only Luau client script with multi-executor HTTP wrapper, singleton guard, closed-UI guard, hatch popup/chat listener, and Inspector mode.
- **Modify:** `tools/telemetry_feeder.py` & `README.md` — multi-account Secret/variant/hatch/world/boost simulation feeder and v2 documentation.

---

### Task 1: Extended Data Models & Normalization Helpers

**Files:**
- Modify: `src/models.py:1-51`
- Test: `tests/test_models_v2.py`

**Interfaces:**
- Consumes: Existing `PetItem`, `TelemetryPayload`, `AccountInfo`, `SessionSummary` in `src/models.py`.
- Produces (exported from `src/models.py`):
  - Helpers: `slugify_pet_name(name: str) -> str`, `normalize_variant(variant: Optional[str]) -> str`, `sanitize_image_url(url: Optional[str]) -> Optional[str]`, `extract_asset_id(raw: Any) -> Optional[int]`
  - Models: `PetItem` (adds `variant`, `tier`, `count`, `isEquipped`, `isLocked`, `eggSource`, `imageAssetId`, `imageUrl`), `BoostItem`, `HatchEventInput`, `TelemetryPayload` (adds `secretPets: Optional[List[PetItem]] = None`, `secretCount: Optional[int] = None`, `eggsHatched: int = 0`, `world: Optional[str] = None`, `activeBoosts: List[BoostItem]`, `recentHatches: List[HatchEventInput]`, `clientSource: str = "telemetry"`), `CatalogImageOverrideRequest`, `AlertSettings`, `AlertSettingsUpdate`, `InspectorReportInput`.

- [ ] **Step 1: Write failing tests in `tests/test_models_v2.py`**

```python
from src.models import (
    TelemetryPayload, PetItem, BoostItem, HatchEventInput,
    AlertSettings, AlertSettingsUpdate, CatalogImageOverrideRequest,
    InspectorReportInput, slugify_pet_name, normalize_variant,
    sanitize_image_url, extract_asset_id,
)

def test_slugify_and_variant_normalization():
    assert slugify_pet_name("Void Overseer") == "void-overseer"
    assert slugify_pet_name("  King Of Hell!! ") == "king-of-hell"
    assert normalize_variant("rainbow") == "Rainbow"
    assert normalize_variant("GOLDEN") == "Golden"
    assert normalize_variant("shiny rainbow") == "Rainbow Shiny"
    assert normalize_variant("  ") == "Normal"
    assert normalize_variant(None) == "Normal"

def test_sanitize_image_url_rejects_unsafe_schemes():
    assert sanitize_image_url("https://tr.rbxcdn.com/pet.png") == "https://tr.rbxcdn.com/pet.png"
    assert sanitize_image_url("/static/assets/pets/dark-cat.svg") == "/static/assets/pets/dark-cat.svg"
    assert sanitize_image_url("/api/v1/pets/icon/dark-cat.svg") == "/api/v1/pets/icon/dark-cat.svg"
    assert sanitize_image_url("javascript:alert(1)") is None
    assert sanitize_image_url("data:text/html,<script>alert(1)</script>") is None
    assert sanitize_image_url("vbscript:msgbox(1)") is None

def test_extract_asset_id_formats():
    assert extract_asset_id(123456789) == 123456789
    assert extract_asset_id("rbxassetid://987654321") == 987654321
    assert extract_asset_id("http://www.roblox.com/asset/?id=5551234") == 5551234
    assert extract_asset_id("rbxthumb://type=Asset&id=777888&w=150&h=150") == 777888
    assert extract_asset_id("not-an-id") is None

def test_v2_telemetry_payload_backward_compat_and_defaults():
    v1 = TelemetryPayload(userId=42, currentTaps=100, totalTaps=500)
    assert v1.secretPets is None
    assert v1.secretCount is None
    assert v1.eggsHatched == 0
    assert v1.world is None
    assert v1.activeBoosts == []
    assert v1.recentHatches == []
    assert v1.clientSource == "telemetry"

    v2 = TelemetryPayload(
        userId=42,
        secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="rainbow", tier="Secret III", count=2, imageAssetId="rbxassetid://12345")],
        eggsHatched=1500,
        world="Void Island",
        activeBoosts=[BoostItem(name="2x Luck", multiplier="2x", remainingSec=600)],
        recentHatches=[HatchEventInput(petName="Dark Cat", variant="rainbow", eggName="Void Egg", odds="1 in 4M")],
        clientSource="luau",
    )
    assert v2.secretPets[0].variant == "Rainbow"
    assert v2.secretPets[0].imageAssetId == 12345
    assert v2.recentHatches[0].variant == "Rainbow"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_v2.py -v`
Expected: FAIL with `ImportError` for new helpers/models.

- [ ] **Step 3: Implement helpers and v2 models in `src/models.py`**

Add `slugify_pet_name`, `normalize_variant` (canonicalizing `Normal`, `Golden`, `Diamond`, `Rainbow`, `Shiny`, `Golden Shiny`, `Diamond Shiny`, `Rainbow Shiny`, falling back to title-case for unknown variants), `sanitize_image_url` (allowing only `http://`, `https://`, `/static/`, `/api/` without whitespace/control chars), `extract_asset_id` (regex extracting positive int from `int`, `rbxassetid://`, `asset/?id=`, `rbxthumb://...id=`). Extend `PetItem` with field validators normalizing `variant`, clamping `count >= 1`, extracting `imageAssetId`, and sanitizing `imageUrl`. Add `BoostItem`, `HatchEventInput`, `CatalogImageOverrideRequest`, `AlertSettings`, `AlertSettingsUpdate` (adds `clearWebhook: bool = False`), `InspectorReportInput`, and v2 optional fields on `TelemetryPayload`.

- [ ] **Step 4: Run tests to verify pass and backward compatibility**

Run: `pytest tests/test_models.py tests/test_models_v2.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_models_v2.py
git commit -m "feat(models): add v2 Secret, boost, hatch, alert models and URL/variant helpers"
```

---

### Task 2: SQLite v2 Migrations, Secret Vault, Catalog, Hatch Events & Settings Persistence

**Files:**
- Modify: `src/database.py:1-285`
- Test: `tests/test_database_v2.py`

**Interfaces:**
- Consumes: Task 1 helpers (`slugify_pet_name`, `normalize_variant`, `sanitize_image_url`).
- Produces (methods on `Database` in `src/database.py`):
  - Idempotent migrations in `init_db()` adding columns to `accounts` (`world`, `eggs_hatched`, `secret_count`, `last_client_source`) and `snapshots` (`eggs_hatched`, `secret_count`, `world`), plus creating tables `account_secrets`, `pet_catalog`, `hatch_events` (`user_id INTEGER NULL`, `actor_name TEXT`), `settings_kv`, `inspector_reports`.
  - `update_account_stats(user_id: int, world: Optional[str] = None, eggs_hatched: Optional[int] = None, secret_count: Optional[int] = None, client_source: Optional[str] = None) -> None`
  - `replace_account_secrets(user_id: int, secrets: List[Dict[str, Any]], updated_at: float) -> int` (returns total secret count)
  - `increment_account_secret(user_id: int, name: str, variant: str = "Normal", tier: Optional[str] = None, egg_source: Optional[str] = None, image_asset_id: Optional[int] = None, image_url: Optional[str] = None, updated_at: Optional[float] = None) -> int` (increments or inserts count=1 and updates `accounts.secret_count`, returns new total secret count)
  - `get_account_secrets(user_id: Optional[int] = None) -> List[Dict[str, Any]]`
  - `upsert_pet_catalog(slug: str, name: str, rarity: str = "Secret", tier: Optional[str] = None, default_egg: Optional[str] = None, odds: Optional[str] = None, image_asset_id: Optional[int] = None, resolved_image_url: Optional[str] = None, custom_image_url: Optional[str] = None, overwrite_custom: bool = False) -> Dict[str, Any]`
  - `get_pet_catalog_item(slug: str) -> Optional[Dict[str, Any]]`
  - `get_pet_catalog() -> List[Dict[str, Any]]`
  - `record_hatch_event(event: Dict[str, Any], dedup_window_sec: float = 15.0) -> Optional[Dict[str, Any]]` (dedups by `event_key` OR `(user_id/actor_name, slug(pet_name), variant)` within `dedup_window_sec`; returns inserted row dict or `None`)
  - `get_hatch_events(limit: int = 50, rarity: Optional[str] = None, user_id: Optional[int] = None) -> List[Dict[str, Any]]`
  - `get_setting(key: str, default: Any = None) -> Any` / `set_setting(key: str, value: Any) -> None`
  - `save_inspector_report(user_id: int, username: Optional[str], place_id: Optional[int], structure: Dict[str, Any], created_at: Optional[float] = None) -> Dict[str, Any]` (prunes to keep last 10)
  - `get_inspector_reports(limit: int = 10) -> List[Dict[str, Any]]`

- [ ] **Step 1: Write failing tests in `tests/test_database_v2.py`**

```python
import json, sqlite3
from src.database import Database

def test_legacy_v1_db_migrates_without_data_loss(tmp_path):
    db_file = tmp_path / "legacy_v1.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript("""
        CREATE TABLE accounts (user_id INTEGER PRIMARY KEY, username TEXT NOT NULL, display_name TEXT, avatar_url TEXT, is_tracking INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, last_seen TIMESTAMP);
        CREATE TABLE sessions (session_id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, start_time REAL NOT NULL, end_time REAL, initial_taps INTEGER DEFAULT 0, final_taps INTEGER DEFAULT 0, taps_gained INTEGER DEFAULT 0, initial_rebirths INTEGER DEFAULT 0, final_rebirths INTEGER DEFAULT 0, rebirths_gained INTEGER DEFAULT 0, max_tps REAL DEFAULT 0.0, avg_tps REAL DEFAULT 0.0);
        CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, user_id INTEGER NOT NULL, timestamp REAL NOT NULL, current_taps INTEGER NOT NULL, total_taps INTEGER DEFAULT 0, tps REAL NOT NULL, current_rebirths INTEGER DEFAULT 0, current_wins INTEGER DEFAULT 0, current_currency INTEGER DEFAULT 0, total_pet_power REAL DEFAULT 0.0, equipped_pets_json TEXT);
        INSERT INTO accounts (user_id, username) VALUES (101, 'LegacyUser');
    """)
    conn.commit()
    conn.close()

    db = Database(str(db_file))
    db.init_db()
    acc = db.get_account(101)
    assert acc["username"] == "LegacyUser"
    assert acc["secret_count"] == 0
    assert acc["eggs_hatched"] == 0
    assert acc["world"] is None

def test_account_secrets_replace_and_increment(tmp_path):
    db = Database(str(tmp_path / "sec.db"))
    db.init_db()
    db.upsert_account(1, "FarmA", "FarmA", "")
    total = db.replace_account_secrets(1, [
        {"name": "Dark Cat", "variant": "Rainbow", "tier": "Secret III", "count": 2, "multiplier": 25000.0, "power": 120000.0, "is_equipped": True},
        {"name": "Dark Cat", "variant": "Rainbow", "tier": "Secret III", "count": 1, "multiplier": 25000.0, "power": 125000.0, "is_equipped": False},
    ], updated_at=1000.0)
    assert total == 3
    rows = db.get_account_secrets(1)
    assert len(rows) == 1
    assert rows[0]["count"] == 3
    assert rows[0]["is_equipped"] == 1
    assert rows[0]["power"] == 125000.0

    new_total = db.increment_account_secret(1, "Dark Cat", "Rainbow", updated_at=1005.0)
    assert new_total == 4
    assert db.get_account(1)["secret_count"] == 4

def test_hatch_event_dedup_15s_and_nullable_user(tmp_path):
    db = Database(str(tmp_path / "hatch.db"))
    db.init_db()
    db.upsert_account(1, "FarmA", "FarmA", "")

    e1 = db.record_hatch_event({"user_id": 1, "actor_name": "FarmA", "pet_name": "Chronos", "rarity": "Secret", "variant": "Golden", "source": "telemetry", "timestamp": 2000.0})
    assert e1 is not None
    # Same pet within 15s from webhook must be deduplicated
    e2 = db.record_hatch_event({"user_id": 1, "actor_name": "FarmA", "pet_name": "Chronos", "rarity": "Secret", "variant": "Golden", "source": "webhook", "timestamp": 2010.0})
    assert e2 is None
    # After 15s window, new hatch allowed
    e3 = db.record_hatch_event({"user_id": 1, "actor_name": "FarmA", "pet_name": "Chronos", "rarity": "Secret", "variant": "Golden", "source": "webhook", "timestamp": 2020.0})
    assert e3 is not None
    # Unlinked webhook hatch with user_id=None succeeds under PRAGMA foreign_keys=ON
    e4 = db.record_hatch_event({"user_id": None, "actor_name": "MysteryPlayer", "pet_name": "Void Wraith", "rarity": "Secret", "variant": "Normal", "source": "webhook", "timestamp": 2025.0})
    assert e4 is not None
    assert e4["user_id"] is None
    assert e4["actor_name"] == "MysteryPlayer"

def test_v1_backup_restore_and_v2_export_roundtrip(tmp_path):
    db = Database(str(tmp_path / "rt.db"))
    db.init_db()
    v1_backup = json.dumps({"accounts": [{"user_id": 7, "username": "OldBackup"}], "sessions": [], "snapshots": []})
    assert db.restore_data(v1_backup) is True
    assert db.get_account(7)["username"] == "OldBackup"

    db.replace_account_secrets(7, [{"name": "Void Wraith", "variant": "Normal", "count": 2}], updated_at=100.0)
    exported = db.export_data("json")
    data = json.loads(exported)
    assert len(data["account_secrets"]) == 1

    db2 = Database(str(tmp_path / "rt2.db"))
    db2.init_db()
    assert db2.restore_data(exported) is True
    assert len(db2.get_account_secrets(7)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_database_v2.py -v`
Expected: FAIL with `AttributeError` / missing columns.

- [ ] **Step 3: Implement v2 schema migrations and CRUD methods in `src/database.py`**

Implement `_ensure_column(conn, table, column, ddl)` using `PRAGMA table_info(table)` inside `init_db()`, create the 5 new tables and indexes (`idx_hatch_events_time`, `idx_account_secrets_user`), implement `replace_account_secrets` (aggregating duplicates by `f"{slugify_pet_name(name)}::{normalize_variant(variant).lower()}"` inside a transaction and updating `accounts.secret_count`), `increment_account_secret`, `record_hatch_event` (checking both `event_key` and recent matching `(user_id/actor_name, pet_name, variant)` within `dedup_window_sec`), `pet_catalog` upsert/get, `settings_kv`, `inspector_reports` (keeping newest 10), and extend `insert_snapshot`, `export_data`, and `restore_data`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_database.py tests/test_database_v2.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/database.py tests/test_database_v2.py
git commit -m "feat(db): add v2 schema migrations, Secret vault, catalog, hatch dedup, and settings tables"
```

---

### Task 3: Curated 18 Secret Pet SVGs & Pet Catalog Service

**Files:**
- Create: `src/pet_catalog.py`
- Create: 18 SVG artwork files under `src/static/assets/pets/`:
  `void-wraith.svg`, `cinder-eye.svg`, `inferno-dragon.svg`, `autumn-warden.svg`, `oasis-spirit.svg`, `void-overseer.svg`, `shinigami.svg`, `helfire-spirit.svg`, `infernal-lord.svg`, `chronos.svg`, `forsaken-knight.svg`, `dragon-tamer.svg`, `king-of-hell.svg`, `malevolent-treat.svg`, `sanguine-heart.svg`, `peace-keeper.svg`, `time-paradox.svg`, `dark-cat.svg`
- Test: `tests/test_pet_catalog.py`

**Interfaces:**
- Consumes: Task 1 (`slugify_pet_name`, `sanitize_image_url`, `extract_asset_id`), Task 2 (`Database`).
- Produces (`src/pet_catalog.py`):
  - `SEEDED_SECRETS: List[Dict[str, str]]` (18 known Tap Simulator Reborn Secrets with `name`, `tier`, `default_egg`, `odds`)
  - `PetCatalogService(db: Database, assets_dir: Optional[Path] = None)`:
    - `seed_defaults() -> int`
    - `resolve_image_url(name: str, explicit_url: Optional[str] = None, asset_id: Optional[int] = None) -> str`
    - `register_discovered_pet(name: str, rarity: str = "Secret", tier: Optional[str] = None, egg_source: Optional[str] = None, odds: Optional[str] = None, image_asset_id: Optional[int] = None) -> Dict[str, Any]`
    - `set_resolved_thumbnail(slug: str, asset_id: int, thumbnail_url: str) -> None`
    - `set_custom_image(slug: str, image_url: Optional[str] = None, image_asset_id: Optional[int] = None, tier: Optional[str] = None, default_egg: Optional[str] = None, odds: Optional[str] = None) -> Dict[str, Any]`
    - `render_procedural_svg(slug: str, name: Optional[str] = None, tier: Optional[str] = None) -> str`
    - `list_catalog() -> List[Dict[str, Any]]`

- [ ] **Step 1: Write failing tests in `tests/test_pet_catalog.py`**

```python
from pathlib import Path
from src.database import Database
from src.pet_catalog import PetCatalogService, SEEDED_SECRETS

def test_seed_defaults_and_18_svg_files_exist(tmp_path):
    db = Database(str(tmp_path / "cat.db"))
    db.init_db()
    svc = PetCatalogService(db)
    count = svc.seed_defaults()
    assert count == 18
    assert len(SEEDED_SECRETS) == 18
    repo_root = Path(__file__).resolve().parent.parent
    for item in SEEDED_SECRETS:
        url = svc.resolve_image_url(item["name"])
        assert url.startswith("/static/assets/pets/") and url.endswith(".svg")
        svg_path = repo_root / "src/static/assets/pets" / url.split("/")[-1]
        assert svg_path.exists()
        assert "<svg" in svg_path.read_text(encoding="utf-8")

def test_image_resolution_5_step_precedence(tmp_path):
    db = Database(str(tmp_path / "prec.db"))
    db.init_db()
    svc = PetCatalogService(db)
    svc.seed_defaults()

    # Step 5: unknown pet falls back to procedural endpoint
    assert svc.resolve_image_url("Cosmic Leviathan") == "/api/v1/pets/icon/cosmic-leviathan.svg"
    # Step 4: seeded pet uses local SVG
    assert svc.resolve_image_url("Dark Cat") == "/static/assets/pets/dark-cat.svg"
    # Step 3: Roblox resolved asset thumbnail beats local SVG
    svc.set_resolved_thumbnail("dark-cat", 123456, "https://tr.rbxcdn.com/darkcat.png")
    assert svc.resolve_image_url("Dark Cat") == "https://tr.rbxcdn.com/darkcat.png"
    # Step 2: safe explicit telemetry URL beats resolved thumbnail; unsafe rejected
    assert svc.resolve_image_url("Dark Cat", explicit_url="https://cdn.example/live.png") == "https://cdn.example/live.png"
    assert svc.resolve_image_url("Dark Cat", explicit_url="javascript:alert(1)") == "https://tr.rbxcdn.com/darkcat.png"
    # Step 1: user custom_image_url override beats everything
    svc.set_custom_image("dark-cat", image_url="https://cdn.example/custom-darkcat.png")
    assert svc.resolve_image_url("Dark Cat", explicit_url="https://cdn.example/live.png") == "https://cdn.example/custom-darkcat.png"

def test_procedural_svg_escapes_html(tmp_path):
    db = Database(str(tmp_path / "svg.db"))
    db.init_db()
    svc = PetCatalogService(db)
    svg = svc.render_procedural_svg("evil-pet", name="<script>alert(1)</script>")
    assert svg.startswith("<svg")
    assert "<script>" not in svg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pet_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.pet_catalog'`.

- [ ] **Step 3: Create the 18 curated Secret pet SVGs under `src/static/assets/pets/` and implement `src/pet_catalog.py`**

Author 18 visually distinct, rich vector SVG portraits (`viewBox="0 0 128 128"`) matching each pet's theme (`Void Wraith` violet spectral hood, `Cinder Eye` molten blazing iris, `Inferno Dragon` crimson horned flame crest, `Autumn Warden` amber leaf-crowned spirit, `Oasis Spirit` emerald-aqua crystal spirit, `Void Overseer` abyssal multi-eye monolith, `Shinigami` cyan-violet reaper mask & scythe, `Helfire Spirit` inferno skull wisp, `Infernal Lord` obsidian crown & lava runes, `Chronos` radiant gold hourglass halo, `Forsaken Knight` cracked shadow visor & rune blade, `Dragon Tamer` imperial drake sigil, `King Of Hell` ruby-obsidian horned crown, `Malevolent Treat` eerie neon candy-jack, `Sanguine Heart` faceted crimson crystal heart, `Peace Keeper` angelic cyan-gold wings & halo, `Time Paradox` swirling twin temporal rings, `Dark Cat` glowing magenta-violet feline silhouette).
Implement `PetCatalogService` with the 5-step resolution precedence and XML-escaped deterministic procedural SVG rendering.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_pet_catalog.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pet_catalog.py src/static/assets/pets tests/test_pet_catalog.py
git commit -m "feat(catalog): add 18 curated Secret pet SVG portraits and PetCatalogService"
```

---

### Task 4: RobloxPoller Asset Thumbnail & Username Resolution

**Files:**
- Modify: `src/roblox_poller.py:1-133`
- Test: `tests/test_roblox_poller_v2.py`

**Interfaces:**
- Consumes: Task 1 (`extract_asset_id`).
- Produces (new async methods on `RobloxPoller` in `src/roblox_poller.py`):
  - `get_asset_thumbnail(asset_id: int) -> Optional[str]` (queries `https://thumbnails.roblox.com/v1/assets?assetIds={asset_id}&returnPolicy=PlaceHolder&size=150x150&format=Png&isCircular=false`, caches non-empty URLs in `self._asset_cache`, sets `self._backoff_until` on 429)
  - `get_user_by_username(username: str) -> Optional[Dict[str, Any]]` (queries `POST https://users.roblox.com/v1/usernames/users` with `{"usernames": [username], "excludeBannedUsers": False}`, returns `{"id": int, "name": str, "displayName": str}` or `None`, caches lowercase username in `self._username_cache`, respects 429 backoff)

- [ ] **Step 1: Write failing tests in `tests/test_roblox_poller_v2.py`**

```python
import pytest
from unittest.mock import patch, MagicMock
from src.roblox_poller import RobloxPoller

@pytest.mark.anyio
async def test_get_asset_thumbnail_caches_result():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"targetId": 999111, "state": "Completed", "imageUrl": "https://tr.rbxcdn.com/asset-999111.png"}]}
        )
        url1 = await poller.get_asset_thumbnail(999111)
        url2 = await poller.get_asset_thumbnail(999111)
        assert url1 == "https://tr.rbxcdn.com/asset-999111.png"
        assert url2 == url1
        assert mock_get.call_count == 1

@pytest.mark.anyio
async def test_get_user_by_username_resolves_and_caches():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"data": [{"id": 888222, "name": "SecretHunter", "displayName": "Hunter"}]}
        )
        user = await poller.get_user_by_username("SecretHunter")
        assert user == {"id": 888222, "name": "SecretHunter", "displayName": "Hunter"}
        user_cached = await poller.get_user_by_username("secrethunter")
        assert user_cached["id"] == 888222
        assert mock_post.call_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_roblox_poller_v2.py -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Implement `get_asset_thumbnail` and `get_user_by_username` in `src/roblox_poller.py`**

Add `_asset_cache: Dict[int, str]` and `_username_cache: Dict[str, Dict[str, Any]]` in `__init__`, respect `_backoff_until`, and implement both async methods cleanly.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_roblox_poller.py tests/test_roblox_poller_v2.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/roblox_poller.py tests/test_roblox_poller_v2.py
git commit -m "feat(poller): add Roblox asset thumbnail and username lookup with caching"
```

---

### Task 5: RateEngine Egg Rate & SessionManager v2 (Secrets, Overview, Boosts, AFK Hatch Sync, Transition-Only Timeouts)

**Files:**
- Modify: `src/rate_engine.py:1-128`
- Modify: `src/session_manager.py:1-194`
- Test: `tests/test_session_manager_v2.py`

**Interfaces:**
- Consumes: Task 1, Task 2 (`Database`), Task 3 (`PetCatalogService`).
- Produces:
  - `RateEngine.get_rates(user_id)` adds `"eggs_per_hour": float` (computed across buffer with `max(10.0, dt)` guard to prevent spikes).
  - `SessionManager(db, rate_engine, poller=None, pet_catalog=None, stale_timeout_sec=15.0, disconnect_timeout_sec=60.0)`:
    - `process_telemetry(payload: TelemetryPayload) -> Dict[str, Any]` returns `{"status", "user_id", "session_id", "tps", "new_hatches", "pending_asset_ids", "needs_profile_lookup"}`.
    - `check_timeouts(now=None) -> List[Dict[str, Any]]`: emits events ONLY on state transition (`prev_state != new_state`), each event containing `{"user_id", "username", "event", "prev_state", "session_id"}`.
    - `get_live_state(user_id, now=None)` preserves all v1 keys and adds `secret_count`, `secret_pets`, `eggs_hatched`, `eggs_per_hour`, `world`, `active_boosts` (remainingSec adjusted by elapsed time), `client_source`.
    - `get_overview(now=None) -> Dict[str, Any]`: returns `total_accounts`, `live_accounts`, `stale_accounts`, `disconnected_accounts`, `paused_accounts`, `idle_accounts`, `total_secrets`, `unique_secret_species`, `by_variant`, `total_tps`, `total_current_taps`, `total_taps`, `total_currency`, `total_rebirths`, `total_eggs_hatched`, `eggs_per_hour`.
    - `get_secrets_summary(user_id=None, variant=None, tier=None, query=None) -> Dict[str, Any]`: returns `total_secrets`, `unique_types`, `by_variant`, `by_tier`, `grouped` (each entry has `pet_key`, `slug`, `name`, `variant`, `tier`, `total_count`, `max_multiplier`, `max_power`, `egg_source`, `image_url`, `owners`), and `items`.
    - `has_recent_authoritative_secret_sync(user_id: int, within_sec: float = 60.0, now: Optional[float] = None) -> bool`

- [ ] **Step 1: Write failing tests in `tests/test_session_manager_v2.py`**

```python
from src.database import Database
from src.rate_engine import RateEngine
from src.pet_catalog import PetCatalogService
from src.session_manager import SessionManager
from src.models import TelemetryPayload, PetItem, BoostItem, HatchEventInput

def _make_mgr(tmp_path):
    db = Database(str(tmp_path / "sm2.db"))
    db.init_db()
    cat = PetCatalogService(db)
    cat.seed_defaults()
    re = RateEngine()
    return SessionManager(db, re, poller=None, pet_catalog=cat)

def test_afk_closed_inventory_preserves_secrets_and_increments_on_recent_hatch(tmp_path):
    mgr = _make_mgr(tmp_path)
    # 1. Initial open-inventory sync with 2 Dark Cats
    p1 = TelemetryPayload(
        userId=10, currentTaps=100, totalTaps=100, eggsHatched=500, world="Void Island",
        secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="Rainbow", tier="Secret III", count=2, multiplier=25000, power=120000)],
        timestamp=1000.0,
    )
    res1 = mgr.process_telemetry(p1)
    assert res1["new_hatches"] == []
    assert mgr.get_live_state(10, now=1001.0)["secret_count"] == 2

    # 2. Inventory closed during AFK: secretPets omitted (None), partial stats + 1 new Secret hatch popup
    p2 = TelemetryPayload(
        userId=10, currentTaps=200, totalTaps=200, eggsHatched=620, world="Void Island",
        secretPets=None,
        recentHatches=[HatchEventInput(petName="Dark Cat", rarity="Secret", variant="Rainbow", eggName="Void Egg", timestamp=1010.0)],
        timestamp=1010.0,
    )
    res2 = mgr.process_telemetry(p2)
    assert len(res2["new_hatches"]) == 1
    assert mgr.get_live_state(10, now=1011.0)["secret_count"] == 3

    # 3. Inventory reopened 5s later with count=3 -> reconciles without duplicate delta hatch!
    p3 = TelemetryPayload(
        userId=10, currentTaps=250, totalTaps=250, eggsHatched=650,
        secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="Rainbow", tier="Secret III", count=3, multiplier=25000, power=120000)],
        timestamp=1015.0,
    )
    res3 = mgr.process_telemetry(p3)
    assert res3["new_hatches"] == []
    assert mgr.get_live_state(10, now=1016.0)["secret_count"] == 3

def test_delta_secret_detection_and_farm_overview_and_boost_countdown(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.process_telemetry(TelemetryPayload(
        userId=10, currentTaps=100, totalTaps=100, eggsHatched=1000, world="Void Island",
        activeBoosts=[BoostItem(name="2x Luck", multiplier="2x", remainingSec=120.0)],
        secretPets=[PetItem(name="Chronos", rarity="Secret", variant="Golden", tier="Secret II", count=1)],
        timestamp=1000.0,
    ))
    res = mgr.process_telemetry(TelemetryPayload(
        userId=10, currentTaps=400, totalTaps=400, eggsHatched=1100, world="Void Island",
        activeBoosts=[BoostItem(name="2x Luck", multiplier="2x", remainingSec=110.0)],
        secretPets=[PetItem(name="Chronos", rarity="Secret", variant="Golden", tier="Secret II", count=2)],
        timestamp=1010.0,
    ))
    assert len(res["new_hatches"]) == 1
    assert res["new_hatches"][0]["source"] == "delta_detected"

    state = mgr.get_live_state(10, now=1020.0)
    assert state["eggs_per_hour"] > 0
    assert state["active_boosts"][0]["remainingSec"] == 100.0
    assert state["secret_pets"][0]["image_url"] == "/static/assets/pets/chronos.svg"

    overview = mgr.get_overview(now=1020.0)
    assert overview["total_secrets"] == 2
    assert overview["live_accounts"] == 1
    summary = mgr.get_secrets_summary(variant="Golden")
    assert summary["total_secrets"] == 2
    assert summary["grouped"][0]["name"] == "Chronos"

def test_check_timeouts_emits_only_on_state_transition(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.process_telemetry(TelemetryPayload(userId=10, currentTaps=10, totalTaps=10, timestamp=1000.0))
    ev1 = mgr.check_timeouts(now=1020.0)
    ev2 = mgr.check_timeouts(now=1022.0)
    assert [e["event"] for e in ev1] == ["STALE"]
    assert ev2 == []  # No repeated STALE spam every 2s

    ev3 = mgr.check_timeouts(now=1065.0)
    ev4 = mgr.check_timeouts(now=1067.0)
    assert [e["event"] for e in ev3] == ["DISCONNECTED"]
    assert ev4 == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_session_manager_v2.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `src/rate_engine.py` and `src/session_manager.py`**

- In `src/rate_engine.py`: store `"eggs_hatched": payload.eggsHatched` in each buffer record; compute `eggs_per_hour = round(max(0, latest["eggs_hatched"] - oldest["eggs_hatched"]) * 3600.0 / max(10.0, dt), 1)` (0.0 if `latest["eggs_hatched"] <= oldest["eggs_hatched"]`).
- In `src/session_manager.py`: accept optional `pet_catalog`; track `_last_authoritative_secret_sync`, `_prev_secret_counts`, `_active_boosts`, `_world`, `_eggs_hatched`; implement Builder Calls #1, #2, #6, #8 cleanly; enrich every pet with `pet_catalog.resolve_image_url(...)` when returning `get_live_state` / `get_secrets_summary`; implement `get_overview`, `get_secrets_summary`, `has_recent_authoritative_secret_sync`; emit timeout events strictly when `prev_state != new_state`. Clean up all new dicts in `remove_account`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_rate_engine.py tests/test_session_manager.py tests/test_fixes.py tests/test_session_manager_v2.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/rate_engine.py src/session_manager.py tests/test_session_manager_v2.py
git commit -m "feat(engine): add egg rate, AFK-safe Secret sync, overview summary, and transition-only timeouts"
```

---

### Task 6: Bidirectional Discord Webhook Service

**Files:**
- Create: `src/webhook_service.py`
- Test: `tests/test_webhook_service.py`

**Interfaces:**
- Consumes: Task 1 (`AlertSettings`, `AlertSettingsUpdate`, `normalize_variant`, `slugify_pet_name`), Task 2 (`Database`), Task 3 (`PetCatalogService`), Task 4 (`RobloxPoller`), Task 5 (`SessionManager`).
- Produces (`src/webhook_service.py`):
  - `ALERT_SETTINGS_KEY = "discord_alerts"`
  - `mask_webhook_url(url: str) -> str`
  - `WebhookService(db, session_manager, pet_catalog, poller=None)`:
    - `get_raw_settings() -> AlertSettings`
    - `get_public_settings() -> Dict[str, Any]` (`webhookUrl` masked, `hasWebhookUrl: bool`, `enabled`, `notifySecretHatch`, `notifyDisconnect`, `notifyStale`, `forwardInboundWebhook`)
    - `update_settings(update: AlertSettingsUpdate) -> Dict[str, Any]` (preserves stored URL if masked sentinel `"****"` in URL or empty without `clearWebhook=True`; validates new URLs start with `https://discord.com/api/webhooks/` or `https://discordapp.com/api/webhooks/` or `http(s)://` for test targets)
    - `async send_secret_hatch_alert(hatch_event: Dict[str, Any], base_url: str = "") -> bool`
    - `async send_status_alert(user_id: int, username: str, event: str) -> bool` (respects `notifyDisconnect` for `"DISCONNECTED"` and `notifyStale` for `"STALE"`)
    - `async send_test_alert() -> Dict[str, Any]`
    - `parse_discord_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]` (extracts `user_id`, `username`, `pet_name`, `variant`, `rarity`, `tier`, `egg_name`, `odds` from standard Discord `content` / `embeds[].{title,description,fields}`)
    - `async ingest_discord_webhook(payload: Dict[str, Any]) -> Dict[str, Any]` (resolves `username` via `poller.get_user_by_username` when present, persists with nullable `user_id` + `actor_name`, applies 15s dedup, increments `account_secrets` ONLY when `rarity.lower() == "secret"`, `user_id is not None`, and `not session_manager.has_recent_authoritative_secret_sync(user_id, 60.0)`, optionally forwards raw payload if `forwardInboundWebhook` is enabled)

- [ ] **Step 1: Write failing tests in `tests/test_webhook_service.py`**

```python
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from src.database import Database
from src.rate_engine import RateEngine
from src.pet_catalog import PetCatalogService
from src.session_manager import SessionManager
from src.webhook_service import WebhookService, mask_webhook_url
from src.models import AlertSettingsUpdate, TelemetryPayload, PetItem

def _make_services(tmp_path):
    db = Database(str(tmp_path / "wh.db"))
    db.init_db()
    cat = PetCatalogService(db)
    cat.seed_defaults()
    mgr = SessionManager(db, RateEngine(), poller=None, pet_catalog=cat)
    poller = MagicMock()
    poller.get_user_by_username = AsyncMock(return_value={"id": 44444, "name": "FarmHero", "displayName": "Hero"})
    poller.get_user_avatar = AsyncMock(return_value="https://tr.rbxcdn.com/hero.png")
    wh = WebhookService(db, mgr, cat, poller=poller)
    return db, mgr, wh

def test_webhook_url_masking_preserved_on_update(tmp_path):
    _, _, wh = _make_services(tmp_path)
    secret_url = "https://discord.com/api/webhooks/123456789/supersecrettokenvalue"
    pub = wh.update_settings(AlertSettingsUpdate(webhookUrl=secret_url, enabled=True, notifySecretHatch=True))
    assert "supersecrettokenvalue" not in pub["webhookUrl"]
    assert pub["hasWebhookUrl"] is True
    assert pub["webhookUrl"].endswith("****")

    # Updating toggle with masked URL returned by GET must NOT overwrite secret_url
    wh.update_settings(AlertSettingsUpdate(webhookUrl=pub["webhookUrl"], enabled=True, notifyStale=True))
    assert wh.get_raw_settings().webhookUrl == secret_url
    assert wh.get_raw_settings().notifyStale is True

    # Explicit clear removes it
    pub2 = wh.update_settings(AlertSettingsUpdate(clearWebhook=True))
    assert pub2["hasWebhookUrl"] is False
    assert wh.get_raw_settings().webhookUrl == ""

@pytest.mark.anyio
async def test_inbound_webhook_parses_resolves_and_avoids_double_count(tmp_path):
    db, mgr, wh = _make_services(tmp_path)
    embed_payload = {
        "embeds": [{
            "title": "Secret Hatched!",
            "description": "Player: FarmHero hatched Rainbow Dark Cat from Void Egg (1 in 4M)",
        }]
    }
    res = await wh.ingest_discord_webhook(embed_payload)
    assert res["status"] == "recorded"
    assert res["event"]["user_id"] == 44444
    assert res["event"]["pet_name"] == "Dark Cat"
    assert res["event"]["variant"] == "Rainbow"
    # No recent Luau sync -> secret vault incremented to 1
    assert db.get_account(44444)["secret_count"] == 1

    # Duplicate within 15s ignored
    dup = await wh.ingest_discord_webhook(embed_payload)
    assert dup["status"] == "duplicate"
    assert db.get_account(44444)["secret_count"] == 1

    # If account HAS recent authoritative Luau sync, a new webhook Secret hatch does NOT inflate account_secrets
    import time
    mgr.process_telemetry(TelemetryPayload(
        userId=44444, currentTaps=100, totalTaps=100,
        secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="Rainbow", count=1)],
        timestamp=time.time(),
    ))
    res2 = await wh.ingest_discord_webhook({
        "embeds": [{"title": "Secret Hatched!", "description": "Player: FarmHero hatched Golden Chronos (1 in 2M)"}]
    })
    assert res2["status"] == "recorded"
    assert db.get_account(44444)["secret_count"] == 1  # untouched because Luau sync is authoritative
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_webhook_service.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/webhook_service.py`**

Implement `mask_webhook_url`, settings persistence in `settings_kv`, async `httpx` outbound Discord embeds (Secret hatch with tier/variant color & pet thumbnail, disconnect/stale alert), standard regex/field parser in `parse_discord_payload`, and `ingest_discord_webhook`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_webhook_service.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/webhook_service.py tests/test_webhook_service.py
git commit -m "feat(webhooks): add bidirectional Discord webhook service with URL masking and dedup"
```

---

### Task 7: FastAPI v2 Endpoints, Background Enrichment, SSE Envelope & Script Endpoint

**Files:**
- Modify: `src/main.py:1-204`
- Test: `tests/test_api_v2.py`

**Interfaces:**
- Consumes: Tasks 1–6 (`PetCatalogService`, `WebhookService`, updated `SessionManager`, `RobloxPoller`, `Database`).
- Produces (FastAPI routes on `app` in `src/main.py`):
  - Singletons exported: `db`, `pet_catalog`, `rate_engine`, `poller`, `session_manager`, `webhook_service`.
  - Updated `POST /api/v1/telemetry`: schedules non-blocking background tasks for Roblox profile enrichment (`needs_profile_lookup`), Roblox asset thumbnail resolution (`pending_asset_ids`), and outbound Secret Hatch Discord alerts (`new_hatches`).
  - Updated `timeout_monitor_loop()`: dispatches transition events from `session_manager.check_timeouts()` to `webhook_service.send_status_alert(...)`.
  - Updated `GET /api/v1/accounts`: adds `secret_count`, `eggs_hatched`, `eggs_per_hour`, `world`, `client_source`, `top_secrets` (top 3 secret thumbnails/names).
  - Updated `GET /api/v1/stream`: emits JSON envelope `{"overview": ..., "accounts": [...], "recent_hatches": [...]}`.
  - New routes:
    - `GET /api/v1/overview`
    - `GET /api/v1/secrets` (query params: `user_id`, `variant`, `tier`, `q`)
    - `GET /api/v1/pets/catalog`
    - `POST /api/v1/pets/catalog/{slug}/image`
    - `GET /api/v1/pets/icon/{slug}.svg` (`media_type="image/svg+xml"`)
    - `GET /api/v1/hatches` (query params: `limit=50`, `rarity`, `user_id`)
    - `GET /api/v1/settings/alerts`, `POST /api/v1/settings/alerts`, `POST /api/v1/settings/alerts/test`
    - `POST /api/v1/webhook/discord`
    - `GET /api/v1/connector/script.lua` (query param optional `endpoint` validated as `http://` or `https://`)
    - `POST /api/v1/connector/inspect` & `GET /api/v1/connector/inspect`

- [ ] **Step 1: Write failing tests in `tests/test_api_v2.py`**

```python
from fastapi.testclient import TestClient
from src.main import app, session_manager, db

client = TestClient(app)

def test_overview_secrets_catalog_and_custom_image():
    uid = 70001
    session_manager.toggle_tracking(uid, True)
    payload = {
        "userId": uid,
        "currentTaps": 5000,
        "totalTaps": 50000,
        "currentRebirths": 10,
        "eggsHatched": 1200,
        "world": "Void Island",
        "secretPets": [
            {"name": "Dark Cat", "rarity": "Secret", "variant": "Rainbow", "tier": "Secret III", "count": 2, "multiplier": 25000, "power": 120000},
            {"name": "Void Wraith", "rarity": "Secret", "variant": "Normal", "tier": "Secret I", "count": 1, "multiplier": 4000, "power": 18000},
        ],
        "recentHatches": [
            {"petName": "Dark Cat", "rarity": "Secret", "variant": "Rainbow", "eggName": "Void Egg", "odds": "1 in 4M", "timestamp": 1700000500.0}
        ],
        "timestamp": 1700000500.0,
    }
    resp = client.post("/api/v1/telemetry", json=payload)
    assert resp.status_code == 200

    ov = client.get("/api/v1/overview").json()
    assert ov["total_secrets"] >= 3

    sec = client.get(f"/api/v1/secrets?user_id={uid}&variant=Rainbow").json()
    assert sec["total_secrets"] == 2
    assert sec["grouped"][0]["name"] == "Dark Cat"
    assert sec["grouped"][0]["image_url"].endswith(".svg") or sec["grouped"][0]["image_url"].startswith("http")

    # Override custom image
    ov_img = client.post("/api/v1/pets/catalog/dark-cat/image", json={"imageUrl": "https://cdn.example/dark-cat.png"})
    assert ov_img.status_code == 200
    assert ov_img.json()["image_url"] == "https://cdn.example/dark-cat.png"

    # Dynamic fallback SVG endpoint
    svg_resp = client.get("/api/v1/pets/icon/brand-new-secret.svg")
    assert svg_resp.status_code == 200
    assert "image/svg+xml" in svg_resp.headers["content-type"]
    assert "<svg" in svg_resp.text

def test_hatches_alerts_and_inspector_endpoints():
    r_alerts = client.get("/api/v1/settings/alerts")
    assert r_alerts.status_code == 200
    assert "hasWebhookUrl" in r_alerts.json()

    r_ins = client.post("/api/v1/connector/inspect", json={
        "userId": 70001, "username": "Tester", "placeId": 72858262610964,
        "structure": {"leaderstats": ["Taps", "Rebirths"], "petGuis": ["PlayerGui.Pets.Grid"]}
    })
    assert r_ins.status_code == 200
    reports = client.get("/api/v1/connector/inspect").json()
    assert len(reports) >= 1
    assert "leaderstats" in reports[0]["structure"]

    hatches = client.get("/api/v1/hatches?rarity=Secret").json()
    assert isinstance(hatches, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_api_v2.py -v`
Expected: FAIL with 404 on new routes.

- [ ] **Step 3: Implement v2 routes and wiring in `src/main.py`**

Wire `pet_catalog` (`seed_defaults()` on init/lifespan) and `webhook_service` into `src/main.py`, add all v2 routes, schedule background enrichment tasks safely (guarded for sync `TestClient` contexts), serve `scripts/tap_sim_reborn_tracker.lua` via `/api/v1/connector/script.lua` (with validated optional `?endpoint=` replacement and clear 404/fallback if file missing), and update `/api/v1/stream` to yield `{ "overview", "accounts", "recent_hatches" }`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_api_endpoints.py tests/test_e2e_pipeline.py tests/test_api_v2.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/main.py tests/test_api_v2.py
git commit -m "feat(api): expose v2 overview, Secret vault, catalog images, webhooks, and connector routes"
```

---

### Task 8: Redesigned 6-Tab Cyber-Glass Website UI

**Files:**
- Modify: `src/static/index.html`
- Modify: `src/static/css/style.css`
- Modify: `src/static/js/app.js`
- Modify/Test: `tests/test_static_ui.py`, Create `tests/test_ui_v2.py`

**Interfaces:**
- Consumes: Task 7 REST endpoints (`/api/v1/overview`, `/api/v1/accounts`, `/api/v1/secrets`, `/api/v1/pets/catalog/{slug}/image`, `/api/v1/hatches`, `/api/v1/settings/alerts`, `/api/v1/connector/script.lua`, `/api/v1/connector/inspect`, `/api/v1/stream`).
- Produces: Complete responsive 6-tab Dark Cyber-Glass SPA (`Overview`, `Secret Vault`, `Hatch Feed`, `Multi-Account`, `History`, `Connector`) featuring:
  - Persistent 5-card **Farm Overview KPI Strip** (`Accounts Online`, `Total Secrets` + variant breakdown, `Farm TPS`, `Farm Taps & Currency`, `Total Eggs & Eggs/hr`).
  - **Overview Tab**: Active Player Card (Avatar, World/Island badge, Session Playtime, Active Boosts countdown pills), **Live Statistics** (TPS, Current/Total Taps, Rebirths, Wins, Currency, Secrets Owned, Eggs Hatched), 1m/5m/15m Growth Rates, Chart.js Live TPS Chart, **Active Account Secret Showcase** (with images), **Equipped Pets** grid, and Mini Hatch Feed.
  - **Secret Vault Tab**: Variant & Tier summary pills, Search + Account/Variant/Tier/Sort filters, **Secret Pet Image Gallery Cards** (88×88 framed image, animated prismatic border for Rainbow, metallic gold glow for Golden, crystalline cyan for Diamond, sparkle badge for Shiny, tier pill, total quantity `×N`, multiplier/power, egg source, clickable owner chips), and **Secret Detail & Custom Image Modal** (`POST /api/v1/pets/catalog/{slug}/image`).
  - **Live Hatch Feed & Alerts Tab**: Filterable real-time hatch timeline with pet images, WebAudio Secret Hatch chime toggle + Test Sound button, Discord Webhook Alert Settings form (masked URL handling, Secret Hatch / Disconnect / Stale / Forward toggles, Save & Test), and Inbound Webhook URL copy box.
  - **Multi-Account Matrix Tab**: Search & status filter, `Track All` / `Pause All`, per-account Secret count + top mini Secret pet icons, World, Eggs, Taps, TPS, Playtime, View/Pause/Delete actions.
  - **History & Export Tab**: Session History table, Export CSV/JSON, and JSON Restore file upload (`POST /api/v1/restore`).
  - **Game Connector Tab**: Copy/Download `tap_sim_reborn_tracker.lua` button, Endpoint & Feeder quick guide, and Live Inspector Dump Viewer (`GET /api/v1/connector/inspect` with refresh button).
  - Security: `escapeHtml(str)` applied to every dynamic text value interpolated into `innerHTML`, and `safeImgUrl(url)` validating image URLs client-side as defense-in-depth.

- [ ] **Step 1: Write failing tests in `tests/test_ui_v2.py`**

```python
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_v2_dashboard_contains_all_views_and_secret_vault_controls():
    html = client.get("/").text
    for token in [
        "Tap Simulator Reborn", "TrackStats", "Live Statistics", "Equipped Pets", "Multi-Account",
        "Secret Vault", "Hatch Feed", "Connector", "farmTotalSecrets", "secretVaultGrid",
        "secretDetailModal", "discordWebhookForm", "inspectorDumpViewer", "btnDownloadScript"
    ]:
        assert token in html, f"Missing UI element/token: {token}"

def test_v2_js_and_css_served_with_xss_helpers_and_variant_styles():
    js = client.get("/static/js/app.js").text
    css = client.get("/static/css/style.css").text
    assert "function escapeHtml" in js
    assert "function safeImageUrl" in js
    assert "/api/v1/secrets" in js
    assert "/api/v1/settings/alerts" in js
    assert ".variant-rainbow" in css
    assert ".variant-golden" in css
    assert ".variant-diamond" in css
    assert ".variant-shiny" in css
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ui_v2.py -v`
Expected: FAIL on missing v2 UI IDs, JS helpers, and variant CSS classes.

- [ ] **Step 3: Implement redesigned `src/static/index.html`, `src/static/css/style.css`, and `src/static/js/app.js`**

Craft the polished dark cyber-glassmorphism UI across `index.html`, `style.css`, and `app.js` with responsive grid layouts, subtle glow/prismatic animations for Secret variants, full `escapeHtml()`/`safeImageUrl()` sanitization, live SSE updates (accepting both `{overview, accounts, recent_hatches}` envelope and legacy array), WebAudio hatch chime, Secret Detail & Image Override modal, Discord Settings form, JSON Restore upload, and Connector Inspector viewer.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_static_ui.py tests/test_ui_v2.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/static/index.html src/static/css/style.css src/static/js/app.js tests/test_ui_v2.py
git commit -m "feat(ui): redesign 6-tab dark cyber-glass TrackStats dashboard with Secret Vault gallery"
```

---

### Task 9: Read-Only Luau In-Game Telemetry Script, Upgraded Multi-Account Feeder, Docs & E2E Tests

**Files:**
- Create: `scripts/tap_sim_reborn_tracker.lua`
- Modify: `tools/telemetry_feeder.py`
- Modify: `README.md`
- Test: `tests/test_v2_e2e.py`

**Interfaces:**
- Consumes: Task 7 REST endpoints (`POST /api/v1/telemetry`, `POST /api/v1/connector/inspect`, `GET /api/v1/connector/script.lua`).
- Produces:
  - `scripts/tap_sim_reborn_tracker.lua`: Read-only Luau client script featuring `CONFIG` (`ENDPOINT_URL`, `INSPECT_URL`, `SEND_INTERVAL`, `INSPECT_ON_START`, `DEBUG_LOG`, `PATHS`), multi-executor HTTP abstraction (`request`, `http_request`, `syn.request`, `fluxus.request`, `http.request`, Studio `HttpService:RequestAsync`), `_G.__TapSimTrackStats_Token` singleton guard, `parseCompactNumber(str)` (handles `K/M/B/T/Qa/Qi/Sx`), `leaderstats` + attributes + HUD reader, **AFK closed-UI guard** (omits `secretPets` when Pet UI is closed/unmounted; only sends `secretPets` array when open/confirmed readable), `PlayerGui` hatch popup & read-only chat listener populating `recentHatches`, `rbxassetid://` extraction, and `INSPECT_ON_START` dump to `/api/v1/connector/inspect`. Zero auto-farm/auto-click/cookie code.
  - Upgraded `tools/telemetry_feeder.py`: preserves `generate_payload(user_id, state, delta_taps, delta_time, is_rebirth=False)` signature for existing `tests/test_feeder.py`, adds optional Secret pets (`secretPets`, `secretCount`), `eggsHatched`, `world`, `activeBoosts`, `recentHatches`, and `--multi N` / `--accounts id1,id2` CLI flags.

- [ ] **Step 1: Write failing tests in `tests/test_v2_e2e.py`**

```python
from pathlib import Path
from fastapi.testclient import TestClient
from src.main import app, session_manager, db
from tools.telemetry_feeder import generate_payload, SAMPLE_SECRETS

client = TestClient(app)

def test_luau_script_served_and_respects_safety_and_afk_guard():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts/tap_sim_reborn_tracker.lua"
    assert script_path.exists()
    lua = script_path.read_text(encoding="utf-8")
    assert "_G.__TapSimTrackStats_Token" in lua
    assert "INSPECT_ON_START" in lua
    assert "parseCompactNumber" in lua
    assert "secretPets" in lua
    assert "recentHatches" in lua
    assert "ROBLOSECURITY" not in lua.upper()
    assert "FireServer" not in lua

    resp = client.get("/api/v1/connector/script.lua?endpoint=http://127.0.0.1:9999/api/v1/telemetry")
    assert resp.status_code == 200
    assert "http://127.0.0.1:9999/api/v1/telemetry" in resp.text

def test_v2_feeder_and_full_farm_secret_e2e():
    uid_a, uid_b = 91001, 91002
    for u in (uid_a, uid_b):
        db.delete_account(u)
        session_manager.remove_account(u)
        session_manager.toggle_tracking(u, True)

    state_a = {"current_taps": 1000, "total_taps": 10000, "rebirths": 5, "wins": 10, "currency": 50000, "eggs_hatched": 1000, "world": "Void Island", "secrets": [SAMPLE_SECRETS[0], SAMPLE_SECRETS[1]]}
    state_b = {"current_taps": 2000, "total_taps": 20000, "rebirths": 8, "wins": 20, "currency": 80000, "eggs_hatched": 2500, "world": "Draconic Island", "secrets": [SAMPLE_SECRETS[0]]}

    pa = generate_payload(uid_a, state_a, delta_taps=40, delta_time=1.0, simulate_secret_hatch=True)
    pb = generate_payload(uid_b, state_b, delta_taps=60, delta_time=1.0)
    assert client.post("/api/v1/telemetry", json=pa).status_code == 200
    assert client.post("/api/v1/telemetry", json=pb).status_code == 200

    secrets = client.get("/api/v1/secrets").json()
    assert secrets["total_secrets"] >= 3
    hatches = client.get(f"/api/v1/hatches?user_id={uid_a}").json()
    assert len(hatches) >= 1
    assert hatches[0]["image_url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_v2_e2e.py -v`
Expected: FAIL (`script_path` missing, `SAMPLE_SECRETS` not defined).

- [ ] **Step 3: Implement `scripts/tap_sim_reborn_tracker.lua`, upgrade `tools/telemetry_feeder.py`, and update `README.md`**

- Author `scripts/tap_sim_reborn_tracker.lua` cleanly with all safety invariants, closed-inventory guard (sending `secretPets` ONLY when inventory container is visible/readable), hatch popup/chat listener, compact number parser, and Inspector dump.
- Upgrade `tools/telemetry_feeder.py` with `SAMPLE_SECRETS` (referencing the 18 seeded Tap Simulator Reborn Secrets with Rainbow/Golden/Diamond/Shiny/Normal variants), `eggs_hatched`, `world`, `activeBoosts`, `simulate_secret_hatch`, and `--accounts` / `--multi` CLI options while remaining 100% compatible with `tests/test_feeder.py`.
- Update `README.md` with v2 Secret Vault, per-Secret images, Discord webhook guide, and Luau connector usage.

- [ ] **Step 4: Run full test suite to verify everything passes (all v1 + v2 tests)**

Run: `pytest tests/ -v`
Expected: All existing 28 tests + all new v2 tests PASS with zero failures.

- [ ] **Step 5: Commit**

```bash
git add scripts/tap_sim_reborn_tracker.lua tools/telemetry_feeder.py README.md tests/test_v2_e2e.py
git commit -m "feat(connector): add read-only Luau tracker script, v2 multi-account feeder, and e2e tests"
```
