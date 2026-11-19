from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)


def test_v2_dashboard_contains_all_views_and_secret_vault_controls():
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    for token in [
        "Tap Simulator Reborn",
        "TrackStats",
        "Live Statistics",
        "Equipped Pets",
        "Multi-Account",
        "Secret Vault",
        "Hatch Feed",
        "Connector",
        "farmTotalSecrets",
        "secretVaultGrid",
        "secretDetailModal",
        "discordWebhookForm",
        "inspectorDumpViewer",
        "btnDownloadScript",
    ]:
        assert token in html, f"Missing UI element/token: {token}"


def test_v2_js_and_css_served_with_xss_helpers_and_variant_styles():
    js_resp = client.get("/static/js/app.js")
    css_resp = client.get("/static/css/style.css")
    assert js_resp.status_code == 200
    assert css_resp.status_code == 200
    js = js_resp.text
    css = css_resp.text
    assert "function escapeHtml" in js
    assert "function safeImageUrl" in js
    assert "/api/v1/secrets" in js
    assert "/api/v1/settings/alerts" in js
    assert ".variant-rainbow" in css
    assert ".variant-golden" in css
    assert ".variant-diamond" in css
    assert ".variant-shiny" in css
