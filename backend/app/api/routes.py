import math
from dataclasses import asdict
from datetime import datetime
from typing import Optional, Callable, Awaitable

import httpx
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session as DBSession

from database import get_db
from config_store import get_config, set_config
from models import (PhysicalKart, Event, EventSchema,
                    EventCreateSchema, Circuit, CIRCUIT_PRESETS, ProxyConfig,
                    EventEntry, EntryPilot, EntryLap, EventPitStop, PilotEventSummary)
from apex.lap_api import fetch_driver_laps
from apex.message_recorder import recorder

router = APIRouter()

# Injected by main.py after startup
_state = None
_pit_manager = None
_kart_ranker = None
_restart_cb: Optional[Callable] = None
_stop_cb: Optional[Callable] = None
_reset_live_cb: Optional[Callable] = None
_get_active_event_id: Optional[Callable] = None
_import_runner = None
_broadcast_cb: Optional[Callable] = None
_session_factory: Optional[Callable] = None
_get_proxy_http_url_cb: Optional[Callable] = None


def init_router(state, pit_manager, kart_ranker, restart_cb=None, stop_cb=None,
                reset_live_cb=None, get_active_event_id=None, import_runner=None,
                broadcast_cb=None, session_factory=None, get_proxy_http_url_cb=None):
    global _state, _pit_manager, _kart_ranker, _restart_cb, _stop_cb
    global _reset_live_cb, _get_active_event_id, _import_runner
    global _broadcast_cb, _session_factory, _get_proxy_http_url_cb
    _state = state
    _pit_manager = pit_manager
    _kart_ranker = kart_ranker
    _restart_cb = restart_cb
    _stop_cb = stop_cb
    _reset_live_cb = reset_live_cb
    _get_active_event_id = get_active_event_id
    _import_runner = import_runner
    _broadcast_cb = broadcast_cb
    _session_factory = session_factory
    _get_proxy_http_url_cb = get_proxy_http_url_cb


# ── Config ───────────────────────────────────────────────────────────────────

@router.get("/config")
def read_config(db: DBSession = Depends(get_db)):
    return get_config(db)


@router.patch("/config")
def update_config(updates: dict = Body(...), db: DBSession = Depends(get_db)):
    return set_config(db, updates)


# ── Live state ────────────────────────────────────────────────────────────────

@router.get("/status")
def status():
    if not _state:
        return {"connected": False}
    return {
        "connected": _state.connected,
        "title1": _state.title1,
        "title2": _state.title2,
        "session_type": _state.session_type(),
        "countdown": _state.countdown,
        "driver_count": len(_state.drivers),
        "ws_port": _state.ws_port,
        "last_update": _state.last_update.isoformat() if _state.last_update else None,
    }


@router.get("/grid")
def grid():
    if not _state:
        raise HTTPException(503, "Not initialized")
    drivers = sorted(_state.drivers.values(), key=lambda d: d.position)
    return {
        "drivers": [
            {**asdict(d), "kart_label": _state.kart_assignments.get(d.driver_id, "?")}
            for d in drivers
        ]
    }


@router.get("/pits/live")
def pits_live():
    if not _state:
        raise HTTPException(503, "Not initialized")
    return {
        "lanes": _pit_manager.pit_lanes_snapshot() if _pit_manager else [],
        "active": [
            {
                "driver_id": ps.driver_id,
                "bib": ps.bib,
                "team": ps.team,
                "kart_label": ps.kart_label,
                "position": ps.position,
                "pit_number": ps.pit_number,
                "seconds_in_pit": int((datetime.utcnow() - ps.timestamp.replace(tzinfo=None)).total_seconds()),
            }
            for ps in _state.active_pit_stops.values()
        ],
    }


def _pit_stop_dict(ps) -> dict:
    return {
        "bib": ps.bib,
        "team": ps.team,
        "kart_in": ps.kart_label,
        "kart_out": ps.kart_out_label,
        "position": ps.position,
        "lap": ps.lap,
        "pit_number": ps.pit_number,
        "pit_lap_ms": ps.pit_lap_ms,
        "timestamp": ps.timestamp.isoformat(),
        "exited_at": ps.exited_at.isoformat() if ps.exited_at else None,
        "duration_s": ps.duration_s,
    }


@router.get("/pits/history")
def pits_history():
    if not _state:
        raise HTTPException(503, "Not initialized")
    return {"history": [_pit_stop_dict(ps) for ps in reversed(_state.pit_history)]}


@router.get("/pits/history/{bib}")
def pits_history_for_team(bib: str):
    if not _state:
        raise HTTPException(503, "Not initialized")
    team_stops = [ps for ps in _state.pit_history if ps.bib == bib]
    return {
        "bib": bib,
        "total_pits": len(team_stops),
        "history": [_pit_stop_dict(ps) for ps in reversed(team_stops)],
    }


@router.get("/comments")
def comments():
    if not _state:
        raise HTTPException(503, "Not initialized")
    return {"comments": _state.comments}


# ── Physical karts ────────────────────────────────────────────────────────────

@router.get("/karts")
def list_karts(db: DBSession = Depends(get_db)):
    karts = db.query(PhysicalKart).all()
    return {"karts": [{"id": k.id, "label": k.kart_label, "notes": k.notes} for k in karts]}


@router.post("/karts")
def create_kart(label: str = Body(..., embed=True),
                notes: str = Body("", embed=True),
                db: DBSession = Depends(get_db)):
    existing = db.query(PhysicalKart).filter(PhysicalKart.kart_label == label).first()
    if existing:
        raise HTTPException(409, "Kart already exists")
    kart = PhysicalKart(kart_label=label, notes=notes)
    db.add(kart)
    db.commit()
    db.refresh(kart)
    return {"id": kart.id, "label": kart.kart_label}


@router.delete("/karts/{kart_id}")
def delete_kart(kart_id: int, db: DBSession = Depends(get_db)):
    kart = db.query(PhysicalKart).filter(PhysicalKart.id == kart_id).first()
    if not kart:
        raise HTTPException(404, "Not found")
    db.delete(kart)
    db.commit()
    return {"ok": True}


# ── Kart assignments ──────────────────────────────────────────────────────────

@router.post("/assignments")
def assign_kart(driver_id: str = Body(..., embed=True),
                kart_label: str = Body(..., embed=True),
                db: DBSession = Depends(get_db)):
    if not _state or not _pit_manager:
        raise HTTPException(503, "Not initialized")
    kart = db.query(PhysicalKart).filter(PhysicalKart.kart_label == kart_label).first()
    pk_id = kart.id if kart else 0
    _pit_manager.set_kart_assignment(driver_id, kart_label, pk_id)
    return {"ok": True, "driver_id": driver_id, "kart_label": kart_label}


@router.post("/pit-reserve/add")
def add_to_reserve(kart_label: str = Body(..., embed=True),
                   lane: int = Body(..., embed=True),
                   db: DBSession = Depends(get_db)):
    if not _pit_manager:
        raise HTTPException(503, "Not initialized")
    kart = db.query(PhysicalKart).filter(PhysicalKart.kart_label == kart_label).first()
    pk_id = kart.id if kart else 0
    _pit_manager.add_kart_to_reserve(kart_label, lane, pk_id)
    return {"ok": True}


@router.delete("/pit-reserve/{kart_label}")
def remove_from_reserve(kart_label: str):
    if not _pit_manager:
        raise HTTPException(503, "Not initialized")
    _pit_manager.remove_kart_from_reserve(kart_label)
    return {"ok": True}


# ── Performance & ranking ─────────────────────────────────────────────────────

@router.get("/performance")
def teams_performance():
    """
    Real-time team performance from the new stint-based model.
    Returns team level (ELITE/FAST/MEDIUM/SLOW) and kart quality (GOOD/NEUTRAL/BAD).
    """
    if not _kart_ranker:
        raise HTTPException(503, "Ranker not initialized")
    return {"teams": _kart_ranker.all_teams_summary()}


@router.get("/performance/{team_id}")
def team_performance(team_id: str):
    if not _kart_ranker:
        raise HTTPException(503, "Ranker not initialized")
    return _kart_ranker.team_summary(team_id)


@router.get("/performance/{team_id}/stints")
def team_perf_stints(team_id: str, db: DBSession = Depends(get_db)):
    """All closed stints for a team in the active event, from DB."""
    if not _get_active_event_id:
        raise HTTPException(503, "Not initialized")
    event_id = _get_active_event_id()
    if not event_id:
        return {"stints": []}
    from sqlalchemy import text as _t
    entry = db.execute(_t(
        "SELECT id FROM event_entries WHERE event_id=:eid AND apex_driver_id=:tid"
    ), {"eid": event_id, "tid": team_id}).fetchone()
    if not entry:
        return {"stints": []}
    rows = db.execute(_t("""
        SELECT driver_name, lap_count, best_lap_ms, avg_lap_ms, std_dev_ms,
               kart_label, kart_quality, started_at
        FROM event_stints
        WHERE entry_id=:eid AND ended_at IS NOT NULL
        ORDER BY stint_number
    """), {"eid": entry.id}).fetchall()

    # Compute field quartiles from all closed stints in this event (min 3 laps)
    field_avgs = db.execute(_t("""
        SELECT es.avg_lap_ms FROM event_stints es
        JOIN event_entries ee ON ee.id=es.entry_id
        WHERE ee.event_id=:eid AND es.ended_at IS NOT NULL AND es.avg_lap_ms IS NOT NULL
          AND es.lap_count >= 3
        ORDER BY es.avg_lap_ms
    """), {"eid": event_id}).fetchall()
    avgs_sorted = [r.avg_lap_ms for r in field_avgs]
    n = len(avgs_sorted)
    def _level_from_avg(avg_ms):
        if not avg_ms or n < 4:
            return "UNKNOWN"
        rank = sum(1 for x in avgs_sorted if x < avg_ms)
        pct = rank / n
        if pct < 0.25:  return "ELITE"
        if pct < 0.50:  return "FAST"
        if pct < 0.75:  return "MEDIUM"
        return "SLOW"

    return {
        "stints": [
            {
                "driver": r.driver_name or "?",
                "lap_count": r.lap_count,
                "total_laps_ms": r.lap_count,
                "avg_ms": int(r.avg_lap_ms) if r.avg_lap_ms else None,
                "best_ms": r.best_lap_ms,
                "std_ms": float(r.std_dev_ms) if r.std_dev_ms else 0.0,
                "delta_pct": None,
                "is_current": False,
                "kart_label": r.kart_label or "",
                "kart_quality": r.kart_quality or "UNKNOWN",
                "level": _level_from_avg(r.avg_lap_ms),
                "started_at": r.started_at,
            }
            for r in rows
        ]
    }


@router.get("/ranking")
def kart_ranking():
    """All teams sorted by level then delta."""
    if not _kart_ranker:
        raise HTTPException(503, "Ranker not initialized")
    return {"ranking": _kart_ranker.all_teams_summary()}


@router.get("/ranking/{kart_label}")
def single_kart_rating(kart_label: str):
    if not _kart_ranker:
        raise HTTPException(503, "Ranker not initialized")
    return _kart_ranker.rate_kart(kart_label)


@router.get("/reserve-summary")
def reserve_summary():
    """% breakdown of GOOD/MEDIUM/BAD/UNKNOWN for karts currently in the reserve."""
    if not _kart_ranker or not _pit_manager:
        raise HTTPException(503, "Not initialized")
    lanes = _pit_manager.pit_lanes_snapshot()
    all_karts = [k["kart_label"] for lane in lanes for k in lane.get("karts", [])]
    return {
        "summary": _kart_ranker.reserve_summary(all_karts),
        "per_kart": [_kart_ranker.rate_kart(k) for k in all_karts],
    }


# ── Driver lap detail ─────────────────────────────────────────────────────────

@router.get("/driver/{driver_id}/laps")
async def driver_laps(driver_id: str):
    if not _state or not _state.ws_port:
        raise HTTPException(503, "Not connected")
    result = await fetch_driver_laps(_state.circuit_url, _state.ws_port, driver_id)
    if "error" in result:
        raise HTTPException(502, result["error"])
    return result


# ── Circuits ──────────────────────────────────────────────────────────────────

def _circuit_to_dict(c: Circuit) -> dict:
    return {
        "id": c.id,
        "is_preset": False,
        "name": c.name,
        "country": c.country,
        "city": c.city,
        "length_km": c.length_km,
        "circuit_url": c.circuit_url,
        "ws_port_override": c.ws_port_override,
        "best_lap_ms": c.best_lap_ms,
        "min_pit_duration_s": c.min_pit_duration_s,
        "min_relay_s": c.min_relay_s,
        "max_relay_s": c.max_relay_s,
        "created_at": c.created_at.isoformat(),
    }


@router.get("/circuits")
def list_circuits(db: DBSession = Depends(get_db)):
    """Return built-in presets followed by user-defined circuits.

    Presets that have been overridden (a custom circuit shares the same circuit_url) are hidden
    so the custom version takes precedence.
    """
    user = [_circuit_to_dict(c) for c in db.query(Circuit).order_by(Circuit.created_at).all()]
    user_urls = {c["circuit_url"] for c in user}
    presets = [
        {"id": None, "is_preset": True, **p}
        for p in CIRCUIT_PRESETS
        if p["circuit_url"] not in user_urls
    ]
    return {"circuits": presets + user}


@router.post("/circuits")
def create_circuit(payload: dict = Body(...), db: DBSession = Depends(get_db)):
    c = Circuit(
        name=payload.get("name", ""),
        country=payload.get("country", ""),
        city=payload.get("city", ""),
        length_km=float(payload.get("length_km", 0.0)),
        circuit_url=payload.get("circuit_url", ""),
        ws_port_override=int(payload.get("ws_port_override", 0)),
        created_at=datetime.utcnow(),
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return _circuit_to_dict(c)


@router.patch("/circuits/{circuit_id}")
def update_circuit(circuit_id: int, payload: dict = Body(...), db: DBSession = Depends(get_db)):
    c = db.query(Circuit).filter(Circuit.id == circuit_id).first()
    if not c:
        raise HTTPException(404, "Circuit not found")
    for key in ("name", "country", "city", "length_km", "circuit_url", "ws_port_override",
                "best_lap_ms", "min_pit_duration_s", "min_relay_s", "max_relay_s"):
        if key in payload:
            setattr(c, key, payload[key])
    db.commit()
    db.refresh(c)
    return _circuit_to_dict(c)


@router.delete("/circuits/{circuit_id}")
def delete_circuit(circuit_id: int, db: DBSession = Depends(get_db)):
    c = db.query(Circuit).filter(Circuit.id == circuit_id).first()
    if not c:
        raise HTTPException(404, "Circuit not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ── Circuit presets (legacy) ──────────────────────────────────────────────────

@router.get("/circuit-presets")
def circuit_presets():
    return {"presets": CIRCUIT_PRESETS}


# ── Events ────────────────────────────────────────────────────────────────────

def _event_to_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "circuit_url": e.circuit_url,
        "ws_port_override": e.ws_port_override,
        "event_date": e.event_date.isoformat() if e.event_date else None,
        "duration_hours": e.duration_hours,
        "min_pit_duration_s": e.min_pit_duration_s,
        "min_relay_s": e.min_relay_s,
        "max_relay_s": e.max_relay_s,
        "num_lanes": e.num_lanes,
        "total_reserve_karts": e.total_reserve_karts,
        "is_active": e.is_active,
        "source": getattr(e, "source", "live"),
        "proxy_ws_url": getattr(e, "proxy_ws_url", ""),
        "created_at": e.created_at.isoformat(),
    }


@router.get("/events")
def list_events(db: DBSession = Depends(get_db)):
    events = db.query(Event).order_by(Event.created_at.desc()).all()
    return {"events": [_event_to_dict(e) for e in events]}


@router.post("/events")
def create_event(payload: EventCreateSchema, db: DBSession = Depends(get_db)):
    ev = Event(
        name=payload.name,
        circuit_url=payload.circuit_url,
        ws_port_override=payload.ws_port_override,
        event_date=payload.event_date,
        duration_hours=payload.duration_hours,
        min_pit_duration_s=payload.min_pit_duration_s,
        min_relay_s=payload.min_relay_s,
        max_relay_s=payload.max_relay_s,
        num_lanes=payload.num_lanes,
        total_reserve_karts=payload.total_reserve_karts,
        is_active=False,
        created_at=datetime.utcnow(),
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return _event_to_dict(ev)


@router.patch("/events/{event_id}")
def update_event(event_id: int, payload: dict = Body(...), db: DBSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    allowed = {"name", "circuit_url", "ws_port_override", "event_date", "duration_hours",
               "min_pit_duration_s", "min_relay_s", "max_relay_s", "num_lanes", "total_reserve_karts",
               "source", "proxy_ws_url"}
    for key, val in payload.items():
        if key not in allowed:
            continue
        if key == "event_date" and isinstance(val, str):
            try:
                val = datetime.fromisoformat(val.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, AttributeError):
                val = None
        setattr(ev, key, val)
    db.commit()
    db.refresh(ev)
    return _event_to_dict(ev)


@router.delete("/events/{event_id}")
def delete_event(event_id: int, db: DBSession = Depends(get_db)):
    from sqlalchemy import text as _text
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    # Delete child tables that have no cascade relationship defined
    db.execute(_text("DELETE FROM event_stint_laps WHERE stint_id IN (SELECT id FROM event_stints WHERE event_id=:eid)"), {"eid": event_id})
    db.execute(_text("DELETE FROM event_stints WHERE event_id=:eid"), {"eid": event_id})
    db.delete(ev)
    db.commit()
    return {"ok": True}


@router.post("/events/{event_id}/reset")
def reset_event(event_id: int, db: DBSession = Depends(get_db)):
    """Delete all recorded tracking data for this event (entries, laps, pit stops, summaries).
    Config fields (circuit, date, rules) are preserved."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")

    entry_ids = [r[0] for r in db.query(EventEntry.id).filter(EventEntry.event_id == event_id).all()]
    if entry_ids:
        db.query(PilotEventSummary).filter(PilotEventSummary.entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(EventPitStop).filter(EventPitStop.entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(EntryLap).filter(EntryLap.entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(EntryPilot).filter(EntryPilot.entry_id.in_(entry_ids)).delete(synchronize_session=False)
        db.query(EventEntry).filter(EventEntry.event_id == event_id).delete(synchronize_session=False)

    ev.best_lap_ms = None
    ev.best_lap_bib = ""
    ev.best_lap_pilot_name = ""
    db.commit()

    # If this is the active event, clear in-memory state so the frontend sees empty standings
    if _reset_live_cb and _get_active_event_id and _get_active_event_id() == event_id:
        import asyncio
        asyncio.create_task(_reset_live_cb())

    return {"ok": True}


def _reanalyze_event_stints(event_id: int, db) -> int:
    """Recompute kart_quality for all completed stints using the final full-event field average.

    Uses each stint's stored avg_lap_ms (already correct, excludes out-laps) to recompute
    kart_score relative to the global field median and per-team skill correction.
    """
    import statistics
    from sqlalchemy import text as _t

    ROCKET_T, FAST_T, BAD_T = -0.015, -0.007, 0.015
    MIN_LAPS = 4

    rows = db.execute(_t("""
        SELECT es.id, es.entry_id, es.avg_lap_ms, es.lap_count
        FROM event_stints es
        JOIN event_entries ee ON ee.id = es.entry_id
        WHERE ee.event_id = :eid AND es.ended_at IS NOT NULL
          AND es.avg_lap_ms IS NOT NULL AND es.lap_count >= :min
    """), {"eid": event_id, "min": MIN_LAPS}).fetchall()

    if not rows:
        return 0

    avgs = [r.avg_lap_ms for r in rows]
    field_avg = statistics.median(avgs)
    if not field_avg:
        return 0

    # Per-entry skill: median raw delta across all their stints
    entry_deltas: dict[int, list[float]] = {}
    for r in rows:
        d = (r.avg_lap_ms - field_avg) / field_avg
        entry_deltas.setdefault(r.entry_id, []).append(d)
    entry_skill = {eid: statistics.median(ds) for eid, ds in entry_deltas.items()}

    updated = 0
    for r in rows:
        raw = (r.avg_lap_ms - field_avg) / field_avg
        score = raw - entry_skill.get(r.entry_id, 0.0)
        if score < ROCKET_T:   kq = "ROCKET"
        elif score < FAST_T:   kq = "FAST"
        elif score > BAD_T:    kq = "BAD"
        else:                  kq = "MEDIUM"
        db.execute(_t("UPDATE event_stints SET kart_quality=:kq WHERE id=:sid"),
                   {"kq": kq, "sid": r.id})
        updated += 1

    db.commit()
    return updated


@router.post("/events/{event_id}/reanalyze")
def reanalyze_event(event_id: int, db: DBSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    updated = _reanalyze_event_stints(event_id, db)
    return {"ok": True, "updated_stints": updated}


@router.post("/events/{event_id}/stop")
async def stop_event(event_id: int, db: DBSession = Depends(get_db)):
    """Stop the Apex client connection without deactivating the event."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    if _stop_cb:
        import asyncio
        asyncio.create_task(_stop_cb())
    return {"ok": True}


@router.post("/events/{event_id}/start")
async def start_event(event_id: int, db: DBSession = Depends(get_db)):
    """Reconnect using the event's current source config (proxy or live Apex)."""
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    karts_per_lane = ev.total_reserve_karts // max(ev.num_lanes, 1)
    ev_source = getattr(ev, "source", "live")
    ev_proxy_ws_url = getattr(ev, "proxy_ws_url", "")
    new_config = set_config(db, {
        "circuit_url":          ev.circuit_url,
        "ws_port_override":     ev.ws_port_override,
        "num_lanes":            ev.num_lanes,
        "karts_per_lane":       karts_per_lane,
        "total_reserve_karts":  ev.total_reserve_karts,
        "min_pit_duration_s":   ev.min_pit_duration_s,
        "min_relay_duration_s": ev.min_relay_s,
        "max_relay_duration_s": ev.max_relay_s,
        "source":               ev_source,
        "proxy_ws_url":         ev_proxy_ws_url if ev_source == "proxy" else "",
    })
    db.commit()
    if _restart_cb:
        import asyncio
        asyncio.create_task(_restart_cb(new_config))
    return {"ok": True}


@router.post("/disconnect")
async def global_disconnect():
    """Stop the active Apex client without changing event config."""
    if _stop_cb:
        import asyncio
        asyncio.create_task(_stop_cb())
    return {"ok": True}


@router.post("/connect")
async def connect_source(payload: dict = Body(...), db: DBSession = Depends(get_db)):
    """Connect to a live circuit or proxy source. Events auto-create from the stream."""
    source = payload.get("source", "live")
    if source == "proxy":
        new_config = set_config(db, {
            "source": "proxy",
            "proxy_ws_url": payload.get("proxy_ws_url", ""),
        })
    else:
        updates: dict = {
            "source": "live",
            "circuit_url": payload.get("circuit_url", ""),
            "ws_port_override": int(payload.get("ws_port_override", 0)),
            "proxy_ws_url": "",
        }
        for key in ("min_pit_duration_s", "min_relay_duration_s", "max_relay_duration_s"):
            if key in payload:
                updates[key] = payload[key]
        new_config = set_config(db, updates)
    if _restart_cb:
        import asyncio
        asyncio.create_task(_restart_cb(new_config))
    return {"ok": True}


@router.post("/events/{event_id}/activate")
async def activate_event(event_id: int, db: DBSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")

    # Deactivate all others, activate this one
    db.query(Event).update({"is_active": False})
    ev.is_active = True

    # karts_per_lane = ceil(total / num_lanes)
    karts_per_lane = ev.total_reserve_karts // max(ev.num_lanes, 1)
    ev_source = getattr(ev, "source", "live")
    ev_proxy_ws_url = getattr(ev, "proxy_ws_url", "")
    new_config = set_config(db, {
        "circuit_url":          ev.circuit_url,
        "ws_port_override":     ev.ws_port_override,
        "num_lanes":            ev.num_lanes,
        "karts_per_lane":       karts_per_lane,
        "total_reserve_karts":  ev.total_reserve_karts,
        "min_pit_duration_s":   ev.min_pit_duration_s,
        "min_relay_duration_s": ev.min_relay_s,
        "max_relay_duration_s": ev.max_relay_s,
        "source":               ev_source,
        "proxy_ws_url":         ev_proxy_ws_url if ev_source == "proxy" else "",
    })
    db.commit()

    if _restart_cb:
        import asyncio
        asyncio.create_task(_restart_cb(new_config))

    return {"ok": True, "event_id": event_id}


# ── Performance seeding ───────────────────────────────────────────────────────

@router.post("/performance/seed-from-history")
def seed_from_history(db: DBSession = Depends(get_db)):
    """Manually seed kart_ranker with historical stints from the most recent previous event on the same circuit."""
    if not _kart_ranker:
        raise HTTPException(503, "KartRanker not ready")

    active = db.query(Event).filter(Event.is_active == True).first()
    if not active:
        raise HTTPException(404, "No active event")

    prev = (
        db.query(Event)
        .filter(Event.circuit_url == active.circuit_url, Event.id != active.id)
        .order_by(Event.id.desc())
        .first()
    )
    if not prev:
        raise HTTPException(404, "No previous event found for this circuit")

    n = _kart_ranker.seed_from_previous_event(prev.id, db)
    return {"seeded_teams": n, "source_event_id": prev.id, "source_event_name": prev.name}


# ── WebSocket message log ─────────────────────────────────────────────────────

@router.get("/ws-log")
def ws_log(limit: int = 500):
    """
    Return the last N raw Apex Timing WebSocket lines with timestamps.
    Use during a live session to analyse column patterns and pit signals.
    limit: max messages to return (default 500, max 2000).
    """
    safe_limit = min(max(limit, 1), 2000)
    return {
        "total": len(recorder),
        "messages": recorder.dump(safe_limit),
    }


@router.delete("/ws-log")
def clear_ws_log():
    """Clear the recorded message buffer."""
    recorder.clear()
    return {"ok": True}


# ── Proxy configs ─────────────────────────────────────────────────────────────

def _proxy_to_dict(p: ProxyConfig) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "ws_url": p.ws_url,
        "created_at": p.created_at.isoformat(),
    }


@router.get("/proxy-configs")
def list_proxy_configs(db: DBSession = Depends(get_db)):
    cfg = get_config(db)
    proxies = db.query(ProxyConfig).order_by(ProxyConfig.created_at).all()
    return {
        "source": cfg.source,
        "active_ws_url": cfg.proxy_ws_url,
        "proxies": [_proxy_to_dict(p) for p in proxies],
    }


@router.post("/proxy-configs")
def create_proxy_config(payload: dict = Body(...), db: DBSession = Depends(get_db)):
    p = ProxyConfig(
        name=payload.get("name", ""),
        ws_url=payload.get("ws_url", ""),
        created_at=datetime.utcnow(),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _proxy_to_dict(p)


@router.delete("/proxy-configs/{proxy_id}")
def delete_proxy_config(proxy_id: int, db: DBSession = Depends(get_db)):
    p = db.query(ProxyConfig).filter(ProxyConfig.id == proxy_id).first()
    if not p:
        raise HTTPException(404, "Not found")
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.post("/proxy-configs/{proxy_id}/activate")
async def activate_proxy(proxy_id: int, db: DBSession = Depends(get_db)):
    """Switch to proxy mode using the given proxy config."""
    p = db.query(ProxyConfig).filter(ProxyConfig.id == proxy_id).first()
    if not p:
        raise HTTPException(404, "Not found")
    new_config = set_config(db, {"source": "proxy", "proxy_ws_url": p.ws_url})
    if _restart_cb:
        import asyncio
        asyncio.create_task(_restart_cb(new_config))
    return {"ok": True, "ws_url": p.ws_url}


@router.post("/source/live")
async def switch_to_live(db: DBSession = Depends(get_db)):
    """Switch back to direct Apex Timing connection."""
    new_config = set_config(db, {"source": "live", "proxy_ws_url": ""})
    if _restart_cb:
        import asyncio
        asyncio.create_task(_restart_cb(new_config))
    return {"ok": True}


# ── Stats ────────────────────────────────────────────────────────────────────

@router.get("/stats/events/{event_id}")
def stats_event(event_id: int, db: DBSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    from sqlalchemy import text as _t
    rows = db.execute(_t("""
        SELECT ee.id, ee.bib, ee.team_name,
            (SELECT COUNT(*) FROM entry_laps WHERE entry_id=ee.id AND is_pit_lap=0 AND total_ms>0) AS total_laps,
            (SELECT MIN(best_lap_ms) FROM event_stints WHERE entry_id=ee.id) AS best_lap_ms,
            (SELECT ROUND(AVG(avg_lap_ms),0) FROM event_stints
             WHERE entry_id=ee.id AND lap_count>=3) AS avg_lap_ms,
            (SELECT COUNT(*) FROM event_pit_stops WHERE entry_id=ee.id) AS pit_count,
            (SELECT COUNT(*) FROM event_stints WHERE entry_id=ee.id) AS stint_count,
            (SELECT ROUND(
                SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                    THEN CAST(es.std_dev_ms AS FLOAT)*es.lap_count ELSE 0 END) /
                NULLIF(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                    THEN es.lap_count ELSE 0 END), 0)
             ,0) FROM event_stints es WHERE es.entry_id=ee.id) AS avg_std_dev_ms
        FROM event_entries ee WHERE ee.event_id=:eid
        ORDER BY total_laps DESC
    """), {"eid": event_id}).fetchall()
    return {
        "event_id": event_id,
        "event_name": ev.name,
        "entries": [dict(r._mapping) for r in rows],
    }


@router.get("/stats/entries/{entry_id}")
def stats_entry(entry_id: int, db: DBSession = Depends(get_db)):
    from sqlalchemy import text as _t
    ee = db.execute(_t("SELECT id,bib,team_name,event_id FROM event_entries WHERE id=:id"),
                    {"id": entry_id}).fetchone()
    if not ee:
        raise HTTPException(404)
    stints = db.execute(_t("""
        SELECT id,stint_number,driver_name,driver_in,lap_count,
               best_lap_ms,avg_lap_ms,std_dev_ms,kart_quality,kart_label,
               pit_duration_ms,out_lap_ms,started_at,ended_at
        FROM event_stints WHERE entry_id=:id ORDER BY stint_number
    """), {"id": entry_id}).fetchall()
    field_avgs = db.execute(_t("""
        SELECT es.avg_lap_ms FROM event_stints es
        JOIN event_entries ee2 ON ee2.id=es.entry_id
        WHERE ee2.event_id=:eid AND es.ended_at IS NOT NULL
          AND es.avg_lap_ms IS NOT NULL AND es.lap_count >= 3
        ORDER BY es.avg_lap_ms
    """), {"eid": ee.event_id}).fetchall()
    avgs = [r.avg_lap_ms for r in field_avgs]
    n = len(avgs)
    def _level(avg_ms):
        if not avg_ms or n < 4:
            return "UNKNOWN"
        pct = sum(1 for x in avgs if x < avg_ms) / n
        if pct < 0.25: return "ELITE"
        if pct < 0.50: return "FAST"
        if pct < 0.75: return "MEDIUM"
        return "SLOW"
    return {
        "id": ee.id, "bib": ee.bib, "team_name": ee.team_name,
        "stints": [dict(s._mapping) | {"level": _level(s.avg_lap_ms)} for s in stints],
    }


@router.get("/stats/events/{event_id}/pilots")
def stats_pilots(event_id: int, db: DBSession = Depends(get_db)):
    from sqlalchemy import text as _t
    rows = db.execute(_t("""
        SELECT es.driver_name,
               COUNT(DISTINCT es.id) AS stint_count,
               COUNT(esl.id)         AS total_laps,
               MIN(es.best_lap_ms) AS best_lap_ms,
               ROUND(AVG(CASE WHEN es.lap_count>=3 THEN es.avg_lap_ms END),0) AS avg_lap_ms,
               ROUND(
                 SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                     THEN CAST(es.std_dev_ms AS FLOAT)*es.lap_count ELSE 0 END) /
                 NULLIF(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                     THEN es.lap_count ELSE 0 END), 0)
               ,0) AS avg_std_dev_ms,
               GROUP_CONCAT(DISTINCT ee.bib) AS bibs,
               GROUP_CONCAT(DISTINCT ee.team_name) AS teams
        FROM event_stints es
        JOIN event_entries ee ON ee.id=es.entry_id
        LEFT JOIN event_stint_laps esl ON esl.stint_id=es.id
        WHERE es.event_id=:eid AND es.driver_name!=''
        GROUP BY es.driver_name
        ORDER BY total_laps DESC
    """), {"eid": event_id}).fetchall()
    return {"pilots": [dict(r._mapping) for r in rows]}


@router.get("/stats/search")
def stats_search(q: str = "", db: DBSession = Depends(get_db)):
    if len(q) < 2:
        return {"results": []}
    from sqlalchemy import text as _t
    like = f"%{q}%"
    rows = db.execute(_t("""
        SELECT ee.id AS entry_id, ee.bib, ee.team_name,
               e.id AS event_id, e.name AS event_name, e.event_date,
               (SELECT COUNT(*) FROM entry_laps WHERE entry_id=ee.id AND is_pit_lap=0 AND total_ms>0) AS total_laps,
               (SELECT MIN(best_lap_ms) FROM event_stints WHERE entry_id=ee.id) AS best_lap_ms
        FROM event_entries ee
        JOIN events e ON e.id=ee.event_id
        WHERE ee.team_name LIKE :q
        ORDER BY e.event_date DESC
        LIMIT 50
    """), {"q": like}).fetchall()
    pilot_rows = db.execute(_t("""
        SELECT es.driver_name, ee.id AS entry_id, ee.bib, ee.team_name,
               e.id AS event_id, e.name AS event_name, e.event_date,
               COUNT(esl.id) AS total_laps, MIN(es.best_lap_ms) AS best_lap_ms
        FROM event_stints es
        JOIN event_entries ee ON ee.id=es.entry_id
        JOIN events e ON e.id=ee.event_id
        LEFT JOIN event_stint_laps esl ON esl.stint_id=es.id
        WHERE es.driver_name LIKE :q AND es.driver_name!=''
        GROUP BY es.driver_name, ee.id
        ORDER BY e.event_date DESC
        LIMIT 50
    """), {"q": like}).fetchall()
    seen = set()
    results = []
    for r in rows:
        d = dict(r._mapping); d["match_type"] = "team"; results.append(d); seen.add(r.entry_id)
    for r in pilot_rows:
        d = dict(r._mapping); d["match_type"] = "pilot"
        if r.entry_id not in seen:
            results.append(d); seen.add(r.entry_id)
    return {"results": results}


@router.get("/stats/pilot-profile")
def stats_pilot_profile(name: str = "", db: DBSession = Depends(get_db)):
    if not name:
        raise HTTPException(400, "name required")
    from sqlalchemy import text as _t
    agg = db.execute(_t("""
        SELECT es.driver_name,
               COUNT(DISTINCT ee.event_id) AS event_count,
               COUNT(DISTINCT es.id) AS total_stints,
               COUNT(esl.id) AS total_laps,
               MIN(es.best_lap_ms) AS best_lap_ms,
               ROUND(SUM(CASE WHEN es.lap_count>=3 THEN CAST(es.avg_lap_ms AS FLOAT)*es.lap_count END) /
                     NULLIF(SUM(CASE WHEN es.lap_count>=3 THEN es.lap_count END), 0), 0) AS avg_lap_ms,
               ROUND(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                              THEN CAST(es.std_dev_ms AS FLOAT)*es.lap_count ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                              THEN es.lap_count END), 0), 0) AS avg_std_dev_ms
        FROM event_stints es
        JOIN event_entries ee ON ee.id=es.entry_id
        LEFT JOIN event_stint_laps esl ON esl.stint_id=es.id
        WHERE es.driver_name=:name
    """), {"name": name}).fetchone()
    if not agg or not agg.total_laps:
        raise HTTPException(404, "Pilot not found")
    events = db.execute(_t("""
        SELECT e.id AS event_id, e.name AS event_name, e.event_date,
               ee.id AS entry_id, ee.bib, ee.team_name,
               COUNT(DISTINCT es.id) AS stint_count,
               COUNT(esl.id) AS total_laps,
               MIN(es.best_lap_ms) AS best_lap_ms,
               ROUND(SUM(CASE WHEN es.lap_count>=3 THEN CAST(es.avg_lap_ms AS FLOAT)*es.lap_count END) /
                     NULLIF(SUM(CASE WHEN es.lap_count>=3 THEN es.lap_count END), 0), 0) AS avg_lap_ms,
               ROUND(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                              THEN CAST(es.std_dev_ms AS FLOAT)*es.lap_count ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                              THEN es.lap_count END), 0), 0) AS avg_std_dev_ms
        FROM event_stints es
        JOIN event_entries ee ON ee.id=es.entry_id
        JOIN events e ON e.id=ee.event_id
        LEFT JOIN event_stint_laps esl ON esl.stint_id=es.id
        WHERE es.driver_name=:name
        GROUP BY e.id, ee.id
        ORDER BY e.event_date DESC NULLS LAST
    """), {"name": name}).fetchall()
    return {
        **dict(agg._mapping),
        "events": [dict(r._mapping) for r in events],
    }


@router.get("/stats/team-profile")
def stats_team_profile(name: str = "", db: DBSession = Depends(get_db)):
    if not name:
        raise HTTPException(400, "name required")
    from sqlalchemy import text as _t
    agg = db.execute(_t("""
        SELECT ee.team_name,
               COUNT(DISTINCT ee.event_id) AS event_count,
               COUNT(DISTINCT es.id) AS total_stints,
               (SELECT COUNT(*) FROM entry_laps WHERE entry_id IN
                (SELECT id FROM event_entries WHERE team_name=:name) AND is_pit_lap=0 AND total_ms>0) AS total_laps,
               MIN(es.best_lap_ms) AS best_lap_ms,
               ROUND(SUM(CASE WHEN es.lap_count>=3 THEN CAST(es.avg_lap_ms AS FLOAT)*es.lap_count END) /
                     NULLIF(SUM(CASE WHEN es.lap_count>=3 THEN es.lap_count END), 0), 0) AS avg_lap_ms,
               ROUND(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                              THEN CAST(es.std_dev_ms AS FLOAT)*es.lap_count ELSE 0 END) /
                     NULLIF(SUM(CASE WHEN es.lap_count>=3 AND es.std_dev_ms IS NOT NULL
                              THEN es.lap_count END), 0), 0) AS avg_std_dev_ms
        FROM event_entries ee
        LEFT JOIN event_stints es ON es.entry_id=ee.id
        WHERE ee.team_name=:name
    """), {"name": name}).fetchone()
    if not agg or not agg.event_count:
        raise HTTPException(404, "Team not found")
    events = db.execute(_t("""
        SELECT e.id AS event_id, e.name AS event_name, e.event_date,
               ee.id AS entry_id, ee.bib,
               (SELECT COUNT(*) FROM entry_laps WHERE entry_id=ee.id AND is_pit_lap=0 AND total_ms>0) AS total_laps,
               (SELECT COUNT(*) FROM event_stints WHERE entry_id=ee.id) AS stint_count,
               (SELECT MIN(best_lap_ms) FROM event_stints WHERE entry_id=ee.id) AS best_lap_ms,
               (SELECT ROUND(SUM(CASE WHEN es2.lap_count>=3 THEN CAST(es2.avg_lap_ms AS FLOAT)*es2.lap_count END)/
                             NULLIF(SUM(CASE WHEN es2.lap_count>=3 THEN es2.lap_count END),0),0)
                FROM event_stints es2 WHERE es2.entry_id=ee.id) AS avg_lap_ms,
               (SELECT ROUND(SUM(CASE WHEN es2.lap_count>=3 AND es2.std_dev_ms IS NOT NULL
                                 THEN CAST(es2.std_dev_ms AS FLOAT)*es2.lap_count ELSE 0 END)/
                             NULLIF(SUM(CASE WHEN es2.lap_count>=3 AND es2.std_dev_ms IS NOT NULL
                                 THEN es2.lap_count END),0),0)
                FROM event_stints es2 WHERE es2.entry_id=ee.id) AS avg_std_dev_ms,
               (SELECT COUNT(*) FROM event_pit_stops WHERE entry_id=ee.id) AS pit_count
        FROM event_entries ee
        JOIN events e ON e.id=ee.event_id
        WHERE ee.team_name=:name
        ORDER BY e.event_date DESC NULLS LAST
    """), {"name": name}).fetchall()
    return {
        **dict(agg._mapping),
        "events": [dict(r._mapping) for r in events],
    }


# ── DB reset ─────────────────────────────────────────────────────────────────

@router.post("/db/reset")
def db_reset():
    """Delete all race data while keeping circuits, config, and proxy configs."""
    if not _session_factory:
        raise HTTPException(503, "Not initialized")
    from sqlalchemy import text as _text
    tables_to_clear = [
        "event_stint_laps",
        "event_stints",
        "entry_laps",
        "event_pit_stops",
        "entry_pilots",
        "pilot_event_summaries",
        "event_entries",
        "pilots",
        "events",
        "physical_karts",
    ]
    with _session_factory() as db:
        for table in tables_to_clear:
            db.execute(_text(f"DELETE FROM {table}"))
        db.commit()
    return {"ok": True, "cleared": tables_to_clear}


# ── Import ────────────────────────────────────────────────────────────────────

@router.post("/import")
async def start_import(payload: dict = Body(...)):
    if not _import_runner:
        raise HTTPException(503, "Not initialized")
    recording_name = payload.get("recording_name", "").strip()
    if not recording_name:
        raise HTTPException(400, "recording_name required")
    event_id = payload.get("event_id") or None
    proxy_http_url = _get_proxy_http_url_cb() if _get_proxy_http_url_cb else None
    if not proxy_http_url:
        raise HTTPException(503, "Proxy not configured")
    if not _broadcast_cb or not _session_factory:
        raise HTTPException(503, "Not initialized")
    started = _import_runner.start(
        recording_name=recording_name,
        proxy_http_url=proxy_http_url,
        session_factory=_session_factory,
        broadcast=_broadcast_cb,
        event_id=event_id,
    )
    if not started:
        raise HTTPException(409, "Import already running")
    return {"ok": True, "event_id": event_id, "recording_name": recording_name}


@router.get("/import/status")
def get_import_status():
    if not _import_runner:
        raise HTTPException(503, "Not initialized")
    return _import_runner.summary()


@router.post("/refresh-grid")
async def refresh_grid():
    proxy_http_url = _get_proxy_http_url_cb() if _get_proxy_http_url_cb else None
    if not proxy_http_url:
        raise HTTPException(503, "Proxy non configuré")
    try:
        async with httpx.AsyncClient(timeout=20.0) as hc:
            r = await hc.post(f"{proxy_http_url}/api/grid")
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(e.response.status_code, e.response.text)
    except Exception as e:
        raise HTTPException(503, str(e))
