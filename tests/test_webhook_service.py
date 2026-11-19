import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from src.database import Database
from src.rate_engine import RateEngine
from src.pet_catalog import PetCatalogService
from src.session_manager import SessionManager
from src.webhook_service import WebhookService, mask_webhook_url
from src.models import AlertSettingsUpdate, TelemetryPayload, PetItem


def _make_services(tmp_path):
    db = Database(str(tmp_path / "wh.db"))
    db.init_db()
    cat = PetCatalogService(db)
    cat.seed_defaults()
    mgr = SessionManager(db, RateEngine(), poller=None, pet_catalog=cat)
    poller = MagicMock()
    poller.get_user_by_username = AsyncMock(
        return_value={"id": 44444, "name": "FarmHero", "displayName": "Hero"}
    )
    poller.get_user_avatar = AsyncMock(return_value="https://tr.rbxcdn.com/hero.png")
    wh = WebhookService(db, mgr, cat, poller=poller)
    return db, mgr, wh


def test_webhook_url_masking_preserved_on_update(tmp_path):
    _, _, wh = _make_services(tmp_path)
    secret_url = "https://discord.com/api/webhooks/123456789/supersecrettokenvalue"
    pub = wh.update_settings(
        AlertSettingsUpdate(webhookUrl=secret_url, enabled=True, notifySecretHatch=True)
    )
    assert "supersecrettokenvalue" not in pub["webhookUrl"]
    assert pub["hasWebhookUrl"] is True
    assert pub["webhookUrl"].endswith("****")

    # Updating toggle with masked URL returned by GET must NOT overwrite secret_url
    wh.update_settings(
        AlertSettingsUpdate(webhookUrl=pub["webhookUrl"], enabled=True, notifyStale=True)
    )
    assert wh.get_raw_settings().webhookUrl == secret_url
    assert wh.get_raw_settings().notifyStale is True

    # Explicit clear removes it
    pub2 = wh.update_settings(AlertSettingsUpdate(clearWebhook=True))
    assert pub2["hasWebhookUrl"] is False
    assert wh.get_raw_settings().webhookUrl == ""


@pytest.mark.anyio
async def test_inbound_webhook_parses_resolves_and_avoids_double_count(tmp_path):
    db, mgr, wh = _make_services(tmp_path)
    embed_payload = {
        "embeds": [
            {
                "title": "Secret Hatched!",
                "description": "Player: FarmHero hatched Rainbow Dark Cat from Void Egg (1 in 4M)",
            }
        ]
    }
    res = await wh.ingest_discord_webhook(embed_payload)
    assert res["status"] == "recorded"
    assert res["event"]["user_id"] == 44444
    assert res["event"]["pet_name"] == "Dark Cat"
    assert res["event"]["variant"] == "Rainbow"
    # No recent Luau sync -> secret vault incremented to 1
    assert db.get_account(44444)["secret_count"] == 1

    # Duplicate within 15s ignored
    dup = await wh.ingest_discord_webhook(embed_payload)
    assert dup["status"] == "duplicate"
    assert db.get_account(44444)["secret_count"] == 1

    # If account HAS recent authoritative Luau sync, a new webhook Secret hatch does NOT inflate account_secrets
    mgr.process_telemetry(
        TelemetryPayload(
            userId=44444,
            currentTaps=100,
            totalTaps=100,
            secretPets=[PetItem(name="Dark Cat", rarity="Secret", variant="Rainbow", count=1)],
            timestamp=time.time(),
        )
    )
    res2 = await wh.ingest_discord_webhook(
        {
            "embeds": [
                {
                    "title": "Secret Hatched!",
                    "description": "Player: FarmHero hatched Golden Chronos (1 in 2M)",
                }
            ]
        }
    )
    assert res2["status"] == "recorded"
    assert db.get_account(44444)["secret_count"] == 1  # untouched because Luau sync is authoritative


@pytest.mark.anyio
async def test_outbound_status_alert_respects_disconnect_vs_stale_toggles(tmp_path):
    _, _, wh = _make_services(tmp_path)
    wh.update_settings(
        AlertSettingsUpdate(
            webhookUrl="https://discord.com/api/webhooks/1/tok",
            enabled=True,
            notifyDisconnect=True,
            notifyStale=False,
        )
    )
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=204)
        sent_stale = await wh.send_status_alert(44444, "FarmHero", "STALE")
        assert sent_stale is False
        assert mock_post.call_count == 0

        sent_disc = await wh.send_status_alert(44444, "FarmHero", "DISCONNECTED")
        assert sent_disc is True
        assert mock_post.call_count == 1
