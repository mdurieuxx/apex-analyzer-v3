"""
Performance model — v2 algorithm.

Two independent dimensions: pace (speed) and regularity (consistency).
Both expressed as percentile ranks in the field (0→100, higher = better).
Combined via configurable weights: combined_rank = WEIGHT_PACE × pace_rank + WEIGHT_REG × regularity_rank.

Default weights: endurance = 30% pace / 70% regularity.

Field reference (ref_piste_T):
  Median of all field normal laps in a rolling 30-min time window (≈1800 laps for 31 teams).
  Falls back to last FIELD_WINDOW_LAPS entries when race time not available (replay mode).

Outlier filter:
  lap > median_current_stint × (1 + OUTLIER_PCT) → excluded from scoring, kept as is_outlier.
  Applied only once the stint has ≥ 3 filtered laps (to avoid filtering during bootstrap).

Kart quality:
  kart_score = current_delta - skill_expected_delta
  Classified into real-time quartiles across all active teams (no fixed thresholds).
  Stabilized: label changes only after KART_STABLE_LAPS consecutive laps in new quartile.

Confidence hierarchy for kart estimates (A→E):
  A: same pilot, same stint (pure kart signal)
  B: same pilot, multiple stints this event
  C: driver DB profile (cross-event EWMA)
  C2: team DB profile (cross-event EWMA)
  D: team historical this event (all pilots)
  E: field category quartile fallback

Lap classification after a pit stop:
  passage 1  : partial lap (pit exit → line) — ignored
  passage 2  : out-lap — separated, compared to out-lap field
  passage 3-4: warm-up — excluded from all scoring
  passage 5+ : normal laps — contribute to scoring
  (first stint: all laps from passage 2 are normal)
"""
import math
import statistics
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from apex.grid_parser import canonical_team_name

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
OUTLIER_PCT        = 0.12   # lap > median × 1.12 → outlier
FIELD_WINDOW_S     = 1800   # 30-min rolling window for ref_piste_T (race elapsed seconds)
FIELD_WINDOW_LAPS  = 1800   # fallback when race time unavailable (same count ≈ 30 min)
MIN_STINT_LAPS     =  4     # filtered normal laps before full scoring mode
RECENT_WINDOW      =  8     # rolling window for current-delta computation
MIN_FIELD_LAPS     = 10     # min field laps before ref_piste_T is valid
MIN_FIELD_TEAMS    =  3     # min teams with data before percentile ranks are meaningful
OUTLAP_FIELD_MIN   =  4
MIN_DRIVER_LAPS    = 15
MIN_DRIVER_STINTS  =  2
KART_STABLE_LAPS   =  2     # consecutive laps before a kart label flip is confirmed
SLOPE_IMPROVING    = -50.0  # ms/lap — intra-stint linear regression threshold
SLOPE_DEGRADING    =  50.0
HISTORICAL_LAPS_CAP = 15   # max weight per historical stint (soft prior)
PROFILE_DECAY_LAMBDA = 0.003  # EWMA decay: λ=0.003 → 1-year-old event weighs ~33%

DEFAULT_WEIGHT_PACE = 0.30
DEFAULT_WEIGHT_REG  = 0.70

# Pace min-floor: a team at pace_rank < PACE_FLOOR_RANK will have combined_rank capped
# regardless of regularity — prevents a very slow but regular team from ranking high.
PACE_FLOOR_RANK = 20.0


# ── Stint summary (immutable snapshot of a closed stint) ─────────────────────

@dataclass
class StintSummary:
    driver: str
    lap_count: int          # filtered normal laps
    total_laps_ms: int      # all non-partial lap count (incl. out-lap / warm-up)
    avg_ms: int
    best_ms: int
    std_ms: float
    delta_pct: Optional[float]
    pace_rank: Optional[float]       = None
    regularity_rank: Optional[float] = None
    combined_rank: Optional[float]   = None
    driver_profile: str              = ""
    stint_trend: str                 = ""
    is_current: bool                 = False


# ── Stint record ──────────────────────────────────────────────────────────────

@dataclass
class StintRecord:
    driver_key: str
    laps: list = field(default_factory=list)        # normalized, unfiltered normal laps
    filtered_laps: list = field(default_factory=list)  # normalized, outlier-excluded
    filtered_laps_ms: list = field(default_factory=list)  # raw ms for trend slope
    laps_ms: list = field(default_factory=list)     # all non-partial raw ms (incl. out/warm-up)
    out_lap: Optional[float] = None
    outlier_count: int = 0
    closed: bool = False

    # Kart label stabilization
    _kart_label_pending: str = ""
    _kart_pending_count: int = 0
    kart_label_stable: str = "UNKNOWN"

    @property
    def avg(self) -> Optional[float]:
        return statistics.median(self.filtered_laps) if self.filtered_laps else None

    @property
    def count(self) -> int:
        """Filtered normal laps — used for MIN_STINT_LAPS threshold."""
        return len(self.filtered_laps)

    @property
    def best_lap(self) -> Optional[float]:
        return min(self.filtered_laps) if self.filtered_laps else None

    def update_kart_label(self, new_label: str) -> str:
        """Stabilized kart label: only flip after KART_STABLE_LAPS consecutive same-label laps."""
        if new_label == self.kart_label_stable:
            self._kart_label_pending = ""
            self._kart_pending_count = 0
            return self.kart_label_stable
        if new_label == self._kart_label_pending:
            self._kart_pending_count += 1
        else:
            self._kart_label_pending = new_label
            self._kart_pending_count = 1
        if self._kart_pending_count >= KART_STABLE_LAPS:
            self.kart_label_stable = new_label
            self._kart_label_pending = ""
            self._kart_pending_count = 0
        return self.kart_label_stable


# ── Driver aggregate ──────────────────────────────────────────────────────────

@dataclass
class DriverAggregate:
    name: str
    deltas: list = field(default_factory=list)
    pace_ranks: list = field(default_factory=list)
    reg_ranks: list = field(default_factory=list)
    total_laps: int = 0

    def profile_label(self, pace_rank: Optional[float], reg_rank: Optional[float]) -> str:
        if pace_rank is None or reg_rank is None:
            return ""
        fast = pace_rank >= 50
        regular = reg_rank >= 50
        if fast and regular:
            return "COMPLET"
        if fast and not regular:
            return "NERVEUX"
        if not fast and regular:
            return "SAFE FINISHER"
        return "IMPRÉVISIBLE"


# ── Team record ───────────────────────────────────────────────────────────────

@dataclass
class TeamRecord:
    team_id: str
    team_name: str = ""
    category: str = ""
    current_stint: StintRecord = field(default_factory=lambda: StintRecord(driver_key=""))
    current_laps: deque = field(default_factory=lambda: deque(maxlen=RECENT_WINDOW))
    last_pit_number: int = 0
    laps_since_relay: int = 0
    stint_deltas: list = field(default_factory=list)  # [(delta, lap_count)]
    drivers: dict = field(default_factory=dict)
    closed_stints: list = field(default_factory=list)  # list of StintSummary

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


# ── Field lap entry ───────────────────────────────────────────────────────────

@dataclass
class FieldLap:
    t: float      # race elapsed seconds (0.0 if unknown)
    val: float    # normalized lap value


# ── Main ranker ───────────────────────────────────────────────────────────────

class KartRanker:
    """Real-time performance ranker — v2 (pace + regularity percentile ranks)."""

    def __init__(self, track_monitor=None, weight_pace: float = DEFAULT_WEIGHT_PACE,
                 weight_reg: float = DEFAULT_WEIGHT_REG):
        self._track = track_monitor
        self._teams: dict[str, TeamRecord] = {}
        self._field_laps: list[FieldLap] = []  # time-windowed normal lap values
        self._field_outlaps: deque = deque(maxlen=100)
        self._kart_to_team: dict[str, str] = {}
        self._current_t: float = 0.0  # last seen race elapsed seconds
        self.weight_pace = weight_pace
        self.weight_reg = weight_reg

        # Historical priors from previous event
        self._hist_stints: dict[str, list[tuple[float, int]]] = {}
        self._hist_drivers: dict[str, dict[str, list[float]]] = {}

        # Cross-event DB profiles (loaded at event start)
        self._db_driver_profiles: dict[str, dict] = {}  # driver_key → profile dict
        self._db_team_profiles: dict[str, dict] = {}    # team_key → profile dict

    def record_lap(
        self,
        team_id: str,
        kart_label: str,
        lap_ms: int,
        is_pit: bool = False,
        pit_number: int = 0,
        driver_name: str = "",
        team_name: str = "",
        category: str = "",
        event_t: float = 0.0,
    ) -> None:
        if is_pit or lap_ms <= 0:
            return

        if event_t > 0:
            self._current_t = event_t

        if kart_label and kart_label not in ("?", ""):
            self._kart_to_team[kart_label] = team_id

        if team_id not in self._teams:
            self._teams[team_id] = TeamRecord(team_id=team_id)
            if team_name and team_name in self._hist_stints:
                self._teams[team_id].stint_deltas = list(self._hist_stints[team_name])
                for drv_name, deltas in self._hist_drivers.get(team_name, {}).items():
                    drv = self._teams[team_id].get_driver(drv_name)
                    drv.deltas = list(deltas)
                logger.info("Seeded historical data for team=%s (%d stints)", team_name,
                            len(self._hist_stints[team_name]))

        team = self._teams[team_id]
        if team_name:
            team.team_name = team_name
        if category:
            team.category = category

        if pit_number > team.last_pit_number:
            self._close_stint(team)
            if self._track:
                self._track.reset_team(team_id)
            team.last_pit_number = pit_number
            team.laps_since_relay = 0
            team.current_stint = StintRecord(driver_key=driver_name or f"relay_{pit_number}")
            team.current_laps.clear()

        team.laps_since_relay += 1
        n = team.laps_since_relay

        if n == 1:
            return  # partial lap

        team.current_stint.laps_ms.append(lap_ms)

        if self._track:
            self._track.update_team_best(team_id, min(team.current_stint.laps_ms))
            norm = self._track.normalize(lap_ms)
            if norm is None:
                return
            lap_val = norm
        else:
            lap_val = lap_ms / 1000.0

        if pit_number > 0:
            if n == 2:
                team.current_stint.out_lap = lap_val
                self._field_outlaps.append(lap_val)
                return
            if n <= 4:
                return  # warm-up

        # Normal lap — outlier filtering
        team.current_stint.laps.append(lap_val)  # unfiltered

        is_outlier = self._is_outlier(team.current_stint, lap_val)
        if is_outlier:
            team.current_stint.outlier_count += 1
        else:
            team.current_stint.filtered_laps.append(lap_val)
            team.current_stint.filtered_laps_ms.append(lap_ms)
            team.current_laps.append(lap_val)

            t = self._current_t if event_t > 0 else 0.0
            self._field_laps.append(FieldLap(t=t, val=lap_val))
            # Keep field list bounded when no time info
            if len(self._field_laps) > FIELD_WINDOW_LAPS * 2:
                self._field_laps = self._field_laps[-FIELD_WINDOW_LAPS:]

        if driver_name:
            drv = team.get_driver(driver_name)
            drv.total_laps += 1

    def reset_live_data(self) -> None:
        self._teams.clear()
        self._field_laps.clear()
        self._field_outlaps.clear()
        self._kart_to_team.clear()
        self._current_t = 0.0
        if self._track:
            self._track._team_bests.clear()

    def on_pit_stop(self, team_id: str) -> None:
        team = self._teams.get(team_id)
        if team:
            self._close_stint(team)

    def on_pit_out(self, team_id: str, driver_name: str = "") -> None:
        team = self._teams.get(team_id)
        if not team:
            return
        if self._track:
            self._track.reset_team(team_id)
        team.current_stint = StintRecord(driver_key=driver_name or f"relay_{team.last_pit_number}")
        team.current_laps.clear()
        team.laps_since_relay = 0

    def team_summary(self, team_id: str) -> dict:
        team = self._teams.get(team_id)
        if not team:
            return self._unknown_team(team_id)

        field_avg = self._field_avg()
        all_pace, all_reg = self._collect_field_scores()
        current_delta = team.current_delta(field_avg) if field_avg else None

        pace_rank = self._compute_pace_rank(current_delta, all_pace) if current_delta is not None else None
        reg_score = self._compute_reg_score(team)
        reg_rank = self._compute_reg_rank(reg_score, all_reg) if reg_score is not None else None
        combined_rank = self._compute_combined_rank(pace_rank, reg_rank)
        driver_profile = self._driver_profile_label(pace_rank, reg_rank)
        stint_trend = self._stint_trend(team)
        kart_quality = self._kart_quality_label(team, field_avg, all_pace)
        team_level = self._team_level_v2(pace_rank, reg_rank, combined_rank)
        kart_score = self._kart_score_raw(team, field_avg)
        kart_conf = self._kart_confidence_level(team)

        drivers_out = [
            {
                "name": drv.name,
                "level": self._driver_level_label(drv),
                "total_laps": drv.total_laps,
                "avg_delta_pct": round(statistics.median(drv.deltas) * 100, 2) if drv.deltas else None,
                "stint_count": len(drv.deltas),
                "pace_rank": round(statistics.mean(drv.pace_ranks), 1) if drv.pace_ranks else None,
                "regularity_rank": round(statistics.mean(drv.reg_ranks), 1) if drv.reg_ranks else None,
            }
            for drv in team.drivers.values()
        ]

        stints_out = [
            {
                "driver": s.driver,
                "lap_count": s.lap_count,
                "total_laps_ms": s.total_laps_ms,
                "avg_ms": s.avg_ms,
                "best_ms": s.best_ms,
                "std_ms": s.std_ms,
                "delta_pct": s.delta_pct,
                "pace_rank": s.pace_rank,
                "regularity_rank": s.regularity_rank,
                "combined_rank": s.combined_rank,
                "driver_profile": s.driver_profile,
                "stint_trend": s.stint_trend,
                "is_current": False,
            }
            for s in team.closed_stints
        ]
        if team.current_stint.laps_ms:
            lms = team.current_stint.laps_ms
            stints_out.append({
                "driver": team.current_stint.driver_key,
                "lap_count": team.current_stint.count,
                "total_laps_ms": len(lms),
                "avg_ms": int(statistics.median(lms)),
                "best_ms": int(min(lms)),
                "std_ms": round(statistics.stdev(lms), 1) if len(lms) >= 2 else 0.0,
                "delta_pct": round(current_delta * 100, 2) if current_delta is not None else None,
                "pace_rank": round(pace_rank, 1) if pace_rank is not None else None,
                "regularity_rank": round(reg_rank, 1) if reg_rank is not None else None,
                "combined_rank": round(combined_rank, 1) if combined_rank is not None else None,
                "driver_profile": driver_profile,
                "stint_trend": stint_trend,
                "is_current": True,
            })

        return {
            "team_id": team_id,
            "team_name": team.team_name,
            "team_level": team_level,
            "kart_quality": kart_quality,
            "kart_score_pct": round(kart_score * 100, 2) if kart_score is not None else None,
            "kart_confidence": kart_conf,
            "current_delta_pct": round(current_delta * 100, 2) if current_delta is not None else None,
            "pace_rank": round(pace_rank, 1) if pace_rank is not None else None,
            "regularity_rank": round(reg_rank, 1) if reg_rank is not None else None,
            "combined_rank": round(combined_rank, 1) if combined_rank is not None else None,
            "driver_profile": driver_profile,
            "stint_trend": stint_trend,
            "outlier_laps": team.current_stint.outlier_count,
            "current_stint_laps": team.current_stint.count,
            "completed_stints": len(team.stint_deltas) + (1 if team.current_stint.laps_ms else 0),
            "drivers": drivers_out,
            "stints": stints_out,
        }

    def all_teams_summary(self) -> list[dict]:
        summaries = [self.team_summary(tid) for tid in self._teams]
        summaries.sort(key=lambda s: (
            -(s["combined_rank"] if s["combined_rank"] is not None else -1),
            s["current_delta_pct"] if s["current_delta_pct"] is not None else 99,
        ))
        return summaries

    def kart_quality_for_team(self, team_id: str) -> dict:
        team = self._teams.get(team_id)
        if not team:
            return {
                "kart_label": "?", "rating": "UNKNOWN", "confidence": 0,
                "delta_pct": 0.0, "observations": 0,
                "team_level": "UNKNOWN", "kart_quality": "UNKNOWN",
            }

        field_avg = self._field_avg()
        all_pace, _ = self._collect_field_scores()
        kart_quality = self._kart_quality_label(team, field_avg, all_pace)
        kart_conf = self._kart_confidence_level(team)
        conf_pct = {"A": 95, "B": 75, "C": 60, "C2": 55, "D": 40, "E": 20}.get(kart_conf, 0)

        current_delta = team.current_delta(field_avg) if field_avg else None
        all_pace2, all_reg = self._collect_field_scores()
        pace_rank = self._compute_pace_rank(current_delta, all_pace2) if current_delta is not None else None
        reg_score = self._compute_reg_score(team)
        reg_rank = self._compute_reg_rank(reg_score, all_reg) if reg_score is not None else None
        combined_rank = self._compute_combined_rank(pace_rank, reg_rank)
        team_level = self._team_level_v2(pace_rank, reg_rank, combined_rank)

        return {
            "kart_label": "?",
            "rating": kart_quality,
            "confidence": conf_pct,
            "delta_pct": round(current_delta * 100, 2) if current_delta is not None else 0.0,
            "observations": team.current_stint.count,
            "team_level": team_level,
            "kart_quality": kart_quality,
        }

    def rate_kart(self, kart_label: str) -> dict:
        team_id = self._kart_to_team.get(kart_label)
        if not team_id:
            return {"kart_label": kart_label, "rating": "UNKNOWN",
                    "confidence": 0, "delta_pct": 0.0, "observations": 0}
        q = self.kart_quality_for_team(team_id)
        q["kart_label"] = kart_label
        return q

    def reserve_summary(self, kart_labels: list[str]) -> dict:
        counts: dict[str, int] = {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 0}
        for label in kart_labels:
            if not label or label == "?":
                counts["unknown"] += 1
                continue
            r = self.rate_kart(label).get("rating", "UNKNOWN").lower()
            counts[r] = counts.get(r, 0) + 1
            if r not in counts:
                counts["unknown"] += 1
        total = sum(counts.values())
        if not total:
            return {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 100}
        return {k: round(v / total * 100) for k, v in counts.items()}

    def get_stint_stats(self, team_id: str) -> dict:
        team = self._teams.get(team_id)
        if not team or not team.current_stint.laps_ms:
            return {"best_lap_ms": None, "avg_lap_ms": None, "std_dev_ms": None, "lap_count": 0}
        laps = team.current_stint.laps_ms
        return {
            "best_lap_ms": min(laps),
            "avg_lap_ms": round(statistics.mean(laps), 1),
            "std_dev_ms": round(statistics.stdev(laps), 1) if len(laps) >= 2 else 0.0,
            "lap_count": len(laps),
        }

    def seed_from_previous_event(self, event_id: int, db) -> int:
        """Load historical stints from a previous event to bootstrap priors."""
        from models import EventStint, EventEntry
        rows = (
            db.query(EventStint, EventEntry)
            .join(EventEntry, EventStint.entry_id == EventEntry.id)
            .filter(
                EventStint.event_id == event_id,
                EventStint.lap_count >= MIN_STINT_LAPS,
                EventStint.avg_lap_ms.isnot(None),
            )
            .all()
        )
        if not rows:
            return 0

        avgs = [s.avg_lap_ms for s, _ in rows]
        field_avg = statistics.median(avgs)
        if not field_avg:
            return 0

        self._hist_stints.clear()
        self._hist_drivers.clear()

        for stint, entry in rows:
            name = canonical_team_name(entry.team_name)
            if not name:
                continue
            delta = (stint.avg_lap_ms - field_avg) / field_avg
            weight = min(stint.lap_count, HISTORICAL_LAPS_CAP)
            self._hist_stints.setdefault(name, []).append((delta, weight))
            if stint.driver_name:
                self._hist_drivers.setdefault(name, {}).setdefault(
                    stint.driver_name, []).append(delta)

        logger.info("Seeded priors from event %d: %d teams", event_id, len(self._hist_stints))
        return len(self._hist_stints)

    def load_db_profiles(self, db) -> None:
        """Load cross-event driver and team profiles from DB (called at event start)."""
        try:
            from models import DriverProfile, TeamProfile
            for p in db.query(DriverProfile).all():
                self._db_driver_profiles[p.driver_key] = {
                    "pace_rank_ewma": p.pace_rank_ewma,
                    "regularity_rank_ewma": p.regularity_rank_ewma,
                    "combined_rank_ewma": p.combined_rank_ewma,
                    "events_count": p.events_count,
                    "is_stale": p.is_stale,
                    "trend": p.trend,
                }
            for p in db.query(TeamProfile).all():
                self._db_team_profiles[p.team_key] = {
                    "pace_rank_ewma": p.pace_rank_ewma,
                    "regularity_rank_ewma": p.regularity_rank_ewma,
                    "combined_rank_ewma": p.combined_rank_ewma,
                    "events_count": p.events_count,
                    "is_stale": p.is_stale,
                    "trend": p.trend,
                }
            logger.info("Loaded %d driver profiles, %d team profiles from DB",
                        len(self._db_driver_profiles), len(self._db_team_profiles))
        except Exception as exc:
            logger.warning("Could not load DB profiles: %s", exc)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _is_outlier(self, stint: StintRecord, lap_val: float) -> bool:
        """True if lap_val is more than OUTLIER_PCT above current stint median.
        Only applied once ≥ 3 filtered laps to avoid bootstrapping bias."""
        if len(stint.filtered_laps) < 3:
            return False
        median_current = statistics.median(stint.filtered_laps)
        return lap_val > median_current * (1.0 + OUTLIER_PCT)

    def _field_avg(self) -> Optional[float]:
        """ref_piste_T — median of field laps within the time window."""
        laps = self._windowed_field_laps()
        if len(laps) < MIN_FIELD_LAPS:
            return None
        return statistics.median(laps)

    def _windowed_field_laps(self) -> list[float]:
        if not self._field_laps:
            return []
        # If we have race time info, apply time window
        if self._current_t > 0:
            cutoff = self._current_t - FIELD_WINDOW_S
            laps = [fl.val for fl in self._field_laps if fl.t >= cutoff or fl.t == 0.0]
        else:
            # No race time — use last FIELD_WINDOW_LAPS entries
            laps = [fl.val for fl in self._field_laps[-FIELD_WINDOW_LAPS:]]
        return laps

    def _field_outlap_avg(self) -> Optional[float]:
        laps = list(self._field_outlaps)
        if len(laps) < OUTLAP_FIELD_MIN:
            return None
        return statistics.median(laps)

    def _collect_field_scores(self) -> tuple[list[float], list[float]]:
        """Collect (pace_delta, reg_score) for all active teams with enough laps."""
        field_avg = self._field_avg()
        pace_scores: list[float] = []
        reg_scores: list[float] = []
        for team in self._teams.values():
            if team.current_stint.count < MIN_STINT_LAPS:
                continue
            if field_avg:
                d = team.current_delta(field_avg)
                if d is not None:
                    pace_scores.append(d)
            rs = self._compute_reg_score(team)
            if rs is not None:
                reg_scores.append(rs)
        return pace_scores, reg_scores

    @staticmethod
    def _percentile_rank_asc(value: float, sorted_values: list[float]) -> float:
        """Fraction of values strictly less than `value`, as a percentage (0→100)."""
        if not sorted_values:
            return 50.0
        count_below = sum(1 for v in sorted_values if v < value)
        return count_below / len(sorted_values) * 100.0

    def _compute_pace_rank(self, pace_delta: float, all_pace_deltas: list[float]) -> Optional[float]:
        """pace_rank: 100 = fastest, 0 = slowest (lower delta = faster → invert percentile)."""
        if len(all_pace_deltas) < MIN_FIELD_TEAMS:
            return None
        # lower delta = faster → rank 100 means lowest in the distribution
        return 100.0 - self._percentile_rank_asc(pace_delta, sorted(all_pace_deltas))

    def _compute_reg_score(self, team: TeamRecord) -> Optional[float]:
        """IQR/median on filtered laps of current stint."""
        laps = list(team.current_stint.filtered_laps)
        if len(laps) < 4:
            return None
        try:
            q75 = statistics.quantiles(laps, n=4)[2]  # upper quartile
            q25 = statistics.quantiles(laps, n=4)[0]  # lower quartile
            med = statistics.median(laps)
            if med <= 0:
                return None
            return (q75 - q25) / med
        except statistics.StatisticsError:
            return None

    def _compute_reg_rank(self, reg_score: float, all_reg_scores: list[float]) -> Optional[float]:
        """regularity_rank: 100 = most regular, 0 = most irregular (lower IQR → invert)."""
        if len(all_reg_scores) < MIN_FIELD_TEAMS:
            return None
        return 100.0 - self._percentile_rank_asc(reg_score, sorted(all_reg_scores))

    def _compute_combined_rank(self, pace_rank: Optional[float],
                               reg_rank: Optional[float]) -> Optional[float]:
        if pace_rank is None or reg_rank is None:
            return None
        combined = self.weight_pace * pace_rank + self.weight_reg * reg_rank
        # Floor: if pace too low, cap combined
        if pace_rank < PACE_FLOOR_RANK:
            combined = min(combined, pace_rank * 1.5)
        return round(combined, 1)

    def _driver_profile_label(self, pace_rank: Optional[float],
                              reg_rank: Optional[float]) -> str:
        if pace_rank is None or reg_rank is None:
            return ""
        fast = pace_rank >= 50
        regular = reg_rank >= 50
        if fast and regular:
            return "COMPLET"
        if fast:
            return "NERVEUX"
        if regular:
            return "SAFE FINISHER"
        return "IMPRÉVISIBLE"

    def _stint_trend(self, team: TeamRecord) -> str:
        """Linear regression slope on filtered_laps_ms."""
        ms_laps = team.current_stint.filtered_laps_ms
        if len(ms_laps) < 5:
            return ""
        try:
            n = len(ms_laps)
            x = list(range(n))
            x_mean = sum(x) / n
            y_mean = sum(ms_laps) / n
            num = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(x, ms_laps))
            den = sum((xi - x_mean) ** 2 for xi in x)
            if den == 0:
                return "STABLE"
            slope = num / den
            if slope < SLOPE_IMPROVING:
                return "IMPROVING"
            if slope > SLOPE_DEGRADING:
                return "DEGRADING"
            return "STABLE"
        except Exception:
            return ""

    def _team_level_v2(self, pace_rank: Optional[float], reg_rank: Optional[float],
                       combined_rank: Optional[float]) -> str:
        if combined_rank is None:
            return "UNKNOWN"
        if combined_rank >= 75:
            return "ELITE"
        if combined_rank >= 50:
            return "FAST"
        if combined_rank >= 25:
            return "MEDIUM"
        return "SLOW"

    def _driver_level_label(self, drv: DriverAggregate) -> str:
        if not drv.pace_ranks or not drv.reg_ranks:
            if drv.deltas and drv.total_laps >= 5:
                avg = statistics.median(drv.deltas)
                if avg <= -0.01:
                    return "ELITE"
                if avg <= 0:
                    return "FAST"
                if avg <= 0.01:
                    return "MEDIUM"
                return "SLOW"
            return "UNKNOWN"
        pr = statistics.mean(drv.pace_ranks)
        rr = statistics.mean(drv.reg_ranks)
        combined = self.weight_pace * pr + self.weight_reg * rr
        if combined >= 75:
            return "ELITE"
        if combined >= 50:
            return "FAST"
        if combined >= 25:
            return "MEDIUM"
        return "SLOW"

    def _kart_score_raw(self, team: TeamRecord, field_avg: Optional[float]) -> Optional[float]:
        if field_avg is None:
            return None
        raw = team.current_delta(field_avg)
        if raw is None:
            return None
        skill = self._skill_expected_delta(team, team.current_stint.driver_key)
        return raw - skill

    def _kart_quality_label(self, team: TeamRecord, field_avg: Optional[float],
                             all_pace_deltas: list[float]) -> str:
        """Quartile-based kart quality across active field — no fixed thresholds."""
        kart_score = self._kart_score_raw(team, field_avg)
        if kart_score is None:
            return self._kart_early_mode(team, field_avg)

        # Collect kart_scores for all teams with enough laps
        all_kart_scores = self._all_kart_scores(field_avg)
        if len(all_kart_scores) < 4:
            # Too few teams — fall back to absolute thresholds
            if kart_score < -0.015:
                return "ROCKET"
            if kart_score < -0.007:
                return "FAST"
            if kart_score > 0.015:
                return "BAD"
            return "MEDIUM"

        all_sorted = sorted(all_kart_scores)
        n = len(all_sorted)
        q25 = all_sorted[max(0, int(n * 0.25) - 1)]
        q75 = all_sorted[max(0, int(n * 0.75) - 1)]

        if kart_score <= q25:
            new_label = "ROCKET"
        elif kart_score <= statistics.median(all_sorted):
            new_label = "FAST"
        elif kart_score <= q75:
            new_label = "MEDIUM"
        else:
            new_label = "BAD"

        return team.current_stint.update_kart_label(new_label)

    def _kart_early_mode(self, team: TeamRecord, field_avg: Optional[float]) -> str:
        out = team.current_stint.out_lap
        outlap_field = self._field_outlap_avg()
        if out is None or outlap_field is None:
            return "UNKNOWN"
        score = (out - outlap_field) / outlap_field
        score -= self._skill_expected_delta(team, team.current_stint.driver_key)
        if score < -0.007:
            return "FAST"
        return "MEDIUM"

    def _all_kart_scores(self, field_avg: Optional[float]) -> list[float]:
        if field_avg is None:
            return []
        scores = []
        for team in self._teams.values():
            ks = self._kart_score_raw(team, field_avg)
            if ks is not None:
                scores.append(ks)
        return scores

    def _skill_expected_delta(self, team: TeamRecord, driver_key: str) -> float:
        """Expected performance delta for this driver/team — kart isolation."""
        # Level B: same driver, multiple stints this event
        if driver_key and not driver_key.startswith("relay_"):
            drv = team.drivers.get(driver_key)
            if (drv and drv.total_laps >= MIN_DRIVER_LAPS
                    and len(drv.deltas) >= MIN_DRIVER_STINTS):
                return statistics.median(drv.deltas)

            # Level C: driver DB profile
            drv_key_norm = _normalize_name(driver_key)
            db_drv = self._db_driver_profiles.get(drv_key_norm)
            if db_drv and not db_drv.get("is_stale") and db_drv.get("pace_rank_ewma") is not None:
                # Convert EWMA pace_rank back to approx delta — use team hist as reference scale
                hist = team.weighted_historical_delta()
                if hist is not None:
                    db_pr = db_drv["pace_rank_ewma"]
                    # Rough mapping: pace_rank=50 ≈ field median → delta=0
                    # This is approximate; the key signal is whether driver is above/below median
                    return hist + (50 - db_pr) * 0.0002  # ~0.02% per percentile point

        # Level C2: team DB profile
        team_key = canonical_team_name(team.team_name)
        db_team = self._db_team_profiles.get(team_key)
        if db_team and not db_team.get("is_stale") and db_team.get("pace_rank_ewma") is not None:
            hist = team.weighted_historical_delta()
            if hist is not None:
                return hist

        # Level D: team historical this event
        hist = team.weighted_historical_delta()
        if hist is not None and len(team.stint_deltas) >= 2:
            return hist

        return 0.0

    def _kart_confidence_level(self, team: TeamRecord) -> str:
        driver_key = team.current_stint.driver_key
        if driver_key and not driver_key.startswith("relay_"):
            drv = team.drivers.get(driver_key)
            if drv and drv.total_laps >= MIN_DRIVER_LAPS and len(drv.deltas) >= MIN_DRIVER_STINTS:
                return "B"
            drv_key_norm = _normalize_name(driver_key)
            if self._db_driver_profiles.get(drv_key_norm):
                return "C"
        team_key = canonical_team_name(team.team_name)
        if self._db_team_profiles.get(team_key):
            return "C2"
        if len(team.stint_deltas) >= 2:
            return "D"
        return "E"

    def _close_stint(self, team: TeamRecord) -> None:
        if team.current_stint.closed:
            return
        team.current_stint.closed = True

        laps_ms = team.current_stint.laps_ms
        if not laps_ms:
            return

        avg_ms = int(statistics.median(laps_ms))
        best_ms = int(min(laps_ms))
        std_ms = round(statistics.stdev(laps_ms), 1) if len(laps_ms) >= 2 else 0.0
        delta_pct = None
        pace_rank = reg_rank = combined_rank = None
        driver_profile = stint_trend = ""

        if team.current_stint.count >= MIN_STINT_LAPS:
            field_avg = self._field_avg()
            if field_avg:
                raw = team.current_delta(field_avg)
                if raw is not None:
                    delta_pct = round(raw * 100, 2)
                    team.stint_deltas.append((raw, team.current_stint.count))
                    drv_key = team.current_stint.driver_key
                    if drv_key and not drv_key.startswith("relay_"):
                        drv = team.get_driver(drv_key)
                        drv.deltas.append(raw)

                    all_pace, all_reg = self._collect_field_scores()
                    pace_rank = self._compute_pace_rank(raw, all_pace)
                    rs = self._compute_reg_score(team)
                    reg_rank = self._compute_reg_rank(rs, all_reg)
                    combined_rank = self._compute_combined_rank(pace_rank, reg_rank)
                    driver_profile = self._driver_profile_label(pace_rank, reg_rank)
                    stint_trend = self._stint_trend(team)

                    drv_key = team.current_stint.driver_key
                    if drv_key and not drv_key.startswith("relay_"):
                        drv = team.get_driver(drv_key)
                        if pace_rank is not None:
                            drv.pace_ranks.append(pace_rank)
                        if reg_rank is not None:
                            drv.reg_ranks.append(reg_rank)

        team.closed_stints.append(StintSummary(
            driver=team.current_stint.driver_key,
            lap_count=team.current_stint.count,
            total_laps_ms=len(laps_ms),
            avg_ms=avg_ms,
            best_ms=best_ms,
            std_ms=std_ms,
            delta_pct=delta_pct,
            pace_rank=round(pace_rank, 1) if pace_rank is not None else None,
            regularity_rank=round(reg_rank, 1) if reg_rank is not None else None,
            combined_rank=round(combined_rank, 1) if combined_rank is not None else None,
            driver_profile=driver_profile,
            stint_trend=stint_trend,
        ))

    @staticmethod
    def _unknown_team(team_id: str) -> dict:
        return {
            "team_id": team_id, "team_name": "", "team_level": "UNKNOWN",
            "kart_quality": "UNKNOWN", "kart_score_pct": None,
            "kart_confidence": "E",
            "current_delta_pct": None, "pace_rank": None, "regularity_rank": None,
            "combined_rank": None, "driver_profile": "", "stint_trend": "",
            "outlier_laps": 0, "current_stint_laps": 0,
            "completed_stints": 0, "drivers": [],
        }


def _normalize_name(name: str) -> str:
    """Normalize a pilot name for DB key lookup."""
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", name or "")
    ascii_str = nfkd.encode("ascii", "ignore").decode("ascii")
    return ascii_str.upper().strip()
