import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from database import engine, SessionLocal, Base
from models import PhysicalKart, ProxyConfig, EventEntry, EventPitStop as DbPitStop, Event, EntryLap, Circuit
from config_store import get_config
from race.state import RaceState, LivePitStop
from race.pit_manager import PitManager
from race.track_condition import TrackConditionMonitor
from race.kart_ranker import KartRanker
from race.event_persister import EventPersister
from race.importer import ImportRunner
from apex.client import ApexClient
from apex.grid_parser import canonical_team_name
from apex.port_discovery import discover_ws_port
from api.routes import router as api_router, init_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# ── Globals ───────────────────────────────────────────────────────────────────

PROXY_WS_URL: Optional[str] = os.environ.get("PROXY_WS_URL")      # e.g. ws://192.168.1.x:9000/ws
# Override HTTP URL for the relay (useful when WS and HTTP URLs differ, e.g. Docker networking)
_PROXY_HTTP_URL_OVERRIDE: Optional[str] = os.environ.get("PROXY_HTTP_URL")  # e.g. http://host.docker.internal:9000
PROXY_HTTP_URL: Optional[str] = None  # derived at startup

state = RaceState()
pit_manager: Optional[PitManager] = None
kart_ranker: Optional[KartRanker] = None
apex_client: Optional[ApexClient] = None
event_persister: Optional[EventPersister] = None
import_runner = ImportRunner()
_ws_clients: list[WebSocket] = []
_active_event_id: Optional[int] = None
_active_event_name: str = ""
_driver_pit_numbers: dict[str, int] = {}   # driver_id → last seen pit_number
_pending_pit_duration: dict[str, int] = {} # driver_id → pit_duration_ms from pit_out
_min_relay_s: int = 3600
_max_relay_s: int = 5400
_circuit_id: Optional[int] = None
_circuit_best_lap_ms: Optional[int] = None  # in-memory cache to avoid per-lap DB reads
_zero_laps_on_next_grid: bool = False  # set when a new event is created mid-stream


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
    base["in_pit"] = d.driver_id in state.active_pit_stops
    # Use internal lap counter when grid doesn't expose a laps column
    if not base.get("laps"):
        base["laps"] = state.driver_lap_counts.get(d.driver_id, 0)
    if kart_ranker:
        base["kart_rating"] = kart_ranker.kart_quality_for_team(d.driver_id)
    else:
        base["kart_rating"] = {
            "kart_label": "?", "rating": "UNKNOWN", "confidence": 0,
            "delta_pct": 0.0, "observations": 0,
            "team_level": "UNKNOWN", "kart_quality": "UNKNOWN",
        }
    return base


def _parse_interval_ms(interval: str) -> int:
    """Parse '1:23.456' or '23.456' interval string into milliseconds. Returns 0 on failure."""
    import re as _re
    s = interval.strip().replace(',', '.')
    m = _re.match(r'^(\d+):(\d{2})\.(\d{1,3})$', s)
    if m:
        return (int(m.group(1)) * 60 + int(m.group(2))) * 1000 + int(m.group(3).ljust(3, '0'))
    m = _re.match(r'^(\d+)\.(\d{1,3})$', s)
    if m:
        return int(m.group(1)) * 1000 + int(m.group(2).ljust(3, '0'))
    return 0


def _fmt_gap(ms: int) -> str:
    m = ms // 60000
    s = (ms % 60000) / 1000
    return f'{m}:{s:06.3f}' if m > 0 else f'{s:.3f}'


def _estimate_lap_ms(drivers: list[dict]) -> Optional[int]:
    """Trimmed mean of drivers' last laps (±2σ filter) — used as '1 lap = X ms'."""
    import statistics as _stats
    times = [
        ms for d in drivers
        if (ms := _parse_interval_ms(str(d.get('last_lap', '') or '').strip()))
    ]
    if len(times) < 3:
        return None
    mean = _stats.mean(times)
    stdev = _stats.stdev(times) if len(times) >= 4 else 0
    trimmed = [x for x in times if abs(x - mean) <= 2 * stdev] if stdev else times
    return round(_stats.mean(trimmed)) if trimmed else None


def _fill_synthetic_gaps(drivers: list[dict]) -> list[dict]:
    """When no circuit-provided gap exists, compute cumulative gap from intervals (sorted by position)."""
    import re as _re2

    def _is_real_gap(s: str) -> bool:
        # Real gaps are pure decimals ("0.086", "1.146") or lap-count ("1 Tour").
        # At race start Apex puts lap times ("1:13.765") in gap — those have ':' and are not real gaps.
        return bool(s) and ':' not in s

    if any(_is_real_gap(d.get('gap', '')) for d in drivers):
        return drivers  # circuit sends real gaps — don't touch

    # Erase stale lap-time values Apex sent before real gaps were available
    for d in drivers:
        if d.get('gap') and ':' in d['gap']:
            d['gap'] = ''

    sorted_d = sorted(drivers, key=lambda d: d.get('position', 9999))
    one_lap_ms = _estimate_lap_ms(drivers)

    cum_ms = 0
    laps_behind = 0  # current lapped group (0 = lead lap)

    for d in sorted_d:
        interval = d.get('interval', '')

        if not interval and d.get('position', 1) == 1:
            d['gap'] = ''  # leader
        elif 'tour' in interval.lower():
            m = _re2.search(r'(\d+)', interval)
            laps_behind = int(m.group(1)) if m else (laps_behind + 1)
            # Always anchor at N × one_lap_ms — each "N Tour(s)" marker resets the group baseline
            cum_ms = laps_behind * one_lap_ms if one_lap_ms else 0
            d['gap'] = ('+' + _fmt_gap(cum_ms)) if one_lap_ms else f'+{laps_behind} tour{"s" if laps_behind > 1 else ""}'
        elif interval:
            ms = _parse_interval_ms(interval)
            if laps_behind > 0:
                if ms and one_lap_ms:
                    cum_ms += ms
                    d['gap'] = '+' + _fmt_gap(cum_ms)
                else:
                    d['gap'] = f'+{laps_behind} tour{"s" if laps_behind > 1 else ""}'
            elif ms:
                cum_ms += ms
                d['gap'] = '+' + _fmt_gap(cum_ms)
            else:
                d['gap'] = ''
        else:
            d['gap'] = ''
    return sorted_d


def _enrich_lanes(lanes: list[dict]) -> list[dict]:
    """Add kart rating to each kart in the pit lane reserve.

    For real kart labels, use rate_kart (looks up via _kart_to_team).
    For placeholders, fall back to the depositing team's current quality
    via from_bib → driver_id → kart_quality_for_team.
    """
    if not kart_ranker:
        return lanes
    bib_to_driver = {d.kart: d.driver_id for d in state.drivers.values()}
    _unknown = {"rating": "UNKNOWN", "confidence": 0, "delta_pct": 0.0, "observations": 0,
                "team_level": "UNKNOWN", "kart_quality": "UNKNOWN"}
    for lane in lanes:
        for kart in lane.get("karts", []):
            label = kart.get("kart_label", "?")
            from_bib = kart.get("from_bib", "")
            if label and label != "?":
                kart["rating"] = kart_ranker.rate_kart(label)
            elif from_bib and from_bib in bib_to_driver:
                kart["rating"] = kart_ranker.kart_quality_for_team(bib_to_driver[from_bib])
            else:
                kart["rating"] = _unknown
    return lanes


def _build_snapshot() -> dict:
    drivers = sorted(state.drivers.values(), key=lambda d: d.position)
    lanes = pit_manager.pit_lanes_snapshot() if pit_manager else []
    _enrich_lanes(lanes)

    # Reserve summary computed from enriched ratings (already resolved per-kart above)
    if lanes:
        counts: dict[str, int] = {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 0}
        for lane in lanes:
            for kart in lane.get("karts", []):
                q = (kart.get("rating") or {}).get("kart_quality", "UNKNOWN").lower()
                counts[q] = counts.get(q, 0) + 1
        total = sum(counts.values())
        reserve_summary = {k: round(v / total * 100) for k, v in counts.items()} if total else {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 100}
    else:
        reserve_summary = {}

    return {
        "active_event_id": _active_event_id,
        "active_event_name": _active_event_name,
        "min_relay_s": _min_relay_s,
        "max_relay_s": _max_relay_s,
        "title1": state.title1,
        "title2": state.title2,
        "session_type": state.session_type(),
        "countdown": state.countdown,
        "connected": state.connected,
        "drivers": _fill_synthetic_gaps([_enrich_driver(d) for d in drivers]),
        "lanes": lanes,
        "reserve_summary": reserve_summary,
        "pit_history": [
            {
                "bib": p.bib, "team": p.team, "kart_in": p.kart_label,
                "kart_out": p.kart_out_label, "position": p.position,
                "pit_number": p.pit_number, "pit_lap_ms": p.pit_lap_ms,
                "timestamp": p.timestamp.isoformat(), "duration_s": p.duration_s,
            }
            for p in state.pit_history[-50:]
        ],
    }


def _seed_lap_counts_from_db():
    """After grid reconnect, fill driver_lap_counts from DB for drivers where grid provides no lap data."""
    from sqlalchemy import func as _func
    try:
        with SessionLocal() as db:
            rows = (
                db.query(EventEntry.apex_driver_id, _func.max(EntryLap.lap_number))
                .join(EntryLap, EntryLap.entry_id == EventEntry.id)
                .filter(EventEntry.event_id == _active_event_id)
                .group_by(EventEntry.apex_driver_id)
                .all()
            )
        for apex_id, max_lap in rows:
            if max_lap and apex_id in state.drivers:
                drv = state.drivers.get(apex_id)
                # Only seed when Apex provides no lap data (c0-layout circuits)
                if drv and drv.laps == 0:
                    state.driver_lap_counts[apex_id] = max_lap
                    drv.laps = max_lap
    except Exception:
        logger.exception("Failed to seed lap counts from DB")


async def on_apex_event(event: str, data: dict):
    """Forward Apex events to all WebSocket clients, enriched with kart ratings."""
    if event == "grid":
        global _zero_laps_on_next_grid
        if _zero_laps_on_next_grid:
            # New event just created — ignore any lap counts from the grid (recording may start mid-session)
            for drv in state.drivers.values():
                drv.laps = 0
            state.driver_lap_counts.clear()
            _zero_laps_on_next_grid = False
        elif _active_event_id:
            # Seed lap counts from DB for drivers where the grid provides no laps (c0 circuits or reconnect)
            _seed_lap_counts_from_db()
        return
    elif event == "pit_stop":
        kart_label = data.get("kart_label", "?")
        if kart_ranker and kart_label != "?":
            data["kart_rating"] = kart_ranker.rate_kart(kart_label)
        if event_persister:
            ts_str = data.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str) if ts_str else datetime.now(timezone.utc)
            except ValueError:
                ts = datetime.now(timezone.utc)
            event_persister.record_pit_stop(
                driver_id=data.get("driver_id", ""),
                bib=data.get("bib", ""),
                team_name=canonical_team_name(data.get("team", "")),
                pit_number=data.get("pit_number", 0),
                lap_number_in=data.get("lap", 0),
                kart_in_label=kart_label,
                entered_at=ts,
            )
    elif event == "pit_out":
        driver_id_out = data.get("driver_id", "")
        drv = state.drivers.get(driver_id_out)
        driver_in_name = drv.driver_name if drv else ""
        # Reset quality immediately at pit exit
        if kart_ranker and driver_id_out:
            kart_ranker.on_pit_out(driver_id_out, driver_in_name)
        if event_persister:
            dur_s = data.get("duration_s")
            event_persister.complete_pit_stop(
                driver_id=driver_id_out,
                pit_number=data.get("pit_number", 0),
                kart_out_label=data.get("new_kart_label"),
                exited_at=datetime.now(timezone.utc),
                stop_duration_ms=dur_s * 1000 if dur_s else None,
                pit_lap_ms=data.get("pit_lap_ms"),
            )
            if dur_s and driver_id_out:
                _pending_pit_duration[driver_id_out] = int(dur_s * 1000)
            # Update driver_in on the just-closed stint
            if driver_in_name and driver_id_out:
                event_persister.update_stint_driver_in(driver_id_out, driver_in_name)
    elif event == "pit_lap_update":
        if event_persister:
            event_persister.update_pit_lap(
                driver_id=data.get("driver_id", ""),
                pit_number=data.get("pit_number", 0),
                pit_lap_ms=data.get("pit_lap_ms", 0),
            )
            event_persister.update_stint_out_lap(
                driver_id=data.get("driver_id", ""),
                out_lap_ms=data.get("pit_lap_ms", 0),
            )
    await broadcast(event, data)


def on_lap_completed(driver_id: str, lap_ms: int, is_pit: bool, pit_number: int, lap_number: int = 0):
    """Called from the apex client each time a lap is detected."""
    global _driver_pit_numbers, _pending_pit_duration, _circuit_best_lap_ms

    if is_pit and driver_id in state.active_pit_stops:
        state.active_pit_stops[driver_id].pit_lap_ms = lap_ms

    entry = state.drivers.get(driver_id)
    driver_name = entry.driver_name if entry else ""
    team_name = canonical_team_name(entry.team) if entry else ""
    bib = entry.kart if entry else ""

    # Detect new stint (pit_number increased since last seen lap)
    prev_pit = _driver_pit_numbers.get(driver_id, -1)
    if pit_number > prev_pit:
        _driver_pit_numbers[driver_id] = pit_number
        if event_persister and _active_event_id and bib:
            kart_label_for_stint = state.kart_assignments.get(driver_id, "?")
            pit_dur = _pending_pit_duration.pop(driver_id, None)
            event_persister.open_stint(
                driver_id=driver_id,
                bib=bib,
                team_name=team_name,
                stint_number=pit_number,
                kart_label=kart_label_for_stint,
                started_at=datetime.now(timezone.utc),
                driver_name=driver_name,
                pit_duration_ms=pit_dur,
            )

    if event_persister and _active_event_id and bib:
        event_persister.record_lap(
            driver_id=driver_id,
            bib=bib,
            team_name=team_name,
            lap_number=lap_number,
            lap_ms=lap_ms,
            is_pit_lap=is_pit,
        )

    if event_persister and _active_event_id and bib and not is_pit and lap_number > 0:
        event_persister.record_stint_lap(driver_id=driver_id, lap_number=lap_number, lap_ms=lap_ms)

    # Update circuit best lap if this is a valid non-pit lap (min 30s to reject spurious signals)
    if not is_pit and lap_ms >= 30_000 and lap_number > 0 and _circuit_id:
        if _circuit_best_lap_ms is None or lap_ms < _circuit_best_lap_ms:
            _circuit_best_lap_ms = lap_ms
            with SessionLocal() as db:
                circ = db.get(Circuit, _circuit_id)
                if circ and (circ.best_lap_ms is None or lap_ms < circ.best_lap_ms):
                    circ.best_lap_ms = lap_ms
                    db.commit()
                    logger.info("Circuit %d new best lap: %dms", _circuit_id, lap_ms)

    if not kart_ranker:
        return
    kart_label = state.kart_assignments.get(driver_id, "?")
    kart_ranker.record_lap(
        team_id=driver_id,
        kart_label=kart_label,
        lap_ms=lap_ms,
        is_pit=is_pit,
        pit_number=pit_number,
        driver_name=driver_name,
        team_name=team_name,
        category=entry.category if entry else "",
    )


async def _reanalyze_event_async(event_id: int) -> None:
    """Run kart quality reanalysis in the background after a stint closes."""
    try:
        from api.routes import _reanalyze_event_stints
        loop = asyncio.get_event_loop()
        def _do():
            with SessionLocal() as db:
                return _reanalyze_event_stints(event_id, db)
        updated = await loop.run_in_executor(None, _do)
        logger.debug("Reanalysis: updated %d stints for event %d", updated, event_id)
    except Exception:
        logger.exception("Reanalysis failed (non-fatal)")


def on_pit_detected(driver_id: str):
    """Called when a pit stop is first detected."""
    driver = state.drivers.get(driver_id)
    driver_out = driver.driver_name if driver else ""
    if kart_ranker:
        kart_ranker.on_pit_stop(driver_id)
    if event_persister:
        stats: dict = {}
        kq = "UNKNOWN"
        if kart_ranker:
            stats = kart_ranker.get_stint_stats(driver_id)
            team = kart_ranker._teams.get(driver_id)
            if team:
                kq, _ = kart_ranker._kart_quality(team, kart_ranker._field_avg(), kart_ranker._quartile_thresholds())
        event_persister.close_stint(
            driver_id=driver_id,
            ended_at=datetime.now(timezone.utc),
            driver_out=driver_out,
            kart_quality=kq,
            best_lap_ms=stats.get("best_lap_ms"),
            avg_lap_ms=stats.get("avg_lap_ms"),
            std_dev_ms=stats.get("std_dev_ms"),
            lap_count=stats.get("lap_count", 0),
        )
        if _active_event_id:
            asyncio.create_task(_reanalyze_event_async(_active_event_id))


_ticker_task: Optional[asyncio.Task] = None


async def _grid_ticker():
    """Broadcast the current driver grid every second so the frontend stays live."""
    while True:
        await asyncio.sleep(1)
        if state.drivers:
            drivers = sorted(state.drivers.values(), key=lambda d: d.position)
            lanes = pit_manager.pit_lanes_snapshot() if pit_manager else []
            _enrich_lanes(lanes)
            if lanes:
                counts_t: dict[str, int] = {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 0}
                for lane in lanes:
                    for kart in lane.get("karts", []):
                        q = (kart.get("rating") or {}).get("kart_quality", "UNKNOWN").lower()
                        counts_t[q] = counts_t.get(q, 0) + 1
                total_t = sum(counts_t.values())
                rsummary = {k: round(v / total_t * 100) for k, v in counts_t.items()} if total_t else {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 100}
            else:
                rsummary = {}
            await broadcast("grid", {
                "drivers": _fill_synthetic_gaps([_enrich_driver(d) for d in drivers]),
                "lanes": lanes,
                "reserve_summary": rsummary,
            })


async def _restore_event_state(event_id: int):
    """Reload pit history and kart assignments from DB after a crash (direct connection only)."""
    with SessionLocal() as db:
        entries = {e.id: e for e in db.query(EventEntry).filter_by(event_id=event_id).all()}
        if not entries:
            return
        pit_stops = (db.query(DbPitStop)
                       .filter_by(event_id=event_id)
                       .order_by(DbPitStop.entered_at)
                       .all())
        history: list[LivePitStop] = []
        latest_kart: dict[str, str] = {}
        for ps in pit_stops:
            entry = entries.get(ps.entry_id)
            if not entry or not entry.apex_driver_id:
                continue
            driver_id = entry.apex_driver_id
            live_ps = LivePitStop(
                driver_id=driver_id,
                kart_label=ps.kart_in_label or "?",
                team=entry.team_name,
                bib=entry.bib,
                position=0,
                lap=ps.lap_number_in,
                pit_number=ps.pit_number,
                timestamp=(ps.entered_at.replace(tzinfo=timezone.utc)
                           if ps.entered_at else datetime.now(timezone.utc)),
                kart_out_label=ps.kart_out_label,
                pit_lap_ms=ps.pit_lap_ms,
                exited_at=(ps.exited_at.replace(tzinfo=timezone.utc)
                           if ps.exited_at else None),
            )
            history.append(live_ps)
            if ps.exited_at and ps.kart_out_label:
                latest_kart[driver_id] = ps.kart_out_label
    state.pit_history = history
    state.kart_assignments.update(latest_kart)
    if history:
        logger.info("Restored %d pit stops and %d kart assignments from DB (event %d)",
                    len(history), len(latest_kart), event_id)


async def _start_apex(cfg):
    """Start the Apex client with the given config. Called at startup and on event activation.

    Requires an active event in the DB. If none is found, starts the ticker without connecting
    to Apex Timing so the frontend receives snapshots with active_event_id=null.
    """
    global apex_client, pit_manager, kart_ranker, event_persister, _ticker_task
    global _active_event_id, _active_event_name, _min_relay_s, _max_relay_s  # noqa
    global _circuit_id, _circuit_best_lap_ms

    from models import Event as EventModel
    with SessionLocal() as db:
        active_ev = db.query(EventModel).filter(EventModel.is_active == True).first()

    if active_ev:
        _active_event_id = active_ev.id
        _active_event_name = active_ev.name
        _min_relay_s = active_ev.min_relay_s
        _max_relay_s = active_ev.max_relay_s
    else:
        _active_event_id = None
        _active_event_name = ""
        event_persister = None

    # Cache circuit identity for best-lap tracking
    with SessionLocal() as db:
        _circ = db.query(Circuit).filter(Circuit.circuit_url == cfg.circuit_url).first()
        if _circ:
            _circuit_id = _circ.id
            _circuit_best_lap_ms = _circ.best_lap_ms
        else:
            _circuit_id = None
            _circuit_best_lap_ms = None

    circuit_url = os.environ.get("CIRCUIT_URL") or cfg.circuit_url
    port = int(os.environ.get("WS_PORT") or 0) or cfg.ws_port_override or 0

    # Determine connection mode
    effective_proxy_url = PROXY_WS_URL or (cfg.proxy_ws_url if cfg.source == "proxy" else None)
    has_connection = bool(effective_proxy_url or circuit_url)

    if not has_connection:
        logger.info("No circuit URL configured — waiting for user to connect.")
        init_router(state, None, None, restart_cb=restart_apex_client, stop_cb=stop_apex_client_only,
                    reset_live_cb=_reset_live_state, get_active_event_id=lambda: _active_event_id,
                    import_runner=import_runner, broadcast_cb=broadcast,
                    session_factory=SessionLocal, get_proxy_http_url_cb=_get_proxy_http_url)
        _ticker_task = asyncio.create_task(_grid_ticker())
        return

    if not effective_proxy_url and not port:
        logger.info("Discovering WS port for %s ...", circuit_url)
        port = await discover_ws_port(circuit_url) or 0
    state.ws_port = port
    state.circuit_url = circuit_url

    logger.info("Apex client starting (port=%d, event_id=%s)", port, _active_event_id)

    track_monitor = TrackConditionMonitor()
    kart_ranker = KartRanker(track_monitor)
    pit_manager = PitManager(state, cfg)

    # Seed kart_ranker from most recent previous event on the same circuit
    if _active_event_id:
        with SessionLocal() as db:
            prev = (
                db.query(Event)
                .filter(Event.circuit_url == cfg.circuit_url, Event.id != _active_event_id)
                .order_by(Event.id.desc())
                .first()
            )
            if prev:
                n = kart_ranker.seed_from_previous_event(prev.id, db)
                if n:
                    logger.info("Historical priors loaded from event '%s' (%d teams)", prev.name, n)

    # Populate initial reserve pool from pre-registered physical karts
    with SessionLocal() as db:
        all_karts = db.query(PhysicalKart).all()
        if all_karts:
            reserve_karts = [(k.kart_label, k.id) for k in all_karts][: cfg.total_reserve_karts]
        else:
            n = cfg.total_reserve_karts
            reserve_karts = [(f"K{i+1:02d}", 0) for i in range(n)]
    if reserve_karts:
        state.pit_lanes.clear()
        pit_manager.init_reserve(reserve_karts)

    # Wire up event persister only when we have an active event
    if _active_event_id:
        event_persister = EventPersister(_active_event_id, SessionLocal)

    init_router(state, pit_manager, kart_ranker, restart_cb=restart_apex_client, stop_cb=stop_apex_client_only,
                reset_live_cb=_reset_live_state, get_active_event_id=lambda: _active_event_id,
                import_runner=import_runner, broadcast_cb=broadcast,
                session_factory=SessionLocal, get_proxy_http_url_cb=_get_proxy_http_url)

    if effective_proxy_url:
        apex_client = ApexClient(
            state, on_apex_event, pit_manager,
            on_lap_cb=on_lap_completed,
            on_pit_cb=on_pit_detected,
            ws_url=effective_proxy_url,
            on_reset_cb=_reset_live_state,
            on_session_change_cb=_auto_create_and_activate_session,
            max_attempts=None,
        )
        asyncio.create_task(apex_client.run())
        logger.info("Apex client started (proxy: %s)", effective_proxy_url)
    elif port:
        if _active_event_id:
            await _restore_event_state(_active_event_id)
        apex_client = ApexClient(
            state, on_apex_event, pit_manager,
            on_lap_cb=on_lap_completed,
            on_pit_cb=on_pit_detected,
            on_session_change_cb=_auto_create_and_activate_session,
            max_attempts=None,
        )
        asyncio.create_task(apex_client.run())
        logger.info("Apex client started (port %d)", port)
    else:
        logger.warning("No WS port — set WS_PORT env var or configure in UI")

    _ticker_task = asyncio.create_task(_grid_ticker())


async def _auto_create_and_activate_session(init_type: str, title1: str, title2: str) -> None:
    """Called by ApexClient when a new Apex session is detected (init|r| or init|p| with title change).
    Creates or reuses an event in DB and resets live state without restarting the WS connection.
    """
    global _active_event_id, _active_event_name, event_persister, _min_relay_s, _max_relay_s, _zero_laps_on_next_grid

    name = f"{title1} — {title2}" if title2 else title1

    # Same session: only reset state for hard resets (init|r|), ignore soft re-inits
    if name == _active_event_name:
        if init_type == "r":
            logger.info("Session '%s' re-init (init|r|) — resetting live state", name)
            _zero_laps_on_next_grid = True
            await _reset_live_state()
        return

    circuit_url = state.circuit_url
    logger.info("New session detected: '%s' (init_type=%s)", name, init_type)

    with SessionLocal() as db:
        cfg = get_config(db)

        # Always create a fresh event for a new live session — never reuse old/imported data
        db.query(Event).update({"is_active": False})

        ev = Event(
            name=name,
            circuit_url=circuit_url,
            ws_port_override=state.ws_port,
            num_lanes=cfg.num_lanes,
            min_pit_duration_s=cfg.min_pit_duration_s,
            min_relay_s=cfg.min_relay_duration_s,
            max_relay_s=cfg.max_relay_duration_s,
            is_active=True,
        )
        db.add(ev)
        db.commit()
        db.refresh(ev)
        logger.info("Auto-created event '%s' (id=%d)", name, ev.id)

        _active_event_id = ev.id
        _active_event_name = ev.name
        _min_relay_s = ev.min_relay_s
        _max_relay_s = ev.max_relay_s

    event_persister = EventPersister(_active_event_id, SessionLocal)
    # For paused/historical sessions the initial grid has stale lap counts → zero them.
    # For live races (init|r|) the grid's current lap values are accurate and must be kept.
    _zero_laps_on_next_grid = (init_type == "p")
    await _reset_live_state()


async def _reset_live_state():
    """Reset in-memory live state (called on proxy reset signal)."""
    global _driver_pit_numbers, _pending_pit_duration
    state.drivers.clear()
    state.pit_lanes.clear()
    state.active_pit_stops.clear()
    state.pit_history.clear()
    state.kart_assignments.clear()
    state.driver_lap_counts.clear()
    state.title1 = ""
    state.title2 = ""
    state.countdown = 0
    state.comments = []
    _driver_pit_numbers.clear()
    _pending_pit_duration.clear()
    if kart_ranker:
        kart_ranker.reset_live_data()  # preserves historical priors from previous events
    if event_persister:
        event_persister.clear_cache()
    # Re-populate reserve lanes after clearing — pit_manager config stays valid
    if pit_manager:
        with SessionLocal() as db:
            cfg = get_config(db)
            all_karts = db.query(PhysicalKart).all()
            if all_karts:
                reserve_karts = [(k.kart_label, k.id) for k in all_karts][: cfg.total_reserve_karts]
            else:
                reserve_karts = [(f"K{i+1:02d}", 0) for i in range(cfg.total_reserve_karts)]
        if reserve_karts:
            pit_manager.init_reserve(reserve_karts)
    await broadcast("snapshot", _build_snapshot())
    logger.info("Live state reset (proxy replay)")


async def stop_apex_client_only():
    """Stop the Apex client without restarting — used by the disconnect button."""
    global apex_client
    logger.info("Manual disconnect — stopping Apex client")
    if apex_client:
        await apex_client.stop()
        apex_client = None
    state.connected = False
    await broadcast("snapshot", _build_snapshot())


async def restart_apex_client(new_cfg):
    """Stop the current client, reset state, and start fresh with new_cfg."""
    global apex_client, event_persister, _ticker_task, _driver_pit_numbers, _pending_pit_duration

    logger.info("Restarting Apex client for %s", new_cfg.circuit_url)

    if _ticker_task and not _ticker_task.done():
        _ticker_task.cancel()
        try:
            await _ticker_task
        except asyncio.CancelledError:
            pass
        _ticker_task = None

    if apex_client:
        await apex_client.stop()
        apex_client = None

    event_persister = None
    await _reset_live_state()

    await _start_apex(new_cfg)
    await broadcast("snapshot", _build_snapshot())


@asynccontextmanager
async def lifespan(app: FastAPI):
    global PROXY_HTTP_URL

    Base.metadata.create_all(bind=engine)
    from database import run_migrations
    run_migrations(engine)

    with SessionLocal() as db:
        cfg0 = get_config(db)
    active_proxy = PROXY_WS_URL or (cfg0.proxy_ws_url if cfg0.source == "proxy" else None)
    if active_proxy:
        PROXY_HTTP_URL = active_proxy.replace("ws://", "http://").replace("wss://", "https://").rsplit("/", 1)[0]
        logger.info("Proxy HTTP relay: %s", PROXY_HTTP_URL)

    with SessionLocal() as db:
        cfg = get_config(db)

    await _start_apex(cfg)

    yield

    if _ticker_task and not _ticker_task.done():
        _ticker_task.cancel()
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


# ── Proxy relay ───────────────────────────────────────────────────────────────

def _get_proxy_http_url() -> Optional[str]:
    """Return the HTTP URL to reach the proxy service for API relay."""
    if _PROXY_HTTP_URL_OVERRIDE:
        return _PROXY_HTTP_URL_OVERRIDE.rstrip("/")
    if PROXY_WS_URL:
        ws = PROXY_WS_URL
    else:
        with SessionLocal() as db:
            cfg = get_config(db)
            if cfg.proxy_ws_url:
                ws = cfg.proxy_ws_url
            else:
                first = db.query(ProxyConfig).first()
                if not first:
                    return None
                ws = first.ws_url
    return ws.replace("ws://", "http://").replace("wss://", "https://").rsplit("/", 1)[0]


@app.api_route("/proxy-api/{path:path}", methods=["GET", "POST", "DELETE", "PATCH"])
async def proxy_relay(path: str, request: Request):
    """Forward /proxy-api/* to the proxy service HTTP API."""
    http_url = _get_proxy_http_url()
    if not http_url:
        return Response(
            content='{"error": "Proxy non configuré"}',
            status_code=503,
            media_type="application/json",
        )
    body = await request.body()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.request(
            method=request.method,
            url=f"{http_url}/api/{path}",
            content=body,
            headers={"Content-Type": request.headers.get("Content-Type", "application/json")},
        )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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
