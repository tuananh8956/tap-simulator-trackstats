import pytest
from src.rate_engine import RateEngine
from src.models import TelemetryPayload

def test_tps_calculation_and_rebirth_fallback():
    engine = RateEngine()
    
    # Record 1 at t=100.0
    p1 = TelemetryPayload(
        userId=1, currentTaps=1000, totalTaps=10000, currentRebirths=1,
        totalRebirths=1, currentWins=0, totalWins=0, currentCurrency=100,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=100.0
    )
    r1 = engine.add_record(1, p1)
    assert r1["tps"] == 0.0
    
    # Record 2 at t=102.0 (gained 50 taps in 2s -> 25 TPS)
    p2 = TelemetryPayload(
        userId=1, currentTaps=1050, totalTaps=10050, currentRebirths=1,
        totalRebirths=1, currentWins=0, totalWins=0, currentCurrency=150,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=102.0
    )
    r2 = engine.add_record(1, p2)
    assert r2["tps"] == 25.0
    
    # Record 3 at t=103.0: Player rebirthed (currentTaps drops to 10, totalTaps increases to 10070)
    p3 = TelemetryPayload(
        userId=1, currentTaps=10, totalTaps=10070, currentRebirths=2,
        totalRebirths=2, currentWins=0, totalWins=0, currentCurrency=200,
        equippedPets=[], petInventoryCount=0, totalPetPower=0, timestamp=103.0
    )
    r3 = engine.add_record(1, p3)
    # Should NOT be negative; must fallback to delta totalTaps (20 taps / 1s = 20 TPS)
    assert r3["tps"] == 20.0

def test_sub_millisecond_jitter_guard():
    engine = RateEngine()
    p1 = TelemetryPayload(userId=2, currentTaps=100, totalTaps=100, timestamp=100.0)
    engine.add_record(2, p1)
    
    # Send another with virtually same timestamp (delta < 0.001s)
    p2 = TelemetryPayload(userId=2, currentTaps=105, totalTaps=105, timestamp=100.0005)
    r2 = engine.add_record(2, p2)
    assert r2["tps"] >= 0.0  # Must not raise ZeroDivisionError

def test_rolling_windows_1m_5m_15m():
    engine = RateEngine()
    
    # Simulate data across 600 seconds (10 minutes)
    for i in range(11):
        t = 1000.0 + (i * 60) # every 60s
        p = TelemetryPayload(
            userId=3,
            currentTaps=1000 + (i * 600), # 10 taps/sec
            totalTaps=10000 + (i * 600),
            currentRebirths=1 + (i // 5),
            totalRebirths=1 + (i // 5),
            currentCurrency=500 + (i * 300),
            timestamp=t
        )
        engine.add_record(3, p)
    
    rates = engine.get_rates(3)
    assert "windows" in rates
    assert rates["windows"]["1m"]["taps_gained"] == 600
    assert rates["windows"]["5m"]["taps_gained"] == 3000
    # Over 10 minutes, 15m window covers all 10 minutes (6000 taps)
    assert rates["windows"]["15m"]["taps_gained"] == 6000
    assert rates["max_tps"] > 0
    assert rates["avg_tps"] > 0
