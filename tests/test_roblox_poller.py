import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.roblox_poller import RobloxPoller, TARGET_PLACE_ID

@pytest.mark.anyio
async def test_roblox_poller_user_info():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"id": 12345, "name": "RobloxLegend", "displayName": "TheLegend"}
        )
        info = await poller.get_user_info(12345)
        assert info["id"] == 12345
        assert info["name"] == "RobloxLegend"
        assert info["displayName"] == "TheLegend"

@pytest.mark.anyio
async def test_roblox_poller_avatar():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {"targetId": 12345, "state": "Completed", "imageUrl": "https://tr.rbxcdn.com/avatar.png"}
                ]
            }
        )
        avatar = await poller.get_user_avatar(12345)
        assert "avatar.png" in avatar

@pytest.mark.anyio
async def test_roblox_poller_presence_target_game():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "userPresences": [
                    {
                        "userId": 12345,
                        "userPresenceType": 2,
                        "lastLocation": "Tap Simulator REBORN",
                        "placeId": TARGET_PLACE_ID,
                        "gameId": "server-job-123"
                    }
                ]
            }
        )
        presence = await poller.get_user_presence(12345)
        assert presence["is_in_target_game"] is True
        assert presence["status"] == "InGame"
        assert presence["placeId"] == TARGET_PLACE_ID
