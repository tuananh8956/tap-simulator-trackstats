#!/usr/bin/env python3
"""
Fetches real in-game Secret pet renders for Tap Simulator Reborn from
public community catalog pages (tapsimreborn.com) and caches optimized
256px local images into src/static/assets/pets/ plus catalog_manifest.json.
"""
import html
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Dict, Any, List, Optional
import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.models import slugify_pet_name

ASSETS_DIR = REPO_ROOT / "src" / "static" / "assets" / "pets"
MANIFEST_PATH = ASSETS_DIR / "catalog_manifest.json"
BASE_SITE = "https://tapsimreborn.com"

# Known typos / spelling aliases normalized cleanly
NAME_FIXUPS = {
    "Oaisis Spirit": "Oasis Spirit",
    "Blue Briar Palidin": "Blue Briar Paladin",
    "Nameless Diety": "Nameless Deity",
    "King of Hell": "King Of Hell",
}

KNOWN_EGG_ODDS = {
    "void-wraith": ("Void Egg", "1 in 500K", "Secret I"),
    "cinder-eye": ("Draconic Egg", "1 in 500K", "Secret I"),
    "inferno-dragon": ("Volcanic Egg", "1 in 500K", "Secret I"),
    "autumn-warden": ("Pumpkin Egg", "1 in 500K", "Secret I"),
    "oasis-spirit": ("Cactus Egg", "1 in 500K", "Secret I"),
    "void-overseer": ("Void Egg", "1 in 1M", "Secret II"),
    "shinigami": ("Void Egg", "1 in 2M", "Secret II"),
    "helfire-spirit": ("Volcanic Egg", "1 in 2M", "Secret II"),
    "infernal-lord": ("Draconic Egg", "1 in 2M", "Secret II"),
    "chronos": ("Chronos Egg", "1 in 2M", "Secret II"),
    "forsaken-knight": ("Void Egg", "1 in 4M", "Secret III"),
    "dragon-tamer": ("Draconic Egg", "1 in 4M", "Secret III"),
    "king-of-hell": ("Volcanic Egg", "1 in 5M", "Secret III"),
    "malevolent-treat": ("Pumpkin Egg", "1 in 5M", "Event"),
    "sanguine-heart": ("Crimson Egg", "1 in 8M", "Secret III"),
    "peace-keeper": ("Celestial Egg", "1 in 8M", "Secret III"),
    "dark-cat": ("Void Egg", "1 in 10M", "Secret III"),
}


def _ext_for_content_type(ct: str, media_path: str) -> str:
    low = (ct or "").lower()
    if "png" in low:
        return ".png"
    if "webp" in low:
        return ".webp"
    if "jpeg" in low or "jpg" in low:
        return ".jpg"
    ext = Path(media_path).suffix.lower()
    return ext if ext in (".png", ".webp", ".jpg", ".jpeg") else ".png"


def fetch_all_secret_pet_images() -> List[Dict[str, Any]]:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "TapSimulatorTrackStats/2.0 (Pet Image Sync)"}
    pets_by_slug: Dict[str, Dict[str, Any]] = {}

    with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
        # 1. Parse /values (60 featured Secret/Value pets)
        r_vals = client.get(f"{BASE_SITE}/values")
        r_vals.raise_for_status()
        cards = re.findall(r'<a[^>]*href="(/[^"]+)"[^>]*>(.*?)</a>', r_vals.text, re.S)
        for href, body in cards:
            img_m = re.search(r'<img[^>]*alt="([^"]+)"[^>]*src="([^"]+)"', body)
            if not img_m:
                continue
            raw_name = html.unescape(img_m.group(1)).strip()
            name = NAME_FIXUPS.get(raw_name, raw_name)
            src_u = html.unescape(img_m.group(2))
            um = re.search(r"url=([^&]+)", src_u)
            media = urllib.parse.unquote(um.group(1)) if um else src_u
            if not media.startswith("/media/"):
                continue

            visible_text = re.sub(r"<[^>]+>", " ", body)
            tier_m = re.search(r"\b(Secret\s+III|Secret\s+II|Secret\s+I|Limited|Leaderboard|Event)\b", visible_text)
            tier = tier_m.group(1) if tier_m else "Secret"
            slug = slugify_pet_name(name)
            source_slug = href.lstrip("/")
            pets_by_slug[slug] = {
                "slug": slug,
                "source_slug": source_slug,
                "name": name,
                "tier": tier,
                "media": media,
            }

        # 2. Check sitemap.xml for any additional Secret pet pages not on page 1
        r_sm = client.get(f"{BASE_SITE}/sitemap.xml")
        if r_sm.status_code == 200:
            locs = re.findall(r"<loc>([^<]+)</loc>", r_sm.text)
            known_source_slugs = {p["source_slug"] for p in pets_by_slug.values()}
            extra_slugs = [
                u.split("/")[-1]
                for u in locs
                if u.count("/") == 3
                and u.split("/")[-1] not in ("values", "wiki", "")
                and u.split("/")[-1] not in known_source_slugs
            ]
            for src_slug in extra_slugs:
                try:
                    rp = client.get(f"{BASE_SITE}/{src_slug}")
                    if rp.status_code != 200:
                        continue
                    img_m = re.search(r'<img[^>]*alt="([^"]+)"[^>]*src="([^"]+)"', rp.text)
                    if not img_m:
                        continue
                    raw_alt = html.unescape(img_m.group(1)).strip()
                    raw_name = raw_alt.split("·")[0].strip()
                    name = NAME_FIXUPS.get(raw_name, raw_name)
                    src_u = html.unescape(img_m.group(2))
                    um = re.search(r"url=([^&]+)", src_u)
                    media = urllib.parse.unquote(um.group(1)) if um else src_u
                    if not media.startswith("/media/"):
                        continue
                    visible_text = re.sub(r"<[^>]+>", " ", rp.text)
                    tier_m = re.search(r"\b(Secret\s+III|Secret\s+II|Secret\s+I|Limited|Leaderboard|Event)\b", visible_text)
                    tier = tier_m.group(1) if tier_m else "Secret"
                    slug = slugify_pet_name(name)
                    if slug not in pets_by_slug:
                        pets_by_slug[slug] = {
                            "slug": slug,
                            "source_slug": src_slug,
                            "name": name,
                            "tier": tier,
                            "media": media,
                        }
                except Exception as exc:
                    print(f"[warn] Skipped {src_slug}: {exc}")

        # 3. Download optimized 256px renders locally
        manifest: List[Dict[str, Any]] = []
        for slug, info in sorted(pets_by_slug.items()):
            media = info["media"]
            img_url = f"{BASE_SITE}/_next/image?url={urllib.parse.quote(media, safe='')}&w=256&q=75"
            try:
                ri = client.get(img_url)
                if ri.status_code != 200 or len(ri.content) < 500:
                    ri = client.get(f"{BASE_SITE}{media}")
                if ri.status_code != 200 or len(ri.content) < 500:
                    print(f"[fail] {slug}: HTTP {ri.status_code}")
                    continue

                ext = _ext_for_content_type(ri.headers.get("content-type", ""), media)
                filename = f"{slug}{ext}"
                out_path = ASSETS_DIR / filename
                out_path.write_bytes(ri.content)

                egg, odds, override_tier = KNOWN_EGG_ODDS.get(slug, ("Secret Pool", "Rare", None))
                tier = info["tier"] if info["tier"] != "Secret" else (override_tier or "Secret")
                manifest.append(
                    {
                        "slug": slug,
                        "name": info["name"],
                        "tier": tier,
                        "default_egg": egg,
                        "odds": odds,
                        "filename": filename,
                        "aliases": [info["source_slug"]] if info["source_slug"] != slug else [],
                    }
                )
            except Exception as exc:
                print(f"[error] {slug}: {exc}")

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[done] Downloaded {len(manifest)} real in-game Secret pet renders -> {ASSETS_DIR}")
    return manifest


if __name__ == "__main__":
    fetch_all_secret_pet_images()
