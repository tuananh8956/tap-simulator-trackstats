import pytest
import time
from src.session_manager import SessionManager
from src.database import Database
from src.rate_engine import RateEngine
from src.models import TelemetryPayload

@pytest.fixture
def manager(tmp_path):
    db = Database(str(tmp_path / "test_session.db"))
    db.init_db()
    db.upsert_account(101, "TestUser", "Test", "https://avatar/101.png")
    rate_engine = RateEngine()
    return SessionManager(db, rate_engine, poller=None)

def test_telemetry_processing_and_live_state(manager):
    p1 = TelemetryPayload(
        userId=101, currentTaps=100, totalTaps=1000, currentRebirths=1,
        totalRebirths=1, currentWins=0, totalWins=0, currentCurrency=50,
        equippedPets=[{"name": "Cat", "rarity": "Common", "multiplier": 1.2, "power": 5.0}],
        petInventoryCount=1, totalPetPower=5.0, timestamp=1000.0
    )
    res1 = manager.process_telemetry(p1)
    assert res1["status"] == "processed"
    
    state1 = manager.get_live_state(101)
    assert state1["connection_status"] == "LIVE"
    assert state1["active_session_id"] is not None
    assert state1["current_taps"] == 100
    assert len(state1["equipped_pets"]) == 1

def test_paused_tracking_ignores_snapshots(manager):
    # Set tracking to False
    manager.toggle_tracking(101, False)
    
    p = TelemetryPayload(
        userId=101, currentTaps=200, totalTaps=2000, timestamp=1010.0
    )
    res = manager.process_telemetry(p)
    assert res["status"] == "paused"
    
    # Verify no snapshots inserted
    snaps = manager.db.get_recent_snapshots(101)
    assert len(snaps) == 0

def test_session_timeouts_stale_and_disconnect(manager):
    # Start tracking
    p1 = TelemetryPayload(userId=101, currentTaps=500, totalTaps=5000, timestamp=1000.0)
    manager.process_telemetry(p1)
    assert manager.get_live_state(101)["connection_status"] == "LIVE"

    # Advance time by 20s (> 15s stale timeout)
    manager.check_timeouts(now=1020.0)
    assert manager.get_live_state(101, now=1020.0)["connection_status"] == "STALE"

    # Advance time by 70s (> 60s disconnect timeout)
    manager.check_timeouts(now=1070.0)
    assert manager.get_live_state(101, now=1070.0)["connection_status"] == "DISCONNECTED"
    # Active session should be cleanly closed
    assert manager.db.get_active_session(101) is None
