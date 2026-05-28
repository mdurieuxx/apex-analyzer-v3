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
GET    /api/circuits/{slug}/tracks — tracks.json parsé (svg + times + size)
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
GET  /api/recordings/sessions     — sessions détectées dans les fichiers JSONL (groupées par event_key)
POST /api/recordings/resolve      — planifier/exécuter split+merge pour avoir un fichier par événement
POST /api/recordings/{name}/meta  — annoter un fichier sans event_meta (stocké dans .recordings_meta.json)
DELETE /api/recordings/{name}/meta — supprimer l'annotation manuelle
"""
import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import ssl
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

import circuits_db
import calendar_sources
import circuit_discovery
import config_store
from typing import Optional
from urllib.parse import urlparse

import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

STATIC_DIR = Path(__file__).parent / "static"

APP_VERSION = "1.2.0"
_STARTED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

RECORDINGS_DIR = Path(os.environ.get("RECORDINGS_DIR", "/data/recordings"))
RESOLVED_DIR = RECORDINGS_DIR / "resolved"
SCHEDULE_FILE = RECORDINGS_DIR / "schedule.json"
RECORDINGS_META_FILE = RECORDINGS_DIR / ".recordings_meta.json"
CALENDAR_FILE = RECORDINGS_DIR / "calendar_events.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_tester_task = None


async def _test_port(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


async def _circuit_tester_loop() -> None:
    """Au démarrage teste tous les circuits non testés, puis toutes les 30 min reteste les échecs."""
    await asyncio.sleep(5)  # laisse le serveur démarrer
    while True:
        pending = circuits_db.get_untested()
        if pending:
            logger.info("Circuit tester: %d circuits à tester", len(pending))
        for c in pending:
            ok = await _test_port(c["ws_host"], c["port"])
            circuits_db.set_tested(c["slug"], ok)
            logger.info("Circuit %s (%s:%d) → %s", c["slug"], c["ws_host"], c["port"], "✓" if ok else "✗")
            await asyncio.sleep(1)
        await asyncio.sleep(config_store.get("tester_retry_s"))


def _default_name(circuit_url: str) -> str:
    c = circuits_db.get_by_url(circuit_url)
    slug = c["slug"] if c else "circuit"
    return f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _compute_event_key(circuit_url: str, countdown_s: int, title1: str, title2: str = "") -> str:
    """Stable identifier derived from race metadata — used to deduplicate events across imports."""
    slug = circuit_url.rstrip('/').split('/')[-1]
    hours = round(countdown_s / 3600)
    title = f"{title1} {title2}".strip()
    title_norm = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    canon = f"{slug}|{hours}h|{title_norm}"
    return hashlib.sha1(canon.encode()).hexdigest()[:12]


def _decode_ws(raw) -> str:
    """Decode a WebSocket frame to str (bytes or already str)."""
    return raw.decode() if isinstance(raw, bytes) else raw


def _parse_apex_line(line: str) -> dict:
    """Parse a single Apex pipe-delimited message line. Returns type + payload."""
    p = line.strip().split("|")
    if not p or not p[0]:
        return {}
    t = p[0]
    if t in ("title1", "title2") and len(p) >= 2:
        return {"type": t, "value": "|".join(p[1:]).lstrip("|")}
    if t == "dyn1" and len(p) >= 3 and p[1] == "countdown":
        try:
            raw_c = int(p[2])
            return {"type": "countdown", "countdown_s": raw_c // 1000 if raw_c > 86400 else raw_c}
        except ValueError:
            pass
    if t == "init" and len(p) >= 2 and p[1] == "r":
        return {"type": "reset"}
    return {"type": t}


def _merge_stored_hints(stored: Optional[dict], hints: dict, fallback_url: str) -> Optional[dict]:
    """Merge stored annotation with extracted hints. Returns None if not enough info."""
    m_url = (stored or {}).get("circuit_url") or fallback_url
    t1    = (stored or {}).get("title1")      or hints.get("title1", "")
    t2    = (stored or {}).get("title2", "")  or hints.get("title2", "")
    cd    = (stored or {}).get("countdown_s") or hints.get("countdown_s", 0)
    if not t1 or not m_url:
        return None
    key = (stored or {}).get("event_key") or _event_key_for_hints(m_url, t1, t2, cd)
    return {"event_key": key, "title1": t1, "title2": t2, "countdown_s": cd, "circuit_url": m_url}


def _create_ssl_ctx() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _ws_attempts(circuit_url: str, ws_port: int) -> list:
    """Return [(ws_url, ssl_ctx_or_None)] to try in priority order.

    Tries the circuit's known ws_host first, then falls back to www.apex-timing.com.
    """
    ssl_ctx = _create_ssl_ctx()

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

_calendar_events: list[dict] = []
_calendar_task: Optional[asyncio.Task] = None
_calendar_last_sync: Optional[str] = None
_port_discovery_task: Optional[asyncio.Task] = None
_tracks_task: Optional[asyncio.Task] = None
_session_scanner_task: Optional[asyncio.Task] = None
_active_sessions: dict[str, dict] = {}   # slug → {active, checked_at, info}
# ThreadPoolExecutor dédié aux scans de session — isolé du main event loop
_scan_executor = concurrent.futures.ThreadPoolExecutor(max_workers=30, thread_name_prefix="session-scan")
_discovery_logs: list[dict] = []
_discovery_running = False


# ── Recording helpers ─────────────────────────────────────────────────────────

def _path(name: str) -> Path:
    # name peut être "foo" (brut) ou "resolved/mariembourg/foo" (résolu)
    return RECORDINGS_DIR / f"{name}.jsonl"


def _list_recordings() -> list[dict]:
    out = []
    for f in sorted(RECORDINGS_DIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            rel = f.relative_to(RECORDINGS_DIR).with_suffix("").as_posix()
            with f.open() as fh:
                meta = json.loads(fh.readline())
                lines = sum(1 for _ in fh)
            out.append({
                "name": rel,
                "circuit_url": meta.get("circuit_url", ""),
                "ws_port": meta.get("ws_port", 0),
                "started_at": meta.get("started_at", ""),
                "msg_count": lines,
                "size_kb": round(f.stat().st_size / 1024, 1),
                "resolved": rel.startswith("resolved/"),
            })
        except Exception as e:
            logger.debug("Skip recording %s: %s", f.name, e)
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
                        msg = _decode_ws(raw)
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

    _title1 = ""
    _title2 = ""
    _countdown_s = 0
    _event_meta_written = False

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
                            msg = _decode_ws(raw)
                            t = round(time.monotonic() - start, 3)
                            bg_file.write(json.dumps({"t": t, "msg": msg}) + "\n")
                            bg_file.flush()
                            state.bg_recordings[name]["msg_count"] += 1

                            for part in msg.split('\n'):
                                parsed = _parse_apex_line(part)
                                pt = parsed.get("type")
                                if pt == "reset":
                                    _title1 = _title2 = ""
                                    _countdown_s = 0
                                    _event_meta_written = False
                                elif not _event_meta_written:
                                    if pt == "title1":
                                        _title1 = parsed["value"]
                                    elif pt == "title2":
                                        _title2 = parsed["value"]
                                    elif pt == "countdown":
                                        _countdown_s = parsed["countdown_s"]
                            if not _event_meta_written and _title1 and _countdown_s > 0:
                                key = _compute_event_key(circuit_url, _countdown_s, _title1, _title2)
                                bg_file.write(json.dumps({"event_meta": {
                                    "event_key": key,
                                    "title1": _title1,
                                    "title2": _title2,
                                    "countdown_s": _countdown_s,
                                }}) + '\n')
                                bg_file.flush()
                                state.bg_recordings[name]["event_key"] = key
                                _event_meta_written = True
                                logger.info("BG Record event_key=%s (%s)", key, name)
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
    state.bg_recordings[name] = {"task": task, "msg_count": 0, "circuit_url": job["circuit_url"], "ws_port": job["ws_port"]}

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


# ── Calendar ──────────────────────────────────────────────────────────────────

def _load_calendar() -> list[dict]:
    if not CALENDAR_FILE.exists():
        return []
    try:
        return json.loads(CALENDAR_FILE.read_text())
    except Exception:
        return []


def _save_calendar():
    try:
        CALENDAR_FILE.write_text(json.dumps(_calendar_events, indent=2))
    except Exception as e:
        logger.warning("Failed to save calendar: %s", e)


def _job_exists_for(apex_url: str, start_dt: str) -> bool:
    """Return True if a ScheduledJob already covers this event."""
    try:
        event_day = start_dt[:10]
    except Exception:
        return False
    for j in _scheduled_jobs:
        if j.get("circuit_url") == apex_url and j.get("start_at", "")[:10] == event_day:
            return True
    return False


async def _sync_calendar():
    global _calendar_events, _calendar_last_sync
    logger.info("Calendar sync started")

    events = await calendar_sources.fetch_all()
    logger.info("Calendar: %d events found across all scrapers", len(events))

    # Preserve existing apex/job data for already-known events
    existing = {e["uid"]: e for e in _calendar_events}

    enriched: list[dict] = []
    for ev in events:
        d = ev.to_dict()
        prev = existing.get(ev.uid, {})

        # Carry over previously discovered Apex info
        d["apex_url"] = d["apex_url"] or prev.get("apex_url")
        d["apex_ws_port"] = d["apex_ws_port"] or prev.get("apex_ws_port")
        d["scheduled_job_id"] = prev.get("scheduled_job_id")

        # Discover Apex Timing if not yet known
        if not d["apex_url"]:
            apex_url, ws_port = await circuit_discovery.discover(
                ev.circuit_name, ev.country
            )
            if apex_url:
                d["apex_url"] = apex_url
                d["apex_ws_port"] = ws_port

        # Auto-create ScheduledJob (30 min before start) when Apex is known
        if d["apex_url"] and d["apex_ws_port"] and not d["scheduled_job_id"]:
            try:
                start = datetime.fromisoformat(d["start_dt"])
                if start.tzinfo is None:
                    start = start.replace(tzinfo=timezone.utc)
                scheduled_start = start - timedelta(minutes=30)
                if scheduled_start > datetime.now(timezone.utc):
                    if not _job_exists_for(d["apex_url"], d["start_dt"]):
                        prefix = ev.event_name[:30]
                        job: dict = {
                            "id": uuid.uuid4().hex[:8],
                            "circuit_url": d["apex_url"],
                            "ws_port": d["apex_ws_port"],
                            "start_at": scheduled_start.isoformat(),
                            "name_prefix": prefix,
                            "duration_minutes": int(ev.duration_h * 60) + 45,
                            "status": "pending",
                            "recording_name": None,
                        }
                        _scheduled_jobs.append(job)
                        _save_jobs()
                        d["scheduled_job_id"] = job["id"]
                        logger.info("Calendar: auto-scheduled '%s' at %s",
                                    ev.event_name, scheduled_start.isoformat())
            except Exception as e:
                logger.warning("Calendar: auto-schedule failed for %s: %s", ev.event_name, e)

        enriched.append(d)

    _calendar_events = enriched
    _calendar_last_sync = datetime.now(timezone.utc).isoformat()
    _save_calendar()
    logger.info("Calendar sync done: %d events", len(_calendar_events))


async def _calendar_loop():
    """Daily sync: scrape calendars, discover circuits, schedule recordings."""
    # First sync after 5 min (let the proxy finish startup)
    await asyncio.sleep(300)
    while True:
        try:
            await _sync_calendar()
        except Exception as e:
            logger.error("Calendar loop error: %s", e)
        await asyncio.sleep(24 * 3600)


def _disc_log(level: str, msg: str, slug: str = "") -> None:
    from datetime import datetime, timezone
    _discovery_logs.append({"ts": datetime.now(timezone.utc).isoformat(), "level": level, "msg": msg, "slug": slug})
    if len(_discovery_logs) > 400:
        del _discovery_logs[0]


async def _discover_one(c: dict) -> None:
    slug = c.get("slug", "")
    url = c.get("url") or f"https://www.apex-timing.com/live-timing/{slug}/"
    name = c.get("name", slug)
    try:
        # Essai direct (page / index.html / config.js) via circuit_discovery._config_port
        config_port = await circuit_discovery._config_port(url)
        if config_port:
            port = config_port + 3
            circuits_db.update_port(slug, port)
            _disc_log("info", f"→ port {port}", slug)
        else:
            # Fallback : recherche DDG (plusieurs variantes de requête)
            country = c.get("country", "")
            _, found_port = await circuit_discovery.discover(name, country)
            if found_port:
                _disc_log("info", f"DDG → port {found_port}", slug)
            else:
                circuits_db.update_port(slug, -1)
                _disc_log("warn", "non trouvé", slug)
    except Exception as e:
        _disc_log("error", str(e)[:80], slug)
        circuits_db.update_port(slug, -1)


def _fetch_tracks_sync(url: str) -> tuple[str, int]:
    """Blocking fetch of tracks.json. Returns (raw_json_or_empty, http_code)."""
    import urllib.request, urllib.error
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace"), resp.status
    except urllib.error.HTTPError as e:
        return "", e.code
    except Exception:
        return "", 0


async def _fetch_tracks_one(c: dict) -> None:
    slug = c.get("slug", "")
    url = c.get("url") or f"https://www.apex-timing.com/live-timing/{slug}/"
    tracks_url = url.rstrip("/") + "/ftp/tracks.json"
    raw, code = await asyncio.get_event_loop().run_in_executor(None, _fetch_tracks_sync, tracks_url)
    if raw:
        try:
            data = json.loads(raw)
            count = len(data.get("list", []))
            if count:
                circuits_db.update_tracks(slug, raw)
                _disc_log("info", f"tracks ✓ ({count} configs)", slug)
                return
        except Exception:
            pass
    circuits_db.update_tracks(slug, "")
    _disc_log("info", f"tracks vide/{code}", slug)


async def _tracks_loop() -> None:
    """Background loop: fetch tracks.json for circuits that don't have it yet."""
    await asyncio.sleep(10)
    while True:
        pending = circuits_db.get_without_tracks(limit=10)
        if not pending:
            await asyncio.sleep(600)
            continue
        for c in pending:
            await _fetch_tracks_one(c)
            await asyncio.sleep(2)
        await asyncio.sleep(30)


# Types de messages indiquant une session live (flux de données actif)
_LIVE_MSG_TYPES = {"grid", "dyn1", "dyn2", "pass", "flag", "countdown", "best", "entry", "message"}


async def _scan_session_async(c: dict) -> None:
    """Async WS probe running in its own thread event loop — never touches the main loop."""
    slug = c["slug"]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ssl_ctx = _create_ssl_ctx()
    active = False
    info = ""

    title1 = ""
    title2 = ""

    async def _probe(ws_url: str, ssl_ctx_arg) -> bool:
        nonlocal info, title1, title2
        try:
            async with websockets.connect(ws_url, ssl=ssl_ctx_arg, open_timeout=config_store.get("ws_connect_timeout_s"), close_timeout=1) as ws:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + config_store.get("probe_timeout_s")
                found_live = False
                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        break
                    # Stop early once we have live confirmation + title
                    if found_live and title1:
                        break
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except (asyncio.TimeoutError, Exception):
                        break
                    if not isinstance(msg, str):
                        continue
                    for line in msg.split("\n"):
                        parsed = _parse_apex_line(line)
                        pt = parsed.get("type")
                        if not pt:
                            continue
                        if pt in _LIVE_MSG_TYPES:
                            info = pt
                            found_live = True
                        elif pt == "title1":
                            title1 = parsed["value"]
                        elif pt == "title2":
                            title2 = parsed["value"]
                return found_live
        except Exception:
            return False

    active = await _probe(f"wss://{c['ws_host']}:{c['port']}/", ssl_ctx)
    if not active:
        active = await _probe(f"ws://{c['ws_host']}:{c['port']}/", None)

    _active_sessions[slug] = {
        "slug": slug,
        "active": active, "checked_at": now, "info": info,
        "name": c.get("name", slug), "country": c.get("country", ""),
        "port": c["port"], "url": c.get("url", ""),
        "title1": title1, "title2": title2,
    }


def _scan_session_in_thread(c: dict) -> None:
    """Entry point for ThreadPoolExecutor — own event loop, basse priorité CPU."""
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    asyncio.run(_scan_session_async(c))


async def _session_scan_loop() -> None:
    """Background loop: every 60s, scan all reachable circuits in the thread pool."""
    await asyncio.sleep(30)
    loop = asyncio.get_event_loop()
    while True:
        candidates = [c for c in circuits_db.get_all() if c.get("tested") is True and c.get("port", 0) > 0]
        futs = [loop.run_in_executor(_scan_executor, _scan_session_in_thread, c) for c in candidates]
        if futs:
            await asyncio.gather(*futs, return_exceptions=True)
        await asyncio.sleep(config_store.get("scan_interval_s"))


async def _port_discovery_loop():
    """Background loop: resolve port=0 circuits by fetching their configPort."""
    global _discovery_running
    await asyncio.sleep(120)
    while True:
        pending = circuits_db.get_undiscovered(limit=config_store.get("discovery_batch_size"))
        if not pending:
            await asyncio.sleep(config_store.get("discovery_idle_s"))
            continue
        _discovery_running = True
        try:
            for c in pending:
                await _discover_one(c)
        finally:
            _discovery_running = False
        await asyncio.sleep(config_store.get("discovery_interval_s"))


# ── App ───────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduled_jobs, _scheduler_task, _tester_task, _port_discovery_task, _tracks_task, _session_scanner_task
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    s = config_store.load()
    logging.getLogger().setLevel(s.get("log_level", "INFO"))
    circuits_db.init_db()
    _scheduled_jobs.extend(_load_jobs())
    _calendar_events.extend(_load_calendar())
    _scheduler_task = asyncio.create_task(_scheduler_loop())
    _tester_task = asyncio.create_task(_circuit_tester_loop())
    _calendar_task = asyncio.create_task(_calendar_loop())
    _port_discovery_task = asyncio.create_task(_port_discovery_loop())
    _tracks_task = asyncio.create_task(_tracks_loop())
    _session_scanner_task = asyncio.create_task(_session_scan_loop())
    yield
    for task in (_scheduler_task, _tester_task, _calendar_task, _port_discovery_task, _tracks_task, _session_scanner_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
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

# ── Sessions / reconciliation ─────────────────────────────────────────────────

# Fast extractor of the leading "t" value from a JSONL data line
_T_PATTERN = re.compile(r'\{"t":\s*([\d.]+)')


def _to_local(utc_str: str, tz_name: str) -> str:
    """Convert an ISO UTC string to the circuit's local timezone (ISO with offset)."""
    try:
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        return dt.astimezone(ZoneInfo(tz_name)).isoformat(timespec="seconds")
    except Exception:
        return utc_str


def _load_recordings_meta() -> dict:
    try:
        if RECORDINGS_META_FILE.exists():
            return json.loads(RECORDINGS_META_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_recordings_meta(data: dict):
    RECORDINGS_META_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


_HINT_TITLE1 = re.compile(r'title1\|+([^\n\r|][^\n\r]*)')
_HINT_TITLE2 = re.compile(r'title2\|+([^\n\r|][^\n\r]*)')
_HINT_COUNTDOWN = re.compile(r'dyn1\|countdown\|(\d+)')


def _extract_hints(lines: list[str]) -> dict:
    """Extraire title1, title2 et countdown depuis les messages bruts d'un JSONL sans event_meta."""
    title1 = ""
    title2 = ""
    max_cd_ms = 0
    for line in lines[:3000]:  # les titres arrivent toujours dans les premières minutes
        if '"msg"' not in line:
            continue
        try:
            msg = json.loads(line).get("msg", "")
        except Exception:
            continue
        if not title1:
            m = _HINT_TITLE1.search(msg)
            if m:
                title1 = m.group(1).strip()
        if not title2:
            m = _HINT_TITLE2.search(msg)
            if m:
                title2 = m.group(1).strip()
        for m in _HINT_COUNTDOWN.finditer(msg):
            ms = int(m.group(1))
            if ms > max_cd_ms:
                max_cd_ms = ms
    countdown_s = max_cd_ms // 1000 if max_cd_ms > 86400 else max_cd_ms
    return {"title1": title1, "title2": title2, "countdown_s": countdown_s}


_HOURS_IN_TITLE = re.compile(r'(\d+)\s*(?:h(?:eure(?:s)?|our(?:s)?)?)\b', re.IGNORECASE)


def _hours_from_title(title: str) -> int:
    """Extraire la durée en heures depuis le titre (ex: '24H AGADIR' → 24)."""
    m = _HOURS_IN_TITLE.search(title)
    return int(m.group(1)) if m else 0


def _event_key_for_hints(circuit_url: str, title1: str, title2: str, countdown_s: int) -> str:
    h = _hours_from_title(title1) or _hours_from_title(title2)
    cd = (h * 3600) if h else countdown_s
    return _compute_event_key(circuit_url, cd, title1, title2)


def _scan_sessions() -> dict:
    """Scan all recordings, extract event_meta lines, group sessions by event_key."""
    sessions: dict[str, dict] = {}
    unidentified: list[dict] = []
    recordings_meta = _load_recordings_meta()

    all_jsonl = sorted(RECORDINGS_DIR.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for f in all_jsonl:
        # nom relatif sans extension — ex: "foo" ou "resolved/mariembourg/foo"
        rel_name = f.relative_to(RECORDINGS_DIR).with_suffix("").as_posix()
        try:
            with f.open() as fh:
                header = json.loads(fh.readline())
                circuit_url = header.get("circuit_url", "")
                started_at = header.get("started_at", "")
                c = circuits_db.get_by_url(circuit_url)
                tz_name = (c.get("timezone") or "UTC") if c else "UTC"
                circuit_name = c.get("name", "") if c else ""
                country = c.get("country", "") if c else ""
                try:
                    base_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                except Exception:
                    base_dt = None

                found_meta = False
                prev_t = 0.0
                hint_lines: list[str] = []
                for line in fh:
                    m = _T_PATTERN.match(line)
                    if m:
                        prev_t = float(m.group(1))
                    if len(hint_lines) < 3000:
                        hint_lines.append(line)
                    if '"event_meta"' not in line:
                        continue
                    try:
                        em = json.loads(line).get("event_meta")
                        if not em or not em.get("event_key"):
                            continue
                        found_meta = True
                        key = em["event_key"]
                        session_start_utc = (
                            (base_dt + timedelta(seconds=prev_t)).isoformat()
                            if base_dt else started_at
                        )
                        rec_entry = {
                            "name": rel_name,
                            "resolved": rel_name.startswith("resolved/"),
                            "started_at_utc": session_start_utc,
                            "started_at_local": _to_local(session_start_utc, tz_name),
                            "timezone": tz_name,
                        }
                        if key not in sessions:
                            sessions[key] = {
                                "event_key": key,
                                "title1": em.get("title1", ""),
                                "title2": em.get("title2", ""),
                                "countdown_s": em.get("countdown_s", 0),
                                "circuit_url": circuit_url,
                                "circuit_name": circuit_name,
                                "country": country,
                                "recordings": [],
                            }
                        if not any(r["name"] == rel_name for r in sessions[key]["recordings"]):
                            sessions[key]["recordings"].append(rec_entry)
                    except Exception:
                        pass

            if not found_meta:
                stem = f.stem
                hints = _extract_hints(hint_lines)
                stored = recordings_meta.get(stem)
                meta = _merge_stored_hints(stored, hints, circuit_url)
                if meta:
                    m_url = meta["circuit_url"]
                    t1, t2, cd, key = meta["title1"], meta["title2"], meta["countdown_s"], meta["event_key"]
                    mc = circuits_db.get_by_url(m_url)
                    m_tz = (mc.get("timezone") or "UTC") if mc else tz_name
                    m_name = mc.get("name", circuit_name) if mc else circuit_name
                    m_country = mc.get("country", country) if mc else country
                    rec_entry = {
                        "name": rel_name,
                        "resolved": rel_name.startswith("resolved/"),
                        "started_at_utc": started_at,
                        "started_at_local": _to_local(started_at, m_tz),
                        "timezone": m_tz,
                    }
                    if key not in sessions:
                        sessions[key] = {
                            "event_key": key,
                            "title1": t1,
                            "title2": t2,
                            "countdown_s": cd,
                            "circuit_url": m_url,
                            "circuit_name": m_name,
                            "country": m_country,
                            "recordings": [],
                        }
                    if not any(r["name"] == rel_name for r in sessions[key]["recordings"]):
                        sessions[key]["recordings"].append(rec_entry)
                else:
                    unidentified.append({
                        "name": rel_name,
                        "resolved": rel_name.startswith("resolved/"),
                        "circuit_url": circuit_url,
                        "circuit_name": circuit_name,
                        "country": country,
                        "started_at_utc": started_at,
                        "started_at_local": _to_local(started_at, tz_name),
                        "timezone": tz_name,
                        "meta": stored,
                        "hints": hints,
                    })
        except Exception as e:
            logger.debug("Skip session scan for %s: %s", f.name, e)

    return {
        "sessions": sorted(
            sessions.values(),
            key=lambda s: s["recordings"][0]["started_at_utc"] if s["recordings"] else "",
            reverse=True,
        ),
        "unidentified": unidentified,
    }


def _slug_for_url(circuit_url: str) -> str:
    c = circuits_db.get_by_url(circuit_url)
    if c:
        return c.get("slug", "unknown")
    # Fallback : dernier segment de l'URL (ex: .../agadir/ → "agadir")
    seg = circuit_url.rstrip("/").split("/")[-1]
    return seg or "unknown"


def _resolve_sessions(dry_run: bool = True) -> dict:
    """Analyse les fichiers JSONL bruts, planifie/exécute copy+split+merge.
    - copy  : fichier propre (1 session) → resolved/{slug}/ avec event_meta injecté
    - split : fichier multi-sessions → N fichiers dans resolved/{slug}/
    - merge : N fichiers même event_key → 1 fichier dans resolved/{slug}/
    Fichiers originaux jamais supprimés."""

    recordings_meta = _load_recordings_meta()

    # --- Pass 1 : analyser chaque fichier brut ---
    files: list[dict] = []
    for f in sorted(RECORDINGS_DIR.glob("*.jsonl"), key=lambda p: p.name):
        try:
            with f.open() as fh:
                header = json.loads(fh.readline())
                all_lines = fh.readlines()
        except Exception as e:
            logger.debug("Skip resolve for %s: %s", f.name, e)
            continue

        # Détection des sessions via event_meta dans le fichier
        sessions_in_file: list[dict] = []
        cur_start = 0
        cur_meta = None
        cur_first_t: Optional[float] = None

        for i, line in enumerate(all_lines):
            lm = _T_PATTERN.match(line)
            if lm:
                t = float(lm.group(1))
                if cur_first_t is None:
                    cur_first_t = t

            if '"init|r|"' in line and cur_meta is not None:
                try:
                    if json.loads(line).get("msg") == "init|r|":
                        sessions_in_file.append({
                            "event_key": cur_meta.get("event_key"),
                            "start_line": cur_start,
                            "end_line": i,
                            "first_t": cur_first_t or 0.0,
                            "event_meta": cur_meta,
                            "injected": False,
                        })
                        cur_start = i
                        cur_meta = None
                        cur_first_t = None
                except Exception:
                    pass
                continue

            if '"event_meta"' in line and cur_meta is None:
                try:
                    em = json.loads(line).get("event_meta")
                    if em and em.get("event_key"):
                        cur_meta = em
                except Exception:
                    pass

        if cur_meta is not None:
            sessions_in_file.append({
                "event_key": cur_meta.get("event_key"),
                "start_line": cur_start,
                "end_line": len(all_lines),
                "first_t": cur_first_t or 0.0,
                "event_meta": cur_meta,
                "injected": False,
            })

        # Pas d'event_meta dans le fichier → utiliser hints ou stored meta
        if not sessions_in_file:
            hints = _extract_hints(all_lines[:3000])
            stored = recordings_meta.get(f.stem)
            meta = _merge_stored_hints(stored, hints, header.get("circuit_url", ""))
            if meta:
                sessions_in_file.append({
                    "event_key": meta["event_key"],
                    "start_line": 0,
                    "end_line": len(all_lines),
                    "first_t": 0.0,
                    "event_meta": meta,
                    "injected": True,
                    "circuit_url": meta["circuit_url"],
                })

        slug = _slug_for_url(header.get("circuit_url", ""))
        # Pour les sessions hint-based, le slug peut être différent (stored meta avec autre circuit)
        if sessions_in_file and sessions_in_file[0].get("injected"):
            slug = _slug_for_url(sessions_in_file[0].get("circuit_url", "")) or slug

        files.append({
            "path": f,
            "stem": f.stem,
            "slug": slug,
            "header": header,
            "lines": all_lines,
            "sessions": sessions_in_file,
        })

    # --- Pass 2 : planifier ---
    actions: list[dict] = []
    skipped: list[str] = []

    # Splits : fichiers avec plusieurs sessions
    for fi in files:
        if len(fi["sessions"]) <= 1:
            continue
        slug = fi["slug"]
        outputs = []
        all_exist = True
        for idx, sess in enumerate(fi["sessions"]):
            ek6 = (sess.get("event_key") or "")[:6] or f"s{idx + 1}"
            out_rel = f"resolved/{slug}/{fi['stem']}__split_{idx + 1}_{ek6}"
            outputs.append(out_rel)
            if not (RESOLVED_DIR / slug / f"{fi['stem']}__split_{idx + 1}_{ek6}.jsonl").exists():
                all_exist = False
        if all_exist:
            skipped.extend(outputs)
            continue
        actions.append({
            "type": "split",
            "source": fi["stem"],
            "session_count": len(fi["sessions"]),
            "outputs": outputs,
            "slug": slug,
        })

    # Copie / merge pour les fichiers à session unique
    ek_sources: dict[str, list[dict]] = {}
    for fi in files:
        if len(fi["sessions"]) != 1:
            continue
        sess = fi["sessions"][0]
        ek = sess.get("event_key")
        if not ek:
            continue
        ek_sources.setdefault(ek, []).append({
            "rel": fi["stem"],
            "path": fi["path"],
            "slug": fi["slug"],
            "started_at": fi["header"].get("started_at", ""),
        })

    # Ajouter aussi les futures sorties de splits au pool ek_sources
    for fi in files:
        if len(fi["sessions"]) <= 1:
            continue
        slug = fi["slug"]
        for idx, sess in enumerate(fi["sessions"]):
            ek = sess.get("event_key")
            if not ek:
                continue
            ek6 = ek[:6]
            stem = f"{fi['stem']}__split_{idx + 1}_{ek6}"
            ek_sources.setdefault(ek, []).append({
                "rel": f"resolved/{slug}/{stem}",
                "path": RESOLVED_DIR / slug / f"{stem}.jsonl",
                "slug": slug,
                "started_at": fi["header"].get("started_at", ""),
            })

    for ek, sources in ek_sources.items():
        slug = sources[0]["slug"]
        if len(sources) == 1:
            src = sources[0]
            if not src["rel"].startswith("resolved/"):  # pas déjà résolu
                out_rel = f"resolved/{slug}/{src['rel']}"
                out_path = RESOLVED_DIR / slug / f"{src['rel']}.jsonl"
                if out_path.exists():
                    skipped.append(out_rel)
                else:
                    actions.append({
                        "type": "copy",
                        "source": src["rel"],
                        "output": out_rel,
                        "out_path": out_path,
                    })
        else:
            # Plusieurs fichiers même event_key → merge
            stem = f"{slug}_{ek}_merged"
            out_rel = f"resolved/{slug}/{stem}"
            out_path = RESOLVED_DIR / slug / f"{stem}.jsonl"
            if out_path.exists():
                skipped.append(out_rel)
            else:
                actions.append({
                    "type": "merge",
                    "event_key": ek,
                    "sources": [s["rel"] for s in sources],
                    "source_paths": [s["path"] for s in sources],
                    "output": out_rel,
                    "out_path": out_path,
                })

    dry_actions = [
        {k: v for k, v in a.items() if k not in ("source_paths", "out_path")}
        for a in actions
    ]

    if dry_run:
        return {"actions": dry_actions, "skipped": skipped, "executed": False}

    # --- Pass 3 : exécuter ---
    created: list[str] = []
    errors: list[str] = []
    split_output_map: dict[str, Path] = {}
    fi_by_stem = {fi["stem"]: fi for fi in files}

    def _write_file(out_path: Path, header: dict, lines: list[str],
                    inject_meta: Optional[dict], first_t: float = 0.0):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w") as out:
            out.write(json.dumps(header) + "\n")
            if inject_meta:
                out.write(json.dumps({"event_meta": inject_meta}) + "\n")
            for line in lines:
                if '"event_meta"' in line:
                    if not inject_meta:
                        out.write(line if line.endswith("\n") else line + "\n")
                    continue  # skip si déjà injecté
                lm = _T_PATTERN.match(line)
                if lm and first_t:
                    try:
                        entry = json.loads(line)
                        entry["t"] = round(entry["t"] - first_t, 3)
                        out.write(json.dumps(entry) + "\n")
                    except Exception:
                        out.write(line if line.endswith("\n") else line + "\n")
                else:
                    out.write(line if line.endswith("\n") else line + "\n")

    # Copies
    for action in [a for a in actions if a["type"] == "copy"]:
        fi = fi_by_stem.get(action["source"])
        if not fi:
            continue
        out_path: Path = action["out_path"]
        if out_path.exists():
            errors.append(f"{action['output']} existe déjà, ignoré")
            continue
        try:
            sess = fi["sessions"][0]
            inject = sess["event_meta"] if sess.get("injected") else None
            _write_file(out_path, fi["header"], fi["lines"], inject)
            created.append(action["output"])
        except Exception as e:
            errors.append(f"Erreur copy {action['output']}: {e}")

    # Splits
    for action in [a for a in actions if a["type"] == "split"]:
        fi = fi_by_stem.get(action["source"])
        if not fi:
            continue
        base_started_at = fi["header"].get("started_at", "")
        try:
            base_dt = datetime.fromisoformat(base_started_at.replace("Z", "+00:00"))
        except Exception:
            base_dt = None

        for idx, sess in enumerate(fi["sessions"]):
            rel = action["outputs"][idx]
            stem = rel.split("/")[-1]
            slug = action["slug"]
            out_path = RESOLVED_DIR / slug / f"{stem}.jsonl"
            split_output_map[rel] = out_path
            if out_path.exists():
                errors.append(f"{rel} existe déjà, ignoré")
                continue
            first_t = sess["first_t"]
            new_header = dict(fi["header"])
            if base_dt and first_t:
                new_header["started_at"] = (base_dt + timedelta(seconds=first_t)).isoformat()
            try:
                inject = sess["event_meta"] if sess.get("injected") else None
                session_lines = fi["lines"][sess["start_line"]:sess["end_line"]]
                _write_file(out_path, new_header, session_lines, inject, first_t)
                created.append(rel)
            except Exception as e:
                errors.append(f"Erreur split {rel}: {e}")

    # Merges
    for action in [a for a in actions if a["type"] == "merge"]:
        rel = action["output"]
        out_path = action["out_path"]
        if out_path.exists():
            errors.append(f"{rel} existe déjà, ignoré")
            continue

        source_data: list[tuple] = []
        for src_rel, src_path in zip(action["sources"], action["source_paths"]):
            actual = split_output_map.get(src_rel, src_path)
            if not actual.exists():
                errors.append(f"Source {src_rel} introuvable")
                continue
            try:
                with actual.open() as fh:
                    hdr = json.loads(fh.readline())
                    lns = fh.readlines()
                source_data.append((hdr, lns))
            except Exception as e:
                errors.append(f"Lecture {src_rel}: {e}")

        if len(source_data) < 2:
            errors.append(f"Pas assez de sources pour {rel}")
            continue

        source_data.sort(key=lambda x: x[0].get("started_at", ""))
        merged_header = dict(source_data[0][0])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with out_path.open("w") as out:
                out.write(json.dumps(merged_header) + "\n")
                max_t = 0.0
                meta_written = False
                for hdr, lns in source_data:
                    t_offset = max_t
                    file_max_t = 0.0
                    for line in lns:
                        if '"event_meta"' in line:
                            if not meta_written:
                                out.write(line if line.endswith("\n") else line + "\n")
                                meta_written = True
                            continue
                        lm = _T_PATTERN.match(line)
                        if lm:
                            try:
                                entry = json.loads(line)
                                new_t = round(entry["t"] + t_offset, 3)
                                file_max_t = max(file_max_t, new_t)
                                entry["t"] = new_t
                                out.write(json.dumps(entry) + "\n")
                            except Exception:
                                out.write(line if line.endswith("\n") else line + "\n")
                        else:
                            out.write(line if line.endswith("\n") else line + "\n")
                    max_t = file_max_t + 1.0
            created.append(rel)
        except Exception as e:
            errors.append(f"Erreur merge {rel}: {e}")

    return {"actions": dry_actions, "skipped": skipped, "executed": True, "created": created, "errors": errors}


def _bg_recordings_status() -> list:
    live_marked = False
    result = []
    for n, e in state.bg_recordings.items():
        is_live = (
            not live_marked
            and state.mode == "live"
            and e.get("circuit_url") == state.circuit_url
        )
        if is_live:
            live_marked = True
        result.append({
            "name": n,
            "msg_count": e["msg_count"],
            "circuit_url": e.get("circuit_url", ""),
            "ws_port": e.get("ws_port", 0),
            "is_live_rec": is_live,
            "event_key": e.get("event_key"),
        })
    return result


@app.get("/api/status")
def get_status():
    return {
        "version": APP_VERSION,
        "started_at": _STARTED_AT,
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
        "bg_recordings": _bg_recordings_status(),
        "scheduled_jobs": [
            j for j in _scheduled_jobs if j["status"] in ("pending", "running")
        ],
    }


@app.get("/api/circuits")
def get_circuits():
    return {"circuits": circuits_db.get_all()}


@app.get("/api/circuits/testlog")
def get_testlog():
    return {"log": circuits_db.get_test_log()}


@app.get("/api/circuits/sessions")
def get_active_sessions():
    return {"sessions": list(_active_sessions.values()), "total": len(_active_sessions)}


@app.post("/api/circuits/sessions/scan")
async def trigger_session_scan():
    """Force immediate scan of all reachable circuits."""
    candidates = [c for c in circuits_db.get_all() if c.get("tested") is True and c.get("port", 0) > 0]
    asyncio.create_task(_do_session_scan(candidates))
    return {"ok": True, "scanning": len(candidates)}


async def _do_session_scan(candidates: list) -> None:
    loop = asyncio.get_event_loop()
    futs = [loop.run_in_executor(_scan_executor, _scan_session_in_thread, c) for c in candidates]
    if futs:
        await asyncio.gather(*futs, return_exceptions=True)


class CircuitRequest(BaseModel):
    slug: str
    name: str
    url: str
    port: int
    ws_host: str
    country: str = ""
    timezone: str = ""   # vide = déduit du pays


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


@app.get("/api/circuits/{slug}/tracks")
def get_circuit_tracks(slug: str):
    raw = circuits_db.get_tracks(slug)
    if raw is None:
        raise HTTPException(404, "Tracks not yet fetched for this circuit")
    if raw == "":
        return {"slug": slug, "list": []}
    try:
        data = json.loads(raw)
        tracks = []
        for t in data.get("list", []):
            tracks.append({
                "title": t.get("title", ""),
                "size": t.get("size", {}),
                "times": t.get("times", {}),
                "svg": t.get("svg", ""),
            })
        return {"slug": slug, "list": tracks}
    except Exception:
        return {"slug": slug, "list": []}


@app.get("/api/recordings")
def get_recordings():
    return {"recordings": _list_recordings()}


@app.get("/api/recordings/sessions")
async def get_recording_sessions():
    """Scan all JSONL files and return sessions grouped by event_key with local timestamps.
    Runs in a thread executor — scanning large files can take a few seconds."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _scan_sessions)


class ResolveRequest(BaseModel):
    dry_run: bool = True


@app.post("/api/recordings/resolve")
async def resolve_recordings(req: ResolveRequest):
    """Plan or execute split/merge of JSONL files to get one file per event.
    dry_run=true (default) returns the action plan without touching any file.
    dry_run=false executes — original files are never deleted."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _resolve_sessions(req.dry_run))


class RecordingMetaRequest(BaseModel):
    circuit_url: str
    title1: str
    title2: str = ""
    countdown_s: int


@app.post("/api/recordings/{name:path}/meta")
def set_recording_meta(name: str, req: RecordingMetaRequest):
    meta = _load_recordings_meta()
    event_key = _compute_event_key(req.circuit_url, req.countdown_s, req.title1, req.title2)
    meta[name] = {
        "circuit_url": req.circuit_url,
        "title1": req.title1,
        "title2": req.title2,
        "countdown_s": req.countdown_s,
        "event_key": event_key,
    }
    _save_recordings_meta(meta)
    return {"event_key": event_key}


@app.delete("/api/recordings/{name:path}/meta")
def delete_recording_meta(name: str):
    meta = _load_recordings_meta()
    meta.pop(name, None)
    _save_recordings_meta(meta)
    return {"ok": True}


@app.get("/api/recordings/{name:path}/download")
def download_recording(name: str):
    path = _path(name)
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(str(path), media_type="application/x-ndjson", filename=f"{Path(name).name}.jsonl")


@app.delete("/api/recordings/{name:path}")
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
    c = circuits_db.get_by_url(req.circuit_url)
    state.mode = "live"
    state.circuit_url = req.circuit_url
    state.ws_port = req.ws_port
    state.ws_host = c["ws_host"] if c else "www.apex-timing.com"
    state.recording_name = None
    state.recording_msg_count = 0
    # Recording is always a bg_recording — survives circuit switches
    if not any(e.get("circuit_url") == req.circuit_url for e in state.bg_recordings.values()):
        bg_name = req.name or _default_name(req.circuit_url)
        while _path(bg_name).exists() or bg_name in state.bg_recordings:
            bg_name += "_"
        bg_task = asyncio.create_task(_run_bg_record(req.circuit_url, req.ws_port, bg_name))
        state.bg_recordings[bg_name] = {"task": bg_task, "msg_count": 0, "circuit_url": req.circuit_url, "ws_port": req.ws_port}
    state._apex_task = asyncio.create_task(
        _run_live(req.circuit_url, req.ws_port, False, None)
    )
    return {"ok": True}


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
                msg = _decode_ws(raw)
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
    state.bg_recordings[name] = {"task": task, "msg_count": 0, "circuit_url": req.circuit_url, "ws_port": req.ws_port}
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


@app.patch("/api/schedule/{job_id}")
def update_schedule(job_id: str, req: ScheduleCreateRequest):
    for job in _scheduled_jobs:
        if job["id"] == job_id:
            if job["status"] not in ("pending",):
                raise HTTPException(400, "Only pending jobs can be edited")
            try:
                datetime.fromisoformat(req.start_at)
            except ValueError:
                raise HTTPException(400, "Invalid start_at datetime format")
            job["circuit_url"] = req.circuit_url
            job["ws_port"] = req.ws_port
            job["start_at"] = req.start_at
            job["name_prefix"] = req.name_prefix or None
            job["duration_minutes"] = req.duration_minutes
            _save_jobs()
            return {"ok": True, "job": job}
    raise HTTPException(404, "Job not found")


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


# ── Calendar endpoints ────────────────────────────────────────────────────────

@app.get("/api/calendar")
def get_calendar():
    return {
        "events": _calendar_events,
        "last_sync": _calendar_last_sync,
    }


@app.post("/api/calendar/sync")
async def trigger_calendar_sync():
    asyncio.create_task(_sync_calendar())
    return {"ok": True}


@app.post("/api/calendar/{uid}/schedule")
async def schedule_calendar_event(uid: str):
    ev = next((e for e in _calendar_events if e["uid"] == uid), None)
    if not ev:
        raise HTTPException(404, "Event not found")
    if not ev.get("apex_url"):
        raise HTTPException(400, "No Apex Timing URL for this event — run sync first")
    if ev.get("scheduled_job_id"):
        return {"ok": True, "job_id": ev["scheduled_job_id"], "already_scheduled": True}

    try:
        start = datetime.fromisoformat(ev["start_dt"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        scheduled_start = start - timedelta(minutes=30)
    except Exception:
        raise HTTPException(400, "Invalid start_dt")

    job: dict = {
        "id": uuid.uuid4().hex[:8],
        "circuit_url": ev["apex_url"],
        "ws_port": ev["apex_ws_port"],
        "start_at": scheduled_start.isoformat(),
        "name_prefix": ev["event_name"][:30],
        "duration_minutes": int(ev["duration_h"] * 60) + 45,
        "status": "pending",
        "recording_name": None,
    }
    _scheduled_jobs.append(job)
    _save_jobs()
    ev["scheduled_job_id"] = job["id"]
    _save_calendar()
    return {"ok": True, "job": job}


# ── Track Discovery ───────────────────────────────────────────────────────────

@app.get("/api/discovery/stats")
def discovery_stats():
    return circuits_db.get_stats()


@app.get("/api/discovery/logs")
def discovery_logs_endpoint():
    return {"logs": list(reversed(_discovery_logs[-200:])), "running": _discovery_running}


@app.post("/api/discovery/run")
async def discovery_run():
    global _discovery_running
    if _discovery_running:
        return {"ok": False, "msg": "Découverte déjà en cours"}
    pending = circuits_db.get_undiscovered(limit=10)
    if not pending:
        return {"ok": True, "processed": 0, "msg": "Aucun circuit en attente"}
    _discovery_running = True
    processed = 0
    try:
        for c in pending:
            await _discover_one(c)
            processed += 1
    finally:
        _discovery_running = False
    return {"ok": True, "processed": processed}


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/api/settings")
def get_settings():
    return {"settings": config_store.get_all(), "defaults": config_store.DEFAULTS}


@app.put("/api/settings")
async def update_settings(request: Request):
    body = await request.json()
    saved = config_store.save(body)
    if "log_level" in body:
        logging.getLogger().setLevel(body["log_level"])
    if "scan_workers" in body:
        global _scan_executor
        _scan_executor.shutdown(wait=False)
        _scan_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=int(body["scan_workers"]), thread_name_prefix="session-scan"
        )
    return {"ok": True, "settings": saved}


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
