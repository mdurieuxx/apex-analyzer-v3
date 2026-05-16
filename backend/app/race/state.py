from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from apex.grid_parser import LiveDriver


@dataclass
class PitQueueKart:
    kart_label: str          # physical kart label
    physical_kart_id: int
    lane: int
    entered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def seconds_in_pit(self) -> int:
        return int((datetime.now(timezone.utc) - self.entered_at).total_seconds())


@dataclass
class LivePitStop:
    driver_id: str
    kart_label: str
    team: str
    bib: str
    position: int
    lap: int
    pit_number: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    kart_out_label: Optional[str] = None
    exited_at: Optional[datetime] = None

    @property
    def duration_s(self) -> Optional[int]:
        if self.exited_at:
            return int((self.exited_at - self.timestamp).total_seconds())
        return None


@dataclass
class RaceState:
    # Connection
    circuit_url: str = ""
    ws_port: int = 0
    connected: bool = False
    last_update: Optional[datetime] = None

    # Session info
    title1: str = ""
    title2: str = ""
    countdown: int = 0
    comments: list[dict] = field(default_factory=list)

    # Live timing grid (driver_id → LiveDriver)
    drivers: dict[str, LiveDriver] = field(default_factory=dict)

    # Pit lane queues: lane_number (1-N) → list of karts (FIFO, index 0 = oldest)
    pit_lanes: dict[int, list[PitQueueKart]] = field(default_factory=dict)

    # Active pit stops (driver currently in pits)
    active_pit_stops: dict[str, LivePitStop] = field(default_factory=dict)

    # Completed pit stops (all time)
    pit_history: list[LivePitStop] = field(default_factory=list)

    # Physical kart assignment: driver_id → physical kart label
    kart_assignments: dict[str, str] = field(default_factory=dict)

    def is_race(self) -> bool:
        t = (self.title2 or self.title1).lower()
        return any(k in t for k in ("course", "race", "final", "finale", "heat", "endur"))

    def is_qualifying(self) -> bool:
        t = (self.title2 or self.title1).lower()
        return any(k in t for k in ("qualif", "qualify", "chrono", "essai"))

    def session_type(self) -> str:
        if self.is_race():
            return "race"
        if self.is_qualifying():
            return "qualifying"
        return "unknown"
