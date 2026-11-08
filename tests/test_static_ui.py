import pytest
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_dashboard_served_with_required_elements():
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "Tap Simulator Reborn" in html
    assert "TrackStats" in html
    assert "chart.js" in html.lower() or "Chart" in html
    assert "Live Statistics" in html or "Live Stats" in html
    assert "Equipped Pets" in html or "Pet Showcase" in html
    assert "Multi-Account" in html
