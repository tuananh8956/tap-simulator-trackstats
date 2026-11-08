import pytest
import json
import csv
import io
from src.database import Database
from src.models import TelemetryPayload

@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_trackstats.db"
    db = Database(str(db_file))
    db.init_db()
    return db

def test_account_crud_and_tracking(test_db):
    test_db.upsert_account(101, "PlayerOne", "P1", "https://avatar/101.png")
    accounts = test_db.get_accounts()
    assert len(accounts) == 1
    assert accounts[0]["user_id"] == 101
    assert accounts[0]["username"] == "PlayerOne"
    assert accounts[0]["is_tracking"] == 1
    
    # Toggle tracking
    test_db.set_account_tracking(101, False)
    acc = test_db.get_account(101)
    assert acc["is_tracking"] == 0

    # Delete account
    res = test_db.delete_account(101)
    assert res is True
    assert len(test_db.get_accounts()) == 0

def test_session_lifecycle_and_snapshots(test_db):
    test_db.upsert_account(202, "PlayerTwo", "P2", "")
    session_id = test_db.start_session(202, 1700000000.0, 1000, 1)
    assert session_id is not None
    
    active = test_db.get_active_session(202)
    assert active is not None
    assert active["session_id"] == session_id

    # Insert snapshots
    payload = TelemetryPayload(
        userId=202, currentTaps=1050, totalTaps=5000, currentRebirths=1,
        totalRebirths=1, currentWins=5, totalWins=5, currentCurrency=2000,
        equippedPets=[{"name": "Dog", "rarity": "Common", "multiplier": 1.5, "power": 10.0}],
        petInventoryCount=1, totalPetPower=10.0, timestamp=1700000010.0
    )
    test_db.insert_snapshot(session_id, payload, tps=5.0)

    snapshots = test_db.get_recent_snapshots(202, limit=10)
    assert len(snapshots) == 1
    assert snapshots[0]["tps"] == 5.0
    assert snapshots[0]["current_taps"] == 1050

    # End session
    test_db.end_session(session_id, 1700000100.0, 2000, 2, max_tps=15.0, avg_tps=10.0)
    assert test_db.get_active_session(202) is None
    
    sessions = test_db.get_sessions(202)
    assert len(sessions) == 1
    assert sessions[0]["taps_gained"] == 1000
    assert sessions[0]["rebirths_gained"] == 1

def test_export_and_restore(test_db):
    test_db.upsert_account(303, "PlayerThree", "P3", "")
    s_id = test_db.start_session(303, 1700000000.0, 50, 0)
    p = TelemetryPayload(userId=303, currentTaps=60, totalTaps=60, timestamp=1700000005.0)
    test_db.insert_snapshot(s_id, p, tps=2.0)
    test_db.end_session(s_id, 1700000010.0, 60, 0, 2.0, 1.0)

    # Export JSON
    json_export = test_db.export_data("json")
    data = json.loads(json_export)
    assert "accounts" in data
    assert "sessions" in data
    assert "snapshots" in data
    assert len(data["accounts"]) == 1

    # Export CSV
    csv_export = test_db.export_data("csv")
    assert "user_id" in csv_export
    assert "PlayerThree" in csv_export

    # Restore in clean DB
    import tempfile
    clean_db = Database(tempfile.mktemp(suffix=".db"))
    clean_db.init_db()
    assert len(clean_db.get_accounts()) == 0
    restore_success = clean_db.restore_data(json_export)
    assert restore_success is True
    assert len(clean_db.get_accounts()) == 1
    assert clean_db.get_accounts()[0]["user_id"] == 303
