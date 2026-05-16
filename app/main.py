import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from models import SessionState
from port_discovery import discover_ws_port
from apex_client import ApexClient
from lap_api import fetch_driver_laps

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

CIRCUIT_URL = os.environ.get(
    "CIRCUIT_URL",
    "https://www.apex-timing.com/live-timing/karting-de-saintes/",
)
WS_PORT_OVERRIDE = os.environ.get("WS_PORT")

session: Optional[SessionState] = None
apex: Optional[ApexClient] = None
_ws_clients: list[WebSocket] = []


async def broadcast(event: str, data: dict):
    payload = json.dumps({"event": event, "data": data, "ts": datetime.now(timezone.utc).isoformat()})
    dead = []
    for ws in _ws_clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


async def on_apex_event(event: str, data: dict):
    await broadcast(event, data)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global session, apex

    port = int(WS_PORT_OVERRIDE) if WS_PORT_OVERRIDE else None
    if not port:
        port = await discover_ws_port(CIRCUIT_URL)
    if not port:
        logger.error("Could not determine WebSocket port — set WS_PORT env var manually")
        port = 0

    session = SessionState(circuit_url=CIRCUIT_URL, ws_port=port)

    if port:
        apex = ApexClient(session, on_apex_event)
        task = asyncio.create_task(apex.run())
        logger.info("Apex client started for %s (port %d)", CIRCUIT_URL, port)
    else:
        task = None
        logger.warning("Apex client NOT started — no port discovered")

    yield

    if apex:
        await apex.stop()
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Karting Live", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def status():
    if not session:
        return {"connected": False}
    return {
        "connected": session.connected,
        "circuit_url": session.circuit_url,
        "ws_port": session.ws_port,
        "title1": session.title1,
        "title2": session.title2,
        "session_type": "race" if session.is_race() else ("qualifying" if session.is_qualifying() else "unknown"),
        "countdown": session.countdown,
        "driver_count": len(session.drivers),
        "last_update": session.last_update.isoformat() if session.last_update else None,
    }


@app.get("/api/grid")
async def grid():
    if not session:
        raise HTTPException(503, "Not initialized")
    drivers = sorted(session.drivers.values(), key=lambda d: d.position)
    return {"drivers": [asdict(d) for d in drivers]}


@app.get("/api/pits")
async def pits():
    if not session:
        raise HTTPException(503, "Not initialized")
    return {
        "pit_stops": [
            {
                "timestamp": e.timestamp.isoformat(),
                "kart": e.kart,
                "team": e.team,
                "position": e.position,
                "pit_number": e.pit_number,
                "lap": e.lap,
            }
            for e in reversed(session.pit_history)
        ]
    }


@app.get("/api/comments")
async def comments():
    if not session:
        raise HTTPException(503, "Not initialized")
    return {"comments": session.comments}


@app.get("/api/driver/{driver_id}/laps")
async def driver_laps(driver_id: str):
    if not session or not session.ws_port:
        raise HTTPException(503, "Not connected")
    result = await fetch_driver_laps(session.circuit_url, session.ws_port, driver_id)
    if "error" in result:
        raise HTTPException(502, result["error"])
    return result


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _ws_clients.append(ws)
    try:
        if session:
            # Send current state immediately on connect
            await ws.send_text(json.dumps({
                "event": "snapshot",
                "data": {
                    "title1": session.title1,
                    "title2": session.title2,
                    "drivers": [asdict(d) for d in sorted(session.drivers.values(), key=lambda x: x.position)],
                    "pit_history": [
                        {"kart": e.kart, "team": e.team, "position": e.position,
                         "pit_number": e.pit_number, "timestamp": e.timestamp.isoformat()}
                        for e in session.pit_history
                    ],
                },
                "ts": datetime.now(timezone.utc).isoformat(),
            }))
        while True:
            await ws.receive_text()  # keep-alive; client can send pings
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


if os.path.isdir("/app/static"):
    app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
