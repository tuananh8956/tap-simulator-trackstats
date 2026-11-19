from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_dashboard_served_with_required_elements():
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "Tap Simulator Reborn" in html
    assert "TrackStats" in html
    assert "Secret Vault" in html
    assert "Multi-Account" in html
    assert "executorLoaderSnippet" in html
    # Redundant sections removed from visible UI
    assert "1-Minute Growth" not in html
    assert "Active Boosts &amp; Potions" not in html
    assert "Session History &amp; Data Export" not in html
    assert "telemetry_feeder.py" not in html
