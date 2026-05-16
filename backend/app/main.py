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
from models import Session as RaceSession, PhysicalKart
from config_store import get_config
from race.state import RaceState
from race.pit_manager import PitManager
from race.track_condition import TrackConditionMonitor
from race.kart_ranker import KartRanker
from apex.client import ApexClient
from apex.port_discovery import discover_ws_port
from api.routes import router as api_router, init_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────────────────────

state = RaceState()
pit_manager: Optional[PitManager] = None
kart_ranker: Optional[KartRanker] = None
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


def _enrich_driver(d) -> dict:
    base = asdict(d)
    kart_label = state.kart_assignments.get(d.driver_id, "?")
    base["kart_label"] = kart_label
    if kart_ranker and kart_label and kart_label != "?":
        base["kart_rating"] = kart_ranker.rate_kart(kart_label)
    else:
        base["kart_rating"] = {"rating": "UNKNOWN", "confidence": 0, "delta_pct": 0.0, "observations": 0}
    return base


def _enrich_lanes(lanes: list[dict]) -> list[dict]:
    """Add kart rating to each kart in the pit lane reserve."""
    if not kart_ranker:
        return lanes
    for lane in lanes:
        for kart in lane.get("karts", []):
            label = kart.get("kart_label", "?")
            kart["rating"] = kart_ranker.rate_kart(label) if label != "?" else {"rating": "UNKNOWN", "confidence": 0, "delta_pct": 0.0, "observations": 0}
    return lanes


def _build_snapshot() -> dict:
    drivers = sorted(state.drivers.values(), key=lambda d: d.position)
    lanes = pit_manager.pit_lanes_snapshot() if pit_manager else []
    _enrich_lanes(lanes)

    # Reserve summary (all karts currently in any lane)
    reserve_karts = [k["kart_label"] for lane in lanes for k in lane.get("karts", [])]
    reserve_summary = kart_ranker.reserve_summary(reserve_karts) if kart_ranker else {}

    return {
        "title1": state.title1,
        "title2": state.title2,
        "session_type": state.session_type(),
        "countdown": state.countdown,
        "connected": state.connected,
        "drivers": [_enrich_driver(d) for d in drivers],
        "lanes": lanes,
        "reserve_summary": reserve_summary,
        "pit_history": [
            {
                "bib": p.bib, "team": p.team, "kart_in": p.kart_label,
                "kart_out": p.kart_out_label, "position": p.position,
                "pit_number": p.pit_number, "timestamp": p.timestamp.isoformat(),
                "duration_s": p.duration_s,
            }
            for p in state.pit_history[-50:]
        ],
    }


async def on_apex_event(event: str, data: dict):
    """Forward Apex events to all WebSocket clients, enriched with kart ratings."""
    if event == "grid":
        data = {"count": data.get("count", 0)}
        data["drivers"] = [_enrich_driver(d) for d in sorted(state.drivers.values(), key=lambda x: x.position)]
        lanes = pit_manager.pit_lanes_snapshot() if pit_manager else []
        _enrich_lanes(lanes)
        reserve_karts = [k["kart_label"] for lane in lanes for k in lane.get("karts", [])]
        data["lanes"] = lanes
        data["reserve_summary"] = kart_ranker.reserve_summary(reserve_karts) if kart_ranker else {}
    elif event == "pit_stop":
        # Enrich pit stop event with kart rating of the incoming kart
        kart_label = data.get("kart_label", "?")
        if kart_ranker and kart_label != "?":
            data["kart_rating"] = kart_ranker.rate_kart(kart_label)
    await broadcast(event, data)


def on_lap_completed(driver_id: str, lap_ms: int, is_pit: bool, pit_number: int):
    """Called from the apex client each time a lap is detected."""
    if not kart_ranker:
        return
    kart_label = state.kart_assignments.get(driver_id, "?")
    entry = state.drivers.get(driver_id)
    driver_name = entry.driver_name if entry else ""
    kart_ranker.record_lap(
        team_id=driver_id,
        kart_label=kart_label,
        lap_ms=lap_ms,
        is_pit=is_pit,
        pit_number=pit_number,
        driver_name=driver_name,
    )


def on_pit_detected(driver_id: str):
    """Called when a pit stop is first detected."""
    if kart_ranker:
        kart_ranker.on_pit_stop(driver_id)


async def _start_apex(cfg):
    """Start the Apex client with the given config. Called at startup and on event activation."""
    global apex_client, pit_manager, kart_ranker, _current_session_id

    circuit_url = os.environ.get("CIRCUIT_URL") or cfg.circuit_url
    port = int(os.environ.get("WS_PORT") or 0) or cfg.ws_port_override or 0
    if not port:
        logger.info("Discovering WS port for %s ...", circuit_url)
        port = await discover_ws_port(circuit_url) or 0
    state.ws_port = port
    state.circuit_url = circuit_url

    with SessionLocal() as db:
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

    track_monitor = TrackConditionMonitor()
    kart_ranker = KartRanker(track_monitor)
    pit_manager = PitManager(state, cfg)

    # Populate initial reserve pool from pre-registered physical karts
    with SessionLocal() as db:
        all_karts = db.query(PhysicalKart).all()
        reserve_karts = [(k.kart_label, k.id) for k in all_karts][: cfg.total_reserve_karts]
    if reserve_karts:
        pit_manager.init_reserve(reserve_karts)

    init_router(state, pit_manager, kart_ranker, get_session_id, restart_cb=restart_apex_client)

    if port:
        apex_client = ApexClient(
            state, on_apex_event, pit_manager,
            on_lap_cb=on_lap_completed,
            on_pit_cb=on_pit_detected,
        )
        asyncio.create_task(apex_client.run())
        logger.info("Apex client started (port %d)", port)
    else:
        logger.warning("No WS port — set WS_PORT env var or configure in UI")


async def restart_apex_client(new_cfg):
    """Stop the current client, reset state, and start fresh with new_cfg."""
    global apex_client

    logger.info("Restarting Apex client for %s", new_cfg.circuit_url)

    if apex_client:
        await apex_client.stop()
        apex_client = None

    # Reset live state
    state.drivers.clear()
    state.pit_lanes.clear()
    state.active_pit_stops.clear()
    state.pit_history.clear()
    state.kart_assignments.clear()
    state.driver_lap_counts.clear()
    state.connected = False
    state.title1 = ""
    state.title2 = ""
    state.countdown = 0
    state.comments = []

    await _start_apex(new_cfg)
    await broadcast("snapshot", _build_snapshot())


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        cfg = get_config(db)

    await _start_apex(cfg)

    yield

    if apex_client:
        await apex_client.stop()


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
        await ws.send_text(json.dumps({
            "event": "snapshot",
            "data": _build_snapshot(),
            "ts": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        try:
            _ws_clients.remove(ws)
        except ValueError:
            pass
        logger.info("WS client disconnected (total: %d)", len(_ws_clients))


if os.path.isdir("/app/static"):
    app.mount("/", StaticFiles(directory="/app/static", html=True), name="static")
