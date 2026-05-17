"""
Performance model based on stints — no physical kart identity needed.

Team level (ELITE/FAST/MEDIUM/SLOW): quartile of team's weighted avg delta vs field.
Kart quality (GOOD/NEUTRAL/BAD): current stint avg vs team's expected delta.
Driver level (ELITE/FAST/MEDIUM/SLOW): same logic aggregated across driver's stints.

Algorithm:
  field_avg  = rolling median of all valid laps in the last FIELD_WINDOW laps
  team_delta = (team_recent_avg - field_avg) / field_avg

  Team level → quartile rank across all teams (updated after each stint):
    top 25%    → ELITE
    25-50%     → FAST
    50-75%     → MEDIUM
    bottom 25% → SLOW

  kart_score = team_current_delta - expected_delta_for_team_level
    < GOOD_THRESHOLD   → GOOD    (faster than expected for their level)
    > BAD_THRESHOLD    → BAD     (slower than expected for their level)
    otherwise          → NEUTRAL

  kart_quality requires at least MIN_STINT_LAPS valid laps on the current stint.
"""
import statistics
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
GOOD_THRESHOLD = -0.015   # 1.5% faster than expected for team level → GOOD
BAD_THRESHOLD  =  0.020   # 2.0% slower than expected for team level → BAD
MIN_STINT_LAPS =  4       # laps needed to rate kart quality in current stint
RECENT_WINDOW  =  8       # rolling window for current-stint avg (laps)
FIELD_WINDOW   = 200      # global rolling window for field average
MIN_FIELD_LAPS = 10       # minimum field laps before any level/quality computed


# ── Stint record ──────────────────────────────────────────────────────────────

@dataclass
class StintRecord:
    driver_key: str
    laps: list = field(default_factory=list)

    @property
    def avg(self) -> Optional[float]:
        return statistics.median(self.laps) if self.laps else None

    @property
    def count(self) -> int:
        return len(self.laps)


# ── Driver aggregate ──────────────────────────────────────────────────────────

@dataclass
class DriverAggregate:
    name: str
    deltas: list = field(default_factory=list)
    total_laps: int = 0

    def level(self, thresholds: Optional[tuple]) -> str:
        if thresholds is None or not self.deltas or self.total_laps < 5:
            return "UNKNOWN"
        avg = statistics.median(self.deltas)
        p25, p50, p75 = thresholds
        if avg <= p25:
            return "ELITE"
        if avg <= p50:
            return "FAST"
        if avg <= p75:
            return "MEDIUM"
        return "SLOW"


# ── Team record ───────────────────────────────────────────────────────────────

@dataclass
class TeamRecord:
    team_id: str
    team_name: str = ""
    current_stint: StintRecord = field(default_factory=lambda: StintRecord(driver_key=""))
    current_laps: deque = field(default_factory=lambda: deque(maxlen=RECENT_WINDOW))
    last_pit_number: int = 0
    laps_since_relay: int = 0
    stint_deltas: list = field(default_factory=list)  # list of (delta, lap_count)
    drivers: dict = field(default_factory=dict)

    def weighted_historical_delta(self) -> Optional[float]:
        if not self.stint_deltas:
            return None
        total_weight = sum(n for _, n in self.stint_deltas)
        if total_weight == 0:
            return None
        return sum(d * n for d, n in self.stint_deltas) / total_weight

    def current_delta(self, field_avg: float) -> Optional[float]:
        laps = list(self.current_laps)
        if len(laps) < MIN_STINT_LAPS:
            return None
        return (statistics.median(laps) - field_avg) / field_avg

    def get_driver(self, name: str) -> DriverAggregate:
        if name not in self.drivers:
            self.drivers[name] = DriverAggregate(name=name)
        return self.drivers[name]


# ── Main ranker ───────────────────────────────────────────────────────────────

class KartRanker:
    """Real-time performance ranker using stint-based relative model."""

    def __init__(self, track_monitor=None):
        self._track = track_monitor
        self._teams: dict[str, TeamRecord] = {}
        self._field_laps: deque = deque(maxlen=FIELD_WINDOW)

    def record_lap(
        self,
        team_id: str,
        kart_label: str,
        lap_ms: int,
        is_pit: bool = False,
        pit_number: int = 0,
        driver_name: str = "",
        team_name: str = "",
    ) -> None:
        if is_pit or lap_ms <= 0:
            return

        if self._track:
            norm = self._track.normalize(lap_ms)
            if norm is None:
                return
            self._track.add_lap(lap_ms)
            lap_val = norm
        else:
            lap_val = lap_ms / 1000.0

        self._field_laps.append(lap_val)

        if team_id not in self._teams:
            self._teams[team_id] = TeamRecord(team_id=team_id)
        team = self._teams[team_id]
        if team_name:
            team.team_name = team_name

        if pit_number > team.last_pit_number:
            self._close_stint(team)
            team.last_pit_number = pit_number
            team.laps_since_relay = 0
            team.current_stint = StintRecord(driver_key=driver_name or f"relay_{pit_number}")
            team.current_laps.clear()

        team.laps_since_relay += 1

        # Skip out-lap
        if team.laps_since_relay == 1:
            logger.debug("out-lap skipped: team=%s", team_id)
            return

        team.current_laps.append(lap_val)
        team.current_stint.laps.append(lap_val)

        if driver_name:
            drv = team.get_driver(driver_name)
            drv.total_laps += 1

    def on_pit_stop(self, team_id: str) -> None:
        team = self._teams.get(team_id)
        if team:
            self._close_stint(team)

    def team_summary(self, team_id: str) -> dict:
        team = self._teams.get(team_id)
        if not team:
            return self._unknown_team(team_id)

        field_avg = self._field_avg()
        thresholds = self._quartile_thresholds()

        team_level = self._team_level(team, thresholds)
        kart_quality, kart_score = self._kart_quality(team, field_avg, thresholds)
        current_delta = team.current_delta(field_avg) if field_avg else None

        drivers_out = [
            {
                "name": drv.name,
                "level": drv.level(thresholds),
                "total_laps": drv.total_laps,
            }
            for drv in team.drivers.values()
        ]

        return {
            "team_id": team_id,
            "team_name": team.team_name,
            "team_level": team_level,
            "kart_quality": kart_quality,
            "kart_score_pct": round(kart_score * 100, 2) if kart_score is not None else None,
            "current_delta_pct": round(current_delta * 100, 2) if current_delta is not None else None,
            "current_stint_laps": team.current_stint.count,
            "completed_stints": len(team.stint_deltas),
            "drivers": drivers_out,
        }

    def all_teams_summary(self) -> list[dict]:
        level_order = {"ELITE": 0, "FAST": 1, "MEDIUM": 2, "SLOW": 3, "UNKNOWN": 4}
        summaries = [self.team_summary(tid) for tid in self._teams]
        summaries.sort(key=lambda s: (
            level_order.get(s["team_level"], 4),
            s["current_delta_pct"] if s["current_delta_pct"] is not None else 99,
        ))
        return summaries

    def kart_quality_for_team(self, team_id: str) -> dict:
        """Returns a KartRating-compatible dict for LiveTiming badge."""
        team = self._teams.get(team_id)
        if not team:
            return {
                "kart_label": "?", "rating": "UNKNOWN", "confidence": 0,
                "delta_pct": 0.0, "observations": 0,
                "team_level": "UNKNOWN", "kart_quality": "UNKNOWN",
            }

        field_avg = self._field_avg()
        thresholds = self._quartile_thresholds()
        kart_quality, kart_score = self._kart_quality(team, field_avg, thresholds)
        team_level = self._team_level(team, thresholds)

        laps_in_stint = team.current_stint.count
        confidence = min(int(laps_in_stint / MIN_STINT_LAPS * 100), 100)
        rating_map = {"GOOD": "GOOD", "NEUTRAL": "MEDIUM", "BAD": "BAD", "UNKNOWN": "UNKNOWN"}

        return {
            "kart_label": "?",
            "rating": rating_map.get(kart_quality, "UNKNOWN"),
            "confidence": confidence,
            "delta_pct": round(kart_score * 100, 2) if kart_score is not None else 0.0,
            "observations": laps_in_stint,
            "team_level": team_level,
            "kart_quality": kart_quality,
        }

    # Legacy compat
    def rate_kart(self, kart_label: str) -> dict:
        return {"kart_label": kart_label, "rating": "UNKNOWN",
                "confidence": 0, "delta_pct": 0.0, "observations": 0}

    def field_ranking(self) -> list[dict]:
        return self.all_teams_summary()

    def reserve_summary(self, kart_labels: list[str]) -> dict:
        return {"good": 0, "medium": 0, "bad": 0, "unknown": 100}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _close_stint(self, team: TeamRecord) -> None:
        if team.current_stint.count < MIN_STINT_LAPS:
            return
        field_avg = self._field_avg()
        if not field_avg:
            return
        avg = team.current_stint.avg
        if avg is None:
            return
        delta = (avg - field_avg) / field_avg
        team.stint_deltas.append((delta, team.current_stint.count))

        drv_key = team.current_stint.driver_key
        if drv_key and not drv_key.startswith("relay_"):
            drv = team.get_driver(drv_key)
            drv.deltas.append(delta)

    def _field_avg(self) -> Optional[float]:
        laps = list(self._field_laps)
        if len(laps) < MIN_FIELD_LAPS:
            return None
        return statistics.median(laps)

    def _all_weighted_deltas(self) -> list:
        return [
            d for team in self._teams.values()
            if (d := team.weighted_historical_delta()) is not None
        ]

    def _quartile_thresholds(self) -> Optional[tuple]:
        deltas = sorted(self._all_weighted_deltas())
        if len(deltas) < 4:
            return None
        n = len(deltas)
        return (
            deltas[max(0, int(n * 0.25) - 1)],
            deltas[max(0, int(n * 0.50) - 1)],
            deltas[max(0, int(n * 0.75) - 1)],
        )

    def _team_level(self, team: TeamRecord, thresholds: Optional[tuple]) -> str:
        if thresholds is None:
            return "UNKNOWN"
        d = team.weighted_historical_delta()
        if d is None:
            return "UNKNOWN"
        p25, p50, p75 = thresholds
        if d <= p25:
            return "ELITE"
        if d <= p50:
            return "FAST"
        if d <= p75:
            return "MEDIUM"
        return "SLOW"

    def _expected_delta_for_level(self, level: str, thresholds: tuple) -> float:
        p25, p50, p75 = thresholds
        p0 = p25 - (p50 - p25)
        p100 = p75 + (p75 - p50)
        return {
            "ELITE":  (p0 + p25) / 2,
            "FAST":   (p25 + p50) / 2,
            "MEDIUM": (p50 + p75) / 2,
            "SLOW":   (p75 + p100) / 2,
        }.get(level, 0.0)

    def _kart_quality(
        self, team: TeamRecord, field_avg: Optional[float], thresholds: Optional[tuple]
    ) -> tuple:
        if field_avg is None or thresholds is None:
            return "UNKNOWN", None
        current_delta = team.current_delta(field_avg)
        if current_delta is None:
            return "UNKNOWN", None
        level = self._team_level(team, thresholds)
        if level == "UNKNOWN":
            return "UNKNOWN", None
        expected = self._expected_delta_for_level(level, thresholds)
        kart_score = current_delta - expected
        if kart_score < GOOD_THRESHOLD:
            return "GOOD", kart_score
        if kart_score > BAD_THRESHOLD:
            return "BAD", kart_score
        return "NEUTRAL", kart_score

    @staticmethod
    def _unknown_team(team_id: str) -> dict:
        return {
            "team_id": team_id, "team_name": "", "team_level": "UNKNOWN",
            "kart_quality": "UNKNOWN", "kart_score_pct": None,
            "current_delta_pct": None, "current_stint_laps": 0,
            "completed_stints": 0, "drivers": [],
        }
