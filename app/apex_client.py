import asyncio
import ssl
import logging
from datetime import datetime, timezone
from typing import Callable, Awaitable

import websockets
import websockets.exceptions

from models import SessionState, Driver, PitEvent
from grid_parser import parse_grid_html, apply_cell_update, parse_comments

logger = logging.getLogger(__name__)

# Apex Timing Java WebSocket server: NEVER send any message on connect —
# even an empty string causes immediate disconnection.
RECONNECT_DELAY = 5
MAX_RECONNECT = 20

EventCallback = Callable[[str, dict], Awaitable[None]]


class ApexClient:
    def __init__(self, state: SessionState, on_event: EventCallback):
        self.state = state
        self.on_event = on_event
        self._running = False

    async def run(self):
        self._running = True
        attempt = 0
        while self._running and attempt < MAX_RECONNECT:
            try:
                await self._connect()
                attempt = 0
            except Exception as e:
                attempt += 1
                logger.warning("WebSocket error (attempt %d/%d): %s", attempt, MAX_RECONNECT, e)
                await asyncio.sleep(RECONNECT_DELAY * min(attempt, 4))

        logger.info("ApexClient stopped after %d attempts", attempt)

    async def stop(self):
        self._running = False

    async def _connect(self):
        port = self.state.ws_port
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        # Try WSS first (port), then WS (port - 1) as fallback
        for scheme, use_ssl in [("wss", ssl_ctx), ("ws", None)]:
            url = f"{scheme}://www.apex-timing.com:{port}/"
            try:
                logger.info("Connecting to %s", url)
                async with websockets.connect(
                    url,
                    ssl=use_ssl,
                    additional_headers={
                        "Origin": self.state.circuit_url.rstrip("/"),
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
                logger.warning("Failed %s: %s", url, e)

        raise ConnectionError(f"Both WSS and WS failed for port {port}")

    async def _receive_loop(self, ws):
        async for raw in ws:
            if not self._running:
                break
            self.state.last_update = datetime.now(timezone.utc)
            for line in raw.split("\n"):
                line = line.strip()
                if not line:
                    continue
                await self._dispatch(line)

        self.state.connected = False

    async def _dispatch(self, line: str):
        parts = line.split("|")
        cmd = parts[0]
        sub = parts[1] if len(parts) > 1 else ""
        val = parts[2] if len(parts) > 2 else sub

        if cmd == "title1":
            self.state.title1 = val
        elif cmd == "title2":
            self.state.title2 = val
        elif cmd == "com":
            self.state.comments = parse_comments(val)
        elif cmd == "dyn1" and sub == "countdown":
            try:
                self.state.countdown = int(val)
            except ValueError:
                pass
        elif cmd == "grid":
            self.state.drivers = parse_grid_html(val)
            logger.info("Grid parsed: %d drivers", len(self.state.drivers))
            await self.on_event("grid", {"count": len(self.state.drivers)})
        else:
            # Incremental cell update r{N}c{M}|css|value
            result = apply_cell_update(self.state.drivers, cmd, sub, val)
            if result:
                row_id, old_pits = result
                driver = self.state.drivers[row_id]
                pit_event = PitEvent(
                    timestamp=datetime.now(timezone.utc),
                    kart=driver.kart,
                    team=driver.team,
                    lap=driver.laps,
                    position=driver.position,
                    pit_number=driver.pits,
                )
                self.state.pit_history.append(pit_event)
                logger.info("PIT STOP: kart=%s team=%s pos=%d pit#=%d",
                            driver.kart, driver.team, driver.position, driver.pits)
                await self.on_event("pit_stop", {
                    "kart": driver.kart,
                    "team": driver.team,
                    "position": driver.position,
                    "pit_number": driver.pits,
                    "timestamp": pit_event.timestamp.isoformat(),
                })
