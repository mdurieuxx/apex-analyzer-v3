"""
Kart performance ranking algorithm.

Goal: isolate kart quality from driver skill.

Key insight:
  lap_time_normalized = driver_skill + kart_quality + noise

We can't observe either separately, but we CAN compare the same driver
on different karts. By anchoring on a team's "baseline speed" (their
normalised lap times on their first kart, pre-first-pit), we measure:

  kart_delta = current_normalized_avg - team_baseline

  kart_delta < 0  → faster than driver's baseline → kart is good
  kart_delta > 0  → slower than driver's baseline → kart is bad

When multiple teams have driven the same physical kart, we aggregate
their deltas (weighted by number of observations) for higher confidence.

Cross-team fallback (before any team has enough baseline):
  We use the team's current rank vs field rank as a weak signal.
  This is less accurate and produces UNKNOWN until we have real data.

Rating thresholds (in normalized units, where 1.0 = reference pace):
  GOOD    : delta < -0.012  (>1.2% faster than baseline)
  MEDIUM  : -0.012 ≤ delta ≤ +0.015
  BAD     : delta > +0.015  (>1.5% slower than baseline)
  UNKNOWN : insufficient data
"""
import statistics
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

GOOD_THRESHOLD   = -0.012   # 1.2 % faster than baseline
BAD_THRESHOLD    =  0.015   # 1.5 % slower than baseline
MIN_BASELINE_LAPS = 5       # laps needed to establish team baseline
MIN_KART_LAPS     = 3       # laps on current kart before rating it
RECENT_WINDOW     = 7       # laps used for current-kart average
MAX_DELTA_OBS     = 20      # max delta observations kept per kart


class KartRating(str, Enum):
    GOOD    = "GOOD"
    MEDIUM  = "MEDIUM"
    BAD     = "BAD"
    UNKNOWN = "UNKNOWN"


@dataclass
class TeamRecord:
    team_id: str
    # chronological list of (normalized_lap, kart_label)
    laps: list[tuple[float, str]] = field(default_factory=list)
    first_pit_index: int | None = None   # index in laps[] where first pit happened

    def add_lap(self, norm: float, kart_label: str, is_first_kart: bool) -> None:
        self.laps.append((norm, kart_label))

    def baseline_speed(self) -> float | None:
        """
        Team's intrinsic speed estimate = median of normalized laps
        on their INITIAL kart (before first pit stop).
        Requires at least MIN_BASELINE_LAPS.
        """
        if self.first_pit_index is None:
            # No pit yet — use all laps as baseline
            pre_pit = self.laps
        else:
            pre_pit = self.laps[:self.first_pit_index]

        valid = [norm for norm, _ in pre_pit]
        if len(valid) < MIN_BASELINE_LAPS:
            return None
        return statistics.median(valid)

    def current_kart_delta(self, kart_label: str) -> float | None:
        """
        How much faster/slower is the team on `kart_label` vs their baseline?
        Negative = faster (good kart). Positive = slower (bad kart).
        """
        baseline = self.baseline_speed()
        if baseline is None:
            return None

        # Recent laps on this specific kart
        kart_laps = [
            norm for norm, k in self.laps[-RECENT_WINDOW * 3:]
            if k == kart_label
        ][-RECENT_WINDOW:]

        if len(kart_laps) < MIN_KART_LAPS:
            return None

        current_avg = statistics.mean(kart_laps)
        return current_avg - baseline


@dataclass
class KartEvidence:
    """Aggregated delta observations for one physical kart."""
    deltas: deque[float] = field(default_factory=lambda: deque(maxlen=MAX_DELTA_OBS))

    def add(self, delta: float) -> None:
        self.deltas.append(delta)

    def rate(self) -> tuple[KartRating, float, float]:
        """
        Returns (rating, confidence 0–1, median_delta).
        confidence = how sure we are; < 0.4 → UNKNOWN regardless.
        """
        if not self.deltas:
            return KartRating.UNKNOWN, 0.0, 0.0

        n = len(self.deltas)
        confidence = min(n / 5.0, 1.0)   # 5 observations → 100 % confident
        median_delta = statistics.median(self.deltas)

        if confidence < 0.4:
            return KartRating.UNKNOWN, confidence, median_delta

        if median_delta < GOOD_THRESHOLD:
            return KartRating.GOOD, confidence, median_delta
        elif median_delta > BAD_THRESHOLD:
            return KartRating.BAD, confidence, median_delta
        else:
            return KartRating.MEDIUM, confidence, median_delta


class KartRanker:
    """Real-time kart performance ranker."""

    def __init__(self, track_monitor):
        self._track = track_monitor
        self._teams: dict[str, TeamRecord] = {}
        self._karts: dict[str, KartEvidence] = defaultdict(KartEvidence)

    # ── Public API ────────────────────────────────────────────────────────────

    def record_lap(
        self,
        team_id: str,
        kart_label: str,
        lap_ms: int,
        is_pit: bool = False,
        pit_number: int = 0,
    ) -> None:
        """
        Call this every time a lap is completed.
        `kart_label` is the PHYSICAL kart label (not the bib number).
        """
        if kart_label in ("?", "", None) or is_pit:
            return  # don't count pit laps or unknown karts

        norm = self._track.normalize(lap_ms)
        if norm is None:
            return

        self._track.add_lap(lap_ms)

        if team_id not in self._teams:
            self._teams[team_id] = TeamRecord(team_id=team_id)

        rec = self._teams[team_id]
        is_first_kart = (rec.first_pit_index is None)
        rec.add_lap(norm, kart_label, is_first_kart)

        # Try to compute delta and update kart evidence
        delta = rec.current_kart_delta(kart_label)
        if delta is not None:
            self._karts[kart_label].add(delta)
            logger.debug("kart=%s delta=%.4f (team=%s)", kart_label, delta, team_id)

    def on_pit_stop(self, team_id: str) -> None:
        """Call when a team enters the pits (pit count increases)."""
        rec = self._teams.get(team_id)
        if rec and rec.first_pit_index is None:
            rec.first_pit_index = len(rec.laps)
            logger.info("Team %s baseline locked at %d laps", team_id, rec.first_pit_index)

    def rate_kart(self, kart_label: str) -> dict:
        """
        Returns a dict with rating, confidence, delta_pct, observations.
        """
        evidence = self._karts.get(kart_label)
        if evidence is None:
            return self._unknown(kart_label)

        rating, conf, delta = evidence.rate()
        return {
            "kart_label": kart_label,
            "rating": rating.value,
            "confidence": round(conf * 100),        # 0–100 %
            "delta_pct": round(delta * 100, 2),     # e.g. -1.5 means 1.5% faster than baseline
            "observations": len(evidence.deltas),
        }

    def rate_all(self, kart_labels: list[str]) -> list[dict]:
        return [self.rate_kart(k) for k in kart_labels]

    def reserve_summary(self, kart_labels: list[str]) -> dict:
        """
        For a list of karts currently in the pit reserve, returns
        the % breakdown of GOOD / MEDIUM / BAD / UNKNOWN.
        """
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
        """
        Rank ALL karts currently tracked, from best to worst.
        Useful for a global overview.
        """
        all_karts = list(self._karts.keys())
        rated = [self.rate_kart(k) for k in all_karts]

        # Also include karts with no evidence at all (UNKNOWN)
        rated.sort(key=lambda r: (
            {"GOOD": 0, "MEDIUM": 1, "BAD": 2, "UNKNOWN": 3}[r["rating"]],
            r["delta_pct"],
        ))
        return rated

    # ── Internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _unknown(kart_label: str) -> dict:
        return {
            "kart_label": kart_label,
            "rating": KartRating.UNKNOWN.value,
            "confidence": 0,
            "delta_pct": 0.0,
            "observations": 0,
        }
