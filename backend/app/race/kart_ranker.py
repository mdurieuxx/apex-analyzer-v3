"""
Performance model based on stints — no physical kart identity needed.

Team level (ELITE/FAST/MEDIUM/SLOW): quartile of team's weighted avg delta vs field.
Kart quality (ROCKET/FAST/MEDIUM/BAD): current stint avg vs field avg, corrected for skill.
Driver level: same logic aggregated across driver's named stints.

Lap classification after a pit stop (by passage number on timing line):
  n=1  partial lap (pit exit → finish line): ignored
  n=2  out-lap: stored separately, compared only to other out-laps
  n=3-4 warm-up: excluded from all scoring
  n≥5  normal laps: contribute to stint avg and field rolling average

Kart quality score (normal mode, n_normal ≥ MIN_STINT_LAPS):
  raw   = (median(recent_laps) - field_avg) / field_avg  # = current_delta
  score = raw - skill_expected_delta(driver > team history > category level > 0)

  skill_expected_delta is derived from the team's historical avg-lap performance,
  so both sides of the equation are on the same scale (avg vs field avg).

  score < ROCKET_THRESHOLD → ROCKET (kart much better than expected for skill level)
  score < FAST_THRESHOLD   → FAST
  score > BAD_THRESHOLD    → BAD
  otherwise                → MEDIUM

Early mode (< MIN_STINT_LAPS normal laps): out-lap vs field out-lap median.
  Never classifies BAD in early mode — a single out-lap is too noisy.
"""
import statistics
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from apex.grid_parser import canonical_team_name

logger = logging.getLogger(__name__)

# ── Tuning constants ──────────────────────────────────────────────────────────
ROCKET_THRESHOLD  = -0.015  # 1.5% better than expected → ROCKET
FAST_THRESHOLD    = -0.007  # 0.7% better → FAST
BAD_THRESHOLD     =  0.015  # 1.5% slower → BAD
MIN_STINT_LAPS    =  4      # normal laps (passage 5+) before switching from out-lap to avg scoring
RECENT_WINDOW     =  8      # rolling window for team current-stint avg (used in current_delta)
FIELD_WINDOW      = 200     # global rolling window for field normal-lap average
MIN_FIELD_LAPS    = 10      # min field laps before any level/quality is computed
OUTLAP_FIELD_MIN  =  4      # min out-laps in field before out-lap comparison is used
MIN_DRIVER_LAPS   = 15      # min total laps before driver skill is considered reliable
MIN_DRIVER_STINTS =  2      # min completed stints for driver delta to be used
CAT_MIN_TEAMS     =  3      # min teams in category before category-aware comparison is used


# ── Stint summary (immutable snapshot of a closed stint) ─────────────────────

@dataclass
class StintSummary:
    driver: str
    lap_count: int          # good (normal) laps used for delta
    total_laps_ms: int      # all non-partial laps recorded (incl. out-lap / warm-up)
    avg_ms: int             # median of all non-partial laps
    best_ms: int
    std_ms: float
    delta_pct: Optional[float]  # None when too few laps for reliable delta
    is_current: bool = False


# ── Stint record ──────────────────────────────────────────────────────────────

@dataclass
class StintRecord:
    driver_key: str
    laps: list = field(default_factory=list)
    laps_ms: list = field(default_factory=list)
    out_lap: Optional[float] = None   # normalized first lap post-pit (excluded from averages)
    closed: bool = False              # set after _close_stint to prevent double-counting

    @property
    def avg(self) -> Optional[float]:
        return statistics.median(self.laps) if self.laps else None

    @property
    def count(self) -> int:
        return len(self.laps)

    @property
    def best_lap(self) -> Optional[float]:
        return min(self.laps) if self.laps else None


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
    category: str = ""
    current_stint: StintRecord = field(default_factory=lambda: StintRecord(driver_key=""))
    current_laps: deque = field(default_factory=lambda: deque(maxlen=RECENT_WINDOW))
    last_pit_number: int = 0
    laps_since_relay: int = 0
    stint_deltas: list = field(default_factory=list)  # list of (delta, lap_count)
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


# ── Main ranker ───────────────────────────────────────────────────────────────

HISTORICAL_LAPS_CAP = 15  # max lap-weight per historical stint (soft prior)


class KartRanker:
    """Real-time performance ranker using stint-based relative model."""

    def __init__(self, track_monitor=None):
        self._track = track_monitor
        self._teams: dict[str, TeamRecord] = {}
        self._field_laps: deque = deque(maxlen=FIELD_WINDOW)
        self._field_outlaps: deque = deque(maxlen=100)  # out-lap reference (passage 2 post-pit)
        self._kart_to_team: dict[str, str] = {}
        # Historical priors from previous event — keyed by team_name
        self._hist_stints: dict[str, list[tuple[float, int]]] = {}   # team_name -> [(delta, laps)]
        self._hist_drivers: dict[str, dict[str, list[float]]] = {}   # team_name -> driver -> [delta]

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
    ) -> None:
        if is_pit or lap_ms <= 0:
            return

        if kart_label and kart_label not in ("?", ""):
            self._kart_to_team[kart_label] = team_id

        if team_id not in self._teams:
            self._teams[team_id] = TeamRecord(team_id=team_id)
            # Inject historical priors if available for this team
            if team_name and team_name in self._hist_stints:
                self._teams[team_id].stint_deltas = list(self._hist_stints[team_name])
                for drv_name, deltas in self._hist_drivers.get(team_name, {}).items():
                    drv = self._teams[team_id].get_driver(drv_name)
                    drv.deltas = list(deltas)
                logger.info("Seeded historical data for team=%s (%d stints)", team_name, len(self._hist_stints[team_name]))
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
            # Partial lap (pit exit → finish line, or rolling start segment): always ignore
            return

        # Only non-partial laps go into laps_ms (used for DB stats: avg/best/std)
        team.current_stint.laps_ms.append(lap_ms)

        if self._track:
            self._track.update_team_best(team_id, min(team.current_stint.laps_ms))
            norm = self._track.normalize(lap_ms)
            if norm is None:
                return  # Bootstrap phase
            lap_val = norm
        else:
            lap_val = lap_ms / 1000.0

        if pit_number > 0:
            # Post-pit stints: out-lap and warm-up exclusion applies
            if n == 2:
                # Out-lap: first full lap post-pit — slower by nature, compare to other out-laps only
                team.current_stint.out_lap = lap_val
                self._field_outlaps.append(lap_val)
                return
            if n <= 4:
                # Warm-up laps (passages 3-4): excluded from all averages
                return

        # Normal laps: first stint (pit_number=0) counts all laps n>=2 as normal;
        # subsequent stints count n>=5 as normal.
        self._field_laps.append(lap_val)
        team.current_laps.append(lap_val)
        team.current_stint.laps.append(lap_val)

        if driver_name:
            drv = team.get_driver(driver_name)
            drv.total_laps += 1

    def reset_live_data(self) -> None:
        """Clear live race data while preserving historical priors from previous events."""
        self._teams.clear()
        self._field_laps.clear()
        self._field_outlaps.clear()
        self._kart_to_team.clear()
        if self._track:
            self._track._team_bests.clear()
        # _hist_stints and _hist_drivers are preserved

    def on_pit_stop(self, team_id: str) -> None:
        team = self._teams.get(team_id)
        if team:
            self._close_stint(team)

    def on_pit_out(self, team_id: str, driver_name: str = "") -> None:
        """Reset current stint and track reference at pit exit."""
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
        thresholds = self._quartile_thresholds(team.category)

        team_level = self._team_level(team, thresholds)
        kart_quality, kart_score = self._kart_quality(team, field_avg, thresholds)
        current_delta = team.current_delta(field_avg) if field_avg else None

        drivers_out = [
            {
                "name": drv.name,
                "level": drv.level(thresholds),
                "total_laps": drv.total_laps,
                "avg_delta_pct": round(statistics.median(drv.deltas) * 100, 2) if drv.deltas else None,
                "stint_count": len(drv.deltas),
            }
            for drv in team.drivers.values()
        ]

        # Closed stints
        stints_out = [
            {
                "driver": s.driver,
                "lap_count": s.lap_count,
                "total_laps_ms": s.total_laps_ms,
                "avg_ms": s.avg_ms,
                "best_ms": s.best_ms,
                "std_ms": s.std_ms,
                "delta_pct": s.delta_pct,
                "is_current": False,
            }
            for s in team.closed_stints
        ]
        # Append live open stint if it has data
        if team.current_stint.laps_ms:
            lms = team.current_stint.laps_ms
            stints_out.append({
                "driver": team.current_stint.driver_key,
                "lap_count": team.current_stint.count,
                "total_laps_ms": len(lms),
                "avg_ms": int(statistics.median(lms)),
                "best_ms": int(min(lms)),
                "std_ms": round(statistics.stdev(lms), 1) if len(lms) >= 2 else 0.0,
                "delta_pct": None,
                "is_current": True,
            })

        return {
            "team_id": team_id,
            "team_name": team.team_name,
            "team_level": team_level,
            "kart_quality": kart_quality,
            "kart_score_pct": round(kart_score * 100, 2) if kart_score is not None else None,
            "current_delta_pct": round(current_delta * 100, 2) if current_delta is not None else None,
            "current_stint_laps": team.current_stint.count,
            "completed_stints": len(team.stint_deltas) + (1 if team.current_stint.laps_ms else 0),
            "drivers": drivers_out,
            "stints": stints_out,
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
        thresholds = self._quartile_thresholds(team.category)
        kart_quality, kart_score = self._kart_quality(team, field_avg, thresholds)
        team_level = self._team_level(team, thresholds)

        laps_in_stint = team.current_stint.count
        confidence = min(int(laps_in_stint / MIN_STINT_LAPS * 100), 100)

        return {
            "kart_label": "?",
            "rating": kart_quality,
            "confidence": confidence,
            "delta_pct": round(kart_score * 100, 2) if kart_score is not None else 0.0,
            "observations": laps_in_stint,
            "team_level": team_level,
            "kart_quality": kart_quality,
        }

    def rate_kart(self, kart_label: str) -> dict:
        """Quality of a kart based on the performance of the team that last used it."""
        team_id = self._kart_to_team.get(kart_label)
        if not team_id:
            return {"kart_label": kart_label, "rating": "UNKNOWN",
                    "confidence": 0, "delta_pct": 0.0, "observations": 0}
        q = self.kart_quality_for_team(team_id)
        q["kart_label"] = kart_label
        return q

    def field_ranking(self) -> list[dict]:
        return self.all_teams_summary()

    def reserve_summary(self, kart_labels: list[str]) -> dict:
        """% breakdown of ROCKET/FAST/MEDIUM/BAD/UNKNOWN for a list of kart labels."""
        counts: dict[str, int] = {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 0}
        for label in kart_labels:
            if not label or label == "?":
                counts["unknown"] += 1
                continue
            r = self.rate_kart(label).get("rating", "UNKNOWN").lower()
            if r in counts:
                counts[r] += 1
            else:
                counts["unknown"] += 1
        total = sum(counts.values())
        if not total:
            return {"rocket": 0, "fast": 0, "medium": 0, "bad": 0, "unknown": 100}
        return {k: round(v / total * 100) for k, v in counts.items()}

    # ── Internal helpers ──────────────────────────────────────────────────────

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

        if team.current_stint.count >= MIN_STINT_LAPS:
            field_avg = self._field_avg()
            if field_avg:
                avg = team.current_stint.avg
                if avg is not None:
                    delta = (avg - field_avg) / field_avg
                    delta_pct = round(delta * 100, 2)
                    team.stint_deltas.append((delta, team.current_stint.count))
                    drv_key = team.current_stint.driver_key
                    if drv_key and not drv_key.startswith("relay_"):
                        drv = team.get_driver(drv_key)
                        drv.deltas.append(delta)

        team.closed_stints.append(StintSummary(
            driver=team.current_stint.driver_key,
            lap_count=team.current_stint.count,
            total_laps_ms=len(laps_ms),
            avg_ms=avg_ms,
            best_ms=best_ms,
            std_ms=std_ms,
            delta_pct=delta_pct,
        ))

    def _field_avg(self) -> Optional[float]:
        laps = list(self._field_laps)
        if len(laps) < MIN_FIELD_LAPS:
            return None
        return statistics.median(laps)

    def _field_outlap_avg(self) -> Optional[float]:
        laps = list(self._field_outlaps)
        if len(laps) < OUTLAP_FIELD_MIN:
            return None
        return statistics.median(laps)

    def _field_best_avg(self) -> Optional[float]:
        """Median of all teams' current-stint best laps — fallback reference when no category match."""
        bests = [
            t.current_stint.best_lap
            for t in self._teams.values()
            if t.current_stint.best_lap is not None and t.current_stint.count >= MIN_STINT_LAPS
        ]
        return statistics.median(bests) if len(bests) >= CAT_MIN_TEAMS else None

    def _category_best_field(self, category: str, exclude_team_id: str) -> Optional[float]:
        """Median of current-stint best laps for teams in same category (fallback: full field)."""
        def best_laps_for(cat_filter):
            return [
                t.current_stint.best_lap
                for tid, t in self._teams.items()
                if tid != exclude_team_id
                and t.current_stint.best_lap is not None
                and t.current_stint.count >= MIN_STINT_LAPS
                and (not cat_filter or not t.category or t.category == cat_filter)
            ]
        same_cat = best_laps_for(category)
        laps = same_cat if len(same_cat) >= CAT_MIN_TEAMS else best_laps_for("")
        return statistics.median(laps) if len(laps) >= CAT_MIN_TEAMS else None

    def _skill_expected_delta(self, team: TeamRecord, driver_key: str,
                              thresholds: Optional[tuple]) -> float:
        """Expected performance delta for this team/driver — used to isolate kart contribution.

        Priority: reliable driver data → team historical → category level → 0.
        """
        if driver_key and not driver_key.startswith("relay_"):
            drv = team.drivers.get(driver_key)
            if (drv and drv.total_laps >= MIN_DRIVER_LAPS
                    and len(drv.deltas) >= MIN_DRIVER_STINTS):
                return statistics.median(drv.deltas)

        hist = team.weighted_historical_delta()
        if hist is not None and len(team.stint_deltas) >= 2:
            return hist

        if thresholds is not None:
            level = self._team_level(team, thresholds)
            if level != "UNKNOWN":
                return self._expected_delta_for_level(level, thresholds)

        return 0.0

    def _all_weighted_deltas(self, category: str = "") -> list:
        return [
            d for team in self._teams.values()
            if (not category or team.category == category)
            and (d := team.weighted_historical_delta()) is not None
        ]

    def _quartile_thresholds(self, category: str = "") -> Optional[tuple]:
        deltas = sorted(self._all_weighted_deltas(category))
        if len(deltas) < 4:
            # Category has too few teams — fall back to global quartiles
            if category:
                return self._quartile_thresholds()
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
        # Use the quartile boundary as the expected delta — no extrapolation beyond measured range.
        # An ELITE team at p25 should score MEDIUM (kart=0), not BAD.
        p25, p50, p75 = thresholds
        return {
            "ELITE":  p25,
            "FAST":   (p25 + p50) / 2,
            "MEDIUM": (p50 + p75) / 2,
            "SLOW":   p75,
        }.get(level, 0.0)

    def _kart_quality(
        self, team: TeamRecord, field_avg: Optional[float], thresholds: Optional[tuple]
    ) -> tuple:
        n_normal = team.current_stint.count
        driver_key = team.current_stint.driver_key

        if n_normal >= MIN_STINT_LAPS:
            # Normal mode: current avg vs field avg — consistent scale with skill correction
            if field_avg is None:
                return "UNKNOWN", None
            raw = team.current_delta(field_avg)
            if raw is None:
                return "UNKNOWN", None
            score = raw
        else:
            # Early mode (< MIN_STINT_LAPS normal laps): use out-lap as weak early signal.
            # Never classify BAD from a single out-lap — too noisy.
            out = team.current_stint.out_lap
            outlap_field = self._field_outlap_avg()
            if out is None or outlap_field is None:
                return "UNKNOWN", None
            score = (out - outlap_field) / outlap_field
            score -= self._skill_expected_delta(team, driver_key, thresholds)
            if score < FAST_THRESHOLD:
                return "FAST", score
            return "MEDIUM", score  # cap at MEDIUM in early mode

        score -= self._skill_expected_delta(team, driver_key, thresholds)

        if score < ROCKET_THRESHOLD:
            return "ROCKET", score
        if score < FAST_THRESHOLD:
            return "FAST", score
        if score > BAD_THRESHOLD:
            return "BAD", score
        return "MEDIUM", score

    def seed_from_previous_event(self, event_id: int, db) -> int:
        """
        Load completed stints from a previous event to bootstrap team/driver levels.
        Returns the number of teams seeded.
        Historical deltas are capped at HISTORICAL_LAPS_CAP per stint so new race
        data quickly takes precedence over the prior.
        """
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
                self._hist_drivers.setdefault(name, {}).setdefault(stint.driver_name, []).append(delta)

        logger.info("Seeded priors from event %d: %d teams", event_id, len(self._hist_stints))
        return len(self._hist_stints)

    def get_stint_stats(self, team_id: str) -> dict:
        """Raw ms stats for the current stint (for DB persistence)."""
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

    @staticmethod
    def _unknown_team(team_id: str) -> dict:
        return {
            "team_id": team_id, "team_name": "", "team_level": "UNKNOWN",
            "kart_quality": "UNKNOWN", "kart_score_pct": None,
            "current_delta_pct": None, "current_stint_laps": 0,
            "completed_stints": 0, "drivers": [],
        }
