import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class LiveDriver:
    driver_id: str
    position: int = 0
    kart: str = ""
    team: str = ""
    gap: str = ""
    interval: str = ""
    s1: str = ""
    s2: str = ""
    s3: str = ""
    last_lap: str = ""
    best_lap: str = ""
    laps: int = 0
    on_track: str = ""
    pits: int = 0
    penalty: str = ""
    # CSS class of last_lap cell — "best" | "improved" | ""
    last_lap_class: str = ""


def parse_grid_html(html: str) -> dict[str, LiveDriver]:
    """
    Parse the initial full-grid HTML dump sent on WebSocket connect.
    Driver names and kart numbers ONLY appear in this initial dump.
    """
    drivers: dict[str, LiveDriver] = {}
    row_re = re.compile(r'<tr[^>]*data-id="r(\d+)"[^>]*>([\s\S]*?)</tr>', re.IGNORECASE)

    for row_m in row_re.finditer(html):
        row_id = row_m.group(1)
        row_html = row_m.group(2)

        if row_id == "0" or 'class="head"' in row_html:
            continue

        d = LiveDriver(driver_id=row_id)

        pos_attr = re.search(r'data-pos="(\d+)"', row_m.group(0))
        if pos_attr:
            d.position = int(pos_attr.group(1))

        _cell(row_html, row_id, 2,  lambda v: setattr(d, "position", int(v)) if v.isdigit() else None)
        _cell(row_html, row_id, 3,  lambda v: setattr(d, "kart", v))
        _cell(row_html, row_id, 4,  lambda v: setattr(d, "team", _clean_team(v)))
        _cell(row_html, row_id, 5,  lambda v: setattr(d, "gap", v))
        _cell(row_html, row_id, 6,  lambda v: setattr(d, "interval", v))
        _cell(row_html, row_id, 7,  lambda v: setattr(d, "s1", v))
        _cell(row_html, row_id, 8,  lambda v: setattr(d, "s2", v))
        _cell(row_html, row_id, 9,  lambda v: setattr(d, "s3", v))
        _cell(row_html, row_id, 10, lambda v: setattr(d, "last_lap", v))
        _cell(row_html, row_id, 11, lambda v: setattr(d, "best_lap", v))
        _cell(row_html, row_id, 12, lambda v: setattr(d, "on_track", v))
        _cell(row_html, row_id, 13, lambda v: setattr(d, "pits", int(v)) if v.isdigit() else None)
        _cell(row_html, row_id, 14, lambda v: setattr(d, "penalty", v))

        # laps may be in a differently numbered column — search by class
        laps_m = re.search(r'class="[^"]*laps[^"]*"[^>]*>(\d+)', row_html, re.IGNORECASE)
        if laps_m:
            d.laps = int(laps_m.group(1))

        if d.kart or d.team:
            drivers[row_id] = d

    return drivers


def apply_update(drivers: dict[str, LiveDriver], element_id: str, css_class: str, raw_val: str) -> Optional[tuple[str, int]]:
    """
    Apply one r{N}c{M} incremental update.
    Returns (driver_id, old_pit_count) when a pit stop is detected, else None.
    """
    m = re.match(r'^r(\d+)c(\d+)$', element_id)
    if not m:
        return None

    row_id, col = m.group(1), int(m.group(2))
    d = drivers.get(row_id)
    if not d:
        return None

    val = _strip(raw_val)

    if col == 2 and val.isdigit():
        d.position = int(val)
    elif col == 5:
        d.gap = val
    elif col == 6:
        d.interval = val
    elif col == 7:
        d.s1 = val
    elif col == 8:
        d.s2 = val
    elif col == 9:
        d.s3 = val
    elif col == 10:
        d.last_lap = val
        d.last_lap_class = css_class
    elif col == 11:
        d.best_lap = val
    elif col == 12:
        d.on_track = val
    elif col == 13 and val.isdigit():
        new_pits = int(val)
        if new_pits > d.pits:
            old = d.pits
            d.pits = new_pits
            return (row_id, old)
        d.pits = new_pits
    elif col == 14:
        d.penalty = val

    return None


def parse_comments(html: str) -> list[dict]:
    comments = []
    if not html:
        return comments
    clean = re.sub(r'</?p>', '', html, flags=re.IGNORECASE)
    for block in re.split(r'<b>', clean, flags=re.IGNORECASE):
        m = re.match(r'^(\d{1,2}:\d{2})</b>(.*)', block, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        time_str = m.group(1)
        content = _strip(m.group(2)).strip()
        if not content:
            continue
        kart_m = re.match(r'^(\d{1,3})\s+(.+)$', content)
        if kart_m:
            comments.append({"time": time_str, "kart": kart_m.group(1), "text": kart_m.group(2).strip()})
        else:
            comments.append({"time": time_str, "text": content})
    return comments


def _cell(row_html: str, row_id: str, col: int, setter):
    pattern = rf'data-id="r{row_id}c{col}"[^>]*>([^<]*)'
    m = re.search(pattern, row_html, re.IGNORECASE)
    if m:
        val = _strip(m.group(1)).strip()
        if val:
            try:
                setter(val)
            except Exception:
                pass


def _strip(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _clean_team(name: str) -> str:
    return re.sub(r'\s*\[[^\]]*\]\s*$', '', name).strip()
