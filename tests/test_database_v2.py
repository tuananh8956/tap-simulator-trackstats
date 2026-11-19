import json
import sqlite3
from src.database import Database


def test_legacy_v1_db_migrates_without_data_loss(tmp_path):
    db_file = tmp_path / "legacy_v1.db"
    conn = sqlite3.connect(str(db_file))
    conn.executescript(
        """
        CREATE TABLE accounts (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL,
            display_name TEXT,
            avatar_url TEXT,
            is_tracking INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP
        );
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL,
            initial_taps INTEGER DEFAULT 0,
            final_taps INTEGER DEFAULT 0,
            taps_gained INTEGER DEFAULT 0,
            initial_rebirths INTEGER DEFAULT 0,
            final_rebirths INTEGER DEFAULT 0,
            rebirths_gained INTEGER DEFAULT 0,
            max_tps REAL DEFAULT 0.0,
            avg_tps REAL DEFAULT 0.0
        );
        CREATE TABLE snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            current_taps INTEGER NOT NULL,
            total_taps INTEGER DEFAULT 0,
            tps REAL NOT NULL,
            current_rebirths INTEGER DEFAULT 0,
            current_wins INTEGER DEFAULT 0,
            current_currency INTEGER DEFAULT 0,
            total_pet_power REAL DEFAULT 0.0,
            equipped_pets_json TEXT
        );
        INSERT INTO accounts (user_id, username) VALUES (101, 'LegacyUser');
        """
    )
    conn.commit()
    conn.close()

    db = Database(str(db_file))
    db.init_db()
    # Calling init_db twice must remain idempotent
    db.init_db()

    acc = db.get_account(101)
    assert acc["username"] == "LegacyUser"
    assert acc["secret_count"] == 0
    assert acc["eggs_hatched"] == 0
    assert acc["world"] is None


def test_account_secrets_replace_and_increment(tmp_path):
    db = Database(str(tmp_path / "sec.db"))
    db.init_db()
    db.upsert_account(1, "FarmA", "FarmA", "")

    total = db.replace_account_secrets(
        1,
        [
            {
                "name": "Dark Cat",
                "variant": "rainbow",
                "tier": "Secret III",
                "count": 2,
                "multiplier": 25000.0,
                "power": 120000.0,
                "is_equipped": True,
                "egg_source": "Void Egg",
            },
            {
                "name": "Dark Cat",
                "variant": "Rainbow",
                "tier": "Secret III",
                "count": 1,
                "multiplier": 25000.0,
                "power": 125000.0,
                "is_equipped": False,
            },
        ],
        updated_at=1000.0,
    )
    assert total == 3
    rows = db.get_account_secrets(1)
    assert len(rows) == 1
    assert rows[0]["count"] == 3
    assert rows[0]["is_equipped"] == 1
    assert rows[0]["power"] == 125000.0
    assert rows[0]["egg_source"] == "Void Egg"

    new_total = db.increment_account_secret(1, "Dark Cat", "Rainbow", updated_at=1005.0)
    assert new_total == 4
    assert db.get_account(1)["secret_count"] == 4


def test_hatch_event_dedup_15s_and_nullable_user(tmp_path):
    db = Database(str(tmp_path / "hatch.db"))
    db.init_db()
    db.upsert_account(1, "FarmA", "FarmA", "")

    e1 = db.record_hatch_event(
        {
            "user_id": 1,
            "actor_name": "FarmA",
            "pet_name": "Chronos",
            "rarity": "Secret",
            "variant": "Golden",
            "source": "telemetry",
            "timestamp": 2000.0,
        }
    )
    assert e1 is not None

    # Same pet within 15s from webhook must be deduplicated
    e2 = db.record_hatch_event(
        {
            "user_id": 1,
            "actor_name": "FarmA",
            "pet_name": "Chronos",
            "rarity": "Secret",
            "variant": "golden",
            "source": "webhook",
            "timestamp": 2010.0,
        }
    )
    assert e2 is None

    # After 15s window, new hatch is allowed
    e3 = db.record_hatch_event(
        {
            "user_id": 1,
            "actor_name": "FarmA",
            "pet_name": "Chronos",
            "rarity": "Secret",
            "variant": "Golden",
            "source": "webhook",
            "timestamp": 2020.0,
        }
    )
    assert e3 is not None

    # Unlinked webhook hatch with user_id=None succeeds under PRAGMA foreign_keys=ON
    e4 = db.record_hatch_event(
        {
            "user_id": None,
            "actor_name": "MysteryPlayer",
            "pet_name": "Void Wraith",
            "rarity": "Secret",
            "variant": "Normal",
            "source": "webhook",
            "timestamp": 2025.0,
        }
    )
    assert e4 is not None
    assert e4["user_id"] is None
    assert e4["actor_name"] == "MysteryPlayer"

    events = db.get_hatch_events(limit=10, rarity="Secret")
    assert len(events) == 3


def test_settings_inspector_and_v1_v2_backup_roundtrip(tmp_path):
    db = Database(str(tmp_path / "rt.db"))
    db.init_db()

    db.set_setting("discord_alerts", {"enabled": True, "webhookUrl": "https://discord.com/api/webhooks/1/a"})
    assert db.get_setting("discord_alerts")["enabled"] is True
    assert db.get_setting("missing_key", {"x": 1}) == {"x": 1}

    for i in range(12):
        db.save_inspector_report(10, "Tester", 72858262610964, {"idx": i}, created_at=100.0 + i)
    reports = db.get_inspector_reports(limit=20)
    assert len(reports) == 10
    assert reports[0]["structure"]["idx"] == 11

    v1_backup = json.dumps(
        {"accounts": [{"user_id": 7, "username": "OldBackup"}], "sessions": [], "snapshots": []}
    )
    assert db.restore_data(v1_backup) is True
    assert db.get_account(7)["username"] == "OldBackup"

    db.replace_account_secrets(7, [{"name": "Void Wraith", "variant": "Normal", "count": 2}], updated_at=100.0)
    db.upsert_pet_catalog("void-wraith", "Void Wraith", tier="Secret I", default_egg="Void Egg", odds="1 in 500K")
    exported = db.export_data("json")
    data = json.loads(exported)
    assert len(data["account_secrets"]) == 1
    assert len(data["pet_catalog"]) == 1

    db2 = Database(str(tmp_path / "rt2.db"))
    db2.init_db()
    assert db2.restore_data(exported) is True
    assert len(db2.get_account_secrets(7)) == 1
    assert db2.get_pet_catalog_item("void-wraith")["default_egg"] == "Void Egg"
