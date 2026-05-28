"""
Offline import: replay a proxy JSONL recording into the DB for a given event.

Runs in a background asyncio task; broadcasts import_progress/import_done/import_error
via the main WebSocket broadcast function.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Callable, Awaitable, Optional

import httpx

from apex.client import ApexClient
from apex.grid_parser import canonical_team_name
from models import Event, Circuit
from race.event_persister import EventPersister
from race.kart_ranker import KartRanker
from race.pit_manager import PitManager
from race.state import RaceState
from race.track_condition import TrackConditionMonitor

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, dict], Awaitable[None]]
BROADCAST_EVERY = 500


class ImportRunner:
    def __init__(self):
        self.status: str = "idle"   # idle | running | done | error
        self.processed: int = 0
        self.total: int = 0
        self.error: Optional[str] = None
        self.event_id: Optional[int] = None
        self.resumed_from_t: float = 0.0
        self.recording_max_t: float = 0.0
        self.recording_name: str = ""
        self._task: Optional[asyncio.Task] = None
        self._queue: list[str] = []
        self._queue_ctx: Optional[tuple] = None  # (proxy_http_url, session_factory, broadcast)

    def summary(self) -> dict:
        return {
            "status": self.status,
            "processed": self.processed,
            "total": self.total,
            "pct": round(self.processed / self.total * 100) if self.total else 0,
            "error": self.error,
            "event_id": self.event_id,
            "resumed_from_t": self.resumed_from_t,
            "recording_max_t": self.recording_max_t,
            "recording_name": self.recording_name,
            "queue_remaining": len(self._queue),
        }

    def start(self, recording_name: str, proxy_http_url: str,
              session_factory: Callable, broadcast: BroadcastFn,
              event_id: Optional[int] = None,
              queue: Optional[list[str]] = None) -> bool:
        if self.status == "running":
            return False
        self.status = "running"
        self.processed = 0
        self.total = 0
        self.error = None
        self.event_id = event_id
        self.resumed_from_t = 0.0
        self.recording_max_t = 0.0
        self.recording_name = recording_name
        self._queue = list(queue or [])
        self._queue_ctx = (proxy_http_url, session_factory, broadcast)
        self._task = asyncio.create_task(
            self._run(event_id, recording_name, proxy_http_url, session_factory, broadcast)
        )
        return True

    async def _run(self, event_id: Optional[int], recording_name: str, proxy_http_url: str,
                   session_factory: Callable, broadcast: BroadcastFn):
        t0 = time.monotonic()
        try:
            await self._do_import(event_id, recording_name, proxy_http_url, session_factory, broadcast)
            elapsed = round(time.monotonic() - t0, 1)
            logger.info("Import done: %d messages in %.1fs (queue=%d)", self.processed, elapsed, len(self._queue))
            if self._queue and self._queue_ctx:
                next_name = self._queue.pop(0)
                self.recording_name = next_name
                self.processed = 0
                self.total = 0
                ph_url, sf, bc = self._queue_ctx
                # Pass self.event_id so subsequent recordings go to the same event
                self._task = asyncio.create_task(
                    self._run(self.event_id, next_name, ph_url, sf, bc)
                )
            else:
                self.status = "done"
                await broadcast("import_done", {
                    "processed": self.processed,
                    "duration_s": elapsed,
                    "event_id": self.event_id,
                    "resumed_from_t": self.resumed_from_t,
                    "recording_max_t": self.recording_max_t,
                })
        except Exception as e:
            logger.exception("Import failed")
            self.error = str(e)
            self.status = "error"
            await broadcast("import_error", {"error": self.error})

    @staticmethod
    def _build_event_name(raw_name: str, circuit, duration_hours: float,
                          event_date: Optional[datetime]) -> str:
        MONTHS_FR = ["jan","fév","mar","avr","mai","jun","jul","aoû","sep","oct","nov","déc"]

        # 1. Circuit label — prefer content in parentheses if present, else strip prefix
        if circuit and circuit.name:
            m_paren = re.search(r'\(([^)]+)\)', circuit.name)
            if m_paren:
                circuit_label = m_paren.group(1).strip()
            else:
                circuit_label = re.sub(r'^karting\s+(de\s+|des\s+|du\s+|d\')?', '', circuit.name, flags=re.IGNORECASE).strip()
        else:
            circuit_label = raw_name

        # 2. Duration: prefer explicit pattern from raw_name (e.g. "24h", "8h", "sprint")
        dur_label = None
        m = re.search(r'(\d+)h', raw_name, re.IGNORECASE)
        if m:
            dur_label = f"{m.group(1)}h"
        elif re.search(r'sprint', raw_name, re.IGNORECASE):
            dur_label = "Sprint"
        elif re.search(r'quali', raw_name, re.IGNORECASE):
            dur_label = "Qualifs"
        else:
            h = int(duration_hours)
            dur_label = f"{h}h" if h >= 1 else f"{int(duration_hours * 60)}min"

        # 3. Date
        date_label = None
        if event_date:
            d = event_date.day
            m_idx = event_date.month - 1
            y = event_date.year
            date_label = f"{d} {MONTHS_FR[m_idx]} {y}"

        parts = [circuit_label, dur_label]
        if date_label:
            parts.append(date_label)
        return " · ".join(p for p in parts if p)

    def _create_event_from_header(self, header_line: str, data_lines: list[str],
                                   recording_name: str, session_factory: Callable) -> int:
        try:
            header = json.loads(header_line)
        except Exception:
            header = {}

        circuit_url = header.get("circuit_url", "")
        ws_port = int(header.get("ws_port", 0))
        name = header.get("name") or recording_name
        started_at_str = header.get("started_at")
        event_date = None
        if started_at_str:
            try:
                event_date = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                # TODO: convertir event_date en heure locale du circuit.
                # Le proxy expose timezone (IANA, ex: "Europe/Brussels") dans GET /api/circuits
                # et dans GET /api/recordings/sessions. Récupérer le timezone via Circuit.circuit_url
                # → appel proxy circuits, puis astimezone(ZoneInfo(tz)) avant de stocker event_date.
            except ValueError:
                pass

        last_t = 0.0
        for line in reversed(data_lines):
            line = line.strip()
            if not line:
                continue
            try:
                last_t = json.loads(line).get("t", 0.0)
                break
            except Exception:
                pass
        duration_hours = round(last_t / 3600, 1) if last_t else 6.0

        with session_factory() as db:
            circuit = db.query(Circuit).filter(Circuit.circuit_url == circuit_url).first()
            event = Event(
                name=self._build_event_name(name, circuit, duration_hours, event_date),
                circuit_url=circuit_url,
                ws_port_override=ws_port,
                event_date=event_date,
                duration_hours=duration_hours,
                source="proxy",
                proxy_ws_url=recording_name,
                circuit_id=circuit.id if circuit else None,
                min_pit_duration_s=circuit.min_pit_duration_s if circuit and circuit.min_pit_duration_s else 300,
                min_relay_s=circuit.min_relay_s if circuit and circuit.min_relay_s else 3600,
                max_relay_s=circuit.max_relay_s if circuit and circuit.max_relay_s else 5400,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            return event.id

    async def _do_import(self, event_id: Optional[int], recording_name: str, proxy_http_url: str,
                         session_factory: Callable, broadcast: BroadcastFn):
        url = f"{proxy_http_url}/api/recordings/{recording_name}/download"
        logger.info("Fetching recording from %s", url)

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(f"Proxy returned HTTP {resp.status_code}")
            content = resp.text

        lines = content.splitlines()
        if not lines:
            raise RuntimeError("Empty recording file")

        data_lines = lines[1:]  # skip metadata header
        self.total = len(data_lines)
        logger.info("Recording has %d messages", self.total)

        # Max t value in recording — used to detect "fully imported"
        recording_max_t = 0.0
        for line in reversed(data_lines):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                recording_max_t = json.loads(stripped).get("t", 0.0)
                break
            except Exception:
                pass
        self.recording_max_t = recording_max_t

        # ── Parse header for circuit info ───────────────────────────────────
        event_start_dt = datetime.now(timezone.utc)
        import_circuit_url = ""
        import_ws_port = 0
        import_event_date: Optional[datetime] = None
        try:
            hdr = json.loads(lines[0])
            import_circuit_url = hdr.get("circuit_url", "")
            import_ws_port = int(hdr.get("ws_port", 0))
            s = hdr.get("started_at", "")
            if s:
                import_event_date = datetime.fromisoformat(s.replace("Z", "+00:00"))
                event_start_dt = import_event_date
        except Exception:
            pass

        # ── Collect all event_meta lines (one per session in the recording) ──────
        # Keyed by (title1, title2) for lookup during session changes.
        import_event_keys: dict[tuple[str, str], str] = {}
        for line in data_lines:
            if '"event_meta"' not in line:
                continue
            try:
                entry = json.loads(line.strip())
                em = entry.get("event_meta")
                if em and em.get("event_key"):
                    import_event_keys[(em.get("title1", ""), em.get("title2", ""))] = em["event_key"]
            except Exception:
                pass
        if import_event_keys:
            logger.info("Recording contains %d event_meta(s): %s", len(import_event_keys), list(import_event_keys.values()))

        # When event_id is provided, use it as-is (no multi-session split).
        # When None, auto-create one event per detected session title.
        auto_create_events = event_id is None
        if not auto_create_events:
            logger.info("Using provided event %d", event_id)

        # t-value tracking: raw seconds since recording start
        current_t_raw: list[float] = [0.0]
        # Warm-up threshold: messages with t <= resume_from are replayed into RaceState
        # but not persisted (data already in DB from a previous import).
        resume_from: list[float] = [0.0]

        # Single-event mode: check prior import progress upfront
        if not auto_create_events and event_id:
            with session_factory() as db:
                ev = db.get(Event, event_id)
                if ev and ev.imported_through_t:
                    resume_from[0] = ev.imported_through_t
                    self.resumed_from_t = resume_from[0]
                    logger.info("Event %d: resuming from t=%.1f (recording_max_t=%.1f)",
                                event_id, resume_from[0], recording_max_t)

        current_ts: list[datetime] = [event_start_dt]

        # Shared mutable context — reassigned by _on_session_change between sessions
        _ctx: dict = {
            "persister": EventPersister(event_id, session_factory) if event_id else None,
            "session_name": "",
        }
        if _ctx["persister"]:
            _ctx["persister"].clear_cache()

        # ── Isolated race stack ──────────────────────────────────────────────
        iso_state = RaceState()
        iso_ranker = KartRanker(TrackConditionMonitor())

        from config_store import get_config
        with session_factory() as db:
            cfg = get_config(db)
            _import_circuit = db.query(Circuit).filter(Circuit.circuit_url == import_circuit_url).first()
            _import_circuit_id = _import_circuit.id if _import_circuit else None
            _import_min_pit = _import_circuit.min_pit_duration_s if _import_circuit and _import_circuit.min_pit_duration_s else 300
            _import_min_relay = _import_circuit.min_relay_s if _import_circuit and _import_circuit.min_relay_s else 3600
            _import_max_relay = _import_circuit.max_relay_s if _import_circuit and _import_circuit.max_relay_s else 5400

        iso_pm = PitManager(iso_state, cfg)

        driver_pit_numbers: dict[str, int] = {}
        pending_pit_duration: dict[str, int] = {}
        pit_entry_times: dict[str, datetime] = {}

        def _reset_session_state():
            iso_state.drivers.clear()
            iso_state.pit_lanes.clear()
            iso_state.active_pit_stops.clear()
            iso_state.pit_history.clear()
            iso_state.kart_assignments.clear()
            iso_state.driver_lap_counts.clear()
            iso_state.title1 = ""
            iso_state.title2 = ""
            iso_state.countdown = 0
            iso_ranker.reset_live_data()
            driver_pit_numbers.clear()
            pending_pit_duration.clear()
            pit_entry_times.clear()
            if _ctx["persister"]:
                _ctx["persister"].clear_cache()

        def _close_all_stints():
            """Close all open stints for the current session, computing stats from the ranker."""
            persister = _ctx["persister"]
            if not persister or not persister._open_stint_ids:
                return
            field_avg = iso_ranker._field_avg()
            quartiles = iso_ranker._quartile_thresholds()
            for driver_id in list(persister._open_stint_ids.keys()):
                drv = iso_state.drivers.get(driver_id)
                driver_out = drv.driver_name if drv else ""
                stats = iso_ranker.get_stint_stats(driver_id)
                kq = "UNKNOWN"
                team = iso_ranker._teams.get(driver_id)
                if team:
                    kq, _ = iso_ranker._kart_quality(team, field_avg, quartiles)
                persister.close_stint(
                    driver_id=driver_id,
                    ended_at=current_ts[0],
                    driver_out=driver_out,
                    kart_quality=kq,
                    best_lap_ms=stats.get("best_lap_ms"),
                    avg_lap_ms=stats.get("avg_lap_ms"),
                    std_dev_ms=stats.get("std_dev_ms"),
                    lap_count=stats.get("lap_count", 0),
                )

        async def _on_session_change(init_type: str, title1: str, title2: str):
            if not auto_create_events:
                return
            name = f"{title1} — {title2}" if title2 else title1

            if _ctx["session_name"]:
                # Once in a session, only a full reset (init|r|) with a different
                # non-empty title can legitimately start a new session.
                # init|p| is always a reconnection — never create a new event.
                # Empty title1 is always a transient reconnect artifact.
                if init_type == "p" or not title1 or name == _ctx["session_name"]:
                    if name != _ctx["session_name"]:
                        logger.info(
                            "Import: ignoring session drift '%s' → '%s' (init_type=%s)",
                            _ctx["session_name"], name, init_type,
                        )
                    _close_all_stints()
                    _reset_session_state()
                    return

            _close_all_stints()
            _ctx["session_name"] = name
            logger.info("Import: new session '%s' (init_type=%s)", name, init_type)
            session_event_key = import_event_keys.get((title1, title2))
            with session_factory() as db:
                existing = None
                # Prefer matching by event_key (stable across re-imports / name drift)
                if session_event_key:
                    existing = (
                        db.query(Event)
                        .filter(Event.event_key == session_event_key)
                        .order_by(Event.id.desc())
                        .first()
                    )
                if not existing:
                    existing = (
                        db.query(Event)
                        .filter(Event.circuit_url == import_circuit_url, Event.name == name)
                        .order_by(Event.id.desc())
                        .first()
                    )
                if existing:
                    # Backfill event_key if missing
                    if session_event_key and not existing.event_key:
                        existing.event_key = session_event_key
                        db.commit()
                    new_ev_id = existing.id
                    resume_from[0] = existing.imported_through_t or 0.0
                    self.resumed_from_t = resume_from[0]
                    logger.info("Import: reusing event '%s' (id=%d, resume_from=%.1f)",
                                name, new_ev_id, resume_from[0])
                else:
                    ev = Event(
                        name=name,
                        circuit_url=import_circuit_url,
                        ws_port_override=import_ws_port,
                        event_date=import_event_date,
                        source="proxy",
                        circuit_id=_import_circuit_id,
                        min_pit_duration_s=_import_min_pit,
                        min_relay_s=_import_min_relay,
                        max_relay_s=_import_max_relay,
                        event_key=session_event_key,
                    )
                    db.add(ev)
                    db.commit()
                    db.refresh(ev)
                    new_ev_id = ev.id
                    resume_from[0] = 0.0
                    logger.info("Import: created event '%s' (id=%d)", name, new_ev_id)
            self.event_id = new_ev_id
            _ctx["persister"] = EventPersister(new_ev_id, session_factory)
            _ctx["persister"].clear_cache()
            _reset_session_state()

        def _on_lap(driver_id: str, lap_ms: int, is_pit: bool,
                    pit_number: int, lap_number: int):
            if current_t_raw[0] <= resume_from[0]:
                return  # warm-up: rebuild RaceState only, data already in DB
            persister = _ctx["persister"]
            if not persister:
                return
            entry = iso_state.drivers.get(driver_id)
            driver_name = entry.driver_name if entry else ""
            team_name = canonical_team_name(entry.team) if entry else ""
            bib = entry.kart if entry else ""
            category = entry.category if entry else ""

            prev_pit = driver_pit_numbers.get(driver_id, -1)
            if pit_number > prev_pit:
                driver_pit_numbers[driver_id] = pit_number
                if bib:
                    pit_dur = pending_pit_duration.pop(driver_id, None)
                    persister.open_stint(
                        driver_id=driver_id,
                        bib=bib,
                        team_name=team_name,
                        stint_number=pit_number,
                        kart_label=iso_state.kart_assignments.get(driver_id, "?"),
                        started_at=current_ts[0],
                        driver_name=driver_name,
                        pit_duration_ms=pit_dur,
                    )

            if bib:
                persister.record_lap(
                    driver_id=driver_id, bib=bib, team_name=team_name,
                    lap_number=lap_number, lap_ms=lap_ms, is_pit_lap=is_pit,
                )
                if not is_pit and lap_number > 0:
                    persister.record_stint_lap(driver_id=driver_id,
                                               lap_number=lap_number, lap_ms=lap_ms)

            iso_ranker.record_lap(
                team_id=driver_id,
                kart_label=iso_state.kart_assignments.get(driver_id, "?"),
                lap_ms=lap_ms,
                is_pit=is_pit,
                pit_number=pit_number,
                driver_name=driver_name,
                team_name=team_name,
                category=category,
            )

        def _on_pit(driver_id: str):
            if current_t_raw[0] <= resume_from[0]:
                return  # warm-up
            persister = _ctx["persister"]
            if not persister:
                return
            drv = iso_state.drivers.get(driver_id)
            driver_out = drv.driver_name if drv else ""
            iso_ranker.on_pit_stop(driver_id)
            stats = iso_ranker.get_stint_stats(driver_id)
            kq = "UNKNOWN"
            team = iso_ranker._teams.get(driver_id)
            if team:
                kq, _ = iso_ranker._kart_quality(
                    team, iso_ranker._field_avg(), iso_ranker._quartile_thresholds()
                )
            persister.close_stint(
                driver_id=driver_id,
                ended_at=current_ts[0],
                driver_out=driver_out,
                kart_quality=kq,
                best_lap_ms=stats.get("best_lap_ms"),
                avg_lap_ms=stats.get("avg_lap_ms"),
                std_dev_ms=stats.get("std_dev_ms"),
                lap_count=stats.get("lap_count", 0),
            )

        async def _on_event(event: str, data: dict):
            if current_t_raw[0] <= resume_from[0]:
                return  # warm-up
            persister = _ctx["persister"]
            if not persister:
                return
            if event == "pit_stop":
                driver_id_in = data.get("driver_id", "")
                pit_entry_times[driver_id_in] = current_ts[0]
                persister.record_pit_stop(
                    driver_id=driver_id_in,
                    bib=data.get("bib", ""),
                    team_name=canonical_team_name(data.get("team", "")),
                    pit_number=data.get("pit_number", 0),
                    lap_number_in=data.get("lap", 0),
                    kart_in_label=data.get("kart_label", "?"),
                    entered_at=current_ts[0],
                )
            elif event == "pit_out":
                driver_id_out = data.get("driver_id", "")
                drv = iso_state.drivers.get(driver_id_out)
                driver_in = drv.driver_name if drv else ""
                iso_ranker.on_pit_out(driver_id_out, driver_in)
                entered = pit_entry_times.pop(driver_id_out, None)
                dur_ms = int((current_ts[0] - entered).total_seconds() * 1000) if entered else None
                persister.complete_pit_stop(
                    driver_id=driver_id_out,
                    pit_number=data.get("pit_number", 0),
                    kart_out_label=data.get("new_kart_label"),
                    exited_at=current_ts[0],
                    stop_duration_ms=dur_ms,
                    pit_lap_ms=data.get("pit_lap_ms"),
                )
                if dur_ms and driver_id_out:
                    pending_pit_duration[driver_id_out] = dur_ms
                if driver_in and driver_id_out:
                    persister.update_stint_driver_in(driver_id_out, driver_in)
            elif event == "pit_lap_update":
                persister.update_pit_lap(
                    driver_id=data.get("driver_id", ""),
                    pit_number=data.get("pit_number", 0),
                    pit_lap_ms=data.get("pit_lap_ms", 0),
                )
                persister.update_stint_out_lap(
                    driver_id=data.get("driver_id", ""),
                    out_lap_ms=data.get("pit_lap_ms", 0),
                )

        apex = ApexClient(
            state=iso_state,
            on_event=_on_event,
            pit_manager=iso_pm,
            on_lap_cb=_on_lap,
            on_pit_cb=_on_pit,
            on_session_change_cb=_on_session_change,
        )

        # ── Replay messages in a thread so the event loop stays responsive ───
        loop = asyncio.get_running_loop()

        def _replay_sync():
            for i, line in enumerate(data_lines):
                line = line.strip()
                if not line:
                    self.processed = i + 1
                    continue
                try:
                    entry = json.loads(line)
                    t = entry.get("t", 0.0)
                    current_t_raw[0] = t
                    current_ts[0] = event_start_dt + timedelta(seconds=t)
                    msg = entry.get("msg", "")
                    # Each JSONL entry is one WS message bundle — clear per-bundle
                    # dedup set exactly as _listen does, so every lap gets processed.
                    apex._lap_counted_in_bundle.clear()
                    for raw in msg.split("\n"):
                        raw = raw.strip()
                        if raw and raw != "__proxy_reset__":
                            asyncio.run_coroutine_threadsafe(
                                apex._dispatch(raw), loop
                            ).result()
                except Exception:
                    pass

                self.processed = i + 1
                if (i + 1) % BROADCAST_EVERY == 0 or i + 1 == self.total:
                    pct = round((i + 1) / self.total * 100) if self.total else 0
                    asyncio.run_coroutine_threadsafe(
                        broadcast("import_progress", {
                            "processed": self.processed,
                            "total": self.total,
                            "pct": pct,
                        }),
                        loop,
                    ).result()

        await loop.run_in_executor(None, _replay_sync)

        # Close any stints still open at the end of the last session
        _close_all_stints()

        # Persist import progress cursor
        final_event_id = self.event_id
        final_t = current_t_raw[0]
        if final_event_id and final_t > 0:
            try:
                with session_factory() as db:
                    ev = db.get(Event, final_event_id)
                    if ev:
                        ev.imported_through_t = final_t
                        db.commit()
                        logger.info("Event %d: imported_through_t updated to %.1f", final_event_id, final_t)
            except Exception:
                logger.exception("Failed to update imported_through_t (non-fatal)")

        # Re-analyze kart quality with the full event field average now that all stints are closed
        if final_event_id:
            try:
                from api.routes import _reanalyze_event_stints
                with session_factory() as db:
                    n = _reanalyze_event_stints(final_event_id, db)
                logger.info("Post-import reanalysis: updated %d stints for event %d", n, final_event_id)
            except Exception:
                logger.exception("Post-import reanalysis failed (non-fatal)")
