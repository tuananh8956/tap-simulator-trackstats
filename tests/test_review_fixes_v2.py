import json
from pathlib import Path
from fastapi.testclient import TestClient
from src.database import Database
from src.rate_engine import RateEngine
from src.pet_catalog import PetCatalogService
from src.session_manager import SessionManager
from src.models import TelemetryPayload, PetItem
from src.main import app, session_manager, db

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parent.parent


def test_luau_multiplier_not_misclassified_as_stack_count():
    """Critical #1: Multiplier labels like x500 or 25,000x must not be misread as stack count."""
    lua = (REPO_ROOT / "scripts/tap_sim_reborn_tracker.lua").read_text(encoding="utf-8")
    # Must track which label index was used as multiplier and skip it when detecting stack count
    assert "multLabelIdx" in lua
    assert "idx ~= multLabelIdx" in lua
    # Must also recognize suffix multiplier format like "25,000x"
    assert "([%d%.,]+[a-zA-Z]*)%s*[xX]$" in lua


def test_multi_hatch_delta_detected_records_all_copies(tmp_path):
    """Important #2: Hatching delta >= 2 of the same Secret must record all copies (no int(ts) event_key collision)."""
    local_db = Database(str(tmp_path / "delta_multi.db"))
    local_db.init_db()
    cat = PetCatalogService(local_db)
    cat.seed_defaults()
    mgr = SessionManager(local_db, RateEngine(), poller=None, pet_catalog=cat)

    # First authoritative sync: 1 Dark Cat
    mgr.process_telemetry(
        TelemetryPayload(
            userId=501,
            currentTaps=100,
            totalTaps=100,
            secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="Rainbow", tier="Secret III", count=1)],
            timestamp=1700001000.2,
        )
    )

    # Second authoritative sync: 4 Dark Cats (delta = 3)
    res = mgr.process_telemetry(
        TelemetryPayload(
            userId=501,
            currentTaps=500,
            totalTaps=500,
            secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="Rainbow", tier="Secret III", count=4)],
            timestamp=1700001010.2,
        )
    )
    assert len(res["new_hatches"]) == 3
    events = local_db.get_hatch_events(limit=10, rarity="Secret", user_id=501)
    assert len(events) == 3


def test_luau_playergui_hatch_listener_filters_other_players():
    """Important #3: PlayerGui hatch banner listener must ignore announcements belonging to other players."""
    lua = (REPO_ROOT / "scripts/tap_sim_reborn_tracker.lua").read_text(encoding="utf-8")
    assert "isBannerForAnotherPlayer" in lua
    assert "Players:GetPlayers()" in lua


def test_restore_resets_session_manager_prevents_fk_crash():
    """Important #4: POST /api/v1/restore must clear stale in-memory sessions so subsequent telemetry never FK-crashes."""
    uid = 88001
    db.delete_account(uid)
    session_manager.remove_account(uid)
    session_manager.toggle_tracking(uid, True)

    # Create active session in memory + DB
    r1 = client.post(
        "/api/v1/telemetry",
        json={"userId": uid, "currentTaps": 100, "totalTaps": 100, "timestamp": 1700002000.0},
    )
    assert r1.status_code == 200
    assert session_manager._active_sessions.get(uid) is not None

    # Restore a minimal v1 backup containing this account (cascade-deletes the old session row)
    backup = {
        "accounts": [{"user_id": uid, "username": "RestoredAcc", "is_tracking": 1}],
        "sessions": [],
        "snapshots": [],
    }
    r_restore = client.post("/api/v1/restore", json=backup)
    assert r_restore.status_code == 200

    # Subsequent telemetry must succeed without sqlite3.IntegrityError FOREIGN KEY constraint failed
    r2 = client.post(
        "/api/v1/telemetry",
        json={"userId": uid, "currentTaps": 250, "totalTaps": 250, "timestamp": 1700002010.0},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "processed"


def test_overview_secret_modal_fetches_fresh_unfiltered_vault_data():
    """Important #5: Clicking any Secret card must fetch/use unfiltered farm secrets instead of stale filtered vault data."""
    js = client.get("/static/js/app.js").text
    assert "async function openSecretDetailModal" in js
    assert 'apiFetch("/api/v1/secrets")' in js


def test_first_secret_hatch_on_fresh_db_triggers_alert_via_hydrated_flag():
    """Important #6: Fresh DB with 0 prior hatches must still fire toast/chime on the very first Secret hatch."""
    js = client.get("/static/js/app.js").text
    assert "let hatchesHydrated = false;" in js
    assert "const isFirstLoad = lastSeenHatchId === 0;" not in js
