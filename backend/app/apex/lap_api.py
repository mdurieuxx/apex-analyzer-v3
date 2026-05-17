import re
import logging
import httpx

logger = logging.getLogger(__name__)

_ENDPOINT = "https://www.apex-timing.com/live-timing/commonv2/functions/request.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.apex-timing.com",
}


def _data_port(ws_port: int) -> int:
    # wsPort = displayPort + 3  →  dataPort = wsPort - 3
    return ws_port - 3


async def fetch_driver_laps(circuit_url: str, ws_port: int, driver_id: str) -> dict:
    port = _data_port(ws_port)
    req = f"D#-30#D{driver_id}.L#-999#D{driver_id}.B#1#D{driver_id}.INF"
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(
                _ENDPOINT,
                data={"port": str(port), "request": req},
                headers={**_HEADERS, "Referer": circuit_url},
            )
            r.raise_for_status()
            return _parse(r.text, driver_id)
    except Exception as e:
        logger.error("lap_api %s: %s", driver_id, e)
        return {"error": str(e)}


def _parse(text: str, driver_id: str) -> dict:
    laps, best_lap, best_sectors, driver_info = [], {}, {}, {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if f"D{driver_id}.L" in line and "#" in line:
            lap = _parse_lap(line)
            if lap:
                laps.append(lap)
        elif f"D{driver_id}.BL#" in line:
            parts = line.split("#", 1)[1].split("|") if "#" in line else []
            if len(parts) >= 4:
                best_lap = {k: _t(v) for k, v in zip(("s1_ms", "s2_ms", "s3_ms", "total_ms"), parts)}
        elif f"D{driver_id}.BS#" in line:
            parts = line.split("#", 1)[1].split("|") if "#" in line else []
            if len(parts) >= 3:
                best_sectors = {k: _t(v) for k, v in zip(("s1_ms", "s2_ms", "s3_ms"), parts)}
        elif f"D{driver_id}.INF#" in line:
            driver_info = _parse_inf(line.split(".INF#", 1)[1])

    laps.sort(key=lambda x: x["lap_number"], reverse=True)
    return {"driver_id": driver_id, "driver_info": driver_info,
            "laps": laps, "best_lap": best_lap, "best_sectors": best_sectors}


def _parse_lap(line: str) -> dict | None:
    m = re.search(r'\.L(\d+)#([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)', line)
    if not m:
        return None
    lap_num = int(m.group(1))
    if lap_num == 0:
        return None

    def dec(s):
        best = s.startswith("g")
        pit = s.startswith("p")
        raw = s.lstrip("gp")
        return {"ms": int(raw) if raw.isdigit() else 0, "best": best, "pit": pit}

    s1, s2, s3, tot = dec(m.group(2)), dec(m.group(3)), dec(m.group(4)), dec(m.group(5))
    return {
        "lap_number": lap_num,
        "s1_ms": s1["ms"], "s1_best": s1["best"],
        "s2_ms": s2["ms"], "s2_best": s2["best"],
        "s3_ms": s3["ms"], "s3_best": s3["best"],
        "total_ms": tot["ms"], "total_best": tot["best"],
        "is_pit": s1["pit"] or tot["pit"],
    }


def _t(s: str) -> int:
    s = s.strip()
    return int(s) if s.isdigit() else 0


def _parse_inf(xml: str) -> dict:
    result = {"team": "", "kart": "", "club": "", "drivers": []}
    m = re.search(r'num="(\d+)"[^>]*name="([^"]+)"', xml)
    if m:
        result["kart"], result["team"] = m.group(1), m.group(2)
    club = re.search(r'type="club"[^>]*value="([^"]+)"', xml)
    if club:
        result["club"] = club.group(1)
    for d in re.finditer(r'<driver[^>]*id="(\d+)"[^>]*num="(\d+)"[^>]*name="([^"]+)"', xml):
        result["drivers"].append({
            "id": d.group(1), "num": d.group(2), "name": d.group(3),
            "current": 'current="1"' in d.group(0),
        })
    return result
