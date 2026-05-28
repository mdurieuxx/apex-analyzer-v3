from datetime import datetime
from typing import Optional
from sqlalchemy import String, Integer, Float, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pydantic import BaseModel
from database import Base

CIRCUIT_PRESETS = [
    {
        "name": "Karting de Saintes",
        "country": "France",
        "city": "Saintes",
        "length_km": 0.9,
        "circuit_url": "https://www.apex-timing.com/live-timing/karting-de-saintes/",
        "ws_port_override": 8583,
    },
    {
        "name": "Karting des Fagnes (Mariembourg)",
        "country": "Belgium",
        "city": "Mariembourg",
        "length_km": 1.2,
        "circuit_url": "https://www.apex-timing.com/live-timing/karting-mariembourg/",
        "ws_port_override": 8313,
    },
    {
        "name": "Karting de Genk",
        "country": "Belgium",
        "city": "Genk",
        "length_km": 1.4,
        "circuit_url": "https://www.apex-timing.com/live-timing/karting-genk/",
        "ws_port_override": 8243,
    },
    {
        "name": "Spa Francorchamps Karting",
        "country": "Belgium",
        "city": "Spa-Francorchamps",
        "length_km": 1.1,
        "circuit_url": "https://live.apex-timing.com/spa-francorchamps-karting/",
        "ws_port_override": 9723,
    },
    {
        "name": "Karting Eupen",
        "country": "Belgium",
        "city": "Eupen",
        "length_km": 1.0,
        "circuit_url": "https://www.apex-timing.com/live-timing/karting-eupen/",
        "ws_port_override": 8523,
    },
    {
        "name": "MRK Agadir",
        "country": "Morocco",
        "city": "Agadir",
        "length_km": 1.3,
        "circuit_url": "https://www.apex-timing.com/live-timing/mrkagadir/",
        "ws_port_override": 8023,
    },
    {
        "name": "Misanino",
        "country": "Italy",
        "city": "Misano Adriatico",
        "length_km": 1.0,
        "circuit_url": "https://www.apex-timing.com/live-timing/misanino/",
        "ws_port_override": 8043,
    },
]


# ── ORM Models ──────────────────────────────────────────────────────────────

class Config(Base):
    __tablename__ = "config"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)



class PhysicalKart(Base):
    """A physical kart machine tracked across bib reassignments."""
    __tablename__ = "physical_karts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kart_label: Mapped[str] = mapped_column(String, unique=True)  # e.g. "KA", "K07"
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Circuit(Base):
    """A user-defined circuit (presets are hardcoded in CIRCUIT_PRESETS)."""
    __tablename__ = "circuits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    country: Mapped[str] = mapped_column(String, default="")
    city: Mapped[str] = mapped_column(String, default="")
    length_km: Mapped[float] = mapped_column(Float, default=0.0)
    circuit_url: Mapped[str] = mapped_column(String)
    ws_port_override: Mapped[int] = mapped_column(Integer, default=0)
    best_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_pit_duration_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_relay_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_relay_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    events: Mapped[list["Event"]] = relationship("Event", back_populates="circuit")


class Event(Base):
    """An endurance race event with all its configuration."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    circuit_url: Mapped[str] = mapped_column(String, default="")
    ws_port_override: Mapped[int] = mapped_column(Integer, default=0)
    event_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_hours: Mapped[float] = mapped_column(Float, default=6.0)
    min_pit_duration_s: Mapped[int] = mapped_column(Integer, default=300)
    min_relay_s: Mapped[int] = mapped_column(Integer, default=3600)
    max_relay_s: Mapped[int] = mapped_column(Integer, default=5400)
    num_lanes: Mapped[int] = mapped_column(Integer, default=4)
    total_reserve_karts: Mapped[int] = mapped_column(Integer, default=20)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Best lap in race (denormalized for quick display)
    best_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    best_lap_bib: Mapped[str] = mapped_column(String, default="")
    best_lap_pilot_name: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="live")        # "live" | "proxy"
    proxy_ws_url: Mapped[str] = mapped_column(String, default="")
    event_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    imported_through_t: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    circuit_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("circuits.id"), nullable=True)
    circuit: Mapped[Optional["Circuit"]] = relationship("Circuit", back_populates="events")
    entries: Mapped[list["EventEntry"]] = relationship("EventEntry", back_populates="event", cascade="all, delete-orphan")


class ProxyConfig(Base):
    """A saved proxy connection (name + WS URL)."""
    __tablename__ = "proxy_configs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    ws_url: Mapped[str] = mapped_column(String)   # e.g. ws://192.168.1.42:9000/ws
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Event tracking entities ──────────────────────────────────────────────────

class Pilot(Base):
    """A named pilot, potentially appearing across multiple events."""
    __tablename__ = "pilots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    event_pilots: Mapped[list["EntryPilot"]] = relationship("EntryPilot", back_populates="pilot")
    summaries: Mapped[list["PilotEventSummary"]] = relationship("PilotEventSummary", back_populates="pilot")


class EventEntry(Base):
    """A team's entry in a specific event (bib + team name)."""
    __tablename__ = "event_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    bib: Mapped[str] = mapped_column(String)
    team_name: Mapped[str] = mapped_column(String, default="")
    apex_driver_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    final_position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    total_laps: Mapped[int] = mapped_column(Integer, default=0)
    best_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    event: Mapped["Event"] = relationship("Event", back_populates="entries")
    pilots: Mapped[list["EntryPilot"]] = relationship("EntryPilot", back_populates="entry", cascade="all, delete-orphan")
    entry_laps: Mapped[list["EntryLap"]] = relationship("EntryLap", back_populates="entry", cascade="all, delete-orphan")
    pit_stops: Mapped[list["EventPitStop"]] = relationship("EventPitStop", back_populates="entry", cascade="all, delete-orphan")
    summaries: Mapped[list["PilotEventSummary"]] = relationship("PilotEventSummary", back_populates="entry", cascade="all, delete-orphan")


class EntryPilot(Base):
    """Association: a pilot drives for a specific entry (unique per entry + pilot)."""
    __tablename__ = "entry_pilots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("event_entries.id"))
    pilot_id: Mapped[int] = mapped_column(ForeignKey("pilots.id"))
    relay_order: Mapped[int] = mapped_column(Integer, default=1)   # order first seen (1-based)
    entry: Mapped["EventEntry"] = relationship("EventEntry", back_populates="pilots")
    pilot: Mapped["Pilot"] = relationship("Pilot", back_populates="event_pilots")


class EntryLap(Base):
    """A single lap driven during an event, optionally linked to a known pilot.

    track_norm_ms stores the track-condition-adjusted time (from TrackConditionMonitor).
    consistency_index on PilotEventSummary uses track_norm_ms to remove conditions drift.
    """
    __tablename__ = "entry_laps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("event_entries.id"))
    pilot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pilots.id"), nullable=True)
    lap_number: Mapped[int] = mapped_column(Integer, default=0)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    s1_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    s2_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    s3_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    track_norm_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_pit_lap: Mapped[bool] = mapped_column(Boolean, default=False)  # out-lap after pit stop
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    entry: Mapped["EventEntry"] = relationship("EventEntry", back_populates="entry_laps")
    pilot: Mapped[Optional["Pilot"]] = relationship("Pilot")


class EventPitStop(Base):
    """A recorded pit stop during an event, including the timing lap during the stop."""
    __tablename__ = "event_pit_stops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("event_entries.id"))
    pilot_id: Mapped[Optional[int]] = mapped_column(ForeignKey("pilots.id"), nullable=True)
    lap_number_in: Mapped[int] = mapped_column(Integer, default=0)
    kart_in_label: Mapped[str] = mapped_column(String, default="")
    kart_out_label: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The out-lap time (first lap after exiting pits — "tour stand")
    pit_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Duration of the actual stationary stop
    stop_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    pit_number: Mapped[int] = mapped_column(Integer, default=1)  # which pit stop (1st, 2nd, ...)
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    exited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    entry: Mapped["EventEntry"] = relationship("EventEntry", back_populates="pit_stops")
    pilot: Mapped[Optional["Pilot"]] = relationship("Pilot")


class EventStint(Base):
    """A driving stint between two pit stops."""
    __tablename__ = "event_stints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("event_entries.id"))
    stint_number: Mapped[int] = mapped_column(Integer, default=0)  # = pit_number at stint start
    driver_name: Mapped[str] = mapped_column(String, default="")   # driver during stint
    driver_out: Mapped[str] = mapped_column(String, default="")    # pilot who entered pits at end
    driver_in: Mapped[str] = mapped_column(String, default="")     # pilot who started next stint
    kart_label: Mapped[str] = mapped_column(String, default="")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    pit_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # pit stop duration before this stint
    out_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)       # first lap after exiting pits
    best_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_lap_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    std_dev_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lap_count: Mapped[int] = mapped_column(Integer, default=0)
    kart_quality: Mapped[str] = mapped_column(String, default="UNKNOWN")
    laps: Mapped[list["EventStintLap"]] = relationship("EventStintLap", back_populates="stint", cascade="all, delete-orphan")


class EventStintLap(Base):
    """Individual lap within a stint."""
    __tablename__ = "event_stint_laps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stint_id: Mapped[int] = mapped_column(ForeignKey("event_stints.id"))
    lap_number: Mapped[int] = mapped_column(Integer, default=0)
    lap_ms: Mapped[int] = mapped_column(Integer, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    stint: Mapped["EventStint"] = relationship("EventStint", back_populates="laps")


class PilotEventSummary(Base):
    """Denormalized per-pilot stats for one event entry — updated live as laps arrive.

    consistency_index = (σ/μ) × 100 on track-normalized times, excluding pit laps.
    A value ≤ 0.55% means very consistent (±400ms on a 73s lap).
    """
    __tablename__ = "pilot_event_summaries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"))
    entry_id: Mapped[int] = mapped_column(ForeignKey("event_entries.id"))
    pilot_id: Mapped[int] = mapped_column(ForeignKey("pilots.id"))
    laps_driven: Mapped[int] = mapped_column(Integer, default=0)
    total_driving_ms: Mapped[int] = mapped_column(Integer, default=0)
    best_lap_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    avg_lap_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    consistency_index: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    entry: Mapped["EventEntry"] = relationship("EventEntry", back_populates="summaries")
    pilot: Mapped["Pilot"] = relationship("Pilot", back_populates="summaries")


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class ConfigSchema(BaseModel):
    circuit_url: str = ""
    ws_port_override: int = 0          # 0 = auto-discover
    num_lanes: int = 4
    karts_per_lane: int = 5
    total_reserve_karts: int = 20
    min_pit_duration_s: int = 300      # 5 min
    min_relay_duration_s: int = 3600   # 60 min
    max_relay_duration_s: int = 5400   # 90 min
    source: str = "live"               # "live" | "proxy"
    proxy_ws_url: str = ""             # active proxy WS URL

    class Config:
        from_attributes = True


class EventSchema(BaseModel):
    id: int
    name: str
    circuit_url: str
    ws_port_override: int = 0
    event_date: Optional[datetime] = None
    duration_hours: float = 6.0
    min_pit_duration_s: int = 300
    min_relay_s: int = 3600
    max_relay_s: int = 5400
    num_lanes: int = 4
    total_reserve_karts: int = 20
    is_active: bool = False
    created_at: datetime
    best_lap_ms: Optional[int] = None
    best_lap_bib: str = ""
    best_lap_pilot_name: str = ""
    source: str = "live"
    proxy_ws_url: str = ""
    event_key: Optional[str] = None
    imported_through_t: Optional[float] = None

    class Config:
        from_attributes = True


class EventCreateSchema(BaseModel):
    name: str
    circuit_url: str
    ws_port_override: int = 0
    event_date: Optional[datetime] = None
    duration_hours: float = 6.0
    min_pit_duration_s: int = 300
    min_relay_s: int = 3600
    max_relay_s: int = 5400
    num_lanes: int = 4
    total_reserve_karts: int = 20
    source: str = "live"
    proxy_ws_url: str = ""

