from pathlib import Path
from src.database import Database
from src.pet_catalog import PetCatalogService, SEEDED_SECRETS


def test_seed_defaults_and_real_ingame_images_exist(tmp_path):
    db = Database(str(tmp_path / "cat.db"))
    db.init_db()
    svc = PetCatalogService(db)
    count = svc.seed_defaults()
    assert count >= 66
    assert len(SEEDED_SECRETS) >= 18

    repo_root = Path(__file__).resolve().parent.parent
    # Verify key real in-game Secret pets resolve to genuine local raster renders (.png/.webp/.jpg)
    for pet_name in [
        "Dark Cat",
        "Sanguine Heart",
        "Forsaken Knight",
        "Chronos",
        "Void Wraith",
        "Void Overseer",
        "Shinigami",
        "King Of Hell",
        "Malevolent Treat",
        "Dragon Tamer",
        "Oasis Spirit",
        "Oaisis Spirit",
        "Operating System OBLITERATED",
        "30M Candycorn Dragon",
        "Peace Keeper",
    ]:
        url = svc.resolve_image_url(pet_name)
        assert url.startswith("/static/assets/pets/"), f"Unexpected URL for {pet_name}: {url}"
        assert url.endswith((".png", ".webp", ".jpg", ".jpeg")), f"Expected real in-game raster image for {pet_name}, got {url}"
        img_path = repo_root / "src/static/assets/pets" / url.split("/")[-1]
        assert img_path.exists() and img_path.stat().st_size > 500, f"Missing or empty image: {img_path}"


def test_image_resolution_5_step_precedence(tmp_path):
    db = Database(str(tmp_path / "prec.db"))
    db.init_db()
    svc = PetCatalogService(db)
    svc.seed_defaults()

    # Step 5: unknown pet falls back to procedural endpoint
    assert svc.resolve_image_url("Cosmic Leviathan") == "/api/v1/pets/icon/cosmic-leviathan.svg"
    # Step 4a: real in-game PNG render takes precedence over SVG fallback
    assert svc.resolve_image_url("Dark Cat") == "/static/assets/pets/dark-cat.png"
    # Step 4b: SVG-only seeded pet still resolves cleanly to SVG
    assert svc.resolve_image_url("Time Paradox") == "/static/assets/pets/time-paradox.svg"
    # Step 3: Roblox resolved asset thumbnail beats local render
    svc.set_resolved_thumbnail("dark-cat", 123456, "https://tr.rbxcdn.com/darkcat.png")
    assert svc.resolve_image_url("Dark Cat") == "https://tr.rbxcdn.com/darkcat.png"
    # Step 2: safe explicit telemetry URL beats resolved thumbnail; unsafe rejected
    assert (
        svc.resolve_image_url("Dark Cat", explicit_url="https://cdn.example/live.png")
        == "https://cdn.example/live.png"
    )
    assert (
        svc.resolve_image_url("Dark Cat", explicit_url="javascript:alert(1)")
        == "https://tr.rbxcdn.com/darkcat.png"
    )
    # Step 1: user custom_image_url override beats everything
    svc.set_custom_image("dark-cat", image_url="https://cdn.example/custom-darkcat.png")
    assert (
        svc.resolve_image_url("Dark Cat", explicit_url="https://cdn.example/live.png")
        == "https://cdn.example/custom-darkcat.png"
    )


def test_procedural_svg_escapes_html(tmp_path):
    db = Database(str(tmp_path / "svg.db"))
    db.init_db()
    svc = PetCatalogService(db)
    svg = svc.render_procedural_svg("evil-pet", name="<script>alert(1)</script>", tier="Secret III")
    assert svg.startswith("<svg")
    assert "<script>" not in svg
    assert "&lt;script&gt;" not in svg or "EV" in svg
