import pytest
import time
from src.database import Database
from src.rate_engine import RateEngine
from src.session_manager import SessionManager
from src.models import TelemetryPayload

def test_rebirth_preserves_session_taps_gained(tmp_path):
    """Critical 1: Ensure session records totalTaps so rebirth doesn't wipe taps_gained to 0."""
    db = Database(str(tmp_path / "rebirth_fix.db"))
    db.init_db()
    db.upsert_account(777, "RebirthTester", "Tester", "")
    rate_engine = RateEngine()
    manager = SessionManager(db, rate_engine, poller=None)

    # 1. Start session at 50,000 current taps, 1,000,000 total taps
    p1 = TelemetryPayload(
        userId=777, currentTaps=50000, totalTaps=1000000, currentRebirths=5,
        totalRebirths=5, timestamp=1000.0
    )
    manager.process_telemetry(p1)
    
    # 2. Gain 50,000 taps (current taps = 100,000, total taps = 1,050,000)
    p2 = TelemetryPayload(
        userId=777, currentTaps=100000, totalTaps=1050000, currentRebirths=5,
        totalRebirths=5, timestamp=1050.0
    )
    manager.process_telemetry(p2)

    # 3. Player Rebirths! currentTaps drops to 1,000, totalTaps increases to 1,051,000, rebirths = 6
    p3 = TelemetryPayload(
        userId=777, currentTaps=1000, totalTaps=1051000, currentRebirths=6,
        totalRebirths=6, timestamp=1055.0
    )
    manager.process_telemetry(p3)

    # 4. Trigger disconnect / end session
    manager.check_timeouts(now=1200.0)

    # Verify session summary in DB
    sessions = db.get_sessions(777)
    assert len(sessions) == 1
    session = sessions[0]
    # In reality the player gained 51,000 taps across the rebirth!
    assert session["taps_gained"] == 51000
    assert session["rebirths_gained"] == 1

def test_dangling_session_recovery_reads_snapshots(tmp_path):
    """Important 3: Ensure close_dangling_sessions populates metrics from existing snapshots."""
    db = Database(str(tmp_path / "dangling_fix.db"))
    db.init_db()
    db.upsert_account(888, "CrashUser", "Crash", "")
    
    # Simulate an open session that crashed
    s_id = db.start_session(888, 1000.0, initial_taps=10000, initial_rebirths=1)
    
    # Several snapshots were saved before the sudden crash
    p1 = TelemetryPayload(userId=888, currentTaps=500, totalTaps=10500, currentRebirths=1, timestamp=1010.0)
    db.insert_snapshot(s_id, p1, tps=20.0)
    
    p2 = TelemetryPayload(userId=888, currentTaps=1000, totalTaps=11000, currentRebirths=1, timestamp=1020.0)
    db.insert_snapshot(s_id, p2, tps=35.0)

    # Now the server restarts and calls close_dangling_sessions
    recovered_count = db.close_dangling_sessions()
    assert recovered_count == 1

    sessions = db.get_sessions(888)
    assert len(sessions) == 1
    recovered = sessions[0]
    assert recovered["end_time"] == 1020.0  # Should be the timestamp of last snapshot, not current system time
    assert recovered["taps_gained"] == 1000
    assert recovered["max_tps"] == 35.0

def test_account_deletion_cleans_session_manager_memory(tmp_path):
    """Important 4: Ensure deleting account clears in-memory active session to prevent FK crash."""
    db = Database(str(tmp_path / "fk_fix.db"))
    db.init_db()
    db.upsert_account(999, "DeleteUser", "Delete", "")
    rate_engine = RateEngine()
    manager = SessionManager(db, rate_engine, poller=None)

    # Send telemetry to create session
    p = TelemetryPayload(userId=999, currentTaps=10, totalTaps=100, timestamp=1000.0)
    manager.process_telemetry(p)
    assert manager._active_sessions.get(999) is not None

    # Delete account from DB & clean memory
    db.delete_account(999)
    manager.remove_account(999)
    assert manager._active_sessions.get(999) is None

    # New telemetry for 999 must auto-recreate account without FK violation
    p2 = TelemetryPayload(userId=999, currentTaps=20, totalTaps=120, timestamp=1005.0)
    res = manager.process_telemetry(p2)
    assert res["status"] == "processed"
