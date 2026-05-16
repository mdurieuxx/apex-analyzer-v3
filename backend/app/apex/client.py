"""
WebSocket client for Apex Timing's Java server.

CRITICAL: Never send ANY message after connecting — even empty strings
cause immediate disconnection from the Java server.
"""
import asyncio
import logging
import ssl
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
LapCb = Callable[[str, int, bool, int], None]   # (driver_id, lap_ms, is_pit, pit_number)
PitCb = Callable[[str], None]                    # (driver_id)


class ApexClient:
    def __init__(
        self,
        state: RaceState,
        on_event: EventCb,
        pit_manager,
        on_lap_cb: Optional[LapCb] = None,
        on_pit_cb: Optional[PitCb] = None,
    ):
        self.state = state
        self.on_event = on_event
        self.pit_manager = pit_manager
        self._on_lap = on_lap_cb
        self._on_pit = on_pit_cb
        self._running = False

    async def run(self):
        self._running = True
        attempt = 0
        while self._running and attempt < MAX_ATTEMPTS:
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
                    additional_headers={
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
            self.state.last_update = datetime.now(timezone.utc)
            for line in raw.split("\n"):
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
                self.state.countdown = int(val)
            except ValueError:
                pass

        elif cmd == "grid":
            drivers, col_map = parse_grid_html(val)
            self.state.drivers = drivers
            self.state.col_map = col_map
            # Initialise lap count tracking
            for driver_id, d in self.state.drivers.items():
                self.state.driver_lap_counts[driver_id] = d.laps
            logger.info("Grid: %d drivers (col_map: last_lap=c%d, pits=c%d)",
                        len(self.state.drivers), col_map.last_lap, col_map.pits)
            await self.on_event("grid", {"count": len(self.state.drivers)})

        else:
            # Incremental cell update r{N}c{M}|css|value
            result = apply_update(self.state.drivers, cmd, sub, val, self.state.col_map)

            # Detect new lap from last_lap column update
            self._maybe_record_lap(cmd, sub, val)

            if result:
                row_id, old_pits = result
                driver = self.state.drivers[row_id]
                # Notify ranker that a pit stop started (locks baseline)
                if self._on_pit:
                    self._on_pit(row_id)
                pit_stop = self.pit_manager.on_pit_stop_detected(driver)
                await self.on_event("pit_stop", {
                    "driver_id": row_id,
                    "bib": driver.kart,
                    "team": driver.team,
                    "position": driver.position,
                    "pit_number": driver.pits,
                    "kart_label": pit_stop.kart_label,
                    "timestamp": pit_stop.timestamp.isoformat(),
                })

    def _maybe_record_lap(self, cmd: str, css: str, raw_val: str):
        """
        When the last_lap column updates for a driver, we have a new lap time.
        Uses dynamic col_map so it works across circuits with different layouts.
        """
        import re
        last_lap_col = self.state.col_map.last_lap
        m = re.match(rf'^r(\d+)c{last_lap_col}$', cmd)
        if not m:
            return
        row_id = m.group(1)
        driver = self.state.drivers.get(row_id)
        if not driver:
            return

        # Parse lap time from raw_val (may contain HTML tags or CSS prefix)
        clean = re.sub(r'<[^>]+>', '', raw_val).strip()
        lap_ms = self._parse_lap_to_ms(clean)
        if not lap_ms:
            return

        old_count = self.state.driver_lap_counts.get(row_id, 0)
        new_count = driver.laps  # already updated by apply_update on c12 or similar

        # Only record if this looks like a genuine new lap
        if self._on_lap:
            is_pit = driver.pits > 0 and old_count == new_count
            self._on_lap(row_id, lap_ms, is_pit, driver.pits)

        self.state.driver_lap_counts[row_id] = driver.laps

    @staticmethod
    def _parse_lap_to_ms(formatted: str) -> int:
        """Parse '1:23.456' or '83.456' into milliseconds."""
        import re
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
