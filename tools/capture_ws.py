#!/usr/bin/env python3
"""
Capture raw Apex Timing WebSocket messages during a live session.

Usage:
    pip install websockets
    python3 capture_ws.py --url https://www.apex-timing.com/live-timing/karting-saintes/index.html --port 8583 --duration 120 --out saintes_race.json

The JSON output contains:
  - ts: UTC timestamp of each line
  - raw: raw protocol line (e.g. "r5c4|pb|Dupont Jean")
"""
import argparse
import asyncio
import json
import ssl
import sys
from datetime import datetime, timezone

try:
    import websockets
except ImportError:
    print("Run: pip install websockets")
    sys.exit(1)


async def capture(circuit_url: str, port: int, duration_s: int, out_path: str):
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE

    messages: list[dict] = []
    connected_at = None

    for scheme, ctx in [("wss", ssl_ctx), ("ws", None)]:
        url = f"{scheme}://www.apex-timing.com:{port}/"
        print(f"Trying {url} ...", flush=True)
        try:
            async with websockets.connect(
                url, ssl=ctx,
                additional_headers={
                    "Origin": circuit_url.rstrip("/"),
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                },
                ping_interval=20,
                ping_timeout=10,
                open_timeout=10,
            ) as ws:
                connected_at = datetime.now(timezone.utc)
                print(f"Connected via {scheme.upper()}. Capturing for {duration_s}s ...", flush=True)

                async def read_loop():
                    async for raw in ws:
                        for line in raw.split("\n"):
                            line = line.strip()
                            if line:
                                messages.append({
                                    "ts": datetime.now(timezone.utc).isoformat(),
                                    "raw": line,
                                })
                                # Progress indicator every 100 messages
                                if len(messages) % 100 == 0:
                                    elapsed = (datetime.now(timezone.utc) - connected_at).total_seconds()
                                    print(f"  {len(messages)} messages in {elapsed:.0f}s ...", flush=True)

                await asyncio.wait_for(read_loop(), timeout=duration_s)

        except asyncio.TimeoutError:
            print(f"Capture complete: {len(messages)} messages", flush=True)
        except Exception as e:
            print(f"{scheme.upper()} failed: {e}", flush=True)
            continue

        break  # success, don't try next scheme

    if not messages:
        print("ERROR: no messages captured", file=sys.stderr)
        sys.exit(1)

    with open(out_path, "w") as f:
        json.dump({"captured_at": connected_at.isoformat() if connected_at else None,
                   "circuit_url": circuit_url,
                   "port": port,
                   "count": len(messages),
                   "messages": messages}, f, indent=2)
    print(f"Saved {len(messages)} messages to {out_path}", flush=True)


def main():
    p = argparse.ArgumentParser(description="Apex Timing WS capture tool")
    p.add_argument("--url", default="https://www.apex-timing.com/live-timing/karting-saintes/index.html")
    p.add_argument("--port", type=int, default=8583)
    p.add_argument("--duration", type=int, default=120, help="capture duration in seconds")
    p.add_argument("--out", default="ws_capture.json")
    args = p.parse_args()
    asyncio.run(capture(args.url, args.port, args.duration, args.out))


if __name__ == "__main__":
    main()
