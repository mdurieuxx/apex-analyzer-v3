"""
Proposition de réécriture de apex/lap_api.py.

Corrections :
- port = configPort directement (pas ws_port - 3)
- fetch_all_laps() : récupère la totalité des tours (pas seulement 30)
- fetch_team_stats() : pit stops + attribution pilotes
- get_laps_per_driver() : croise pits × tours
"""

import re
import logging
import httpx

logger = logging.getLogger(__name__)

_ENDPOINT = "https://live-data.apex-timing.com/live-timing/commonv2/functions/request.php"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://www.apex-timing.com",
}


async def _post(circuit_url: str, port: int, request: str) -> str:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            _ENDPOINT,
            data={"port": str(port), "request": request},
            headers={**_HEADERS, "Referer": circuit_url},
        )
        r.raise_for_status()
        return r.text


async def fetch_driver_laps(circuit_url: str, config_port: int, driver_id: str) -> dict:
    """
    Remplace l'ancienne signature fetch_driver_laps(circuit_url, ws_port, driver_id).
    BREAKING CHANGE : config_port = configPort (WS port direct, ex: 8600).
    L'ancien code faisait ws_port - 3, ce qui était incorrect pour Brignoles.
    """
    req = f"D#-30#D{driver_id}.L#-999#D{driver_id}.BL#-999#D{driver_id}.BS#1#D{driver_id}.INF"
    try:
        text = await _post(circuit_url, config_port, req)
        return _parse(text, driver_id)
    except Exception as e:
        logger.error("lap_api %s: %s", driver_id, e)
        return {"error": str(e)}


async def fetch_all_laps(circuit_url: str, config_port: int, driver_id: str) -> dict:
    """
    Récupère la totalité des tours d'une équipe.
    Étape 1 : récupère le total de tours via D#-1#D{id}.L
    Étape 2 : récupère total+50 tours d'un coup.
    """
    try:
        count_text = await _post(circuit_url, config_port, f"D#-1#D{driver_id}.L")
        total = _parse_lap_count(count_text, driver_id)
        if total == 0:
            return {"driver_id": driver_id, "laps": [], "total_laps": 0}

        full_text = await _post(
            circuit_url, config_port,
            f"D#-{total + 50}#D{driver_id}.L#-999#D{driver_id}.BL#1#D{driver_id}.INF"
        )
        return _parse(full_text, driver_id)
    except Exception as e:
        logger.error("lap_api full %s: %s", driver_id, e)
        return {"error": str(e)}


async def fetch_team_stats(circuit_url: str, config_port: int, driver_id: str) -> dict:
    """
    Retourne pit stops + infos pilotes + attribution tours par pilote.
    """
    try:
        text = await _post(
            circuit_url, config_port,
            f"D#-999#D{driver_id}.P#1#D{driver_id}.INF"
        )
        pits, driver_info = _parse_pits_and_inf(text, driver_id)

        count_text = await _post(circuit_url, config_port, f"D#-1#D{driver_id}.L")
        total = _parse_lap_count(count_text, driver_id)

        laps_text = await _post(
            circuit_url, config_port,
            f"D#-{total + 50}#D{driver_id}.L"
        )
        laps = _parse_laps_raw(laps_text, driver_id)

        laps_per_driver = get_laps_per_driver(pits, laps)
        return {
            "driver_id": driver_id,
            "driver_info": driver_info,
            "pit_stops": pits,
            "laps": laps,
            "laps_per_driver": laps_per_driver,
            "total_laps": total,
        }
    except Exception as e:
        logger.error("lap_api stats %s: %s", driver_id, e)
        return {"error": str(e)}


# ── Parsers ──────────────────────────────────────────────────────────────────

def _parse_lap_count(text: str, driver_id: str) -> int:
    for line in text.splitlines():
        m = re.search(rf'D{driver_id}\.L(\d+)#', line)
        if m:
            return int(m.group(1))
    return 0


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
            parts = line.split("#", 1)[1].split("|")
            if len(parts) >= 4:
                best_lap = {k: _t(v) for k, v in zip(("s1_ms", "s2_ms", "s3_ms", "total_ms"), parts)}
        elif f"D{driver_id}.BS#" in line:
            parts = line.split("#", 1)[1].split("|")
            if len(parts) >= 3:
                best_sectors = {k: _t(v) for k, v in zip(("s1_ms", "s2_ms", "s3_ms"), parts)}
        elif f"D{driver_id}.INF#" in line:
            driver_info = _parse_inf(line.split(".INF#", 1)[1])
    laps.sort(key=lambda x: x["lap_number"], reverse=True)
    return {
        "driver_id": driver_id, "driver_info": driver_info,
        "laps": laps, "best_lap": best_lap, "best_sectors": best_sectors,
    }


def _parse_laps_raw(text: str, driver_id: str) -> list[dict]:
    laps = []
    for line in text.splitlines():
        if f"D{driver_id}.L" in line and "#" in line:
            lap = _parse_lap(line)
            if lap:
                laps.append(lap)
    laps.sort(key=lambda x: x["lap_number"])
    return laps


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


def _parse_pits_and_inf(text: str, driver_id: str) -> tuple[list[dict], dict]:
    pits = []
    driver_info = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if f"D{driver_id}.P" in line and "#" in line:
            pit = _parse_pit(line)
            if pit:
                pits.append(pit)
        elif f"D{driver_id}.INF#" in line:
            driver_info = _parse_inf(line.split(".INF#", 1)[1])

    # Réponse en ordre décroissant → inverser pour avoir ordre chronologique
    pits.sort(key=lambda p: p["pit_number"])
    return pits, driver_info


def _parse_pit(line: str) -> dict | None:
    # Format: D{id}.P{n}#{pit_n}|{lap}|{in_ms}|{out_ms}|{pit_dur_ms}|{track_ms}|{relay_laps}|{driver_id}|{driver_total_ms}
    m = re.search(r'\.P(\d+)#(.+)', line)
    if not m:
        return None
    pit_num = int(m.group(1))
    fields = m.group(2).split("|")
    if len(fields) < 9:
        return None
    return {
        "pit_number": pit_num,
        "lap": _t(fields[1]),
        "in_ms": _t(fields[2]),
        "out_ms": _t(fields[3]),
        "pit_duration_ms": _t(fields[4]),
        "track_ms": _t(fields[5]),
        "relay_laps": _t(fields[6]),
        "driver_id": fields[7].strip(),
        "driver_total_ms": _t(fields[8]),
    }


def get_laps_per_driver(pits: list[dict], laps: list[dict]) -> dict[str, list[dict]]:
    """
    Attribue chaque tour à un pilote en croisant les pit stops.
    Pits doit être trié par pit_number croissant.
    Laps doit être trié par lap_number croissant.

    Formule : le pilote P du pit N a fait les tours [prev_end+1 .. prev_end+relay_laps]
    """
    laps_by_num = {lap["lap_number"]: lap for lap in laps}
    result: dict[str, list[dict]] = {}

    prev_end = 0
    for pit in pits:
        driver_id = pit["driver_id"]
        start = prev_end + 1
        end = prev_end + pit["relay_laps"]
        driver_laps = [laps_by_num[n] for n in range(start, end + 1) if n in laps_by_num]
        result.setdefault(driver_id, []).extend(driver_laps)
        prev_end = end

    return result


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


def _t(s: str) -> int:
    s = s.strip()
    return int(s) if s.isdigit() else 0
