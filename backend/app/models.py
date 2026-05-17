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
]


# ── ORM Models ──────────────────────────────────────────────────────────────

class Config(Base):
    __tablename__ = "config"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Session(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    circuit_url: Mapped[str] = mapped_column(String)
    ws_port: Mapped[int] = mapped_column(Integer, default=0)
    title1: Mapped[str] = mapped_column(String, default="")
    title2: Mapped[str] = mapped_column(String, default="")
    session_type: Mapped[str] = mapped_column(String, default="unknown")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PhysicalKart(Base):
    """A physical kart machine tracked across bib reassignments."""
    __tablename__ = "physical_karts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kart_label: Mapped[str] = mapped_column(String, unique=True)  # e.g. "KA", "K07"
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    laps: Mapped[list["Lap"]] = relationship("Lap", back_populates="physical_kart")
    pit_entries: Mapped[list["PitStop"]] = relationship("PitStop", foreign_keys="PitStop.kart_in_id", back_populates="kart_in")
    pit_exits: Mapped[list["PitStop"]] = relationship("PitStop", foreign_keys="PitStop.kart_out_id", back_populates="kart_out")


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    bib: Mapped[str] = mapped_column(String)   # the number shown in timing
    team_name: Mapped[str] = mapped_column(String, default="")
    laps: Mapped[list["Lap"]] = relationship("Lap", back_populates="team")


class KartAssignment(Base):
    """History: which physical kart was assigned to which bib at what time."""
    __tablename__ = "kart_assignments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    physical_kart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_karts.id"), nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    unassigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Lap(Base):
    __tablename__ = "laps"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    physical_kart_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_karts.id"), nullable=True)
    lap_number: Mapped[int] = mapped_column(Integer, default=0)
    s1_ms: Mapped[int] = mapped_column(Integer, default=0)
    s2_ms: Mapped[int] = mapped_column(Integer, default=0)
    s3_ms: Mapped[int] = mapped_column(Integer, default=0)
    total_ms: Mapped[int] = mapped_column(Integer, default=0)
    is_pit: Mapped[bool] = mapped_column(Boolean, default=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    team: Mapped["Team"] = relationship("Team", back_populates="laps")
    physical_kart: Mapped[Optional["PhysicalKart"]] = relationship("PhysicalKart", back_populates="laps")


class PitStop(Base):
    __tablename__ = "pit_stops"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    kart_in_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_karts.id"), nullable=True)
    kart_out_id: Mapped[Optional[int]] = mapped_column(ForeignKey("physical_karts.id"), nullable=True)
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    exited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_s: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    position_at_entry: Mapped[int] = mapped_column(Integer, default=0)
    lap_at_entry: Mapped[int] = mapped_column(Integer, default=0)
    lane: Mapped[int] = mapped_column(Integer, default=1)
    kart_in: Mapped[Optional[PhysicalKart]] = relationship("PhysicalKart", foreign_keys=[kart_in_id], back_populates="pit_entries")
    kart_out: Mapped[Optional[PhysicalKart]] = relationship("PhysicalKart", foreign_keys=[kart_out_id], back_populates="pit_exits")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PitQueueEntry(Base):
    """A kart waiting in the pit lane reserve."""
    __tablename__ = "pit_queue"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    physical_kart_id: Mapped[int] = mapped_column(ForeignKey("physical_karts.id"))
    lane: Mapped[int] = mapped_column(Integer)
    entered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    exited_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


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


# ── Pydantic Schemas ─────────────────────────────────────────────────────────

class ConfigSchema(BaseModel):
    circuit_url: str = "https://www.apex-timing.com/live-timing/karting-de-saintes/"
    ws_port_override: int = 0          # 0 = auto-discover
    num_lanes: int = 4
    karts_per_lane: int = 5
    total_reserve_karts: int = 20
    min_pit_duration_s: int = 300      # 5 min
    min_relay_duration_s: int = 3600   # 60 min
    max_relay_duration_s: int = 5400   # 90 min

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


class KartPerformanceSchema(BaseModel):
    kart_label: str
    physical_kart_id: int
    total_laps: int
    avg_lap_ms: float
    best_lap_ms: int
    std_dev_ms: float
    relative_score: float   # 1.0 = session best, higher = slower
    rating: str             # "EXCELLENT" / "GOOD" / "AVERAGE" / "POOR"
    laps_in_pit: int
    time_in_pit_s: int
