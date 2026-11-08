import pytest
from fastapi.testclient import TestClient
from src.main import app, session_manager, db

client = TestClient(app)

def test_telemetry_post_and_live_stats():
    payload = {
        "userId": 55555,
        "currentTaps": 1000,
        "totalTaps": 20000,
        "currentRebirths": 3,
        "totalRebirths": 3,
        "currentWins": 12,
        "totalWins": 12,
        "currentCurrency": 450000,
        "equippedPets": [
            {"name": "Phoenix", "rarity": "Mythic", "multiplier": 500.0, "power": 10000.0}
        ],
        "petInventoryCount": 15,
        "totalPetPower": 25000.0,
        "timestamp": 1700000000.0
    }
    resp = client.post("/api/v1/telemetry", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "processed"
    assert data["user_id"] == 55555

    # Check live stats
    live_resp = client.get("/api/v1/accounts/55555/live")
    assert live_resp.status_code == 200
    live_data = live_resp.json()
    assert live_data["current_taps"] == 1000
    assert live_data["current_currency"] == 450000
    assert len(live_data["equipped_pets"]) == 1

def test_accounts_api_and_tracking_toggle():
    # List accounts
    acc_resp = client.get("/api/v1/accounts")
    assert acc_resp.status_code == 200
    accounts = acc_resp.json()
    assert any(a["user_id"] == 55555 for a in accounts)

    # Toggle tracking to false
    tog_resp = client.post("/api/v1/accounts/55555/tracking", json={"is_tracking": False})
    assert tog_resp.status_code == 200
    assert tog_resp.json()["is_tracking"] is False

    # Check live state reflects paused
    live_resp = client.get("/api/v1/accounts/55555/live")
    assert live_resp.json()["connection_status"] == "PAUSED"

def test_export_endpoints():
    csv_resp = client.get("/api/v1/export/csv")
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]

    json_resp = client.get("/api/v1/export/json")
    assert json_resp.status_code == 200
    assert "application/json" in json_resp.headers["content-type"]
    assert "accounts" in json_resp.json()
