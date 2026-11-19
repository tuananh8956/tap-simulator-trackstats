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
    assert p.tradeMessage == "Offering 6 secrets"
    assert p.secretInstanceIds == ["uuid-1", "uuid-2"]


def test_database_auto_trade_settings_roundtrip(tmp_path):
    db = Database(str(tmp_path / "trade.db"))
    db.init_db()
    defaults = db.get_auto_trade_settings()
    assert defaults["enabled"] is False
    assert defaults["mainUserId"] is None
    assert defaults["mainUsername"] == ""
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


from fastapi.testclient import TestClient
from src.main import app, session_manager, db
from src.config import settings


def test_coordinator_assigns_one_clone_at_a_time_and_advances_on_completion(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "ingest_key", "")
    session_manager.reset_after_restore()
    for acc in db.get_accounts():
        db.delete_account(acc["user_id"])

    client = TestClient(app)
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
    assert r_b["trade_directive"]["role"] == "CLONE_QUEUED"

    # Main Account comes online with jobId "job-main-server"
    r_main = client.post(
        "/api/v1/telemetry",
        json={"userId": 1000, "placeId": 72858262610964, "jobId": "job-main-server"},
    ).json()
    assert r_main["trade_directive"]["role"] == "MAIN"
    assert r_main["trade_directive"]["action"] == "AUTO_ACCEPT"
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


def test_lease_timeout_and_manual_priority_queue_and_skip(monkeypatch):
    import time

    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "ingest_key", "")
    session_manager.reset_after_restore()
    for acc in db.get_accounts():
        db.delete_account(acc["user_id"])

    t0 = time.time()
    client = TestClient(app)
    db.upsert_account(1000, "MainAcc", "MainAcc", "")
    db.upsert_account(3001, "Clone1", "Clone1", "")
    db.upsert_account(3002, "Clone2", "Clone2", "")

    # Auto-trade global toggle is OFF, but user manually queues Clone1
    client.post("/api/v1/trade/settings", json={"enabled": False, "mainUserId": 1000, "leaseTimeoutSec": 30})
    client.post("/api/v1/telemetry", json={"userId": 1000, "placeId": 72858262610964, "jobId": "job-main-2", "timestamp": t0})
    client.post("/api/v1/telemetry", json={"userId": 3001, "placeId": 72858262610964, "jobId": "job-c1", "timestamp": t0, "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 2}]})
    client.post("/api/v1/telemetry", json={"userId": 3002, "placeId": 72858262610964, "jobId": "job-c2", "timestamp": t0, "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 5}]})

    res_q = client.post("/api/v1/trade/queue/3001")
    assert res_q.status_code == 200
    assert res_q.json()["active_clone_id"] == 3001

    # Also enable global queue and check skip endpoint
    client.post("/api/v1/trade/settings", json={"enabled": True})
    res_skip = client.post("/api/v1/trade/skip")
    assert res_skip.status_code == 200
    assert res_skip.json()["active_clone_id"] == 3002

    # Simulate lease timeout (> 30s) on Clone2 when Clone1 cooldown (20s) has expired (Review Focus #2)
    st_after_timeout = session_manager.get_trade_status(now=time.time() + 35.0)
    assert st_after_timeout["active_clone_id"] == 3001


def test_trade_write_endpoints_require_admin_when_password_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "secret-admin-pw")
    client = TestClient(app)
    res = client.post("/api/v1/trade/settings", json={"enabled": True})
    assert res.status_code == 401
    res_q = client.post("/api/v1/trade/queue-all")
    assert res_q.status_code == 401
    res_skip = client.post("/api/v1/trade/skip")
    assert res_skip.status_code == 401


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


def test_review_fixes_stale_teleport_retention_cooldown_respect_and_userid_override(monkeypatch):
    import time

    monkeypatch.setattr(settings, "admin_password", "")
    monkeypatch.setattr(settings, "ingest_key", "")
    session_manager.reset_after_restore()
    for acc in db.get_accounts():
        db.delete_account(acc["user_id"])

    t0 = time.time()
    client = TestClient(app)
    db.upsert_account(1000, "MainOne", "MainOne", "")
    db.upsert_account(1001, "MainTwo", "MainTwo", "")
    db.upsert_account(2001, "SoloClone", "SoloClone", "")

    # 1. Configure by mainUsername = MainOne, then override by mainUserId = 1001 without mainUsername (Finding #7)
    client.post("/api/v1/trade/settings", json={"enabled": True, "mainUsername": "MainOne"})
    res_override = client.post("/api/v1/trade/settings", json={"mainUserId": 1001})
    assert res_override.status_code == 200
    assert res_override.json()["main_user_id"] == 1001
    assert res_override.json()["main_username"] == "MainTwo"

    # 2. MainTwo and SoloClone come online
    client.post("/api/v1/telemetry", json={"userId": 1001, "placeId": 72858262610964, "jobId": "job-main-two", "timestamp": t0})
    r_clone = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2001,
            "placeId": 72858262610964,
            "jobId": "job-clone-1",
            "timestamp": t0,
            "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 4}],
        },
    ).json()
    assert r_clone["trade_directive"]["role"] == "CLONE_ACTIVE"

    # 3. During teleport (t0 + 20s), SoloClone becomes STALE (15s < 20s < 60s), while MainTwo heartbeats at t0 + 20s.
    # SoloClone MUST retain its active lease while STALE during teleport (Finding #4).
    client.post("/api/v1/telemetry", json={"userId": 1001, "placeId": 72858262610964, "jobId": "job-main-two", "timestamp": t0 + 20.0})
    session_manager.check_timeouts(now=t0 + 20.0)
    st_stale = session_manager.get_trade_status(now=t0 + 20.0)
    assert st_stale["active_clone_id"] == 2001

    # 4. If SoloClone is skipped when it is the ONLY clone, it must stay on cooldown and NOT be immediately re-leased (Finding #6).
    client.post("/api/v1/telemetry", json={"userId": 2001, "placeId": 72858262610964, "jobId": "job-main-two", "timestamp": t0 + 21.0, "secretPets": [{"name": "Anubis", "rarity": "Secret", "count": 4}]})
    res_skip = client.post("/api/v1/trade/skip").json()
    assert res_skip["active_clone_id"] is None

    # 5. Idle directive includes mainJobId & hopOutAfterTrade so completed clone can hop out of Main's server (Finding #1)
    r_done = client.post(
        "/api/v1/telemetry",
        json={
            "userId": 2001,
            "placeId": 72858262610964,
            "jobId": "job-main-two",
            "timestamp": t0 + 45.0,
            "tradeState": "COMPLETED",
            "secretPets": [],
        },
    ).json()
    assert r_done["trade_directive"]["mainJobId"] == "job-main-two"
    assert r_done["trade_directive"]["hopOutAfterTrade"] is True


def test_luau_script_includes_partner_verification_and_empty_owned_sync():
    lua_path = Path(__file__).resolve().parent.parent / "scripts" / "tap_sim_reborn_tracker.lua"
    src = lua_path.read_text(encoding="utf-8")
    assert "isTradePartnerVerified" in src
    assert "type(repData.Pets.Owned) == \"table\"" in src
