from pathlib import Path
from fastapi.testclient import TestClient
from src.main import app, session_manager, db
from tools.telemetry_feeder import generate_payload, SAMPLE_SECRETS

client = TestClient(app)


def test_luau_script_served_and_respects_safety_and_afk_guard():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts/tap_sim_reborn_tracker.lua"
    assert script_path.exists()
    lua = script_path.read_text(encoding="utf-8")
    assert "_G.__TapSimTrackStats_Token" in lua
    assert "INSPECT_ON_START" in lua
    assert "parseCompactNumber" in lua
    assert "secretPets" in lua
    assert "recentHatches" in lua
    assert "ROBLOSECURITY" not in lua.upper()
    assert "executeTradeDirective" in lua

    resp = client.get("/api/v1/connector/script.lua?endpoint=http://127.0.0.1:9999/api/v1/telemetry")
    assert resp.status_code == 200
    assert "http://127.0.0.1:9999/api/v1/telemetry" in resp.text
    assert "http://127.0.0.1:9999/api/v1/connector/inspect" in resp.text


def test_v2_feeder_and_full_farm_secret_e2e():
    uid_a, uid_b = 91001, 91002
    for u in (uid_a, uid_b):
        db.delete_account(u)
        session_manager.remove_account(u)
        session_manager.toggle_tracking(u, True)

    state_a = {
        "current_taps": 1000,
        "total_taps": 10000,
        "rebirths": 5,
        "wins": 10,
        "currency": 50000,
        "eggs_hatched": 1000,
        "world": "Void Island",
        "secrets": [dict(SAMPLE_SECRETS[0]), dict(SAMPLE_SECRETS[1])],
    }
    state_b = {
        "current_taps": 2000,
        "total_taps": 20000,
        "rebirths": 8,
        "wins": 20,
        "currency": 80000,
        "eggs_hatched": 2500,
        "world": "Draconic Island",
        "secrets": [dict(SAMPLE_SECRETS[0])],
    }

    pa = generate_payload(uid_a, state_a, delta_taps=40, delta_time=1.0, simulate_secret_hatch=True)
    pb = generate_payload(uid_b, state_b, delta_taps=60, delta_time=1.0)
    assert client.post("/api/v1/telemetry", json=pa).status_code == 200
    assert client.post("/api/v1/telemetry", json=pb).status_code == 200

    secrets = client.get("/api/v1/secrets").json()
    assert secrets["total_secrets"] >= 3
    hatches = client.get(f"/api/v1/hatches?user_id={uid_a}").json()
    assert len(hatches) >= 1
    assert hatches[0]["image_url"]
