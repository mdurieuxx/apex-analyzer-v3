"""
Kart performance ranking — per-driver baseline model.

A kart (bib) represents a TEAM, not a driver.
Multiple drivers share the same kart/team across relays.

Baseline strategy:
  • If driver names are detected in the grid, each named driver has their own
    baseline built from the first relay where they drove.  On subsequent relays
    the same driver can be compared against that baseline even on a different kart.
  • If no driver name is available, we fall back to relay-index keys
    ("relay_0", "relay_1" …).  Each relay is then treated independently.

kart_delta = mean(recent laps on current kart) - driver_baseline
  < -1.2 %  → GOOD
  > +1.5 %  → BAD
  otherwise → MEDIUM
  insufficient data → UNKNOWN
"""
import statistics
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

GOOD_THRESHOLD    = -0.012  # 1.2 % faster than baseline
BAD_THRESHOLD     =  0.015  # 1.5 % slower than baseline
MIN_BASELINE_LAPS =  5      # laps to establish a driver baseline
MIN_KART_LAPS     =  2      # clean laps on current kart before rating (out-lap already excluded)
RECENT_WINDOW     =  7      # sliding window for current-kart average
MAX_DELTA_OBS     = 20      # max delta observations kept per kart


# ── Per-driver record ─────────────────────────────────────────────────────────

@dataclass
class DriverRecord:
    """Tracks one driver (identified by name or relay index) across all stints."""
    key: str                    # driver name or "relay_N"
    baseline_laps: list[float] = field(default_factory=list)
    baseline_locked: bool = False
    # kart_label → recent normalised laps
    kart_laps: dict[str, deque] = field(
        default_factory=lambda: defaultdict(lambda: deque(maxlen=RECENT_WINDOW))
    )

    def baseline_speed(self) -> float | None:
        if len(self.baseline_laps) < MIN_BASELINE_LAPS:
            return None
        return statistics.median(self.baseline_laps)

    def delta_on(self, kart_label: str) -> float | None:
        baseline = self.baseline_speed()
        if baseline is None:
            return None
        laps = list(self.kart_laps.get(kart_label, []))
        if len(laps) < MIN_KART_LAPS:
            return None
        return statistics.mean(laps) - baseline

    def lock_baseline(self) -> None:
        if not self.baseline_locked and len(self.baseline_laps) >= MIN_BASELINE_LAPS:
            self.baseline_locked = True
            logger.info("Driver %s baseline locked (%d laps)", self.key, len(self.baseline_laps))


# ── Per-team record ───────────────────────────────────────────────────────────

@dataclass
class TeamRecord:
    team_id: str
    last_pit_number: int = 0
    current_driver_key: str = ""
    laps_since_relay: int = 0          # resets to 0 on each relay change; out-lap (1) is skipped
    drivers: dict[str, DriverRecord] = field(default_factory=dict)

    def relay_key(self, pit_number: int, driver_name: str) -> str:
        """
        Derive the driver key for a given relay.
        Named driver → use their name (so the same person across relays shares a baseline).
        Unknown driver → use relay index to isolate stints.
        """
        return driver_name if driver_name else f"relay_{pit_number}"

    def get_driver(self, key: str) -> DriverRecord:
        if key not in self.drivers:
            self.drivers[key] = DriverRecord(key=key)
        return self.drivers[key]


# ── Kart evidence (aggregate across all teams/drivers) ────────────────────────

@dataclass
class KartEvidence:
    deltas: deque = field(default_factory=lambda: deque(maxlen=MAX_DELTA_OBS))

    def add(self, delta: float) -> None:
        self.deltas.append(delta)

    def rate(self) -> tuple[str, float, float]:
        """Returns (rating, confidence 0–1, median_delta)."""
        if not self.deltas:
            return "UNKNOWN", 0.0, 0.0
        n = len(self.deltas)
        confidence = min(n / 5.0, 1.0)
        median_delta = statistics.median(self.deltas)
        if confidence < 0.4:
            return "UNKNOWN", confidence, median_delta
        if median_delta < GOOD_THRESHOLD:
            return "GOOD", confidence, median_delta
        if median_delta > BAD_THRESHOLD:
            return "BAD", confidence, median_delta
        return "MEDIUM", confidence, median_delta


# ── Main ranker ───────────────────────────────────────────────────────────────

class KartRanker:
    """Real-time kart performance ranker — per-driver baseline model."""

    def __init__(self, track_monitor):
        self._track = track_monitor
        self._teams: dict[str, TeamRecord] = {}
        self._karts: dict[str, KartEvidence] = defaultdict(KartEvidence)

    def record_lap(
        self,
        team_id: str,
        kart_label: str,
        lap_ms: int,
        is_pit: bool = False,
        pit_number: int = 0,
        driver_name: str = "",
    ) -> None:
        """
        Record a completed lap.
        kart_label  : physical kart label ("K07"), not the bib number.
        pit_number  : current pit-stop count from the timing grid.
        driver_name : current driver name if the grid exposes it, else "".
        """
        if kart_label in ("?", "", None) or is_pit:
            return

        norm = self._track.normalize(lap_ms)
        if norm is None:
            return
        self._track.add_lap(lap_ms)

        if team_id not in self._teams:
            self._teams[team_id] = TeamRecord(team_id=team_id)
        team = self._teams[team_id]

        # Detect relay change (pit count advanced)
        if pit_number > team.last_pit_number:
            outgoing = team.drivers.get(team.current_driver_key)
            if outgoing:
                outgoing.lock_baseline()
            team.last_pit_number = pit_number
            team.laps_since_relay = 0

        team.laps_since_relay += 1

        # Determine current driver key
        driver_key = team.relay_key(pit_number, driver_name)
        team.current_driver_key = driver_key
        drv = team.get_driver(driver_key)

        # Skip out-lap: first lap after a relay change is always slow
        if team.laps_since_relay == 1:
            logger.debug("out-lap skipped: team=%s kart=%s", team_id, kart_label)
            return

        # Feed kart lap
        drv.kart_laps[kart_label].append(norm)

        # Build baseline while not yet locked
        if not drv.baseline_locked:
            drv.baseline_laps.append(norm)

        # Compute delta and feed kart evidence
        delta = drv.delta_on(kart_label)
        if delta is not None:
            self._karts[kart_label].add(delta)
            logger.debug("kart=%s delta=%.4f (team=%s driver=%s)", kart_label, delta, team_id, driver_key)

    def on_pit_stop(self, team_id: str) -> None:
        """
        Called when a pit-stop entry is detected (pit count just increased).
        Locks the current driver's baseline so it won't be polluted by the
        slow-down / in-lap.
        """
        team = self._teams.get(team_id)
        if not team:
            return
        drv = team.drivers.get(team.current_driver_key)
        if drv:
            drv.lock_baseline()

    def rate_kart(self, kart_label: str) -> dict:
        evidence = self._karts.get(kart_label)
        if evidence is None:
            return self._unknown(kart_label)
        rating, conf, delta = evidence.rate()
        return {
            "kart_label": kart_label,
            "rating": rating,
            "confidence": round(conf * 100),
            "delta_pct": round(delta * 100, 2),
            "observations": len(evidence.deltas),
        }

    def reserve_summary(self, kart_labels: list[str]) -> dict:
        if not kart_labels:
            return {"good": 0, "medium": 0, "bad": 0, "unknown": 100}
        ratings = [self.rate_kart(k)["rating"] for k in kart_labels]
        total = len(ratings)
        return {
            "good":    round(ratings.count("GOOD")    / total * 100),
            "medium":  round(ratings.count("MEDIUM")  / total * 100),
            "bad":     round(ratings.count("BAD")     / total * 100),
            "unknown": round(ratings.count("UNKNOWN") / total * 100),
        }

    def field_ranking(self) -> list[dict]:
        rated = [self.rate_kart(k) for k in self._karts]
        rated.sort(key=lambda r: (
            {"GOOD": 0, "MEDIUM": 1, "BAD": 2, "UNKNOWN": 3}[r["rating"]],
            r["delta_pct"],
        ))
        return rated

    @staticmethod
    def _unknown(kart_label: str) -> dict:
        return {"kart_label": kart_label, "rating": "UNKNOWN",
                "confidence": 0, "delta_pct": 0.0, "observations": 0}
