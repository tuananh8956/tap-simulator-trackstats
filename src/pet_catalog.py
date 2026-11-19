import hashlib
import html
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.database import Database
from src.models import slugify_pet_name, sanitize_image_url, extract_asset_id


SEEDED_SECRETS: List[Dict[str, str]] = [
    # Secret I (~1 in 500K)
    {"name": "Void Wraith", "tier": "Secret I", "default_egg": "Void Egg", "odds": "1 in 500K"},
    {"name": "Cinder Eye", "tier": "Secret I", "default_egg": "Draconic Egg", "odds": "1 in 500K"},
    {"name": "Inferno Dragon", "tier": "Secret I", "default_egg": "Volcanic Egg", "odds": "1 in 500K"},
    {"name": "Autumn Warden", "tier": "Secret I", "default_egg": "Pumpkin Egg", "odds": "1 in 500K"},
    {"name": "Oasis Spirit", "tier": "Secret I", "default_egg": "Cactus Egg", "odds": "1 in 500K"},
    # Secret II (~1 in 1M - 2M)
    {"name": "Void Overseer", "tier": "Secret II", "default_egg": "Void Egg", "odds": "1 in 1M"},
    {"name": "Shinigami", "tier": "Secret II", "default_egg": "Void Egg", "odds": "1 in 2M"},
    {"name": "Helfire Spirit", "tier": "Secret II", "default_egg": "Volcanic Egg", "odds": "1 in 2M"},
    {"name": "Infernal Lord", "tier": "Secret II", "default_egg": "Draconic Egg", "odds": "1 in 2M"},
    {"name": "Chronos", "tier": "Secret II", "default_egg": "Chronos Egg", "odds": "1 in 2M"},
    # Secret III & High-Tier / Event Secrets (~1 in 4M+)
    {"name": "Forsaken Knight", "tier": "Secret III", "default_egg": "Void Egg", "odds": "1 in 4M"},
    {"name": "Dragon Tamer", "tier": "Secret III", "default_egg": "Draconic Egg", "odds": "1 in 4M"},
    {"name": "King Of Hell", "tier": "Secret III", "default_egg": "Volcanic Egg", "odds": "1 in 5M"},
    {"name": "Malevolent Treat", "tier": "Event", "default_egg": "Pumpkin Egg", "odds": "1 in 5M"},
    {"name": "Sanguine Heart", "tier": "Secret III", "default_egg": "Crimson Egg", "odds": "1 in 8M"},
    {"name": "Peace Keeper", "tier": "Secret III", "default_egg": "Celestial Egg", "odds": "1 in 8M"},
    {"name": "Time Paradox", "tier": "Secret III", "default_egg": "Chronos Egg", "odds": "1 in 10M"},
    {"name": "Dark Cat", "tier": "Secret III", "default_egg": "Void Egg", "odds": "1 in 10M"},
]

_DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "assets" / "pets"

_PALETTES = [
    ("#a855f7", "#ec4899", "#1e1035"),
    ("#00f2fe", "#3b82f6", "#091b34"),
    ("#f97316", "#ef4444", "#2b100c"),
    ("#fbbf24", "#f59e0b", "#2a1e08"),
    ("#10b981", "#06b6d4", "#082420"),
    ("#f43f5e", "#a855f7", "#2b0c22"),
]


class PetCatalogService:
    def __init__(self, db: Database, assets_dir: Optional[Path] = None):
        self.db = db
        self.assets_dir = Path(assets_dir) if assets_dir else _DEFAULT_ASSETS_DIR

    def seed_defaults(self) -> int:
        count = 0
        for item in SEEDED_SECRETS:
            slug = slugify_pet_name(item["name"])
            self.db.upsert_pet_catalog(
                slug=slug,
                name=item["name"],
                rarity="Secret",
                tier=item.get("tier"),
                default_egg=item.get("default_egg"),
                odds=item.get("odds"),
            )
            count += 1
        return count

    def resolve_image_url(
        self,
        name: str,
        explicit_url: Optional[str] = None,
        asset_id: Optional[int] = None,
    ) -> str:
        slug = slugify_pet_name(name)
        item = self.db.get_pet_catalog_item(slug)

        # 1. User custom override
        if item:
            custom = sanitize_image_url(item.get("custom_image_url"))
            if custom:
                return custom

        # 2. Safe explicit telemetry URL
        safe_explicit = sanitize_image_url(explicit_url)
        if safe_explicit:
            return safe_explicit

        # 3. Resolved Roblox asset thumbnail cached in catalog
        if item:
            resolved = sanitize_image_url(item.get("resolved_image_url"))
            if resolved:
                return resolved

        # 4. Curated local SVG file
        local_svg = self.assets_dir / f"{slug}.svg"
        if local_svg.exists():
            return f"/static/assets/pets/{slug}.svg"

        # 5. Dynamic procedural SVG fallback
        return f"/api/v1/pets/icon/{slug}.svg"

    def register_discovered_pet(
        self,
        name: str,
        rarity: str = "Secret",
        tier: Optional[str] = None,
        egg_source: Optional[str] = None,
        odds: Optional[str] = None,
        image_asset_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        slug = slugify_pet_name(name)
        return self.db.upsert_pet_catalog(
            slug=slug,
            name=(name or "Unknown Secret").strip() or "Unknown Secret",
            rarity=rarity or "Secret",
            tier=tier,
            default_egg=egg_source,
            odds=odds,
            image_asset_id=extract_asset_id(image_asset_id),
        )

    def set_resolved_thumbnail(self, slug: str, asset_id: int, thumbnail_url: str) -> None:
        clean_slug = slugify_pet_name(slug)
        safe_url = sanitize_image_url(thumbnail_url)
        if not safe_url:
            return
        existing = self.db.get_pet_catalog_item(clean_slug)
        name = existing["name"] if existing else clean_slug.replace("-", " ").title()
        self.db.upsert_pet_catalog(
            slug=clean_slug,
            name=name,
            image_asset_id=extract_asset_id(asset_id),
            resolved_image_url=safe_url,
        )

    def set_custom_image(
        self,
        slug: str,
        image_url: Optional[str] = None,
        image_asset_id: Optional[int] = None,
        tier: Optional[str] = None,
        default_egg: Optional[str] = None,
        odds: Optional[str] = None,
    ) -> Dict[str, Any]:
        clean_slug = slugify_pet_name(slug)
        existing = self.db.get_pet_catalog_item(clean_slug)
        name = existing["name"] if existing else clean_slug.replace("-", " ").title()
        safe_url = sanitize_image_url(image_url) if image_url is not None else None
        clean_asset = extract_asset_id(image_asset_id)

        updated = self.db.upsert_pet_catalog(
            slug=clean_slug,
            name=name,
            tier=tier,
            default_egg=default_egg,
            odds=odds,
            image_asset_id=clean_asset,
            custom_image_url=safe_url,
            overwrite_custom=(image_url is not None),
        )
        updated["image_url"] = self.resolve_image_url(updated["name"])
        return updated

    def list_catalog(self) -> List[Dict[str, Any]]:
        rows = self.db.get_pet_catalog()
        for r in rows:
            r["image_url"] = self.resolve_image_url(r["name"])
        return rows

    def render_procedural_svg(
        self,
        slug: str,
        name: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> str:
        clean_slug = slugify_pet_name(slug or name or "secret-pet")
        digest = hashlib.sha256(clean_slug.encode("utf-8")).digest()
        c1, c2, bg = _PALETTES[digest[0] % len(_PALETTES)]
        words = [w for w in clean_slug.split("-") if w]
        initials = "".join(w[0].upper() for w in words[:2]) or "SP"
        safe_initials = html.escape(initials)
        safe_tier = html.escape((tier or "SECRET").upper()[:12])

        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">'
            f"<defs>"
            f'<radialGradient id="bg" cx="50%" cy="42%" r="62%">'
            f'<stop offset="0%" stop-color="{c1}" stop-opacity="0.35"/>'
            f'<stop offset="100%" stop-color="{bg}" stop-opacity="1"/>'
            f"</radialGradient>"
            f'<linearGradient id="body" x1="0%" y1="0%" x2="100%" y2="100%">'
            f'<stop offset="0%" stop-color="{c1}"/>'
            f'<stop offset="100%" stop-color="{c2}"/>'
            f"</linearGradient>"
            f"</defs>"
            f'<rect width="128" height="128" rx="22" fill="url(#bg)"/>'
            f'<circle cx="64" cy="60" r="42" fill="none" stroke="url(#body)" stroke-width="2" stroke-dasharray="6 4" opacity="0.55"/>'
            f'<path d="M36 52 L44 26 L56 42 L72 42 L84 26 L92 52 Q96 86 64 94 Q32 86 36 52 Z" fill="url(#body)" opacity="0.92"/>'
            f'<rect x="44" y="48" width="40" height="32" rx="12" fill="#090d1a" opacity="0.5"/>'
            f'<circle cx="53" cy="62" r="5" fill="#ffffff"/>'
            f'<circle cx="75" cy="62" r="5" fill="#ffffff"/>'
            f'<circle cx="54" cy="62" r="2.2" fill="{c1}"/>'
            f'<circle cx="76" cy="62" r="2.2" fill="{c2}"/>'
            f'<text x="64" y="84" text-anchor="middle" font-family="Segoe UI,sans-serif" font-size="13" font-weight="800" fill="#ffffff" opacity="0.9">{safe_initials}</text>'
            f'<text x="64" y="114" text-anchor="middle" font-family="Segoe UI,sans-serif" font-size="10" font-weight="700" letter-spacing="1.2" fill="{c1}">{safe_tier}</text>'
            f"</svg>"
        )
