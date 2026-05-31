"""
Converts all test-data files to the canonical proxy format:
  line 0: {"v":1, "circuit_url":..., "ws_port":..., "name":..., "started_at":...}
  line N: {"t": <float seconds since start>, "msg": "<pipe-delimited WS message>"}

Handles:
  - Old format (metadata + timestamp/data lines) → new format
  - Multiple files for the same race → merged single new-format file
  - New-format files from the same race → merged (t offsets adjusted)
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).parent


# ── Helpers ────────────────────────────────────────────────────────────────────

def parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def ws_url_to_circuit_url(ws_url: str) -> str:
    """wss://www.apex-timing.com:8313 → best-guess HTTP URL (not always known)."""
    m = re.match(r"wss?://([^:]+):(\d+)", ws_url)
    if not m:
        return ws_url
    host, port = m.group(1), m.group(2)
    known = {
        "8313": "https://www.apex-timing.com/live-timing/karting-mariembourg/",
        "8043": "https://www.apex-timing.com/live-timing/misanino/",
        "8583": "https://www.apex-timing.com/live-timing/karting-de-saintes/",
    }
    return known.get(port, f"https://{host}/")


def ws_url_to_port(ws_url: str) -> int:
    m = re.search(r":(\d+)$", ws_url)
    return int(m.group(1)) if m else 0


# ── Old-format reader ──────────────────────────────────────────────────────────

def read_old_format(paths: list[Path]) -> tuple[dict, list[tuple[float, str]]]:
    """
    Returns (header_dict, [(t_seconds, msg_str), ...]).
    t is relative to the very first data message across all files.
    """
    header = {}
    messages = []  # (abs_datetime, msg)

    for path in paths:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "metadata" in obj and not header:
                    m = obj["metadata"]
                    header = {
                        "v": 1,
                        "circuit_url": ws_url_to_circuit_url(m.get("websocketUrl", "")),
                        "ws_port": ws_url_to_port(m.get("websocketUrl", "")),
                        "name": m.get("sessionName", ""),
                        "started_at": m.get("recordingStartTime", ""),
                    }

                msg = obj.get("data", "")
                ts_str = obj.get("timestamp", "")
                if msg and ts_str:
                    messages.append((parse_iso(ts_str), msg))

    if not messages:
        return header, []

    t0 = messages[0][0]
    result = [(( dt - t0).total_seconds(), msg) for dt, msg in messages]
    if header and header.get("started_at"):
        header["started_at"] = messages[0][0].isoformat()

    return header, result


# ── New-format reader ──────────────────────────────────────────────────────────

def read_new_format(paths: list[Path]) -> tuple[dict, list[tuple[float, str]]]:
    """
    Reads one or more new-format files representing the same race.
    Adjusts t values so the merged output is continuous.
    """
    header = {}
    all_segments = []

    for path in paths:
        seg_header = {}
        seg_messages = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "v" in obj and "started_at" in obj:
                    seg_header = obj
                elif "t" in obj and "msg" in obj:
                    seg_messages.append((obj["t"], obj["msg"]))
        if seg_header and seg_messages:
            all_segments.append((seg_header, seg_messages))

    if not all_segments:
        return header, []

    # Use first segment's header
    header = dict(all_segments[0][0])

    # Merge: compute absolute time for each message using started_at + t
    abs_messages = []
    for seg_header, seg_msgs in all_segments:
        t0 = parse_iso(seg_header["started_at"])
        for t_rel, msg in seg_msgs:
            abs_dt = t0.timestamp() + t_rel
            abs_messages.append((abs_dt, msg))

    # Sort by absolute time (in case files are not perfectly ordered)
    abs_messages.sort(key=lambda x: x[0])

    # Rebase t to first message
    t_base = abs_messages[0][0]
    result = [(abs_t - t_base, msg) for abs_t, msg in abs_messages]

    # Update started_at to actual first message time
    header["started_at"] = datetime.fromtimestamp(t_base, tz=timezone.utc).isoformat()

    return header, result


# ── Writer ─────────────────────────────────────────────────────────────────────

def write_new_format(output_path: Path, header: dict, messages: list[tuple[float, str]]):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(json.dumps(header, ensure_ascii=False) + "\n")
        for t, msg in messages:
            f.write(json.dumps({"t": round(t, 3), "msg": msg}, ensure_ascii=False) + "\n")
    size_mb = output_path.stat().st_size / 1_000_000
    print(f"  → {output_path} ({len(messages):,} messages, {size_mb:.1f}MB)")


# ── Conversion jobs ────────────────────────────────────────────────────────────

def run():
    jobs = [
        # ── Misanino 24h 2025 — 3 old-format files → 1 merged ────────────────
        {
            "output": BASE / "misanino" / "2025_24h" / "misanino_24h_20251018.jsonl",
            "format": "old",
            "inputs": sorted((BASE / "misanino" / "2025_24h").glob("*.jsonl")),
            "skip_existing": ["misanino_24h_20251018.jsonl"],
        },
        # ── Mariembourg sprint/qualif 2025-10-26 — 1 old-format file ─────────
        {
            "output": BASE / "mariembourg" / "mariembourg_sprint_20251026.jsonl",
            "format": "old",
            "inputs": [BASE / "mariembourg" / "20251026_mariembourg_course_8h.jsonl"],
        },
        # ── Mariembourg 8h 2025-10-19 — 1 old-format file ────────────────────
        # (already converted as 20251019_converted.jsonl — redo from original for clean naming)
        {
            "output": BASE / "mariembourg" / "mariembourg_8h_20251019.jsonl",
            "format": "old",
            "inputs": [BASE / "mariembourg" / "mariembourg_8h_2025" / "20251019_073928_20251019_160408.jsonl"],
        },
        # ── Mariembourg 4h fun 2026-05-17 — 2 new-format files → 1 merged ────
        {
            "output": BASE / "mariembourg" / "mariembourg_4h_fun_20260517.jsonl",
            "format": "new",
            "inputs": [
                BASE / "mariembourg" / "20260517_4h_fun" / "mariembourg 4h fun.jsonl",
                BASE / "mariembourg" / "20260517_4h_fun" / "mariembourg_20260517_105903.jsonl",
            ],
        },
    ]

    for job in jobs:
        output = job["output"]
        inputs = [p for p in job["inputs"] if p.exists()]
        skip = job.get("skip_existing", [])

        # Skip already-converted output files from input list
        inputs = [p for p in inputs if p.name not in skip]

        if not inputs:
            print(f"SKIP (no inputs): {output.name}")
            continue

        print(f"\n{'─'*60}")
        print(f"Converting → {output.name}")
        for p in inputs:
            print(f"  < {p.name}")

        if job["format"] == "old":
            header, messages = read_old_format(inputs)
        else:
            header, messages = read_new_format(inputs)

        if not messages:
            print("  ERROR: no messages found")
            continue

        print(f"  Header: circuit_url={header.get('circuit_url')} port={header.get('ws_port')}")
        print(f"  started_at: {header.get('started_at')}")
        t_max = messages[-1][0]
        print(f"  Duration: {t_max/3600:.2f}h, Messages: {len(messages):,}")

        write_new_format(output, header, messages)


if __name__ == "__main__":
    run()
    print("\nDone.")
