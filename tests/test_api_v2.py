from fastapi.testclient import TestClient
from src.main import app, session_manager, db

client = TestClient(app)


def test_overview_secrets_catalog_and_custom_image():
    uid = 70001
    db.delete_account(uid)
    session_manager.remove_account(uid)
    session_manager.toggle_tracking(uid, True)

    payload = {
        "userId": uid,
        "currentTaps": 5000,
        "totalTaps": 50000,
        "currentRebirths": 10,
        "eggsHatched": 1200,
        "world": "Void Island",
        "secretPets": [
            {
                "name": "Dark Cat",
                "rarity": "Secret",
                "variant": "Rainbow",
                "tier": "Secret III",
                "count": 2,
                "multiplier": 25000,
                "power": 120000,
            },
            {
                "name": "Void Wraith",
                "rarity": "Secret",
                "variant": "Normal",
                "tier": "Secret I",
                "count": 1,
                "multiplier": 4000,
                "power": 18000,
            },
        ],
        "recentHatches": [
            {
                "petName": "Dark Cat",
                "rarity": "Secret",
                "variant": "Rainbow",
                "eggName": "Void Egg",
                "odds": "1 in 4M",
                "timestamp": 1700000500.0,
            }
        ],
        "timestamp": 1700000500.0,
    }
    resp = client.post("/api/v1/telemetry", json=payload)
    assert resp.status_code == 200

    ov = client.get("/api/v1/overview")
    assert ov.status_code == 200
    assert ov.json()["total_secrets"] >= 3

    sec = client.get(f"/api/v1/secrets?user_id={uid}&variant=Rainbow")
    assert sec.status_code == 200
    sec_data = sec.json()
    assert sec_data["total_secrets"] == 2
    assert sec_data["grouped"][0]["name"] == "Dark Cat"
    assert sec_data["grouped"][0]["image_url"].endswith((".png", ".webp", ".jpg", ".svg")) or sec_data["grouped"][0]["image_url"].startswith("http")

    # Catalog list
    cat_resp = client.get("/api/v1/pets/catalog")
    assert cat_resp.status_code == 200
    assert len(cat_resp.json()) >= 66

    # Override custom image
    ov_img = client.post(
        "/api/v1/pets/catalog/dark-cat/image",
        json={"imageUrl": "https://cdn.example/dark-cat.png"},
    )
    assert ov_img.status_code == 200
    assert ov_img.json()["image_url"] == "https://cdn.example/dark-cat.png"

    # Reset custom image so other tests see curated SVG
    client.post("/api/v1/pets/catalog/dark-cat/image", json={"imageUrl": ""})

    # Dynamic fallback SVG endpoint
    svg_resp = client.get("/api/v1/pets/icon/brand-new-secret.svg")
    assert svg_resp.status_code == 200
    assert "image/svg+xml" in svg_resp.headers["content-type"]
    assert "<svg" in svg_resp.text


def test_hatches_alerts_webhook_and_inspector_endpoints():
    r_alerts = client.get("/api/v1/settings/alerts")
    assert r_alerts.status_code == 200
    assert "hasWebhookUrl" in r_alerts.json()

    r_upd = client.post(
        "/api/v1/settings/alerts",
        json={"webhookUrl": "https://discord.com/api/webhooks/111/secretval", "enabled": False, "notifyStale": True},
    )
    assert r_upd.status_code == 200
    assert r_upd.json()["hasWebhookUrl"] is True
    assert "secretval" not in r_upd.json()["webhookUrl"]

    r_ins = client.post(
        "/api/v1/connector/inspect",
        json={
            "userId": 70001,
            "username": "Tester",
            "placeId": 72858262610964,
            "structure": {"leaderstats": ["Taps", "Rebirths"], "petGuis": ["PlayerGui.Pets.Grid"]},
        },
    )
    assert r_ins.status_code == 200
    reports = client.get("/api/v1/connector/inspect").json()
    assert len(reports) >= 1
    assert "leaderstats" in reports[0]["structure"]

    r_wh = client.post(
        "/api/v1/webhook/discord",
        json={"content": "[WebhookTester] hatched Golden Sanguine Heart from Crimson Egg (1 in 8M)"},
    )
    assert r_wh.status_code == 200
    assert r_wh.json()["status"] in ("recorded", "duplicate")

    hatches = client.get("/api/v1/hatches?rarity=Secret")
    assert hatches.status_code == 200
    assert isinstance(hatches.json(), list)
    assert len(hatches.json()) >= 1
