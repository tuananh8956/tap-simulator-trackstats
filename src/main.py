import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Any, List

from fastapi import FastAPI, HTTPException, Response, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import settings
from src.models import TelemetryPayload
from src.database import Database
from src.rate_engine import RateEngine
from src.roblox_poller import RobloxPoller
from src.session_manager import SessionManager

# Initialize singletons
db = Database(settings.db_path)
db.init_db()
rate_engine = RateEngine(max_window_sec=settings.rate_window_max_sec)
poller = RobloxPoller(debounce_sec=settings.poller_interval_sec)
session_manager = SessionManager(
    db=db,
    rate_engine=rate_engine,
    poller=poller,
    stale_timeout_sec=settings.stale_timeout_sec,
    disconnect_timeout_sec=settings.disconnect_timeout_sec
)

# Background timeout task
timeout_task: asyncio.Task = None

async def timeout_monitor_loop():
    while True:
        try:
            session_manager.check_timeouts()
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(2.0)

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    global timeout_task
    timeout_task = asyncio.create_task(timeout_monitor_loop())
    yield
    if timeout_task:
        timeout_task.cancel()
        try:
            await timeout_task
        except asyncio.CancelledError:
            pass

app = FastAPI(
    title="Tap Simulator Reborn - TrackStats API",
    version="1.0.0",
    description="Real-time Statistics Tracker and Telemetry Companion for Tap Simulator Reborn",
    lifespan=lifespan
)

class AddAccountRequest(BaseModel):
    userId: int

class TrackingToggleRequest(BaseModel):
    is_tracking: bool

# Telemetry ingestion endpoint
@app.post("/api/v1/telemetry")
async def ingest_telemetry(payload: TelemetryPayload):
    result = session_manager.process_telemetry(payload)
    return result

# Accounts endpoints
@app.get("/api/v1/accounts")
async def list_accounts():
    accounts = db.get_accounts()
    result = []
    for acc in accounts:
        uid = acc["user_id"]
        live = session_manager.get_live_state(uid)
        result.append({
            **acc,
            "connection_status": live["connection_status"],
            "current_taps": live["current_taps"],
            "total_taps": live["total_taps"],
            "current_rebirths": live["current_rebirths"],
            "tps": live["tps"],
            "session_duration_sec": live["session_duration_sec"]
        })
    return result

@app.post("/api/v1/accounts")
async def add_account(req: AddAccountRequest):
    uid = req.userId
    # Fetch public profile from Roblox
    user_info = await poller.get_user_info(uid)
    avatar_url = await poller.get_user_avatar(uid)
    db.upsert_account(
        user_id=uid,
        username=user_info.get("name", f"Player_{uid}"),
        display_name=user_info.get("displayName", user_info.get("name")),
        avatar_url=avatar_url
    )
    return db.get_account(uid)

@app.delete("/api/v1/accounts/{user_id}")
async def delete_account(user_id: int):
    success = db.delete_account(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Account not found")
    rate_engine.reset_account(user_id)
    return {"status": "deleted", "user_id": user_id}

@app.post("/api/v1/accounts/{user_id}/tracking")
async def toggle_account_tracking(user_id: int, req: TrackingToggleRequest):
    acc = db.get_account(user_id)
    if not acc:
        raise HTTPException(status_code=404, detail="Account not found")
    session_manager.toggle_tracking(user_id, req.is_tracking)
    return {"status": "updated", "user_id": user_id, "is_tracking": req.is_tracking}

@app.post("/api/v1/accounts/tracking/all")
async def toggle_all_tracking(req: TrackingToggleRequest):
    accounts = db.get_accounts()
    for acc in accounts:
        session_manager.toggle_tracking(acc["user_id"], req.is_tracking)
    return {"status": "updated_all", "is_tracking": req.is_tracking, "count": len(accounts)}

@app.get("/api/v1/accounts/{user_id}/live")
async def get_account_live_state(user_id: int):
    live = session_manager.get_live_state(user_id)
    return live

@app.get("/api/v1/accounts/{user_id}/history")
async def get_account_history(user_id: int):
    return db.get_sessions(user_id)

@app.get("/api/v1/accounts/{user_id}/snapshots")
async def get_account_snapshots(user_id: int, limit: int = 50):
    return db.get_recent_snapshots(user_id, limit=limit)

# Export & Restore
@app.get("/api/v1/export/csv")
async def export_csv():
    csv_data = db.export_data("csv")
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=trackstats_export_{int(time.time())}.csv"}
    )

@app.get("/api/v1/export/json")
async def export_json():
    json_data = db.export_data("json")
    return Response(
        content=json_data,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=trackstats_export_{int(time.time())}.json"}
    )

@app.post("/api/v1/restore")
async def restore_database(payload: Dict[str, Any]):
    success = db.restore_data(json.dumps(payload))
    if not success:
        raise HTTPException(status_code=400, detail="Invalid restore payload")
    return {"status": "restored"}

# Server-Sent Events (SSE) Stream
@app.get("/api/v1/stream")
async def sse_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            accounts = db.get_accounts()
            payload = []
            for a in accounts:
                uid = a["user_id"]
                payload.append(session_manager.get_live_state(uid))
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )

# Static UI serving
static_dir = Path(__file__).resolve().parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>Tap Simulator Reborn TrackStats API</h1><p>Dashboard UI initializing...</p>")
