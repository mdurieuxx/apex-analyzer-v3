"""
Compute per-physical-kart performance scores from lap history.

Score = avg(lap_ms) / session_best_lap_ms
  1.0 = as fast as the best lap in session (EXCELLENT)
  >1.05 = slightly slower (GOOD)
  >1.10 = noticeably slower (AVERAGE)
  >1.15 = significantly slower (POOR)

Laps < 60s or > 300s are filtered as outliers.
"""
import math
import logging
from collections import defaultdict
from sqlalchemy.orm import Session
from models import Lap, PhysicalKart, KartPerformanceSchema

logger = logging.getLogger(__name__)

_MIN_LAP_MS = 30_000
_MAX_LAP_MS = 300_000


def compute_performance(db: Session, session_id: int) -> list[KartPerformanceSchema]:
    laps = (
        db.query(Lap)
        .filter(Lap.session_id == session_id, Lap.is_pit == False, Lap.total_ms > 0)
        .all()
    )

    # Group valid laps by physical kart
    kart_laps: dict[int, list[int]] = defaultdict(list)
    kart_pit_laps: dict[int, int] = defaultdict(int)

    for lap in laps:
        if not lap.physical_kart_id:
            continue
        if _MIN_LAP_MS <= lap.total_ms <= _MAX_LAP_MS:
            kart_laps[lap.physical_kart_id].append(lap.total_ms)

    pit_laps = (
        db.query(Lap)
        .filter(Lap.session_id == session_id, Lap.is_pit == True)
        .all()
    )
    for lap in pit_laps:
        if lap.physical_kart_id:
            kart_pit_laps[lap.physical_kart_id] += 1

    if not kart_laps:
        return []

    session_best = min(min(v) for v in kart_laps.values())

    results = []
    for pk_id, times in kart_laps.items():
        kart = db.query(PhysicalKart).filter(PhysicalKart.id == pk_id).first()
        if not kart:
            continue

        avg = sum(times) / len(times)
        best = min(times)
        variance = sum((t - avg) ** 2 for t in times) / len(times)
        std_dev = math.sqrt(variance)
        relative = avg / session_best

        if relative <= 1.03:
            rating = "EXCELLENT"
        elif relative <= 1.07:
            rating = "GOOD"
        elif relative <= 1.12:
            rating = "AVERAGE"
        else:
            rating = "POOR"

        # Time in pit = number of pit lap records × avg lap time (rough estimate)
        pit_count = kart_pit_laps.get(pk_id, 0)

        results.append(KartPerformanceSchema(
            kart_label=kart.kart_label,
            physical_kart_id=pk_id,
            total_laps=len(times),
            avg_lap_ms=round(avg),
            best_lap_ms=best,
            std_dev_ms=round(std_dev),
            relative_score=round(relative, 4),
            rating=rating,
            laps_in_pit=pit_count,
            time_in_pit_s=0,  # enriched from pit_queue table by caller
        ))

    results.sort(key=lambda x: x.relative_score)
    return results
