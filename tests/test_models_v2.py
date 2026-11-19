from src.models import (
    TelemetryPayload,
    PetItem,
    BoostItem,
    HatchEventInput,
    AlertSettings,
    AlertSettingsUpdate,
    CatalogImageOverrideRequest,
    InspectorReportInput,
    slugify_pet_name,
    normalize_variant,
    sanitize_image_url,
    extract_asset_id,
)


def test_slugify_and_variant_normalization():
    assert slugify_pet_name("Void Overseer") == "void-overseer"
    assert slugify_pet_name("  King Of Hell!! ") == "king-of-hell"
    assert normalize_variant("rainbow") == "Rainbow"
    assert normalize_variant("GOLDEN") == "Golden"
    assert normalize_variant("diamond") == "Diamond"
    assert normalize_variant("shiny") == "Shiny"
    assert normalize_variant("shiny rainbow") == "Rainbow Shiny"
    assert normalize_variant("golden shiny") == "Golden Shiny"
    assert normalize_variant("  ") == "Normal"
    assert normalize_variant(None) == "Normal"


def test_sanitize_image_url_rejects_unsafe_schemes():
    assert sanitize_image_url("https://tr.rbxcdn.com/pet.png") == "https://tr.rbxcdn.com/pet.png"
    assert sanitize_image_url("http://127.0.0.1:3883/static/a.png") == "http://127.0.0.1:3883/static/a.png"
    assert sanitize_image_url("/static/assets/pets/dark-cat.svg") == "/static/assets/pets/dark-cat.svg"
    assert sanitize_image_url("/api/v1/pets/icon/dark-cat.svg") == "/api/v1/pets/icon/dark-cat.svg"
    assert sanitize_image_url("javascript:alert(1)") is None
    assert sanitize_image_url("JAVASCRIPT:alert(1)") is None
    assert sanitize_image_url("data:text/html,<script>alert(1)</script>") is None
    assert sanitize_image_url("vbscript:msgbox(1)") is None
    assert sanitize_image_url("  ") is None
    assert sanitize_image_url(None) is None


def test_extract_asset_id_formats():
    assert extract_asset_id(123456789) == 123456789
    assert extract_asset_id("123456789") == 123456789
    assert extract_asset_id("rbxassetid://987654321") == 987654321
    assert extract_asset_id("http://www.roblox.com/asset/?id=5551234") == 5551234
    assert extract_asset_id("rbxthumb://type=Asset&id=777888&w=150&h=150") == 777888
    assert extract_asset_id("not-an-id") is None
    assert extract_asset_id(-5) is None
    assert extract_asset_id(None) is None


def test_v2_telemetry_payload_backward_compat_and_defaults():
    v1 = TelemetryPayload(userId=42, currentTaps=100, totalTaps=500)
    assert v1.secretPets is None
    assert v1.secretCount is None
    assert v1.eggsHatched == 0
    assert v1.world is None
    assert v1.activeBoosts == []
    assert v1.recentHatches == []
    assert v1.clientSource == "telemetry"

    v2 = TelemetryPayload(
        userId=42,
        secretPets=[
            PetItem(
                name="Dark Cat",
                rarity="Secret",
                variant="rainbow",
                tier="Secret III",
                count=2,
                imageAssetId="rbxassetid://12345",
                imageUrl="javascript:alert(1)",
            )
        ],
        eggsHatched=1500,
        world="Void Island",
        activeBoosts=[BoostItem(name="2x Luck", multiplier="2x", remainingSec=600)],
        recentHatches=[
            HatchEventInput(
                petName="Dark Cat",
                variant="rainbow",
                eggName="Void Egg",
                odds="1 in 4M",
                imageAssetId="rbxassetid://99999",
            )
        ],
        clientSource="luau",
    )
    assert v2.secretPets[0].variant == "Rainbow"
    assert v2.secretPets[0].imageAssetId == 12345
    assert v2.secretPets[0].imageUrl is None
    assert v2.recentHatches[0].variant == "Rainbow"
    assert v2.recentHatches[0].imageAssetId == 99999

    settings = AlertSettings()
    assert settings.notifySecretHatch is True
    assert settings.notifyDisconnect is True
    assert settings.notifyStale is False

    upd = AlertSettingsUpdate(clearWebhook=True)
    assert upd.clearWebhook is True

    ov = CatalogImageOverrideRequest(imageUrl="javascript:evil()", imageAssetId="rbxassetid://777")
    assert ov.imageUrl is None
    assert ov.imageAssetId == 777

    ins = InspectorReportInput(userId=42, username="Test", structure={"leaderstats": ["Taps"]})
    assert ins.userId == 42
