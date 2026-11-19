import asyncio
import hmac
import json
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

from fastapi import Depends, FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.auth import (
    ADMIN_COOKIE_NAME,
    constant_time_equals,
    create_admin_session_token,
    is_admin_request,
    require_admin,
    require_ingest_key,
    require_read_access,
    resolve_public_base_url,
)
from src.config import settings, BASE_DIR
from src.models import (
    TelemetryPayload,
    AlertSettingsUpdate,
    CatalogImageOverrideRequest,
    InspectorReportInput,
    slugify_pet_name,
)
from src.database import Database
from src.pet_catalog import PetCatalogService
from src.rate_engine import RateEngine
from src.roblox_poller import RobloxPoller
from src.session_manager import SessionManager
from src.webhook_service import WebhookService

# Initialize singletons
db = Database(settings.db_path)
db.init_db()
pet_catalog = PetCatalogService(db)
pet_catalog.seed_defaults()
rate_engine = RateEngine(max_window_sec=settings.rate_window_max_sec)
poller = RobloxPoller(debounce_sec=settings.poller_interval_sec)
session_manager = SessionManager(
    db=db,
    rate_engine=rate_engine,
    poller=poller,
    pet_catalog=pet_catalog,
    stale_timeout_sec=settings.stale_timeout_sec,
    disconnect_timeout_sec=settings.disconnect_timeout_sec,
)
webhook_service = WebhookService(
    db=db,
    session_manager=session_manager,
    pet_catalog=pet_catalog,
    poller=poller,
)

# Background task management & enrichment debounce caches
timeout_task: Optional[asyncio.Task] = None
_bg_tasks: Set[asyncio.Task] = set()
_profile_lookup_last: Dict[int, float] = {}
_asset_lookup_last: Dict[int, float] = {}


def _spawn_bg(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
    except RuntimeError:
        coro.close()


async def _enrich_profile_bg(user_id: int) -> None:
    now = time.time()
    if now - _profile_lookup_last.get(user_id, 0.0) < 60.0:
        return
    _profile_lookup_last[user_id] = now
    try:
        user_info = await poller.get_user_info(user_id)
        avatar_url = await poller.get_user_avatar(user_id)
        name = user_info.get("name")
        if name and name != f"Player_{user_id}":
            db.upsert_account(
                user_id=user_id,
                username=name,
                display_name=user_info.get("displayName", name),
                avatar_url=avatar_url,
            )
    except Exception:
        pass


async def _resolve_asset_bg(slug: str, asset_id: int) -> None:
    now = time.time()
    if now - _asset_lookup_last.get(asset_id, 0.0) < 60.0:
        return
    _asset_lookup_last[asset_id] = now
    try:
        thumb = await poller.get_asset_thumbnail(asset_id)
        if thumb:
            pet_catalog.set_resolved_thumbnail(slug, asset_id, thumb)
    except Exception:
        pass


async def timeout_monitor_loop():
    while True:
        try:
            events = session_manager.check_timeouts()
            for ev in events:
                if ev.get("event") in ("STALE", "DISCONNECTED"):
                    _spawn_bg(
                        webhook_service.send_status_alert(
                            user_id=ev["user_id"],
                            username=ev.get("username", f"Player_{ev['user_id']}"),
                            event=ev["event"],
                        )
                    )
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(2.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    pet_catalog.seed_defaults()
    global timeout_task
    timeout_task = asyncio.create_task(timeout_monitor_loop())
    yield
    if timeout_task:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass
    for t in list(_bg_tasks):
        t.cancel()


app = FastAPI(
    title="Tap Simulator Reborn - TrackStats API",
    version="2.0.0",
    description="Real-time Statistics Tracker, Secret Vault, and Telemetry Companion for Tap Simulator Reborn",
    lifespan=lifespan,
)


class AddAccountRequest(BaseModel):
    userId: int


class TrackingToggleRequest(BaseModel):
    is_tracking: bool


class AdminLoginRequest(BaseModel):
    password: str


# --- Health & Authentication endpoints ---


@app.get("/healthz")
async def healthcheck():
    return {"status": "ok", "version": "2.0.0"}


@app.get("/api/v1/auth/status")
async def get_auth_status(request: Request):
    admin_pw = (settings.admin_password or "").strip()
    ingest_key = (settings.ingest_key or "").strip()
    return {
        "auth_enabled": bool(admin_pw),
        "public_read": bool(settings.public_read),
        "is_admin": is_admin_request(request),
        "ingest_key_required": bool(ingest_key),
    }


@app.post("/api/v1/auth/login")
async def admin_login(req: AdminLoginRequest, request: Request, response: Response):
    admin_pw = (settings.admin_password or "").strip()
    if admin_pw and not constant_time_equals((req.password or "").strip(), admin_pw):
        raise HTTPException(status_code=401, detail="Invalid admin password")

    base_url = resolve_public_base_url(request)
    is_https = base_url.lower().startswith("https://")
    token = create_admin_session_token(admin_pw) if admin_pw else "local"
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=is_https,
        max_age=30 * 24 * 3600,
        path="/",
    )
    return {"ok": True, "is_admin": True}


@app.post("/api/v1/auth/logout")
async def admin_logout(response: Response):
    response.delete_cookie(key=ADMIN_COOKIE_NAME, path="/")
    return {"ok": True, "is_admin": False}


@app.get("/api/v1/connector/config", dependencies=[Depends(require_read_access)])
async def get_connector_config(request: Request):
    base_url = resolve_public_base_url(request)
    has_admin_pw = bool((settings.admin_password or "").strip())
    is_admin = is_admin_request(request) if has_admin_pw else False
    ingest_key = (settings.ingest_key or "").strip()
    can_reveal_key = bool(has_admin_pw and is_admin)
    return {
        "base_url": base_url,
        "telemetry_url": f"{base_url}/api/v1/telemetry",
        "inspect_url": f"{base_url}/api/v1/connector/inspect",
        "loader_url": f"{base_url}/loader.lua",
        "webhook_url": f"{base_url}/api/v1/webhook/discord",
        "ingest_key_required": bool(ingest_key),
        "is_admin": is_admin_request(request),
        "ingest_key": (ingest_key if can_reveal_key else None) if ingest_key else "",
    }


# --- Telemetry ingestion endpoint ---


@app.post("/api/v1/telemetry", dependencies=[Depends(require_ingest_key)])
async def ingest_telemetry(payload: TelemetryPayload, request: Request):
    result = session_manager.process_telemetry(payload)
    base_url = resolve_public_base_url(request)

    if result.get("needs_profile_lookup"):
        _spawn_bg(_enrich_profile_bg(payload.userId))

    for slug, asset_id in result.get("pending_asset_ids", []):
        _spawn_bg(_resolve_asset_bg(slug, asset_id))

    for hatch in result.get("new_hatches", []):
        if (hatch.get("rarity") or "").lower() == "secret":
            _spawn_bg(webhook_service.send_secret_hatch_alert(hatch, base_url=base_url))

    return {
        "status": result["status"],
        "user_id": result["user_id"],
        "session_id": result.get("session_id"),
        "tps": result.get("tps", 0.0),
        "secret_count": result.get("secret_count", 0),
        "new_hatches_count": len(result.get("new_hatches", [])),
        "script_version": "2.3.2",
    }


# --- Farm Overview & Secret Vault endpoints (v2) ---


@app.get("/api/v1/overview", dependencies=[Depends(require_read_access)])
async def get_farm_overview():
    return session_manager.get_overview()


@app.get("/api/v1/secrets", dependencies=[Depends(require_read_access)])
async def get_secrets_vault(
    user_id: Optional[int] = None,
    variant: Optional[str] = None,
    tier: Optional[str] = None,
    q: Optional[str] = None,
):
    return session_manager.get_secrets_summary(user_id=user_id, variant=variant, tier=tier, query=q)


@app.get("/api/v1/pets/catalog", dependencies=[Depends(require_read_access)])
async def get_pet_catalog():
    return pet_catalog.list_catalog()


@app.post("/api/v1/pets/catalog/{slug}/image", dependencies=[Depends(require_admin)])
async def update_pet_catalog_image(slug: str, req: CatalogImageOverrideRequest):
    clean_slug = slugify_pet_name(slug)
    existing = db.get_pet_catalog_item(clean_slug)
    name = existing["name"] if existing else clean_slug.replace("-", " ").title()

    overwrite_custom = "imageUrl" in req.model_fields_set
    updated = db.upsert_pet_catalog(
        slug=clean_slug,
        name=name,
        tier=req.tier,
        default_egg=req.defaultEgg,
        odds=req.odds,
        image_asset_id=req.imageAssetId,
        custom_image_url=req.imageUrl,
        overwrite_custom=overwrite_custom,
    )
    if req.imageAssetId:
        thumb = await poller.get_asset_thumbnail(req.imageAssetId)
        if thumb:
            pet_catalog.set_resolved_thumbnail(clean_slug, req.imageAssetId, thumb)
            updated = db.get_pet_catalog_item(clean_slug) or updated

    updated["image_url"] = pet_catalog.resolve_image_url(updated["name"])
    return updated


@app.get("/api/v1/pets/icon/{slug}.svg")
async def get_procedural_pet_icon(slug: str):
    clean_slug = slugify_pet_name(slug)
    item = db.get_pet_catalog_item(clean_slug)
    svg = pet_catalog.render_procedural_svg(
        clean_slug,
        name=item["name"] if item else None,
        tier=item.get("tier") if item else "Secret",
    )
    return Response(
        content=svg,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/v1/hatches", dependencies=[Depends(require_read_access)])
async def list_hatch_events(
    limit: int = 50,
    rarity: Optional[str] = None,
    user_id: Optional[int] = None,
):
    rows = db.get_hatch_events(limit=limit, rarity=rarity, user_id=user_id)
    for r in rows:
        r["image_url"] = pet_catalog.resolve_image_url(r["pet_name"], explicit_url=r.get("image_url"))
        if not r.get("username"):
            r["username"] = r.get("actor_name") or (f"Player_{r['user_id']}" if r.get("user_id") else "Webhook")
    return rows


# --- Alerts & Discord Webhook endpoints (v2) ---


@app.get("/api/v1/settings/alerts", dependencies=[Depends(require_read_access)])
async def get_alert_settings():
    return webhook_service.get_public_settings()


@app.post("/api/v1/settings/alerts", dependencies=[Depends(require_admin)])
async def update_alert_settings(req: AlertSettingsUpdate):
    return webhook_service.update_settings(req)


@app.post("/api/v1/settings/alerts/test", dependencies=[Depends(require_admin)])
async def test_alert_webhook():
    return await webhook_service.send_test_alert()


@app.post("/api/v1/webhook/discord", dependencies=[Depends(require_ingest_key)])
async def ingest_discord_webhook(payload: Dict[str, Any]):
    return await webhook_service.ingest_discord_webhook(payload)


# --- Game Connector & Luau Script endpoints (v2) ---


@app.get("/loader.lua")
@app.get("/api/v1/connector/script.lua")
async def get_luau_connector_script(request: Request, endpoint: Optional[str] = None):
    script_path = BASE_DIR / "scripts" / "tap_sim_reborn_tracker.lua"
    if not script_path.exists():
        raise HTTPException(status_code=404, detail="Luau connector script not found")

    lua_text = script_path.read_text(encoding="utf-8")
    base_url = resolve_public_base_url(request)
    raw_ep = (endpoint or "").strip()
    is_safe_raw = bool(
        raw_ep
        and raw_ep.lower().startswith(("http://", "https://"))
        and not any(ch in raw_ep for ch in ("\r", "\n", '"', "'", "\\", " "))
    )
    clean_ep = raw_ep if is_safe_raw else f"{base_url}/api/v1/telemetry"
    if not any(ch in clean_ep for ch in ("\r", "\n", '"', "'", "\\", " ")):
        lua_text = re.sub(
            r'(ENDPOINT_URL\s*=\s*")[^"]*(")',
            lambda m: f"{m.group(1)}{clean_ep}{m.group(2)}",
            lua_text,
            count=1,
        )
        inspect_ep = re.sub(r"/api/v1/telemetry/?$", "/api/v1/connector/inspect", clean_ep)
        if inspect_ep == clean_ep or any(ch in inspect_ep for ch in ("\r", "\n", '"', "'", "\\", " ")):
            inspect_ep = f"{base_url}/api/v1/connector/inspect"
        lua_text = re.sub(
            r'(INSPECT_URL\s*=\s*")[^"]*(")',
            lambda m: f"{m.group(1)}{inspect_ep}{m.group(2)}",
            lua_text,
            count=1,
        )
        loader_ep = f"{base_url}/loader.lua"
        if not any(ch in loader_ep for ch in ("\r", "\n", '"', "'", "\\", " ")):
            lua_text = re.sub(
                r'(LOADER_URL\s*=\s*")[^"]*(")',
                lambda m: f"{m.group(1)}{loader_ep}{m.group(2)}",
                lua_text,
                count=1,
            )

    return Response(
        content=lua_text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "inline; filename=tap_sim_reborn_tracker.lua"},
    )


@app.post("/api/v1/connector/inspect", dependencies=[Depends(require_ingest_key)])
async def submit_inspector_report(req: InspectorReportInput):
    return db.save_inspector_report(
        user_id=req.userId,
        username=req.username,
        place_id=req.placeId,
        structure=req.structure,
    )


@app.get("/api/v1/connector/inspect", dependencies=[Depends(require_read_access)])
async def list_inspector_reports(limit: int = 10):
    return db.get_inspector_reports(limit=limit)


# --- Accounts endpoints (v1 preserved + v2 fields) ---


@app.get("/api/v1/accounts", dependencies=[Depends(require_read_access)])
async def list_accounts():
    accounts = db.get_accounts()
    result = []
    for acc in accounts:
        uid = acc["user_id"]
        live = session_manager.get_live_state(uid)
        result.append(
            {
                **acc,
                "connection_status": live["connection_status"],
                "current_taps": live["current_taps"],
                "total_taps": live["total_taps"],
                "current_rebirths": live["current_rebirths"],
                "tps": live["tps"],
                "session_duration_sec": live["session_duration_sec"],
                "secret_count": live["secret_count"],
                "eggs_hatched": live["eggs_hatched"],
                "eggs_per_hour": live["eggs_per_hour"],
                "world": live["world"],
                "client_source": live["client_source"],
                "secret_pets": live["secret_pets"],
                "top_secrets": live["secret_pets"][:3],
            }
        )
    return result


@app.post("/api/v1/accounts", dependencies=[Depends(require_admin)])
async def add_account(req: AddAccountRequest):
    uid = req.userId
    user_info = await poller.get_user_info(uid)
    avatar_url = await poller.get_user_avatar(uid)
    db.upsert_account(
        user_id=uid,
        username=user_info.get("name", f"Player_{uid}"),
        display_name=user_info.get("displayName", user_info.get("name")),
        avatar_url=avatar_url,
    )
    return db.get_account(uid)


@app.delete("/api/v1/accounts/{user_id}", dependencies=[Depends(require_admin)])
async def delete_account(user_id: int):
    success = db.delete_account(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    session_manager.remove_account(user_id)
    return {"status": "deleted", "user_id": user_id}


@app.post("/api/v1/accounts/{user_id}/tracking", dependencies=[Depends(require_admin)])
async def toggle_account_tracking(user_id: int, req: TrackingToggleRequest):
    acc = db.get_account(user_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    session_manager.toggle_tracking(user_id, req.is_tracking)
    return {"status": "updated", "user_id": user_id, "is_tracking": req.is_tracking}


@app.post("/api/v1/accounts/tracking/all", dependencies=[Depends(require_admin)])
async def toggle_all_tracking(req: TrackingToggleRequest):
    accounts = db.get_accounts()
    for acc in accounts:
        session_manager.toggle_tracking(acc["user_id"], req.is_tracking)
    return {"status": "updated_all", "is_tracking": req.is_tracking, "count": len(accounts)}


@app.get("/api/v1/accounts/{user_id}/live", dependencies=[Depends(require_read_access)])
async def get_account_live_state(user_id: int):
    return session_manager.get_live_state(user_id)


@app.get("/api/v1/accounts/{user_id}/history", dependencies=[Depends(require_read_access)])
async def get_account_history(user_id: int):
    return db.get_sessions(user_id)


@app.get("/api/v1/accounts/{user_id}/snapshots", dependencies=[Depends(require_read_access)])
async def get_account_snapshots(user_id: int, limit: int = 50):
    return db.get_recent_snapshots(user_id, limit=limit)


# --- Export & Restore ---


@app.get("/api/v1/export/csv", dependencies=[Depends(require_admin)])
async def export_csv():
    csv_data = db.export_data("csv")
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=trackstats_export_{int(time.time())}.csv"},
    )


@app.get("/api/v1/export/json", dependencies=[Depends(require_admin)])
async def export_json():
    json_data = db.export_data("json")
    return Response(
        content=json_data,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=trackstats_export_{int(time.time())}.json"},
    )


@app.post("/api/v1/restore", dependencies=[Depends(require_admin)])
async def restore_database(payload: Dict[str, Any]):
    success = db.restore_data(json.dumps(payload))
    if not success:
        raise HTTPException(status_code=400, detail="Invalid restore payload")
    pet_catalog.seed_defaults()
    session_manager.reset_after_restore()
    return {"status": "restored"}


# --- Server-Sent Events (SSE) Stream ---


@app.get("/api/v1/stream", dependencies=[Depends(require_read_access)])
async def sse_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            accounts = db.get_accounts()
            accounts_payload = [session_manager.get_live_state(a["user_id"]) for a in accounts]
            overview = session_manager.get_overview()
            recent_hatches = db.get_hatch_events(limit=25)
            for h in recent_hatches:
                h["image_url"] = pet_catalog.resolve_image_url(h["pet_name"], explicit_url=h.get("image_url"))
                if not h.get("username"):
                    h["username"] = h.get("actor_name") or (
                        f"Player_{h['user_id']}" if h.get("user_id") else "Webhook"
                    )
            envelope = {
                "overview": overview,
                "accounts": accounts_payload,
                "recent_hatches": recent_hatches,
            }
            yield f"data: {json.dumps(envelope)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# --- Static UI serving ---

static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Tap Simulator Reborn TrackStats API</h1><p>Dashboard UI initializing...</p>")
