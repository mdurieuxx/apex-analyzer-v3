"""
WebSocket client for Apex Timing's Java server.

CRITICAL: Never send ANY message after connecting — even empty strings
cause immediate disconnection from the Java server.
"""
import asyncio
import json
import logging
import re
import ssl
import time
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

import websockets
import websockets.exceptions

from apex.grid_parser import parse_grid_html, apply_update, parse_comments
from apex.message_recorder import recorder
from race.state import RaceState

logger = logging.getLogger(__name__)

RECONNECT_BASE = 3
MAX_ATTEMPTS = 100
EventCb = Callable[[str, dict], Awaitable[None]]
LapCb = Callable[[str, int, bool, int, int], None]  # (driver_id, lap_ms, is_pit, pit_number, lap_number)
PitCb = Callable[[str], None]                        # (driver_id)
SessionChangeCb = Callable[[str, str, str], Awaitable[None]]  # (init_type, title1, title2)


class ApexClient:
    def __init__(
        self,
        state: RaceState,
        on_event: EventCb,
        pit_manager,
        on_lap_cb: Optional[LapCb] = None,
        on_pit_cb: Optional[PitCb] = None,
        ws_url: Optional[str] = None,    # proxy URL (bypasses Apex Timing direct connection)
        on_reset_cb: Optional[Callable] = None,  # called when proxy sends __proxy_reset__
        on_session_change_cb: Optional[SessionChangeCb] = None,  # called on init|r| or new session
        on_need_grid_cb: Optional[Callable] = None,  # async, called when updates arrive without a grid
        max_attempts: Optional[int] = MAX_ATTEMPTS,  # None = retry indefinitely
    ):
        self.state = state
        self.on_event = on_event
        self.pit_manager = pit_manager
        self._on_lap = on_lap_cb
        self._on_pit = on_pit_cb
        self._ws_url = ws_url
        self._on_reset = on_reset_cb
        self._on_session_change = on_session_change_cb
        self._on_need_grid = on_need_grid_cb
        self._max_attempts = max_attempts
        self._running = False
        self._got_grid = False
        self._updates_without_grid = 0
        # Event-time timestamp from proxy replay (seconds since recording start); None in live mode
        self._event_ts: Optional[float] = None
        # Drivers who just exited pits — next lap they complete is the out-lap (tour stand)
        self._pending_out_lap: set[str] = set()
        # Dedup: row_ids that already had a lap counted in the current WS frame.
        # Cleared at the start of each frame so identical consecutive lap times don't cause skips.
        self._lap_counted_in_bundle: set[str] = set()
        # Pending init type (set on init|r| or init|p|, consumed on grid||)
        self._pending_init_type: Optional[str] = None

    async def run(self):
        self._running = True
        attempt = 0
        while self._running and (self._max_attempts is None or attempt < self._max_attempts):
            try:
                await self._connect()
                attempt = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                attempt += 1
                delay = min(RECONNECT_BASE * attempt, 60)
                logger.warning("WS error (attempt %d): %s — retry in %ds", attempt, e, delay)
                self.state.connected = False
                await self.on_event("disconnected", {})
                await asyncio.sleep(delay)

    async def stop(self):
        self._running = False

    async def _connect(self):
        self._got_grid = False
        self._updates_without_grid = 0
        # Proxy mode: connect directly to the proxy WS URL
        if self._ws_url:
            logger.info("Connecting to proxy: %s", self._ws_url)
            async with websockets.connect(
                self._ws_url, ping_interval=20, ping_timeout=10, close_timeout=5
            ) as ws:
                self.state.connected = True
                await self.on_event("connected", {"url": self._ws_url})
                await self._receive_loop(ws)
            return

        # Direct Apex Timing connection
        port = self.state.ws_port
        if not port:
            raise ValueError("ws_port not set")

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        errors = []
        for scheme, ctx in [("wss", ssl_ctx), ("ws", None)]:
            url = f"{scheme}://www.apex-timing.com:{port}/"
            try:
                logger.info("Connecting %s", url)
                async with websockets.connect(
                    url,
                    ssl=ctx,
                    extra_headers={
                        "Origin": self.state.circuit_url.rstrip("/"),
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/124.0.0.0 Safari/537.36",
                    },
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self.state.connected = True
                    logger.info("Connected via %s", scheme.upper())
                    await self.on_event("connected", {"url": url})
                    await self._receive_loop(ws)
                    return
            except Exception as e:
                logger.warning("%s failed: %s", url, e)
                errors.append(str(e))

        raise ConnectionError(f"Both WSS and WS failed: {errors}")

    async def _receive_loop(self, ws):
        async for raw in ws:
            if not self._running:
                break
            msg = raw.decode() if isinstance(raw, bytes) else raw
            # Proxy reset signal — clear state before replay
            if msg.strip() == "__proxy_reset__":
                logger.info("Proxy reset signal received")
                if self._on_reset:
                    await self._on_reset()
                # TODO: après reset, appeler GET /api/status sur le proxy pour récupérer
                # l'event_key courant et l'associer à l'Event live créé par RaceManager.
                # Le proxy expose event_key dans la réponse /api/status (champ top-level
                # à ajouter) ou via bg_recordings[is_live_rec].event_key.
                continue
            # JSON wrapper from proxy replay: {"t": elapsed_s, "msg": "..."}
            # Absent in live/direct-Apex mode — _event_ts stays None.
            if msg.startswith('{"t":'):
                try:
                    wrapper = json.loads(msg)
                    self._event_ts = wrapper["t"]
                    msg = wrapper["msg"]
                except Exception:
                    pass
            self.state.last_update = datetime.now(timezone.utc)
            self._lap_counted_in_bundle.clear()
            for line in msg.split("\n"):
                line = line.strip()
                if line:
                    recorder.record(line)
                    await self._dispatch(line)
        self.state.connected = False

    async def _dispatch(self, line: str):
        parts = line.split("|")
        cmd = parts[0]
        sub = parts[1] if len(parts) > 1 else ""
        val = parts[2] if len(parts) > 2 else sub

        # Row-level special commands: rN|*out|0, rN|*in|0, rN|#|pos, rN|*|…
        if (cmd.startswith("r") and sub.startswith("*")) or (cmd.startswith("r") and sub == "#"):
            if re.match(r'^r\d+$', cmd):
                row_id = cmd[1:]
                if sub == "*out":
                    await self._handle_pit_exit(row_id)
                elif sub == "*in":
                    driver = self.state.drivers.get(row_id)
                    if driver and row_id not in self.state.active_pit_stops:
                        # No pits column: count from *in signal directly
                        if self.state.col_map.pits == 0:
                            driver.pits += 1
                        if self._on_pit:
                            self._on_pit(row_id)
                        pit_stop = self.pit_manager.on_pit_stop_detected(driver)
                        pit_stop.event_ts_entered = self._event_ts
                        await self.on_event("pit_stop", {
                            "driver_id": row_id,
                            "bib": driver.kart,
                            "team": driver.team,
                            "position": driver.position,
                            "pit_number": driver.pits,
                            "lap": pit_stop.lap,
                            "kart_label": pit_stop.kart_label,
                            "timestamp": pit_stop.timestamp.isoformat(),
                        })
                elif sub == "*":
                    # rN|*|lap_ms — exact integer milliseconds from timing system
                    try:
                        lap_ms = int(val)
                    except (ValueError, TypeError):
                        return
                    if lap_ms > 0:
                        await self._record_lap_from_timing(row_id, lap_ms)
                elif sub == "#":
                    # rN|#|pos — position update from ranking system
                    driver = self.state.drivers.get(row_id)
                    if driver:
                        try:
                            driver.position = int(val)
                        except (ValueError, TypeError):
                            pass
                # *i1, *i2 and other sub-commands → ignore
                return

        if cmd == "init":
            # "r" = full reset (new race), "p" = partial reset (qualif / new category)
            self._pending_init_type = sub
            return

        if cmd == "title1":
            changed = self.state.title1 != val
            self.state.title1 = val
            if changed:
                await self.on_event("session_update", {"title1": val, "title2": self.state.title2})

        elif cmd == "title2":
            changed = self.state.title2 != val
            self.state.title2 = val
            if changed:
                await self.on_event("session_update", {"title1": self.state.title1, "title2": val})

        elif cmd == "com":
            self.state.comments = parse_comments(val)
            await self.on_event("comments", {"comments": self.state.comments})

        elif cmd == "dyn1" and sub == "countdown":
            try:
                raw = int(val)
                # Apex sends milliseconds when value > 86400 (24h in seconds)
                self.state.countdown = raw // 1000 if raw > 86400 else raw
            except ValueError:
                pass

        elif cmd == "grid":
            self._got_grid = True
            # Fire session-change callback BEFORE applying new grid so state is reset first
            if self._pending_init_type is not None and self._on_session_change:
                await self._on_session_change(self._pending_init_type, self.state.title1, self.state.title2)
            self._pending_init_type = None

            drivers, col_map = parse_grid_html(val)
            self.state.drivers = drivers
            self.state.col_map = col_map
            self._pending_out_lap.clear()
            self._lap_counted_in_bundle.clear()
            # Initialise lap count tracking
            for driver_id, d in self.state.drivers.items():
                self.state.driver_lap_counts[driver_id] = d.laps
            logger.info(
                "Grid: %d drivers (pos=c%d kart=c%d team=c%d last_lap=c%d best_lap=c%d "
                "gap=c%d interval=c%d laps=c%d pits=c%d s1=c%d s2=c%d s3=c%d)",
                len(self.state.drivers),
                col_map.position, col_map.kart, col_map.team,
                col_map.last_lap, col_map.best_lap, col_map.gap, col_map.interval,
                col_map.laps, col_map.pits, col_map.s1, col_map.s2, col_map.s3,
            )
            await self.on_event("grid", {"count": len(self.state.drivers)})

        else:
            # Incremental cell update r{N}c{M}|css|value
            if not self._got_grid and self._on_need_grid:
                self._updates_without_grid += 1
                if self._updates_without_grid == 5:
                    asyncio.create_task(self._on_need_grid())

            result = apply_update(self.state.drivers, cmd, sub, val, self.state.col_map)

            # Detect new lap from last_lap column update
            await self._maybe_record_lap(cmd, sub, val)

            if result:
                row_id, old_pits = result
                driver = self.state.drivers[row_id]
                # Notify ranker that a pit stop started (locks baseline)
                if self._on_pit:
                    self._on_pit(row_id)
                pit_stop = self.pit_manager.on_pit_stop_detected(driver)
                pit_stop.event_ts_entered = self._event_ts
                await self.on_event("pit_stop", {
                    "driver_id": row_id,
                    "bib": driver.kart,
                    "team": driver.team,
                    "position": driver.position,
                    "pit_number": driver.pits,
                    "lap": pit_stop.lap,
                    "kart_label": pit_stop.kart_label,
                    "timestamp": pit_stop.timestamp.isoformat(),
                })

    async def _handle_pit_exit(self, row_id: str):
        """Called when rN|*out|0 is received — team has exited the pit lane."""
        driver = self.state.drivers.get(row_id)
        if not driver:
            return
        active = self.state.active_pit_stops.get(row_id)
        pit_lap_ms = active.pit_lap_ms if active else None
        pit_number = active.pit_number if active else 0
        if active:
            active.event_ts_exited = self._event_ts
        new_kart = self.pit_manager.on_team_exited_pits(row_id)
        # Retrieve duration from the stop that was just moved to history
        duration_s = None
        if self.state.pit_history:
            last = self.state.pit_history[-1]
            if last.driver_id == row_id:
                duration_s = last.duration_s
        # Next lap this driver completes will be the out-lap (tour stand)
        self._pending_out_lap.add(row_id)
        logger.info("PIT OUT: team=%s new_kart=%s duration=%ss", driver.team, new_kart, duration_s)
        await self.on_event("pit_out", {
            "driver_id": row_id,
            "bib": driver.kart,
            "team": driver.team,
            "position": driver.position,
            "pit_number": pit_number,
            "new_kart_label": new_kart,
            "pit_lap_ms": pit_lap_ms,
            "duration_s": duration_s,
        })

    async def _record_lap_from_timing(self, row_id: str, lap_ms: int):
        """
        Primary lap path: rN|*|lap_ms — exact integer ms from timing system.
        Fires before the display column update so driver.laps may not yet reflect
        the new lap; lap count is updated again by _maybe_record_lap when it arrives.
        """
        driver = self.state.drivers.get(row_id)
        if not driver:
            return

        is_out_lap = row_id in self._pending_out_lap
        if is_out_lap:
            self._pending_out_lap.discard(row_id)
            for stop in reversed(self.state.pit_history):
                if stop.driver_id == row_id:
                    stop.pit_lap_ms = lap_ms
                    await self.on_event("pit_lap_update", {
                        "driver_id": row_id,
                        "bib": stop.bib,
                        "pit_number": stop.pit_number,
                        "pit_lap_ms": lap_ms,
                    })
                    break

        # Store lap ms and timestamp for frontend progress bar
        driver.last_lap_ms = lap_ms
        driver.last_lap_received_at = time.time()

        # last_lap display column may have fired first in this bundle — don't double-count
        if row_id in self._lap_counted_in_bundle:
            return
        self._lap_counted_in_bundle.add(row_id)

        old_count = self.state.driver_lap_counts.get(row_id, 0)
        new_count = driver.laps

        if self._on_lap:
            if new_count > 0:
                is_pit = driver.pits > 0 and old_count == new_count
            else:
                is_pit = is_out_lap
            lap_count = new_count if new_count > 0 else (old_count + 1)
            self._on_lap(row_id, lap_ms, is_pit, driver.pits, lap_count)

        if new_count <= 0:
            self.state.driver_lap_counts[row_id] = old_count + 1

    async def _maybe_record_lap(self, cmd: str, css: str, raw_val: str):
        """
        Display column update for last_lap.
        If rN|*|ms already fired for this lap in the same WS bundle, only
        update driver_lap_counts with the now-applied laps column value.
        Fallback lap path when the * command is absent.
        """
        last_lap_col = self.state.col_map.last_lap
        m = re.match(rf'^r(\d+)c{last_lap_col}$', cmd)
        if not m:
            return
        row_id = m.group(1)
        driver = self.state.drivers.get(row_id)
        if not driver:
            return

        clean = re.sub(r'<[^>]+>', '', raw_val).strip()
        lap_ms = self._parse_lap_to_ms(clean)
        # Gap values (e.g. "0.085" → 85 ms) are not lap times — ignore anything < 30 s
        if not lap_ms or lap_ms < 30_000:
            return

        # * already counted this lap in the same WS bundle — sync driver.laps if valid
        if row_id in self._lap_counted_in_bundle:
            new_count = driver.laps
            if new_count > 0:
                self.state.driver_lap_counts[row_id] = new_count
            return
        self._lap_counted_in_bundle.add(row_id)

        # Fallback: * command not received, fire _on_lap from display string
        is_out_lap = row_id in self._pending_out_lap
        if is_out_lap:
            self._pending_out_lap.discard(row_id)
            for stop in reversed(self.state.pit_history):
                if stop.driver_id == row_id:
                    stop.pit_lap_ms = lap_ms
                    await self.on_event("pit_lap_update", {
                        "driver_id": row_id,
                        "bib": stop.bib,
                        "pit_number": stop.pit_number,
                        "pit_lap_ms": lap_ms,
                    })
                    break

        old_count = self.state.driver_lap_counts.get(row_id, 0)
        new_count = driver.laps

        if self._on_lap:
            if new_count > 0:
                is_pit = driver.pits > 0 and old_count == new_count
            else:
                is_pit = is_out_lap
            lap_count = new_count if new_count > 0 else (old_count + 1)
            self._on_lap(row_id, lap_ms, is_pit, driver.pits, lap_count)

        if new_count > 0:
            self.state.driver_lap_counts[row_id] = new_count
        else:
            self.state.driver_lap_counts[row_id] = old_count + 1

    @staticmethod
    def _parse_lap_to_ms(formatted: str) -> int:
        """Parse '1:23.456' or '83.456' into milliseconds."""
        # Format: M:SS.mmm
        m = re.match(r'^(\d+):(\d{2})[\.,](\d{1,3})$', formatted)
        if m:
            minutes = int(m.group(1))
            seconds = int(m.group(2))
            millis = int(m.group(3).ljust(3, '0'))
            return (minutes * 60 + seconds) * 1000 + millis
        # Format: SS.mmm
        m = re.match(r'^(\d+)[\.,](\d{1,3})$', formatted)
        if m:
            seconds = int(m.group(1))
            millis = int(m.group(2).ljust(3, '0'))
            return seconds * 1000 + millis
        return 0
