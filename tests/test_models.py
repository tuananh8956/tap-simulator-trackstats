import pytest
from src.models import TelemetryPayload, PetItem, AccountInfo, SessionSummary
from src.config import Settings

def test_telemetry_payload_validation():
    payload_data = {
        "userId": 12345678,
        "currentTaps": 1500,
        "totalTaps": 50000,
        "currentRebirths": 5,
        "totalRebirths": 5,
        "currentWins": 10,
        "totalWins": 10,
        "currentCurrency": 250000,
        "equippedPets": [
            {"id": "p1", "name": "Hydra", "rarity": "Legendary", "multiplier": 150.0, "power": 3000.0}
        ],
        "petInventoryCount": 20,
        "totalPetPower": 15000.0,
        "timestamp": 1700000000.0
    }
    payload = TelemetryPayload(**payload_data)
    assert payload.userId == 12345678
    assert len(payload.equippedPets) == 1
    assert payload.equippedPets[0].name == "Hydra"
    assert payload.equippedPets[0].multiplier == 150.0

def test_telemetry_payload_defaults():
    payload_data = {
        "userId": 88888,
        "currentTaps": 0,
        "totalTaps": 0
    }
    payload = TelemetryPayload(**payload_data)
    assert payload.currentRebirths == 0
    assert payload.currentWins == 0
    assert payload.currentCurrency == 0
    assert payload.equippedPets == []
    assert payload.timestamp > 0

def test_config_settings_defaults():
    settings = Settings()
    assert settings.port == 3883
    assert settings.stale_timeout_sec == 15.0
    assert settings.disconnect_timeout_sec == 60.0
    assert "trackstats.db" in settings.db_path
