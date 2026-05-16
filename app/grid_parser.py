import re
import logging
from html.parser import HTMLParser
from models import Driver

logger = logging.getLogger(__name__)


def parse_grid_html(html: str) -> dict[str, Driver]:
    """
    Parse the initial full-grid HTML dump sent by Apex Timing on WebSocket connect.
    Each row has data-id="r{N}" and cells have data-id="r{N}c{M}".
    Column mapping (standard Apex layout):
      c2=position  c3=kart  c4=team  c5=gap  c6=interval
      c7=s1  c8=s2  c9=s3  c10=last_lap  c11=best_lap
      c12=on_track  c13=pits  c14=penalty
    Driver names/kart numbers appear ONLY in this initial dump, not in incremental updates.
    """
    drivers: dict[str, Driver] = {}
    row_re = re.compile(r'<tr[^>]*data-id="r(\d+)"[^>]*>([\s\S]*?)</tr>', re.IGNORECASE)

    for row_m in row_re.finditer(html):
        row_id = row_m.group(1)
        row_html = row_m.group(2)

        if row_id == "0" or 'class="head"' in row_html:
            continue

        driver = Driver(driver_id=row_id)

        pos_attr = re.search(r'data-pos="(\d+)"', row_m.group(0))
        if pos_attr:
            driver.position = int(pos_attr.group(1))

        _extract_cell(row_html, row_id, 2, lambda v: setattr(driver, "position", int(v)) if v.isdigit() else None)
        _extract_cell(row_html, row_id, 3, lambda v: setattr(driver, "kart", v))
        _extract_cell(row_html, row_id, 4, lambda v: setattr(driver, "team", _clean_team(v)))
        _extract_cell(row_html, row_id, 5, lambda v: setattr(driver, "gap", v))
        _extract_cell(row_html, row_id, 6, lambda v: setattr(driver, "interval", v))
        _extract_cell(row_html, row_id, 7, lambda v: setattr(driver, "s1", v))
        _extract_cell(row_html, row_id, 8, lambda v: setattr(driver, "s2", v))
        _extract_cell(row_html, row_id, 9, lambda v: setattr(driver, "s3", v))
        _extract_cell(row_html, row_id, 10, lambda v: setattr(driver, "last_lap", v))
        _extract_cell(row_html, row_id, 11, lambda v: setattr(driver, "best_lap", v))
        _extract_cell(row_html, row_id, 12, lambda v: setattr(driver, "on_track", v))
        _extract_cell(row_html, row_id, 13, lambda v: setattr(driver, "pits", int(v)) if v.isdigit() else None)
        _extract_cell(row_html, row_id, 14, lambda v: setattr(driver, "penalty", v))

        if driver.kart or driver.team:
            drivers[row_id] = driver

    return drivers


def apply_cell_update(drivers: dict[str, Driver], element_id: str, css_class: str, value: str) -> tuple[str, int] | None:
    """
    Apply an incremental r{N}c{M} update to the driver state.
    Returns (driver_id, old_pit_count) if a pit count change is detected, else None.
    """
    m = re.match(r'^r(\d+)c(\d+)$', element_id)
    if not m:
        return None

    row_id, col = m.group(1), int(m.group(2))
    driver = drivers.get(row_id)
    if not driver:
        return None

    clean = _strip_tags(value)

    if col == 2:
        if clean.isdigit():
            driver.position = int(clean)
    elif col == 5:
        driver.gap = clean
    elif col == 6:
        driver.interval = clean
    elif col == 7:
        driver.s1 = clean
    elif col == 8:
        driver.s2 = clean
    elif col == 9:
        driver.s3 = clean
    elif col == 10:
        driver.last_lap = clean
    elif col == 11:
        driver.best_lap = clean
    elif col == 12:
        driver.on_track = clean
    elif col == 13:
        if clean.isdigit():
            old_pits = driver.pits
            new_pits = int(clean)
            if new_pits > old_pits:
                driver.pits = new_pits
                return (row_id, old_pits)
            driver.pits = new_pits
    elif col == 14:
        driver.penalty = clean

    return None


def _extract_cell(row_html: str, row_id: str, col: int, setter):
    pattern = rf'data-id="r{row_id}c{col}"[^>]*>([^<]*)'
    m = re.search(pattern, row_html, re.IGNORECASE)
    if m:
        val = _strip_tags(m.group(1)).strip()
        if val:
            try:
                setter(val)
            except Exception:
                pass


def _strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _clean_team(name: str) -> str:
    # Remove trailing bracket annotations like " [Team A]"
    return re.sub(r'\s*\[[^\]]*\]\s*$', '', name).strip()


def parse_comments(html: str) -> list[dict]:
    """Parse the <b>MM:SS</b> comment blocks sent in 'com' messages."""
    comments = []
    if not html:
        return comments

    clean = re.sub(r'</?p>', '', html, flags=re.IGNORECASE)
    blocks = re.split(r'<b>', clean, flags=re.IGNORECASE)

    for block in blocks:
        m = re.match(r'^(\d{1,2}:\d{2})</b>(.*)', block, re.DOTALL | re.IGNORECASE)
        if not m:
            continue
        time_str = m.group(1)
        content = _strip_tags(m.group(2)).strip()
        if not content:
            continue
        kart_m = re.match(r'^(\d{1,3})\s+(.+)$', content)
        if kart_m:
            comments.append({"time": time_str, "kart": kart_m.group(1), "text": kart_m.group(2).strip()})
        else:
            comments.append({"time": time_str, "text": content})

    return comments
