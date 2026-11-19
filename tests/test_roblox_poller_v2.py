import pytest
from unittest.mock import patch, MagicMock
from src.roblox_poller import RobloxPoller


@pytest.mark.anyio
async def test_get_asset_thumbnail_caches_result():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [
                    {
                        "targetId": 999111,
                        "state": "Completed",
                        "imageUrl": "https://tr.rbxcdn.com/asset-999111.png",
                    }
                ]
            },
        )
        url1 = await poller.get_asset_thumbnail(999111)
        url2 = await poller.get_asset_thumbnail(999111)
        assert url1 == "https://tr.rbxcdn.com/asset-999111.png"
        assert url2 == url1
        assert mock_get.call_count == 1


@pytest.mark.anyio
async def test_get_user_by_username_resolves_and_caches():
    poller = RobloxPoller()
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "data": [{"id": 888222, "name": "SecretHunter", "displayName": "Hunter"}]
            },
        )
        user = await poller.get_user_by_username("SecretHunter")
        assert user == {"id": 888222, "name": "SecretHunter", "displayName": "Hunter"}
        user_cached = await poller.get_user_by_username("secrethunter")
        assert user_cached["id"] == 888222
        assert mock_post.call_count == 1
