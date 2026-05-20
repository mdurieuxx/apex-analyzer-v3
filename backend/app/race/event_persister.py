"""Persists live timing data (laps, pit stops) to the DB during a race event.

Deduplication: on proxy replay after a crash, the same laps/pit stops are re-sent.
Before inserting, we check whether the row already exists and skip it. This makes
replays idempotent — only data recorded after the crash is added.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, Callable

from models import EventEntry, EntryLap, EventPitStop, EventStint, EventStintLap

logger = logging.getLogger(__name__)


class EventPersister:
    def __init__(self, event_id: int, session_factory: Callable):
        self._event_id = event_id
        self._make_session = session_factory
        # apex_driver_id → DB entry_id (cleared on proxy reset so stale IDs are re-fetched)
        self._entry_cache: dict[str, int] = {}
        self._open_stint_ids: dict[str, int] = {}  # driver_id → EventStint.id

    def clear_cache(self):
        self._entry_cache.clear()
        self._open_stint_ids.clear()

    def _get_or_create_entry(self, db, driver_id: str, bib: str, team_name: str) -> int:
        if driver_id in self._entry_cache:
            return self._entry_cache[driver_id]
        entry = db.query(EventEntry).filter_by(event_id=self._event_id, apex_driver_id=driver_id).first()
        if not entry:
            entry = EventEntry(
                event_id=self._event_id,
                bib=bib,
                team_name=team_name,
                apex_driver_id=driver_id,
                created_at=datetime.utcnow(),
            )
            db.add(entry)
            db.flush()
        self._entry_cache[driver_id] = entry.id
        return entry.id

    def record_lap(self, driver_id: str, bib: str, team_name: str,
                   lap_number: int, lap_ms: int, is_pit_lap: bool):
        try:
            with self._make_session() as db:
                entry_id = self._get_or_create_entry(db, driver_id, bib, team_name)
                # Dedup: skip if this lap was already recorded (e.g. proxy replay)
                if lap_number > 0:
                    existing = db.query(EntryLap).filter_by(
                        event_id=self._event_id, entry_id=entry_id, lap_number=lap_number
                    ).first()
                    if existing:
                        return
                lap = EntryLap(
                    event_id=self._event_id,
                    entry_id=entry_id,
                    lap_number=lap_number,
                    total_ms=lap_ms,
                    is_pit_lap=is_pit_lap,
                    recorded_at=datetime.utcnow(),
                )
                db.add(lap)
                entry = db.get(EventEntry, entry_id)
                if entry:
                    entry.total_laps = (entry.total_laps or 0) + 1
                    if not entry.best_lap_ms or (not is_pit_lap and lap_ms < entry.best_lap_ms):
                        entry.best_lap_ms = lap_ms
                db.commit()
        except Exception:
            logger.exception("Failed to record lap: driver=%s lap=%d", driver_id, lap_number)

    def record_pit_stop(self, driver_id: str, bib: str, team_name: str,
                        pit_number: int, lap_number_in: int,
                        kart_in_label: str, entered_at: datetime):
        try:
            with self._make_session() as db:
                entry_id = self._get_or_create_entry(db, driver_id, bib, team_name)
                # Dedup: skip if pit stop with same pit_number already exists for this entry
                existing = db.query(EventPitStop).filter_by(
                    entry_id=entry_id, pit_number=pit_number
                ).first()
                if existing:
                    return
                ps = EventPitStop(
                    event_id=self._event_id,
                    entry_id=entry_id,
                    pit_number=pit_number,
                    lap_number_in=lap_number_in,
                    kart_in_label=kart_in_label,
                    entered_at=entered_at.replace(tzinfo=None) if entered_at.tzinfo else entered_at,
                )
                db.add(ps)
                db.commit()
        except Exception:
            logger.exception("Failed to record pit stop: driver=%s pit#=%d", driver_id, pit_number)

    def complete_pit_stop(self, driver_id: str, pit_number: int,
                          kart_out_label: Optional[str], exited_at: datetime,
                          stop_duration_ms: Optional[int], pit_lap_ms: Optional[int]):
        try:
            with self._make_session() as db:
                entry = db.query(EventEntry).filter_by(
                    event_id=self._event_id, apex_driver_id=driver_id
                ).first()
                if not entry:
                    return
                ps = (db.query(EventPitStop)
                        .filter_by(entry_id=entry.id, pit_number=pit_number)
                        .filter(EventPitStop.exited_at == None)  # noqa: E711
                        .order_by(EventPitStop.entered_at.desc())
                        .first())
                if ps:
                    ps.kart_out_label = kart_out_label
                    ps.exited_at = exited_at.replace(tzinfo=None) if exited_at.tzinfo else exited_at
                    ps.stop_duration_ms = stop_duration_ms
                    if pit_lap_ms:
                        ps.pit_lap_ms = pit_lap_ms
                    db.commit()
        except Exception:
            logger.exception("Failed to complete pit stop: driver=%s pit#=%d", driver_id, pit_number)

    def update_pit_lap(self, driver_id: str, pit_number: int, pit_lap_ms: int):
        try:
            with self._make_session() as db:
                entry = db.query(EventEntry).filter_by(
                    event_id=self._event_id, apex_driver_id=driver_id
                ).first()
                if not entry:
                    return
                ps = (db.query(EventPitStop)
                        .filter_by(entry_id=entry.id, pit_number=pit_number)
                        .order_by(EventPitStop.entered_at.desc())
                        .first())
                if ps:
                    ps.pit_lap_ms = pit_lap_ms
                    db.commit()
        except Exception:
            logger.exception("Failed to update pit lap: driver=%s pit#=%d", driver_id, pit_number)

    def open_stint(self, driver_id: str, bib: str, team_name: str,
                   stint_number: int, kart_label: str, started_at: datetime,
                   driver_name: str = "", pit_duration_ms: Optional[int] = None):
        try:
            with self._make_session() as db:
                entry_id = self._get_or_create_entry(db, driver_id, bib, team_name)
                # Dedup: skip if stint already exists for this entry + stint_number
                existing = db.query(EventStint).filter_by(
                    event_id=self._event_id, entry_id=entry_id, stint_number=stint_number
                ).first()
                if existing:
                    self._open_stint_ids[driver_id] = existing.id
                    return
                stint = EventStint(
                    event_id=self._event_id,
                    entry_id=entry_id,
                    stint_number=stint_number,
                    driver_name=driver_name,
                    kart_label=kart_label,
                    started_at=started_at.replace(tzinfo=None) if started_at.tzinfo else started_at,
                    pit_duration_ms=pit_duration_ms,
                )
                db.add(stint)
                db.commit()
                db.refresh(stint)
                self._open_stint_ids[driver_id] = stint.id
        except Exception:
            logger.exception("Failed to open stint: driver=%s stint#=%d", driver_id, stint_number)

    def record_stint_lap(self, driver_id: str, lap_number: int, lap_ms: int):
        stint_id = self._open_stint_ids.get(driver_id)
        if not stint_id:
            return
        try:
            with self._make_session() as db:
                # Dedup
                existing = db.query(EventStintLap).filter_by(
                    stint_id=stint_id, lap_number=lap_number
                ).first()
                if existing:
                    return
                db.add(EventStintLap(
                    stint_id=stint_id,
                    lap_number=lap_number,
                    lap_ms=lap_ms,
                    recorded_at=datetime.utcnow(),
                ))
                db.commit()
        except Exception:
            logger.exception("Failed to record stint lap: driver=%s lap=%d", driver_id, lap_number)

    def close_stint(self, driver_id: str, ended_at: datetime, driver_out: str = "",
                    kart_quality: str = "UNKNOWN", best_lap_ms: Optional[int] = None,
                    avg_lap_ms: Optional[float] = None, std_dev_ms: Optional[float] = None,
                    lap_count: int = 0):
        stint_id = self._open_stint_ids.pop(driver_id, None)
        if not stint_id:
            return
        try:
            with self._make_session() as db:
                stint = db.get(EventStint, stint_id)
                if stint:
                    stint.ended_at = ended_at.replace(tzinfo=None) if ended_at.tzinfo else ended_at
                    stint.driver_out = driver_out
                    stint.kart_quality = kart_quality
                    stint.best_lap_ms = best_lap_ms
                    stint.avg_lap_ms = avg_lap_ms
                    stint.std_dev_ms = std_dev_ms
                    stint.lap_count = lap_count
                    db.commit()
        except Exception:
            logger.exception("Failed to close stint: driver=%s", driver_id)

    def update_stint_driver_in(self, driver_id: str, driver_in: str):
        """Set driver_in on the most recently closed stint for this driver."""
        try:
            with self._make_session() as db:
                entry = db.query(EventEntry).filter_by(
                    event_id=self._event_id, apex_driver_id=driver_id
                ).first()
                if not entry:
                    return
                stint = (db.query(EventStint)
                         .filter_by(event_id=self._event_id, entry_id=entry.id)
                         .filter(EventStint.ended_at != None)  # noqa: E711
                         .order_by(EventStint.ended_at.desc())
                         .first())
                if stint and driver_in:
                    stint.driver_in = driver_in
                    db.commit()
        except Exception:
            logger.exception("Failed to update stint driver_in: driver=%s", driver_id)

    def update_stint_out_lap(self, driver_id: str, out_lap_ms: int):
        stint_id = self._open_stint_ids.get(driver_id)
        if not stint_id:
            return
        try:
            with self._make_session() as db:
                stint = db.get(EventStint, stint_id)
                if stint and not stint.out_lap_ms:
                    stint.out_lap_ms = out_lap_ms
                    db.commit()
        except Exception:
            logger.exception("Failed to update stint out_lap: driver=%s", driver_id)

    def update_stint_pit_duration(self, driver_id: str, pit_duration_ms: int):
        stint_id = self._open_stint_ids.get(driver_id)
        if not stint_id:
            return
        try:
            with self._make_session() as db:
                stint = db.get(EventStint, stint_id)
                if stint and not stint.pit_duration_ms:
                    stint.pit_duration_ms = pit_duration_ms
                    db.commit()
        except Exception:
            logger.exception("Failed to update stint pit_duration: driver=%s", driver_id)
