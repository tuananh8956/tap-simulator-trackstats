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
