import hashlib
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.database import Database
from src.models import is_bogus_secret_name, slugify_pet_name, sanitize_image_url, extract_asset_id


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
    {"name": "Malevolent Treat", "tier": "Secret III", "default_egg": "Pumpkin Egg", "odds": "1 in 5M"},
    {"name": "Sanguine Heart", "tier": "Secret III", "default_egg": "Crimson Egg", "odds": "1 in 8M"},
    {"name": "Peace Keeper", "tier": "Secret III", "default_egg": "Celestial Egg", "odds": "1 in 8M"},
    {"name": "Time Paradox", "tier": "Secret III", "default_egg": "Chronos Egg", "odds": "1 in 10M"},
    {"name": "Dark Cat", "tier": "Secret III", "default_egg": "Void Egg", "odds": "1 in 10M"},
]

SLUG_ALIASES: Dict[str, str] = {
    "oaisis-spirit": "oasis-spirit",
    "chronus": "chronos",
    "blue-briar-palidin": "blue-briar-paladin",
    "nameless-diety": "nameless-deity",
    "imperfection": "30m-imperfection",
}

_DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent / "static" / "assets" / "pets"
_RASTER_EXTS = (".png", ".webp", ".jpg", ".jpeg")

_PALETTES = [
    ("#a855f7", "#ec4899", "#1e1035"),
    ("#00f2fe", "#3b82f6", "#091b34"),
    ("#f97316", "#ef4444", "#2b100c"),
    ("#fbbf24", "#f59e0b", "#2a1e08"),
    ("#10b981", "#06b6d4", "#082420"),
    ("#f43f5e", "#a855f7", "#2b0c22"),
]


class PetCatalogService:
    _STRIP_PREFIXES = (
        "golden-shiny-",
        "rainbow-shiny-",
        "diamond-shiny-",
        "golden-",
        "gold-",
        "rainbow-",
        "diamond-",
        "shiny-",
        "normal-",
        "secret-iii-",
        "secret-ii-",
        "secret-i-",
        "secret-",
        "mythic-",
    )

    def __init__(self, db: Database, assets_dir: Optional[Path] = None):
        self.db = db
        self.assets_dir = Path(assets_dir) if assets_dir else _DEFAULT_ASSETS_DIR
        self._aliases: Dict[str, str] = dict(SLUG_ALIASES)
        self._compact_to_slug: Dict[str, str] = {}
        self._slug_to_name: Dict[str, str] = {}
        self._manifest_entries: List[Dict[str, Any]] = self._load_manifest()
        self._index_known_slugs()

    def _register_slug_index(self, slug: str, name: Optional[str] = None) -> None:
        if not slug:
            return
        compact = slug.replace("-", "")
        if compact:
            self._compact_to_slug[compact] = slug
        if name:
            self._slug_to_name[slug] = name

    def _index_known_slugs(self) -> None:
        for entry in self._manifest_entries:
            c_slug = slugify_pet_name(entry.get("slug") or entry.get("name") or "")
            c_name = entry.get("name")
            self._register_slug_index(c_slug, c_name)
            for alias in entry.get("aliases", []) or []:
                a_slug = slugify_pet_name(alias)
                if a_slug and c_slug:
                    self._compact_to_slug[a_slug.replace("-", "")] = c_slug
        for item in SEEDED_SECRETS:
            c_slug = slugify_pet_name(item["name"])
            self._register_slug_index(c_slug, item["name"])
        for alias_slug, target_slug in self._aliases.items():
            self._compact_to_slug[alias_slug.replace("-", "")] = target_slug

    def _load_manifest(self) -> List[Dict[str, Any]]:
        manifest_path = self.assets_dir / "catalog_manifest.json"
        if not manifest_path.exists():
            return []
        try:
            entries = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                return []
            for entry in entries:
                canonical = slugify_pet_name(entry.get("slug") or entry.get("name") or "")
                for alias in entry.get("aliases", []) or []:
                    a_slug = slugify_pet_name(alias)
                    if a_slug and canonical:
                        self._aliases[a_slug] = canonical
            return entries
        except Exception:
            return []

    def canonical_slug(self, name_or_slug: str) -> str:
        raw_slug = slugify_pet_name(name_or_slug)
        if raw_slug in self._aliases:
            return self._aliases[raw_slug]
        if raw_slug in self._slug_to_name:
            return raw_slug
        compact = raw_slug.replace("-", "")
        if compact in self._compact_to_slug:
            return self._compact_to_slug[compact]

        # Strip leading variant/rarity prefixes like "Golden Dark Cat" or "[Secret] Chronos"
        candidate = raw_slug
        changed = True
        while changed:
            changed = False
            for pref in self._STRIP_PREFIXES:
                if candidate.startswith(pref) and len(candidate) > len(pref):
                    candidate = candidate[len(pref):]
                    changed = True
                    break
        if candidate != raw_slug:
            if candidate in self._aliases:
                return self._aliases[candidate]
            if candidate in self._slug_to_name or self._find_local_asset_url(candidate):
                return candidate
            c_compact = candidate.replace("-", "")
            if c_compact in self._compact_to_slug:
                return self._compact_to_slug[c_compact]

        return self._aliases.get(raw_slug, raw_slug)

    def canonical_name(self, raw_name: str) -> str:
        slug = self.canonical_slug(raw_name)
        if slug in self._slug_to_name:
            return self._slug_to_name[slug]
        item = self.db.get_pet_catalog_item(slug)
        if item and item.get("name"):
            return item["name"]
        return (raw_name or "").strip()

    def seed_defaults(self) -> int:
        seeded: Dict[str, Dict[str, Any]] = {}

        # Load real in-game Secret catalog from catalog_manifest.json first
        for entry in self._manifest_entries:
            slug = self.canonical_slug(entry.get("slug") or entry.get("name") or "")
            if not slug:
                continue
            seeded[slug] = {
                "slug": slug,
                "name": entry["name"],
                "tier": entry.get("tier") or "Secret",
                "default_egg": entry.get("default_egg") or "Secret Pool",
                "odds": entry.get("odds") or "Rare",
            }

        # Ensure all core fallback SEEDED_SECRETS exist (preserving richer egg/odds metadata)
        for item in SEEDED_SECRETS:
            slug = self.canonical_slug(item["name"])
            if slug not in seeded:
                seeded[slug] = {
                    "slug": slug,
                    "name": item["name"],
                    "tier": item.get("tier"),
                    "default_egg": item.get("default_egg"),
                    "odds": item.get("odds"),
                }
            else:
                if seeded[slug].get("default_egg") == "Secret Pool" and item.get("default_egg"):
                    seeded[slug]["default_egg"] = item["default_egg"]
                if seeded[slug].get("odds") == "Rare" and item.get("odds"):
                    seeded[slug]["odds"] = item["odds"]

        count = 0
        for rec in seeded.values():
            self.db.upsert_pet_catalog(
                slug=rec["slug"],
                name=rec["name"],
                rarity="Secret",
                tier=rec.get("tier"),
                default_egg=rec.get("default_egg"),
                odds=rec.get("odds"),
            )
            count += 1
        return count

    def _find_local_asset_url(self, slug: str) -> Optional[str]:
        # Prefer real in-game raster renders (.png/.webp/.jpg) before curated .svg fallback
        for ext in _RASTER_EXTS:
            candidate = self.assets_dir / f"{slug}{ext}"
            if candidate.exists():
                return f"/static/assets/pets/{slug}{ext}"
        local_svg = self.assets_dir / f"{slug}.svg"
        if local_svg.exists():
            return f"/static/assets/pets/{slug}.svg"
        return None

    def resolve_image_url(
        self,
        name: str,
        explicit_url: Optional[str] = None,
        asset_id: Optional[int] = None,
    ) -> str:
        slug = self.canonical_slug(name)
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

        # 4. Real in-game local render (.png/.webp/.jpg) or curated local SVG
        local_url = self._find_local_asset_url(slug)
        if local_url:
            return local_url

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
        if is_bogus_secret_name(name):
            return {}
        slug = self.canonical_slug(name)
        canon_name = self.canonical_name(name)
        return self.db.upsert_pet_catalog(
            slug=slug,
            name=canon_name or "Secret Pet",
            rarity=rarity or "Secret",
            tier=tier,
            default_egg=egg_source,
            odds=odds,
            image_asset_id=extract_asset_id(image_asset_id),
        )

    def set_resolved_thumbnail(self, slug: str, asset_id: int, thumbnail_url: str) -> None:
        clean_slug = self.canonical_slug(slug)
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
        clean_slug = self.canonical_slug(slug)
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

    def list_catalog(self, rarity: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = self.db.get_pet_catalog()
        if rarity:
            target = rarity.strip().lower()
            rows = [r for r in rows if (r.get("rarity") or "").lower() == target]
        for r in rows:
            r["image_url"] = self.resolve_image_url(r["name"])
        return rows

    def render_procedural_svg(
        self,
        slug: str,
        name: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> str:
        clean_slug = self.canonical_slug(slug or name or "secret-pet")
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
