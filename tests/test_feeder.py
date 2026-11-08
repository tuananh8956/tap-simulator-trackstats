import pytest
from tools.telemetry_feeder import generate_payload

def test_generate_payload_progression():
    state = {
        "current_taps": 1000,
        "total_taps": 5000,
        "rebirths": 1,
        "wins": 2,
        "currency": 10000,
        "pets": [
            {"id": "p1", "name": "Hydra", "rarity": "Legendary", "multiplier": 150.0, "power": 3000.0}
        ]
    }
    p1 = generate_payload(123, state, delta_taps=50, delta_time=1.0)
    assert p1["userId"] == 123
    assert p1["currentTaps"] == 1050
    assert p1["totalTaps"] == 5050
    assert p1["currentRebirths"] == 1
    assert len(p1["equippedPets"]) == 1

def test_generate_payload_with_rebirth_reset():
    state = {
        "current_taps": 5000,
        "total_taps": 20000,
        "rebirths": 2,
        "wins": 5,
        "currency": 50000,
        "pets": []
    }
    # Simulate rebirth event: current taps reset to 0, total_taps increases, rebirths + 1
    p = generate_payload(123, state, delta_taps=100, delta_time=1.0, is_rebirth=True)
    assert p["currentTaps"] == 0
    assert p["totalTaps"] == 20100
    assert p["currentRebirths"] == 3
