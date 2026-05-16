from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime


@dataclass
class Driver:
    driver_id: str
    position: int = 0
    kart: str = ""
    team: str = ""
    gap: str = ""
    interval: str = ""
    s1: str = ""
    s2: str = ""
    s3: str = ""
    last_lap: str = ""
    best_lap: str = ""
    laps: int = 0
    on_track: str = ""
    pits: int = 0
    penalty: str = ""

    def pit_count_changed(self, new_pits: int) -> bool:
        return new_pits > self.pits


@dataclass
class PitEvent:
    timestamp: datetime
    kart: str
    team: str
    lap: int
    position: int
    pit_number: int


@dataclass
class SessionState:
    circuit_url: str
    ws_port: int
    title1: str = ""
    title2: str = ""
    session_type: str = "unknown"
    countdown: int = 0
    drivers: dict[str, Driver] = field(default_factory=dict)
    pit_history: list[PitEvent] = field(default_factory=list)
    comments: list[dict] = field(default_factory=list)
    connected: bool = False
    last_update: Optional[datetime] = None

    def is_race(self) -> bool:
        t = (self.title2 or self.title1).lower()
        return any(k in t for k in ("course", "race", "final", "finale", "heat"))

    def is_qualifying(self) -> bool:
        t = (self.title2 or self.title1).lower()
        return any(k in t for k in ("qualif", "qualify", "chrono"))
