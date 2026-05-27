"""
Apex Timing WebSocket proxy — enregistre des sessions live et les rejoue.

State machine: idle → live | replaying → idle
Background recording runs independently of the main mode (usable during replay).

WS  /ws                          — le backend ApexClient se connecte ici
GET  /api/status                  — état courant
GET    /api/circuits              — circuits (depuis SQLite, avec country + ws_host)
POST   /api/circuits              — ajouter un circuit
PUT    /api/circuits/{slug}       — modifier un circuit
DELETE /api/circuits/{slug}       — supprimer un circuit
GET  /api/recordings              — liste des enregistrements
DELETE /api/recordings/{name}     — supprimer un enregistrement
POST /api/live                    — démarrer relais live (+ enregistrement optionnel)
POST /api/live/record             — démarrer enregistrement du live en cours
POST /api/live/stop-record        — arrêter enregistrement du live (sans couper le relay)
POST /api/replay                  — démarrer replay
POST /api/speed                   — modifier vitesse replay
POST /api/stop                    — arrêter replay/live
POST /api/grid                    — re-broadcaster la grille (cache ou fresh)
POST /api/record                  — enregistrement en arrière-plan (sans diffusion)
POST /api/stop-record             — arrêter un enregistrement en arrière-plan
"""
import asyncio
import json
import logging
import os
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import circuits_db
from typing import Optional
from urllib.parse import urlparse

import websockets
import websockets.exceptions
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).parent / "static"

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "/data/recordings"))
SCHEDULE_FILE = RECORDINGS_DIR / "schedule.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)



def _default_name(circuit_url: str) -> str:
    c = circuits_db.get_by_url(circuit_url)
    slug = c["slug"] if c else "circuit"
    return f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _ws_attempts(circuit_url: str, ws_port: int) -> list:
    """Return [(ws_url, ssl_ctx_or_None)] to try in priority order.

    Tries the circuit's known ws_host first, then falls back to www.apex-timing.com.
    """
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    c = circuits_db.get_by_url(circuit_url)
    if c:
        primary = c["ws_host"]
    else:
        parsed = urlparse(circuit_url)
        h = parsed.hostname or "www.apex-timing.com"
        primary = h if h != "www.apex-timing.com" else "www.apex-timing.com"

    seen: set = set()
    attempts = []
    for host in ([primary, "www.apex-timing.com"] if primary != "www.apex-timing.com" else ["www.apex-timing.com"]):
        for scheme, ctx in [("wss", ssl_ctx), ("ws", None)]:
            url = f"{scheme}://{host}:{ws_port}/"
            if url not in seen:
                seen.add(url)
                attempts.append((url, ctx))
    return attempts


# ── State ─────────────────────────────────────────────────────────────────────

class _State:
    mode: str = "idle"                    # idle | live | replaying
    circuit_url: str = ""
    ws_port: int = 0
    ws_host: str = ""
    recording_name: Optional[str] = None
    recording_file = None
    recording_msg_count: int = 0
    recording_start: float = 0.0
    replay_name: Optional[str] = None
    replay_speed: float = 1.0
    replay_progress: int = 0
    replay_total: int = 0
    clients: set = None
    _apex_task: Optional[asyncio.Task] = None
    _replay_task: Optional[asyncio.Task] = None
    bg_recordings: dict = None
    last_grid_msg: Optional[str] = None

    def __init__(self):
        self.clients = set()
        self.bg_recordings = {}

state = _State()

_scheduled_jobs: list[dict] = []
_scheduler_task: Optional[asyncio.Task] = None


# ── Recording helpers ─────────────────────────────────────────────────────────

def _path(name: str) -> Path:
    return RECORDINGS_DIR / f"{name}.jsonl"


def _list_recordings() -> list[dict]:
    out = []
    for f in sorted(RECORDINGS_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            with f.open() as fh:
                meta = json.loads(fh.readline())
                lines = sum(1 for _ in fh)
            out.append({
                "name": f.stem,
                "circuit_url": meta.get("circuit_url", ""),
                "ws_port": meta.get("ws_port", 0),
                "started_at": meta.get("started_at", ""),
                "msg_count": lines,
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
        except Exception:
            pass
    return out


def _open_live_recording(name: str, circuit_url: str, ws_port: int):
    """Open and initialise a recording file for the current live stream."""
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "v": 1,
        "circuit_url": circuit_url,
        "ws_port": ws_port,
        "name": name,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    state.recording_file = _path(name).open("w")
    state.recording_file.write(json.dumps(meta) + "\n")
    state.recording_file.flush()
    state.recording_start = time.monotonic()
    logger.info("Recording → %s", _path(name))


def _close_recording():
    if state.recording_file:
        state.recording_file.close()
        state.recording_file = None


# ── Schedule persistence ──────────────────────────────────────────────────────

def _load_jobs() -> list[dict]:
    if not SCHEDULE_FILE.exists():
        return []
    try:
        jobs = json.loads(SCHEDULE_FILE.read_text())
        for j in jobs:
            if j.get("status") == "running":
                j["status"] = "interrupted"
        return jobs
    except Exception:
        return []


def _save_jobs():
    try:
        SCHEDULE_FILE.write_text(json.dumps(_scheduled_jobs, indent=2))
    except Exception as e:
        logger.warning("Failed to save schedule: %s", e)


# ── Broadcast ─────────────────────────────────────────────────────────────────

async def _broadcast(msg: str):
    inner = msg
    if msg.startswith('{"t":'):
        try:
            inner = json.loads(msg)["msg"]
        except Exception:
            pass
    for line in inner.split("\n"):
        if line.startswith("grid|"):
            state.last_grid_msg = msg
            break
    dead = set()
    for ws in list(state.clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    state.clients -= dead


# ── Live relay ────────────────────────────────────────────────────────────────

async def _run_live(circuit_url: str, ws_port: int, record: bool, name: Optional[str]):
    if record and name:
        _open_live_recording(name, circuit_url, ws_port)

    attempt = 0
    while state.mode == "live":
        connected = False
        for url, ctx in _ws_attempts(circuit_url, ws_port):
            if state.mode != "live":
                break
            try:
                logger.info("Proxy → %s", url)
                async with websockets.connect(url, ssl=ctx, ping_interval=None, close_timeout=5) as ws:
                    attempt = 0
                    connected = True
                    logger.info("Proxy connected: %s", url)
                    async for raw in ws:
                        if state.mode != "live":
                            break
                        msg = raw.decode() if isinstance(raw, bytes) else raw
                        await _broadcast(msg)
                        f = state.recording_file
                        if f:
                            t = round(time.monotonic() - state.recording_start, 3)
                            f.write(json.dumps({"t": t, "msg": msg}) + "\n")
                            f.flush()
                            state.recording_msg_count += 1
                break
            except Exception as e:
                logger.warning("Proxy WS error (%s): %s", url, e)

        if state.mode != "live":
            break
        if not connected:
            attempt += 1
            await asyncio.sleep(min(3 * attempt, 30))

    _close_recording()
    logger.info("Live relay stopped")


# ── Background recording (record only, no broadcast) ─────────────────────────

async def _run_bg_record(circuit_url: str, ws_port: int, name: str):
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "v": 1,
        "circuit_url": circuit_url,
        "ws_port": ws_port,
        "name": name,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    bg_file = _path(name).open("w")
    bg_file.write(json.dumps(meta) + "\n")
    bg_file.flush()
    start = time.monotonic()
    logger.info("BG Recording → %s", _path(name))

    attempt = 0
    try:
        while name in state.bg_recordings:
            connected = False
            for url, ctx in _ws_attempts(circuit_url, ws_port):
                if name not in state.bg_recordings:
                    break
                try:
                    async with websockets.connect(url, ssl=ctx, ping_interval=None, close_timeout=5) as ws:
                        attempt = 0
                        connected = True
                        async for raw in ws:
                            if name not in state.bg_recordings:
                                break
                            msg = raw.decode() if isinstance(raw, bytes) else raw
                            t = round(time.monotonic() - start, 3)
                            bg_file.write(json.dumps({"t": t, "msg": msg}) + "\n")
                            bg_file.flush()
                            state.bg_recordings[name]["msg_count"] += 1
                    break
                except Exception as e:
                    logger.warning("BG record WS error (%s): %s", url, e)

            if name not in state.bg_recordings:
                break
            if not connected:
                attempt += 1
                await asyncio.sleep(min(3 * attempt, 30))
    finally:
        bg_file.close()
        logger.info("BG Recording stopped: %s", name)


# ── Replay ────────────────────────────────────────────────────────────────────

async def _run_replay(name: str, speed: float):
    path = _path(name)
    if not path.exists():
        logger.error("Recording not found: %s", name)
        state.mode = "idle"
        return

    await _broadcast("__proxy_reset__")
    await asyncio.sleep(0.1)

    logger.info("Replay start: %s @ %.2fx", name, speed)
    loop = asyncio.get_event_loop()
    prev_t = 0.0
    state.replay_progress = 0

    with path.open() as fh:
        fh.readline()
        while state.mode == "replaying":
            line = await loop.run_in_executor(None, fh.readline)
            if not line:
                break
            try:
                entry = json.loads(line)
                delay = (entry["t"] - prev_t) / state.replay_speed
                if delay > 0.001:
                    await asyncio.sleep(delay)
                prev_t = entry["t"]
                await _broadcast(json.dumps({"t": entry["t"], "msg": entry["msg"]}))
                state.replay_progress += 1
            except Exception:
                pass

    logger.info("Replay finished: %s", name)
    state.mode = "idle"
    state.replay_name = None


# ── Stop ──────────────────────────────────────────────────────────────────────

async def _stop():
    state.mode = "idle"
    for task in (state._apex_task, state._replay_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    _close_recording()
    state._apex_task = None
    state._replay_task = None
    state.recording_name = None
    state.recording_msg_count = 0
    state.replay_name = None
    state.replay_progress = 0
    state.replay_total = 0
    state.last_grid_msg = None


async def _stop_bg_record(name: Optional[str] = None):
    targets = [name] if name else list(state.bg_recordings.keys())
    for n in targets:
        entry = state.bg_recordings.pop(n, None)
        if entry:
            task = entry["task"]
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


# ── Scheduler ─────────────────────────────────────────────────────────────────

async def _launch_scheduled_job(job: dict):
    prefix = job.get("name_prefix")
    if prefix:
        name = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    else:
        name = _default_name(job["circuit_url"])
    base = name
    suffix = 2
    while _path(name).exists() or name in state.bg_recordings:
        name = f"{base}_{suffix}"; suffix += 1

    job["recording_name"] = name
    _save_jobs()
    logger.info("Scheduled job %s starting → %s", job["id"], name)

    task = asyncio.create_task(_run_bg_record(job["circuit_url"], job["ws_port"], name))
    state.bg_recordings[name] = {"task": task, "msg_count": 0}

    duration = job.get("duration_minutes")
    if duration:
        await asyncio.sleep(duration * 60)
        await _stop_bg_record(name)
    else:
        try:
            await task
        except asyncio.CancelledError:
            pass

    job["status"] = "done"
    _save_jobs()
    logger.info("Scheduled job done: %s → %s", job["id"], name)


async def _scheduler_loop():
    while True:
        await asyncio.sleep(15)
        now = datetime.now(timezone.utc)
        for job in _scheduled_jobs:
            if job["status"] != "pending":
                continue
            try:
                start = datetime.fromisoformat(job["start_at"])
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if now >= start:
                job["status"] = "running"
                _save_jobs()
                asyncio.create_task(_launch_scheduled_job(job))


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduled_jobs, _scheduler_task
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    circuits_db.init_db()
    _scheduled_jobs.extend(_load_jobs())
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    yield
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
    await _stop()
    await _stop_bg_record()


app = FastAPI(title="Apex Proxy", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/", include_in_schema=False)
def ui():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ── REST ──────────────────────────────────────────────────────────────────────

@app.get("/api/status")
def get_status():
    return {
        "mode": state.mode,
        "clients": len(state.clients),
        "circuit_url": state.circuit_url,
        "ws_port": state.ws_port,
        "ws_host": state.ws_host,
        "recording_name": state.recording_name,
        "recording_msg_count": state.recording_msg_count,
        "replay_name": state.replay_name,
        "replay_speed": state.replay_speed,
        "replay_progress": state.replay_progress,
        "bg_recordings": [
            {"name": n, "msg_count": e["msg_count"]}
            for n, e in state.bg_recordings.items()
        ],
        "scheduled_jobs": [
            j for j in _scheduled_jobs if j["status"] in ("pending", "running")
        ],
    }


@app.get("/api/circuits")
def get_circuits():
    return {"circuits": circuits_db.get_all()}


class CircuitRequest(BaseModel):
    slug: str
    name: str
    url: str
    port: int
    ws_host: str
    country: str = ""


@app.post("/api/circuits", status_code=201)
def create_circuit(req: CircuitRequest):
    if circuits_db.get_by_slug(req.slug):
        raise HTTPException(409, f"Slug '{req.slug}' already exists")
    return circuits_db.upsert(req.model_dump())


@app.put("/api/circuits/{slug}")
def update_circuit(slug: str, req: CircuitRequest):
    if not circuits_db.get_by_slug(slug):
        raise HTTPException(404, "Circuit not found")
    data = req.model_dump()
    data["slug"] = slug
    return circuits_db.upsert(data)


@app.delete("/api/circuits/{slug}")
def delete_circuit(slug: str):
    if not circuits_db.delete(slug):
        raise HTTPException(404, "Circuit not found")
    return {"ok": True}


@app.get("/api/recordings")
def get_recordings():
    return {"recordings": _list_recordings()}


@app.get("/api/recordings/{name}/download")
def download_recording(name: str):
    path = _path(name)
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(str(path), media_type="application/x-ndjson", filename=f"{name}.jsonl")


@app.delete("/api/recordings/{name}")
def delete_recording(name: str):
    path = _path(name)
    if not path.exists():
        raise HTTPException(404, "Not found")
    if name in (state.recording_name, state.replay_name) or name in state.bg_recordings:
        raise HTTPException(409, "Recording currently in use")
    path.unlink()
    return {"ok": True}


class LiveRequest(BaseModel):
    circuit_url: str
    ws_port: int
    record: bool = False
    name: Optional[str] = None


@app.post("/api/live")
async def start_live(req: LiveRequest):
    if state.mode != "idle":
        await _stop()
    if req.record and not req.name:
        req.name = _default_name(req.circuit_url)
    c = circuits_db.get_by_url(req.circuit_url)
    state.mode = "live"
    state.circuit_url = req.circuit_url
    state.ws_port = req.ws_port
    state.ws_host = c["ws_host"] if c else "www.apex-timing.com"
    state.recording_name = req.name if req.record else None
    state.recording_msg_count = 0
    state._apex_task = asyncio.create_task(
        _run_live(req.circuit_url, req.ws_port, req.record, req.name)
    )
    return {"ok": True, "recording": req.name}


class LiveRecordRequest(BaseModel):
    name: Optional[str] = None


@app.post("/api/live/record")
async def start_live_record(req: LiveRecordRequest = LiveRecordRequest()):
    if state.mode != "live":
        raise HTTPException(400, "Not in live mode")
    if state.recording_file:
        raise HTTPException(409, "Already recording live stream")
    name = req.name or _default_name(state.circuit_url)
    if _path(name).exists():
        raise HTTPException(409, f"Recording '{name}' already exists")
    _open_live_recording(name, state.circuit_url, state.ws_port)
    state.recording_name = name
    state.recording_msg_count = 0
    return {"ok": True, "name": name}


@app.post("/api/live/stop-record")
async def stop_live_record():
    if not state.recording_file:
        raise HTTPException(400, "Not recording live stream")
    # Atomically clear before closing to avoid write-after-close in _run_live
    f = state.recording_file
    state.recording_file = None
    name = state.recording_name
    state.recording_name = None
    state.recording_msg_count = 0
    f.close()
    logger.info("Live recording stopped: %s", name)
    return {"ok": True, "name": name}


class ReplayRequest(BaseModel):
    name: str
    speed: float = 1.0


@app.post("/api/replay")
async def start_replay(req: ReplayRequest):
    if state.mode != "idle":
        await _stop()
    path = _path(req.name)
    if not path.exists():
        raise HTTPException(404, "Recording not found")
    with path.open() as fh:
        fh.readline()
        state.replay_total = sum(1 for _ in fh)
    state.mode = "replaying"
    state.replay_name = req.name
    state.replay_speed = req.speed
    state.replay_progress = 0
    state._replay_task = asyncio.create_task(_run_replay(req.name, req.speed))
    return {"ok": True, "total": state.replay_total}


class SpeedRequest(BaseModel):
    speed: float


@app.post("/api/speed")
async def set_speed(req: SpeedRequest):
    speed = max(0.1, min(req.speed, 20.0))
    state.replay_speed = speed
    return {"ok": True, "speed": speed}


@app.post("/api/stop")
async def stop():
    await _stop()
    return {"ok": True}


@app.post("/api/grid")
async def refresh_grid():
    """Re-broadcast cached grid to all clients, or fetch a fresh one from Apex."""
    if state.last_grid_msg:
        await _broadcast(state.last_grid_msg)
        return {"ok": True, "source": "cached"}

    if state.mode != "live" or not state.circuit_url or not state.ws_port:
        raise HTTPException(404, "No grid available and not in live mode")

    async def _fetch(url: str, ctx) -> Optional[str]:
        async with websockets.connect(url, ssl=ctx, ping_interval=None, close_timeout=3) as ws:
            async for raw in ws:
                msg = raw.decode() if isinstance(raw, bytes) else raw
                for line in msg.split("\n"):
                    if line.startswith("grid|"):
                        return msg
        return None

    grid_msg: Optional[str] = None
    for url, ctx in _ws_attempts(state.circuit_url, state.ws_port):
        try:
            grid_msg = await asyncio.wait_for(_fetch(url, ctx), timeout=15.0)
            if grid_msg:
                break
        except asyncio.TimeoutError:
            logger.warning("refresh_grid timeout on %s", url)
        except Exception as e:
            logger.warning("refresh_grid error (%s): %s", url, e)

    if not grid_msg:
        raise HTTPException(503, "Could not fetch grid from Apex")

    state.last_grid_msg = grid_msg
    await _broadcast(grid_msg)
    return {"ok": True, "source": "fresh"}


class RecordRequest(BaseModel):
    circuit_url: str
    ws_port: int
    name: Optional[str] = None


@app.post("/api/record")
async def start_bg_record(req: RecordRequest):
    name = req.name or _default_name(req.circuit_url)
    if _path(name).exists():
        raise HTTPException(409, f"Recording '{name}' already exists")
    if name in state.bg_recordings:
        raise HTTPException(409, f"Already recording '{name}'")
    task = asyncio.create_task(_run_bg_record(req.circuit_url, req.ws_port, name))
    state.bg_recordings[name] = {"task": task, "msg_count": 0}
    return {"ok": True, "name": name}


@app.post("/api/stop-record")
async def stop_bg_record(name: Optional[str] = None):
    await _stop_bg_record(name)
    return {"ok": True}


# ── Schedule ──────────────────────────────────────────────────────────────────

class ScheduleCreateRequest(BaseModel):
    circuit_url: str
    ws_port: int
    start_at: str
    name_prefix: Optional[str] = None
    duration_minutes: Optional[int] = None


@app.get("/api/schedule")
def get_schedule():
    return {"jobs": _scheduled_jobs}


@app.post("/api/schedule")
def create_schedule(req: ScheduleCreateRequest):
    try:
        datetime.fromisoformat(req.start_at)
    except ValueError:
        raise HTTPException(400, "Invalid start_at datetime format")
    job: dict = {
        "id": uuid.uuid4().hex[:8],
        "circuit_url": req.circuit_url,
        "ws_port": req.ws_port,
        "start_at": req.start_at,
        "name_prefix": req.name_prefix or None,
        "duration_minutes": req.duration_minutes,
        "status": "pending",
        "recording_name": None,
    }
    _scheduled_jobs.append(job)
    _save_jobs()
    return {"ok": True, "job": job}


@app.delete("/api/schedule/{job_id}")
async def cancel_schedule(job_id: str):
    for job in _scheduled_jobs:
        if job["id"] == job_id:
            if job["status"] == "running" and job.get("recording_name"):
                await _stop_bg_record(job["recording_name"])
            job["status"] = "cancelled"
            _save_jobs()
            return {"ok": True}
    raise HTTPException(404, "Job not found")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    if state.last_grid_msg:
        try:
            await ws.send_text(state.last_grid_msg)
        except Exception:
            await ws.close()
            return
    state.clients.add(ws)
    logger.info("Backend client connected (total: %d)", len(state.clients))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        state.clients.discard(ws)
        logger.info("Backend client disconnected (total: %d)", len(state.clients))
