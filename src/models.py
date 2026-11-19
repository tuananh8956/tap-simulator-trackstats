import re
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict, field_validator


_SAFE_IMAGE_PREFIXES = ("https://", "http://", "/static/", "/api/")
_ASSET_ID_PATTERNS = (
    re.compile(r"rbxassetid://(\d+)", re.IGNORECASE),
    re.compile(r"[?&]id=(\d+)", re.IGNORECASE),
    re.compile(r"^(\d+)$"),
)


def slugify_pet_name(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower())
    return text.strip("-") or "unknown-pet"


def normalize_variant(variant: Optional[str]) -> str:
    if not variant or not str(variant).strip():
        return "Normal"
    raw = str(variant).strip().lower()
    tokens = [t for t in re.split(r"[\s_\-/+]+", raw) if t]
    if not tokens:
        return "Normal"

    token_set = set(tokens)
    has_shiny = "shiny" in token_set
    base: Optional[str] = None
    if "rainbow" in token_set or "rb" in token_set:
        base = "Rainbow"
    elif "diamond" in token_set or "dia" in token_set:
        base = "Diamond"
    elif "golden" in token_set or "gold" in token_set:
        base = "Golden"
    elif "normal" in token_set or "default" in token_set or "basic" in token_set:
        base = "Normal"

    if base and base != "Normal" and has_shiny:
        return f"{base} Shiny"
    if has_shiny and (not base or base == "Normal"):
        return "Shiny"
    if base:
        return base
    return " ".join(w.capitalize() for w in tokens)


def sanitize_image_url(url: Optional[str]) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    cleaned = url.strip()
    if not cleaned:
        return None
    if any(ch in cleaned for ch in ("\r", "\n", "\t", " ", "\"", "'", "<", ">")):
        return None
    lower = cleaned.lower()
    if not any(lower.startswith(prefix) for prefix in _SAFE_IMAGE_PREFIXES):
        return None
    return cleaned


def extract_asset_id(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw > 0 else None
    text = str(raw).strip()
    if not text:
        return None
    for pat in _ASSET_ID_PATTERNS:
        m = pat.search(text)
        if m:
            val = int(m.group(1))
            return val if val > 0 else None
    return None


class PetItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = "pet_default"
    name: str = "Unknown Pet"
    rarity: str = "Common"
    multiplier: float = 1.0
    power: float = 0.0
    variant: str = "Normal"
    tier: Optional[str] = None
    count: int = 1
    isEquipped: bool = False
    isLocked: bool = False
    eggSource: Optional[str] = None
    imageAssetId: Optional[int] = None
    imageUrl: Optional[str] = None

    @field_validator("variant", mode="before")
    @classmethod
    def _clean_variant(cls, v: Any) -> str:
        return normalize_variant(v)

    @field_validator("count", mode="before")
    @classmethod
    def _clean_count(cls, v: Any) -> int:
        try:
            n = int(v)
            return max(1, n)
        except Exception:
            return 1

    @field_validator("imageAssetId", mode="before")
    @classmethod
    def _clean_asset_id(cls, v: Any) -> Optional[int]:
        return extract_asset_id(v)

    @field_validator("imageUrl", mode="before")
    @classmethod
    def _clean_image_url(cls, v: Any) -> Optional[str]:
        return sanitize_image_url(v)


class BoostItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    multiplier: Optional[str] = None
    remainingSec: float = 0.0


class HatchEventInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    eventId: Optional[str] = None
    petName: str
    rarity: str = "Secret"
    variant: str = "Normal"
    tier: Optional[str] = None
    eggName: Optional[str] = None
    odds: Optional[str] = None
    imageAssetId: Optional[int] = None
    imageUrl: Optional[str] = None
    timestamp: Optional[float] = None

    @field_validator("variant", mode="before")
    @classmethod
    def _clean_variant(cls, v: Any) -> str:
        return normalize_variant(v)

    @field_validator("imageAssetId", mode="before")
    @classmethod
    def _clean_asset_id(cls, v: Any) -> Optional[int]:
        return extract_asset_id(v)

    @field_validator("imageUrl", mode="before")
    @classmethod
    def _clean_image_url(cls, v: Any) -> Optional[str]:
        return sanitize_image_url(v)


class TelemetryPayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    userId: int = Field(..., alias="userId")
    currentTaps: int = Field(default=0, alias="currentTaps")
    totalTaps: int = Field(default=0, alias="totalTaps")
    currentRebirths: int = Field(default=0, alias="currentRebirths")
    totalRebirths: int = Field(default=0, alias="totalRebirths")
    currentWins: int = Field(default=0, alias="currentWins")
    totalWins: int = Field(default=0, alias="totalWins")
    currentCurrency: int = Field(default=0, alias="currentCurrency")
    equippedPets: List[PetItem] = Field(default_factory=list, alias="equippedPets")
    petInventoryCount: int = Field(default=0, alias="petInventoryCount")
    totalPetPower: float = Field(default=0.0, alias="totalPetPower")
    timestamp: float = Field(default_factory=lambda: time.time())

    # v2 optional fields (backward compatible)
    secretPets: Optional[List[PetItem]] = Field(default=None, alias="secretPets")
    secretCount: Optional[int] = Field(default=None, alias="secretCount")
    eggsHatched: int = Field(default=0, alias="eggsHatched")
    world: Optional[str] = Field(default=None, alias="world")
    activeBoosts: List[BoostItem] = Field(default_factory=list, alias="activeBoosts")
    recentHatches: List[HatchEventInput] = Field(default_factory=list, alias="recentHatches")
    clientSource: str = Field(default="telemetry", alias="clientSource")


class CatalogImageOverrideRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    imageUrl: Optional[str] = None
    imageAssetId: Optional[int] = None
    tier: Optional[str] = None
    defaultEgg: Optional[str] = None
    odds: Optional[str] = None

    @field_validator("imageUrl", mode="before")
    @classmethod
    def _clean_image_url(cls, v: Any) -> Optional[str]:
        return sanitize_image_url(v)

    @field_validator("imageAssetId", mode="before")
    @classmethod
    def _clean_asset_id(cls, v: Any) -> Optional[int]:
        return extract_asset_id(v)


class AlertSettings(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    webhookUrl: str = ""
    enabled: bool = False
    notifySecretHatch: bool = True
    notifyDisconnect: bool = True
    notifyStale: bool = False
    forwardInboundWebhook: bool = False


class AlertSettingsUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    webhookUrl: Optional[str] = None
    enabled: Optional[bool] = None
    notifySecretHatch: Optional[bool] = None
    notifyDisconnect: Optional[bool] = None
    notifyStale: Optional[bool] = None
    forwardInboundWebhook: Optional[bool] = None
    clearWebhook: bool = False


class InspectorReportInput(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    userId: int
    username: Optional[str] = None
    placeId: Optional[int] = None
    structure: Dict[str, Any] = Field(default_factory=dict)


class AccountInfo(BaseModel):
    user_id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    is_tracking: bool = True
    created_at: Optional[str] = None
    last_seen: Optional[str] = None


class SessionSummary(BaseModel):
    session_id: str
    user_id: int
    start_time: float
    end_time: Optional[float] = None
    initial_taps: int = 0
    final_taps: int = 0
    taps_gained: int = 0
    initial_rebirths: int = 0
    final_rebirths: int = 0
    rebirths_gained: int = 0
    max_tps: float = 0.0
    avg_tps: float = 0.0
