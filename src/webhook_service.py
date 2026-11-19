import re
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx
from src.database import Database
from src.pet_catalog import PetCatalogService
from src.session_manager import SessionManager
from src.models import (
    AlertSettings,
    AlertSettingsUpdate,
    normalize_variant,
    sanitize_image_url,
    slugify_pet_name,
)

ALERT_SETTINGS_KEY = "discord_alerts"

_VARIANT_COLORS = {
    "Rainbow": 0xEC4899,
    "Rainbow Shiny": 0xF472B6,
    "Golden": 0xFBBF24,
    "Golden Shiny": 0xFDE047,
    "Diamond": 0x38BDF8,
    "Diamond Shiny": 0x67E8F9,
    "Shiny": 0xE879F9,
    "Normal": 0xA855F7,
}

_VARIANT_PREFIX_RE = re.compile(
    r"^(?:\[)?(Rainbow\s+Shiny|Shiny\s+Rainbow|Golden\s+Shiny|Shiny\s+Golden|Diamond\s+Shiny|Shiny\s+Diamond|Rainbow|Golden|Gold|Diamond|Shiny)(?:\])?\s+(.+)$",
    re.IGNORECASE,
)


def mask_webhook_url(url: str) -> str:
    clean = (url or "").strip()
    if not clean:
        return ""
    if "****" in clean:
        return clean
    parts = clean.rstrip("/").split("/")
    if len(parts) >= 2 and len(parts[-1]) > 6:
        return "/".join(parts[:-1]) + "/" + parts[-1][:4] + "****"
    if len(clean) > 12:
        return clean[:8] + "...****"
    return "****"


def _split_variant_and_pet(raw_pet: str, explicit_variant: Optional[str] = None) -> Tuple[str, str]:
    text = (raw_pet or "").strip().strip("*_`[]")
    if explicit_variant and explicit_variant.strip():
        return text, normalize_variant(explicit_variant)
    m = _VARIANT_PREFIX_RE.match(text)
    if m:
        return m.group(2).strip(), normalize_variant(m.group(1))
    return text, "Normal"


class WebhookService:
    def __init__(
        self,
        db: Database,
        session_manager: SessionManager,
        pet_catalog: PetCatalogService,
        poller: Optional[Any] = None,
    ):
        self.db = db
        self.session_manager = session_manager
        self.pet_catalog = pet_catalog
        self.poller = poller

    def get_raw_settings(self) -> AlertSettings:
        stored = self.db.get_setting(ALERT_SETTINGS_KEY)
        if not isinstance(stored, dict):
            return AlertSettings()
        try:
            return AlertSettings(**stored)
        except Exception:
            return AlertSettings()

    def get_public_settings(self) -> Dict[str, Any]:
        raw = self.get_raw_settings()
        return {
            "webhookUrl": mask_webhook_url(raw.webhookUrl),
            "hasWebhookUrl": bool(raw.webhookUrl),
            "enabled": raw.enabled,
            "notifySecretHatch": raw.notifySecretHatch,
            "notifyDisconnect": raw.notifyDisconnect,
            "notifyStale": raw.notifyStale,
            "forwardInboundWebhook": raw.forwardInboundWebhook,
        }

    def update_settings(self, update: AlertSettingsUpdate) -> Dict[str, Any]:
        current = self.get_raw_settings()
        data = current.model_dump()

        if update.clearWebhook:
            data["webhookUrl"] = ""
        elif update.webhookUrl is not None:
            candidate = update.webhookUrl.strip()
            # Preserve existing secret URL if frontend submits empty or masked placeholder
            if candidate and "****" not in candidate:
                if candidate.lower().startswith(("https://", "http://")):
                    data["webhookUrl"] = candidate

        for field_name in ("enabled", "notifySecretHatch", "notifyDisconnect", "notifyStale", "forwardInboundWebhook"):
            val = getattr(update, field_name)
            if val is not None:
                data[field_name] = bool(val)

        validated = AlertSettings(**data)
        self.db.set_setting(ALERT_SETTINGS_KEY, validated.model_dump())
        return self.get_public_settings()

    async def _post_discord(self, url: str, body: Dict[str, Any]) -> bool:
        if not url or not url.lower().startswith(("https://", "http://")):
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(url, json=body)
                return 200 <= resp.status_code < 300
        except Exception:
            return False

    async def send_secret_hatch_alert(self, hatch_event: Dict[str, Any], base_url: str = "") -> bool:
        cfg = self.get_raw_settings()
        if not cfg.enabled or not cfg.notifySecretHatch or not cfg.webhookUrl:
            return False
        if (hatch_event.get("rarity") or "").lower() != "secret":
            return False

        pet_name = hatch_event.get("pet_name", "Unknown Secret")
        variant = normalize_variant(hatch_event.get("variant"))
        actor = hatch_event.get("username") or hatch_event.get("actor_name") or f"User {hatch_event.get('user_id')}"
        tier = hatch_event.get("tier") or "Secret"
        egg = hatch_event.get("egg_name") or "Unknown Egg"
        odds = hatch_event.get("odds") or "N/A"
        color = _VARIANT_COLORS.get(variant, 0xA855F7)

        embed: Dict[str, Any] = {
            "title": f"✨ SECRET HATCHED — {variant} {pet_name}",
            "color": color,
            "fields": [
                {"name": "Account", "value": str(actor), "inline": True},
                {"name": "Tier", "value": str(tier), "inline": True},
                {"name": "Variant", "value": variant, "inline": True},
                {"name": "Egg", "value": str(egg), "inline": True},
                {"name": "Odds", "value": str(odds), "inline": True},
            ],
            "footer": {"text": "Tap Simulator Reborn • TrackStats v2"},
        }
        img_url = sanitize_image_url(hatch_event.get("image_url"))
        if img_url and img_url.lower().startswith(("https://", "http://")):
            embed["thumbnail"] = {"url": img_url}
        elif img_url and base_url.lower().startswith(("https://", "http://")):
            embed["thumbnail"] = {"url": f"{base_url.rstrip('/')}{img_url}"}

        return await self._post_discord(cfg.webhookUrl, {"embeds": [embed]})

    async def send_status_alert(self, user_id: int, username: str, event: str) -> bool:
        cfg = self.get_raw_settings()
        if not cfg.enabled or not cfg.webhookUrl:
            return False
        ev = (event or "").upper()
        if ev == "DISCONNECTED" and not cfg.notifyDisconnect:
            return False
        if ev == "STALE" and not cfg.notifyStale:
            return False
        if ev not in ("DISCONNECTED", "STALE"):
            return False

        color = 0xEF4444 if ev == "DISCONNECTED" else 0xF59E0B
        title = f"🔴 Account Disconnected: {username}" if ev == "DISCONNECTED" else f"🟠 Account Stale: {username}"
        desc = (
            f"No telemetry received for **60s+** from `{username}` (ID: `{user_id}`). Session closed."
            if ev == "DISCONNECTED"
            else f"No telemetry received for **15s+** from `{username}` (ID: `{user_id}`)."
        )
        body = {
            "embeds": [
                {
                    "title": title,
                    "description": desc,
                    "color": color,
                    "footer": {"text": "Tap Simulator Reborn • TrackStats v2"},
                }
            ]
        }
        return await self._post_discord(cfg.webhookUrl, body)

    async def send_test_alert(self) -> Dict[str, Any]:
        cfg = self.get_raw_settings()
        if not cfg.webhookUrl:
            return {"status": "error", "detail": "No Discord Webhook URL configured."}
        ok = await self._post_discord(
            cfg.webhookUrl,
            {
                "embeds": [
                    {
                        "title": "✅ TrackStats v2 Webhook Connected",
                        "description": "Your **Tap Simulator Reborn – TrackStats** Discord alerts are active.",
                        "color": 0x10B981,
                    }
                ]
            },
        )
        return {"status": "sent" if ok else "failed", "ok": ok}

    def parse_discord_payload(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(payload, dict):
            return None

        content = str(payload.get("content") or "")
        embeds: List[Dict[str, Any]] = payload.get("embeds") if isinstance(payload.get("embeds"), list) else []

        title_parts: List[str] = []
        text_parts: List[str] = [content]
        field_map: Dict[str, str] = {}
        embed_thumb: Optional[str] = None

        for emb in embeds:
            if not isinstance(emb, dict):
                continue
            if emb.get("title"):
                title_parts.append(str(emb["title"]))
                text_parts.append(str(emb["title"]))
            if emb.get("description"):
                text_parts.append(str(emb["description"]))
            if isinstance(emb.get("thumbnail"), dict) and emb["thumbnail"].get("url"):
                embed_thumb = sanitize_image_url(str(emb["thumbnail"]["url"]))
            for f in emb.get("fields", []) or []:
                if isinstance(f, dict) and f.get("name"):
                    field_map[str(f["name"]).strip().lower()] = str(f.get("value") or "").strip()
                    text_parts.append(f"{f['name']}: {f.get('value', '')}")

        full_text = "\n".join(p for p in text_parts if p).strip()
        if not full_text:
            return None

        # Extract rarity
        rarity = field_map.get("rarity") or ""
        if not rarity:
            if re.search(r"\bsecret\b", full_text, re.IGNORECASE):
                rarity = "Secret"
            elif re.search(r"\bmythic(?:al)?\b", full_text, re.IGNORECASE):
                rarity = "Mythic"
            elif re.search(r"\blegendary\b", full_text, re.IGNORECASE):
                rarity = "Legendary"
            else:
                rarity = "Secret"
        else:
            rarity = rarity.strip().strip("*_`").title()

        # Extract userId / username
        user_id: Optional[int] = None
        username: Optional[str] = None
        for key in ("userid", "user id", "roblox id", "id"):
            if key in field_map and field_map[key].isdigit():
                user_id = int(field_map[key])
                break
        if user_id is None:
            m_uid = re.search(r"user\s*id\s*[:=#]\s*(\d+)", full_text, re.IGNORECASE)
            if m_uid:
                user_id = int(m_uid.group(1))

        for key in ("player", "account", "username", "user"):
            if key in field_map and field_map[key]:
                username = field_map[key].strip().strip("*_`@")
                break
        if not username:
            m_user = re.search(r"(?:player|account|user)\s*[:\-]\s*`?@?([A-Za-z0-9_]{3,20})`?", full_text, re.IGNORECASE)
            if m_user:
                username = m_user.group(1)
            else:
                m_bracket = re.search(r"\[([A-Za-z0-9_]{3,20})\]\s+hatched", full_text, re.IGNORECASE)
                if m_bracket:
                    username = m_bracket.group(1)

        # Extract pet name & variant
        explicit_variant = field_map.get("variant")
        raw_pet = field_map.get("pet") or field_map.get("secret") or field_map.get("pet name")
        if not raw_pet:
            m_hatched = re.search(
                r"hatched\s+(?:a\s+|an\s+|SECRET\s*[:\-]?\s*)?([A-Za-z0-9\s\-\[\]]+?)(?:\s+from\s+|\s*\(|\s*\||\n|$)",
                full_text,
                re.IGNORECASE,
            )
            if m_hatched:
                raw_pet = m_hatched.group(1).strip()
            else:
                # Try matching any known catalog secret name in text
                for cat_item in self.db.get_pet_catalog():
                    if cat_item["name"].lower() in full_text.lower():
                        raw_pet = cat_item["name"]
                        break

        if not raw_pet:
            return None

        pet_name, variant = _split_variant_and_pet(raw_pet, explicit_variant=explicit_variant)
        if not pet_name:
            return None

        # Extract egg name & odds
        egg_name = field_map.get("egg") or field_map.get("egg source")
        if not egg_name:
            m_egg = re.search(r"from\s+([A-Za-z0-9\s]+?Egg)\b", full_text, re.IGNORECASE)
            if m_egg:
                egg_name = m_egg.group(1).strip()

        odds = field_map.get("odds") or field_map.get("chance")
        if not odds:
            m_odds = re.search(r"(1\s+in\s+[0-9.,]+[KMBT]?)", full_text, re.IGNORECASE)
            if m_odds:
                odds = m_odds.group(1).strip()

        tier = field_map.get("tier")
        if not tier:
            m_tier = re.search(r"\b(Secret\s+(?:III|II|I)|Event)\b", full_text, re.IGNORECASE)
            if m_tier:
                tier = m_tier.group(1)

        return {
            "user_id": user_id,
            "username": username,
            "pet_name": pet_name,
            "variant": variant,
            "rarity": rarity,
            "tier": tier,
            "egg_name": egg_name,
            "odds": odds,
            "image_url": embed_thumb,
        }

    async def ingest_discord_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        parsed = self.parse_discord_payload(payload)
        if not parsed:
            return {"status": "ignored", "reason": "Could not parse pet hatch from webhook payload"}

        user_id = parsed.get("user_id")
        username = parsed.get("username")

        # Resolve username via RobloxPoller if user_id missing
        if user_id is None and username:
            # First check existing local accounts by username
            for acc in self.db.get_accounts():
                if (acc.get("username") or "").lower() == username.lower():
                    user_id = acc["user_id"]
                    username = acc["username"]
                    break
            if user_id is None and self.poller is not None:
                resolved = await self.poller.get_user_by_username(username)
                if resolved and resolved.get("id"):
                    user_id = int(resolved["id"])
                    username = resolved.get("name", username)
                    avatar = await self.poller.get_user_avatar(user_id)
                    self.db.upsert_account(user_id, username, resolved.get("displayName", username), avatar)
        elif user_id is not None and not self.db.get_account(user_id):
            self.db.upsert_account(user_id, username or f"Player_{user_id}", username or f"Player_{user_id}", "")

        self.pet_catalog.register_discovered_pet(
            parsed["pet_name"],
            rarity=parsed["rarity"],
            tier=parsed.get("tier"),
            egg_source=parsed.get("egg_name"),
            odds=parsed.get("odds"),
        )
        img_url = self.pet_catalog.resolve_image_url(parsed["pet_name"], explicit_url=parsed.get("image_url"))
        now = time.time()

        recorded = self.db.record_hatch_event(
            {
                "user_id": user_id,
                "actor_name": username or (f"Player_{user_id}" if user_id is not None else "Webhook"),
                "pet_name": parsed["pet_name"],
                "rarity": parsed["rarity"],
                "variant": parsed["variant"],
                "tier": parsed.get("tier"),
                "egg_name": parsed.get("egg_name"),
                "odds": parsed.get("odds"),
                "image_url": img_url,
                "source": "webhook",
                "timestamp": now,
            },
            dedup_window_sec=15.0,
        )

        if recorded is None:
            return {"status": "duplicate", "parsed": parsed}

        # Only mutate account_secrets if user resolved AND no recent authoritative Luau sync within 60s
        if (
            user_id is not None
            and (parsed["rarity"] or "").lower() == "secret"
            and not self.session_manager.has_recent_authoritative_secret_sync(user_id, within_sec=60.0, now=now)
        ):
            self.db.increment_account_secret(
                user_id=user_id,
                name=parsed["pet_name"],
                variant=parsed["variant"],
                tier=parsed.get("tier"),
                egg_source=parsed.get("egg_name"),
                image_url=parsed.get("image_url"),
                updated_at=now,
            )

        # Optional forwarding of raw Discord payload
        cfg = self.get_raw_settings()
        if cfg.enabled and cfg.forwardInboundWebhook and cfg.webhookUrl:
            await self._post_discord(cfg.webhookUrl, payload)

        recorded["image_url"] = img_url
        return {"status": "recorded", "event": recorded}
