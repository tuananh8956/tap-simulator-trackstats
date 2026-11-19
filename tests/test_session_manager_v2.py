from src.database import Database
from src.rate_engine import RateEngine
from src.pet_catalog import PetCatalogService
from src.session_manager import SessionManager
from src.models import TelemetryPayload, PetItem, BoostItem, HatchEventInput


def _make_mgr(tmp_path):
    db = Database(str(tmp_path / "sm2.db"))
    db.init_db()
    cat = PetCatalogService(db)
    cat.seed_defaults()
    re = RateEngine()
    return SessionManager(db, re, poller=None, pet_catalog=cat)


def test_afk_closed_inventory_preserves_secrets_and_increments_on_recent_hatch(tmp_path):
    mgr = _make_mgr(tmp_path)

    # 1. Initial open-inventory sync with 2 Dark Cats
    p1 = TelemetryPayload(
        userId=10,
        currentTaps=100,
        totalTaps=100,
        eggsHatched=500,
        world="Void Island",
        secretPets=[
            PetItem(
                name="Dark Cat",
                rarity="Secret",
                variant="Rainbow",
                tier="Secret III",
                count=2,
                multiplier=25000,
                power=120000,
            )
        ],
        timestamp=1000.0,
    )
    res1 = mgr.process_telemetry(p1)
    assert res1["new_hatches"] == []
    assert mgr.get_live_state(10, now=1001.0)["secret_count"] == 2

    # 2. Inventory closed during AFK: secretPets omitted (None), partial stats + 1 new Secret hatch popup
    p2 = TelemetryPayload(
        userId=10,
        currentTaps=200,
        totalTaps=200,
        eggsHatched=620,
        world="Void Island",
        secretPets=None,
        recentHatches=[
            HatchEventInput(
                petName="Dark Cat",
                rarity="Secret",
                variant="Rainbow",
                eggName="Void Egg",
                timestamp=1010.0,
            )
        ],
        timestamp=1010.0,
    )
    res2 = mgr.process_telemetry(p2)
    assert len(res2["new_hatches"]) == 1
    assert mgr.get_live_state(10, now=1011.0)["secret_count"] == 3

    # 3. Inventory reopened 5s later with count=3 -> reconciles without duplicate delta hatch!
    p3 = TelemetryPayload(
        userId=10,
        currentTaps=250,
        totalTaps=250,
        eggsHatched=650,
        secretPets=[
            PetItem(
                name="Dark Cat",
                rarity="Secret",
                variant="Rainbow",
                tier="Secret III",
                count=3,
                multiplier=25000,
                power=120000,
            )
        ],
        timestamp=1015.0,
    )
    res3 = mgr.process_telemetry(p3)
    assert res3["new_hatches"] == []
    assert mgr.get_live_state(10, now=1016.0)["secret_count"] == 3


def test_delta_secret_detection_and_farm_overview_and_boost_countdown(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.process_telemetry(
        TelemetryPayload(
            userId=10,
            currentTaps=100,
            totalTaps=100,
            eggsHatched=1000,
            world="Void Island",
            activeBoosts=[BoostItem(name="2x Luck", multiplier="2x", remainingSec=120.0)],
            secretPets=[PetItem(name="Chronos", rarity="Secret", variant="Golden", tier="Secret II", count=1)],
            timestamp=1000.0,
        )
    )
    res = mgr.process_telemetry(
        TelemetryPayload(
            userId=10,
            currentTaps=400,
            totalTaps=400,
            eggsHatched=1100,
            world="Void Island",
            activeBoosts=[BoostItem(name="2x Luck", multiplier="2x", remainingSec=110.0)],
            secretPets=[PetItem(name="Chronos", rarity="Secret", variant="Golden", tier="Secret II", count=2)],
            timestamp=1010.0,
        )
    )
    assert len(res["new_hatches"]) == 1
    assert res["new_hatches"][0]["source"] == "delta_detected"

    state = mgr.get_live_state(10, now=1020.0)
    assert state["eggs_per_hour"] > 0
    assert state["active_boosts"][0]["remainingSec"] == 100.0
    assert state["secret_pets"][0]["image_url"] == "/static/assets/pets/chronos.svg"

    overview = mgr.get_overview(now=1020.0)
    assert overview["total_secrets"] == 2
    assert overview["live_accounts"] == 1
    assert overview["total_eggs_hatched"] == 1100

    summary = mgr.get_secrets_summary(variant="Golden")
    assert summary["total_secrets"] == 2
    assert summary["grouped"][0]["name"] == "Chronos"
    assert summary["grouped"][0]["owners"][0]["count"] == 2


def test_check_timeouts_emits_only_on_state_transition(tmp_path):
    mgr = _make_mgr(tmp_path)
    mgr.process_telemetry(TelemetryPayload(userId=10, currentTaps=10, totalTaps=10, timestamp=1000.0))
    ev1 = mgr.check_timeouts(now=1020.0)
    ev2 = mgr.check_timeouts(now=1022.0)
    assert [e["event"] for e in ev1] == ["STALE"]
    assert ev2 == []  # No repeated STALE spam every 2s

    ev3 = mgr.check_timeouts(now=1065.0)
    ev4 = mgr.check_timeouts(now=1067.0)
    assert [e["event"] for e in ev3] == ["DISCONNECTED"]
    assert ev4 == []
