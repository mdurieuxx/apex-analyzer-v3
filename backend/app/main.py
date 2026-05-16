import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import engine, SessionLocal, Base
from models import Session as RaceSession
from config_store import get_config
from race.state import RaceState
from race.pit_manager import PitManager
from apex.client import ApexClient
from apex.port_discovery import discover_ws_port
from api.routes import router as api_router, init_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Globals ──────────────────────────────────────────────────────────────────

state = RaceState()
pit_manager: Optional[PitManager] = None
apex_client: Optional[ApexClient] = None
_ws_clients: list[WebSocket] = []
_current_session_id: Optional[int] = None


def get_session_id() -> Optional[int]:
    return _current_session_id


async def broadcast(event: str, data: dict):
    if not _ws_clients:
        return
    payload = json.dumps({
        "event": event,
        "data": data,
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    dead = []
    for ws in list(_ws_clients):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            _ws_clients.remove(ws)
        except ValueError:
            pass


async def on_apex_event(event: str, data: dict):
    """Forward apex events to all connected WebSocket clients."""
    if event == "grid":
        # Enrich grid event with full driver list
        drivers = sorted(state.drivers.values(), key=lambda d: d.position)
        data["drivers"] = [
            {**asdict(d), "kart_label": state.kart_assignments.get(d.driver_id, "?")}
            for d in drivers
        ]
    await broadcast(event, data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pit_manager, apex_client, _current_session_id

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        cfg = get_config(db)
        state.circuit_url = cfg.circuit_url

        # Port discovery
        port = cfg.ws_port_override or 0
        if not port:
            logger.info("Discovering WS port for %s ...", cfg.circuit_url)
            port = await discover_ws_port(cfg.circuit_url) or 0
        state.ws_port = port

        # Create or reuse session record
        session_row = RaceSession(
            circuit_url=cfg.circuit_url,
            ws_port=port,
            started_at=datetime.utcnow(),
        )
        db.add(session_row)
        db.commit()
        db.refresh(session_row)
        _current_session_id = session_row.id
        logger.info("DB session id=%d, ws_port=%d", _current_session_id, port)

    pit_manager = PitManager(state, cfg)
    init_router(state, pit_manager, get_session_id)

    task = None
    if port:
        apex_client = ApexClient(state, on_apex_event, pit_manager)
        task = asyncio.create_task(apex_client.run())
        logger.info("Apex client started")
    else:
        logger.warning("No WS port — set WS_PORT env var or configure in UI")

    yield

    if apex_client:
        await apex_client.stop()
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Karting Live", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    logger.info("WS client connected (total: %d)", len(_ws_clients))

    try:
        # Send current state snapshot immediately
        drivers = sorted(state.drivers.values(), key=lambda d: d.position)
        await ws.send_text(json.dumps({
            "event": "snapshot",
            "data": {
                "title1": state.title1,
                "title2": state.title2,
                "session_type": state.session_type(),
                "countdown": state.countdown,
                "connected": state.connected,
                "drivers": [
                    {**asdict(d), "kart_label": state.kart_assignments.get(d.driver_id, "?")}
                    for d in drivers
                ],
                "lanes": pit_manager.pit_lanes_snapshot() if pit_manager else [],
                "pit_history": [
                    {
                        "bib": p.bib, "team": p.team, "kart_in": p.kart_label,
                        "kart_out": p.kart_out_label, "position": p.position,
                        "pit_number": p.pit_number, "timestamp": p.timestamp.isoformat(),
                        "duration_s": p.duration_s,
                    }
                    for p in state.pit_history[-50:]
                ],
            },
            "ts": datetime.now(timezone.utc).isoformat(),
        }))

        while True:
            await ws.receive_text()  # keep-alive
    except WebSocketDisconnect:
        pass
    finally:
        try:
            _ws_clients.remove(ws)
        except ValueError:
            pass
        logger.info("WS client disconnected (total: %d)", len(_ws_clients))


# Serve built frontend if present
if os.path.isdir("/app/static"):
    app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
