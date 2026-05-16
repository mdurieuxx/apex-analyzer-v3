import math
from dataclasses import asdict
from datetime import datetime
from typing import Optional, Callable, Awaitable

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session as DBSession

from database import get_db
from config_store import get_config, set_config
from models import PhysicalKart, KartAssignment, PitStop, PitQueueEntry, Event, EventSchema, EventCreateSchema, Circuit, CIRCUIT_PRESETS
from race.kart_performance import compute_performance
from apex.lap_api import fetch_driver_laps

router = APIRouter()

# Injected by main.py after startup
_state = None
_pit_manager = None
_kart_ranker = None
_current_session_id: Optional[int] = None
_restart_cb: Optional[Callable] = None


def init_router(state, pit_manager, kart_ranker, session_id_fn, restart_cb=None):
    global _state, _pit_manager, _kart_ranker, _current_session_id, _restart_cb
    _state = state
    _pit_manager = pit_manager
    _kart_ranker = kart_ranker
    _current_session_id = session_id_fn
    _restart_cb = restart_cb


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


@router.get("/pits/history")
def pits_history(db: DBSession = Depends(get_db)):
    if not _state:
        raise HTTPException(503, "Not initialized")
    return {
        "history": [
            {
                "bib": ps.bib,
                "team": ps.team,
                "kart_in": ps.kart_label,
                "kart_out": ps.kart_out_label,
                "position": ps.position,
                "pit_number": ps.pit_number,
                "timestamp": ps.timestamp.isoformat(),
                "duration_s": ps.duration_s,
            }
            for ps in reversed(_state.pit_history)
        ]
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
def kart_performance(db: DBSession = Depends(get_db)):
    if _current_session_id is None or not callable(_current_session_id):
        raise HTTPException(503, "No session")
    sid = _current_session_id()
    if not sid:
        return {"karts": []}
    results = compute_performance(db, sid)
    return {"karts": [r.model_dump() for r in results]}


@router.get("/ranking")
def kart_ranking():
    """
    Real-time kart ranking from the KartRanker algorithm.
    Returns all tracked karts sorted GOOD → MEDIUM → BAD → UNKNOWN.
    """
    if not _kart_ranker:
        raise HTTPException(503, "Ranker not initialized")
    return {"ranking": _kart_ranker.field_ranking()}


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
        "created_at": c.created_at.isoformat(),
    }


@router.get("/circuits")
def list_circuits(db: DBSession = Depends(get_db)):
    """Return built-in presets followed by user-defined circuits."""
    presets = [{"id": None, "is_preset": True, **p} for p in CIRCUIT_PRESETS]
    user = [_circuit_to_dict(c) for c in db.query(Circuit).order_by(Circuit.created_at).all()]
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
    for key in ("name", "country", "city", "length_km", "circuit_url", "ws_port_override"):
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
               "min_pit_duration_s", "min_relay_s", "max_relay_s", "num_lanes", "total_reserve_karts"}
    for key, val in payload.items():
        if key in allowed:
            setattr(ev, key, val)
    db.commit()
    db.refresh(ev)
    return _event_to_dict(ev)


@router.delete("/events/{event_id}")
def delete_event(event_id: int, db: DBSession = Depends(get_db)):
    ev = db.query(Event).filter(Event.id == event_id).first()
    if not ev:
        raise HTTPException(404, "Event not found")
    db.delete(ev)
    db.commit()
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
    karts_per_lane = math.ceil(ev.total_reserve_karts / max(ev.num_lanes, 1))
    new_config = set_config(db, {
        "circuit_url":        ev.circuit_url,
        "ws_port_override":   ev.ws_port_override,
        "num_lanes":          ev.num_lanes,
        "karts_per_lane":     karts_per_lane,
        "min_pit_duration_s": ev.min_pit_duration_s,
        "min_relay_duration_s": ev.min_relay_s,
        "max_relay_duration_s": ev.max_relay_s,
    })
    db.commit()

    if _restart_cb:
        import asyncio
        asyncio.create_task(_restart_cb(new_config))

    return {"ok": True, "event_id": event_id}
