import pytest
import time
from fastapi.testclient import TestClient
from src.main import app, session_manager, db
from tools.telemetry_feeder import generate_payload, SAMPLE_PETS

client = TestClient(app)

def test_e2e_multi_account_pipeline():
    user_a = 90001
    user_b = 90002

    # 1. Register accounts
    session_manager.toggle_tracking(user_a, True)
    session_manager.toggle_tracking(user_b, True)

    state_a = {
        "current_taps": 1000,
        "total_taps": 10000,
        "rebirths": 1,
        "wins": 5,
        "currency": 50000,
        "pets": [SAMPLE_PETS[0]]
    }
    state_b = {
        "current_taps": 500,
        "total_taps": 5000,
        "rebirths": 0,
        "wins": 1,
        "currency": 10000,
        "pets": [SAMPLE_PETS[1], SAMPLE_PETS[2]]
    }

    # 2. Feed telemetry for both accounts
    for i in range(5):
        t = 1700000000.0 + i
        pa = generate_payload(user_a, state_a, delta_taps=30, delta_time=1.0)
        pa["timestamp"] = t
        resp_a = client.post("/api/v1/telemetry", json=pa)
        assert resp_a.status_code == 200

        pb = generate_payload(user_b, state_b, delta_taps=15, delta_time=1.0)
        pb["timestamp"] = t
        resp_b = client.post("/api/v1/telemetry", json=pb)
        assert resp_b.status_code == 200

    # 3. Check Live Stats for Account A
    live_a = client.get(f"/api/v1/accounts/{user_a}/live").json()
    assert live_a["connection_status"] == "LIVE"
    assert live_a["current_taps"] == 1150
    assert live_a["total_taps"] == 10150
    assert live_a["tps"] == 30.0

    # 4. Check Live Stats for Account B
    live_b = client.get(f"/api/v1/accounts/{user_b}/live").json()
    assert live_b["connection_status"] == "LIVE"
    assert live_b["current_taps"] == 575
    assert live_b["total_taps"] == 5075
    assert live_b["tps"] == 15.0

    # 5. Check SQLite Snapshots Isolation
    snaps_a = db.get_recent_snapshots(user_a, limit=10)
    snaps_b = db.get_recent_snapshots(user_b, limit=10)
    assert len(snaps_a) == 5
    assert len(snaps_b) == 5
    assert all(s["user_id"] == user_a for s in snaps_a)
    assert all(s["user_id"] == user_b for s in snaps_b)

    # 6. Verify Export Contains Both Accounts
    export_resp = client.get("/api/v1/export/json").json()
    account_ids = [a["user_id"] for a in export_resp["accounts"]]
    assert user_a in account_ids
    assert user_b in account_ids
