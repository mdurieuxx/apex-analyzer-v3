"""
WebSocket client for Apex Timing's Java server.

CRITICAL: Never send ANY message after connecting — even empty strings
cause immediate disconnection from the Java server.
"""
import asyncio
import logging
import ssl
from datetime import datetime, timezone
from typing import Callable, Awaitable

import websockets
import websockets.exceptions

from apex.grid_parser import parse_grid_html, apply_update, parse_comments
from race.state import RaceState

logger = logging.getLogger(__name__)

RECONNECT_BASE = 3
MAX_ATTEMPTS = 100
EventCb = Callable[[str, dict], Awaitable[None]]


class ApexClient:
    def __init__(self, state: RaceState, on_event: EventCb, pit_manager):
        self.state = state
        self.on_event = on_event
        self.pit_manager = pit_manager
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
            self.state.drivers = parse_grid_html(val)
            logger.info("Grid: %d drivers", len(self.state.drivers))
            await self.on_event("grid", {"count": len(self.state.drivers)})

        else:
            # Incremental cell update r{N}c{M}|css|value
            pit_result = apply_update(self.state.drivers, cmd, sub, val)
            if pit_result:
                row_id, old_pits = pit_result
                driver = self.state.drivers[row_id]
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
