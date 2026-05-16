import logging
import httpx

logger = logging.getLogger(__name__)

# Apex Timing HTTP endpoint for fetching per-driver lap details.
# Port here is the "data port" = wsPort - 3 (the base display port).
_LAP_ENDPOINT = "https://www.apex-timing.com/live-timing/commonv2/functions/request.php"


def _data_port(ws_port: int) -> int:
    # wsPort = displayPort + 3; data port = displayPort
    return ws_port - 3


async def fetch_driver_laps(circuit_url: str, ws_port: int, driver_id: str) -> dict:
    """
    Fetch per-lap detail for a driver from the Apex Timing HTTP API.
    Returns raw parsed data: laps, best_lap, best_sectors, driver_info.
    """
    port = _data_port(ws_port)
    request_str = f"D#-30#D{driver_id}.L#-999#D{driver_id}.B#1#D{driver_id}.INF"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _LAP_ENDPOINT,
                data={"port": str(port), "request": request_str},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": "https://www.apex-timing.com",
                    "Referer": circuit_url,
                },
            )
            resp.raise_for_status()
            return _parse_response(resp.text, driver_id)
    except Exception as e:
        logger.error("lap_api error driver=%s: %s", driver_id, e)
        return {"error": str(e)}


def _parse_response(text: str, driver_id: str) -> dict:
    laps = []
    best_lap = {}
    best_sectors = {}
    driver_info = {}

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        if f"D{driver_id}.L" in line and "#" in line:
            lap = _parse_lap_line(line)
            if lap:
                laps.append(lap)
        elif f"D{driver_id}.BL#" in line:
            m_parts = line.split("#", 1)
            if len(m_parts) > 1:
                vals = m_parts[1].split("|")
                if len(vals) >= 4:
                    best_lap = {
                        "s1": _parse_time(vals[0]),
                        "s2": _parse_time(vals[1]),
                        "s3": _parse_time(vals[2]),
                        "total": _parse_time(vals[3]),
                    }
        elif f"D{driver_id}.BS#" in line:
            m_parts = line.split("#", 1)
            if len(m_parts) > 1:
                vals = m_parts[1].split("|")
                if len(vals) >= 3:
                    best_sectors = {
                        "s1": _parse_time(vals[0]),
                        "s2": _parse_time(vals[1]),
                        "s3": _parse_time(vals[2]),
                    }
        elif f"D{driver_id}.INF#" in line:
            driver_info = _parse_driver_inf(line.split(".INF#", 1)[1])

    laps.sort(key=lambda x: x["lap_number"], reverse=True)

    return {
        "driver_id": driver_id,
        "driver_info": driver_info,
        "laps": laps,
        "best_lap": best_lap,
        "best_sectors": best_sectors,
    }


def _parse_lap_line(line: str) -> dict | None:
    import re
    m = re.search(r'\.L(\d+)#([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)', line)
    if not m:
        return None
    lap_num = int(m.group(1))
    if lap_num == 0:
        return None

    def decode(s):
        is_best = s.startswith("g")
        is_pit = s.startswith("p")
        raw = s.lstrip("gp")
        return {"time_ms": int(raw) if raw.isdigit() else 0, "best": is_best, "pit": is_pit}

    s1 = decode(m.group(2))
    s2 = decode(m.group(3))
    s3 = decode(m.group(4))
    total = decode(m.group(5))

    return {
        "lap_number": lap_num,
        "s1_ms": s1["time_ms"], "s1_best": s1["best"],
        "s2_ms": s2["time_ms"], "s2_best": s2["best"],
        "s3_ms": s3["time_ms"], "s3_best": s3["best"],
        "total_ms": total["time_ms"], "total_best": total["best"],
        "is_pit": s1["pit"] or total["pit"],
    }


def _parse_time(s: str) -> int:
    s = s.strip()
    return int(s) if s.isdigit() else 0


def _parse_driver_inf(xml: str) -> dict:
    import re
    result = {"team": "", "kart": "", "club": "", "drivers": []}
    m = re.search(r'num="(\d+)"[^>]*name="([^"]+)"', xml)
    if m:
        result["kart"] = m.group(1)
        result["team"] = m.group(2)
    club = re.search(r'type="club"[^>]*value="([^"]+)"', xml)
    if club:
        result["club"] = club.group(1)
    for drv in re.finditer(r'<driver[^>]*id="(\d+)"[^>]*num="(\d+)"[^>]*name="([^"]+)"', xml):
        result["drivers"].append({
            "id": drv.group(1), "num": drv.group(2), "name": drv.group(3),
            "current": 'current="1"' in drv.group(0),
        })
    return result
