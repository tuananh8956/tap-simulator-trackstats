import httpx
import time
import asyncio
from typing import Dict, Any, Optional

TARGET_PLACE_ID = 72858262610964
TARGET_UNIVERSE_ID = 10629695169

class RobloxPoller:
    PRESENCE_TYPES = {
        0: "Offline",
        1: "Online",
        2: "InGame",
        3: "InStudio"
    }

    def __init__(self, debounce_sec: float = 5.0):
        self.debounce_sec = debounce_sec
        self._user_cache: Dict[int, Dict[str, Any]] = {}
        self._avatar_cache: Dict[int, str] = {}
        self._presence_cache: Dict[int, Dict[str, Any]] = {}
        self._last_presence_query: Dict[int, float] = {}
        self._backoff_until: float = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": "TapSimulatorTrackStats/1.0 (Legitimate Analytics Companion)"},
            timeout=6.0
        )

    async def get_user_info(self, user_id: int) -> Dict[str, Any]:
        if user_id in self._user_cache:
            return self._user_cache[user_id]

        url = f"https://users.roblox.com/v1/users/{user_id}"
        try:
            async with await self._get_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    info = {
                        "id": data.get("id", user_id),
                        "name": data.get("name", f"User_{user_id}"),
                        "displayName": data.get("displayName", data.get("name", f"User_{user_id}")),
                        "created": data.get("created")
                    }
                    self._user_cache[user_id] = info
                    return info
                elif resp.status_code == 429:
                    self._backoff_until = time.time() + 15.0
        except Exception:
            pass

        return {
            "id": user_id,
            "name": f"Player_{user_id}",
            "displayName": f"Player_{user_id}",
            "created": None
        }

    async def get_user_avatar(self, user_id: int) -> str:
        if user_id in self._avatar_cache:
            return self._avatar_cache[user_id]

        url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png&isCircular=true"
        try:
            async with await self._get_client() as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json().get("data", [])
                    if data and "imageUrl" in data[0]:
                        img_url = data[0]["imageUrl"]
                        self._avatar_cache[user_id] = img_url
                        return img_url
        except Exception:
            pass

        # Fallback SVG avatar placeholder
        fallback = f"https://www.roblox.com/headshot-thumbnail/image?userId={user_id}&width=150&height=150&format=png"
        return fallback

    async def get_user_presence(self, user_id: int) -> Dict[str, Any]:
        now = time.time()
        if now < self._backoff_until:
            # Under rate limit backoff, return cached presence if available
            return self._presence_cache.get(user_id, {
                "userId": user_id,
                "status": "Unknown",
                "placeId": None,
                "is_in_target_game": False,
                "lastLocation": "Rate limited"
            })

        # Check debounce
        if user_id in self._presence_cache and (now - self._last_presence_query.get(user_id, 0)) < self.debounce_sec:
            return self._presence_cache[user_id]

        url = "https://presence.roblox.com/v1/presence/users"
        try:
            async with await self._get_client() as client:
                resp = await client.post(url, json={"userIds": [user_id]})
                if resp.status_code == 200:
                    presences = resp.json().get("userPresences", [])
                    if presences:
                        p = presences[0]
                        ptype = p.get("userPresenceType", 0)
                        status_str = self.PRESENCE_TYPES.get(ptype, "Offline")
                        place_id = p.get("placeId")
                        is_target = (place_id == TARGET_PLACE_ID) or ("Tap Simulator REBORN" in (p.get("lastLocation") or ""))
                        
                        res = {
                            "userId": user_id,
                            "status": status_str,
                            "placeId": place_id,
                            "is_in_target_game": is_target,
                            "lastLocation": p.get("lastLocation", "")
                        }
                        self._presence_cache[user_id] = res
                        self._last_presence_query[user_id] = now
                        return res
                elif resp.status_code == 429:
                    self._backoff_until = now + 15.0
        except Exception:
            pass

        default_res = {
            "userId": user_id,
            "status": "Offline",
            "placeId": None,
            "is_in_target_game": False,
            "lastLocation": ""
        }
        return self._presence_cache.get(user_id, default_res)
