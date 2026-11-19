from pathlib import Path
from src.database import Database
from src.pet_catalog import PetCatalogService, SEEDED_SECRETS


def test_seed_defaults_and_18_svg_files_exist(tmp_path):
    db = Database(str(tmp_path / "cat.db"))
    db.init_db()
    svc = PetCatalogService(db)
    count = svc.seed_defaults()
    assert count == 18
    assert len(SEEDED_SECRETS) == 18

    repo_root = Path(__file__).resolve().parent.parent
    for item in SEEDED_SECRETS:
        url = svc.resolve_image_url(item["name"])
        assert url.startswith("/static/assets/pets/") and url.endswith(".svg")
        svg_path = repo_root / "src/static/assets/pets" / url.split("/")[-1]
        assert svg_path.exists(), f"Missing SVG asset: {svg_path}"
        content = svg_path.read_text(encoding="utf-8")
        assert "<svg" in content and "</svg>" in content


def test_image_resolution_5_step_precedence(tmp_path):
    db = Database(str(tmp_path / "prec.db"))
    db.init_db()
    svc = PetCatalogService(db)
    svc.seed_defaults()

    # Step 5: unknown pet falls back to procedural endpoint
    assert svc.resolve_image_url("Cosmic Leviathan") == "/api/v1/pets/icon/cosmic-leviathan.svg"
    # Step 4: seeded pet uses local curated SVG
    assert svc.resolve_image_url("Dark Cat") == "/static/assets/pets/dark-cat.svg"
    # Step 3: Roblox resolved asset thumbnail beats local SVG
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
