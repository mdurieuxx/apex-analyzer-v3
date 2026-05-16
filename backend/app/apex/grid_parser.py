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
    last_lap_class: str = ""
    category: str = ""      # detected from CSS class or name pattern


@dataclass
class ColumnMap:
    """Maps driver field names to Apex Timing grid column indices.

    Defaults match Karting de Saintes racing layout.
    Auto-detected from grid header on connect; falls back to defaults.
    """
    position:  int = 2
    kart:      int = 3
    team:      int = 4
    gap:       int = 5
    interval:  int = 6
    s1:        int = 7
    s2:        int = 8
    s3:        int = 9
    last_lap:  int = 10
    best_lap:  int = 11
    on_track:  int = 12
    pits:      int = 13
    penalty:   int = 14

    def reverse(self) -> dict[int, str]:
        return {v: k for k, v in self.__dict__.items()}


# Keywords (lowercase) that identify each column from its header text
_HEADER_KEYWORDS: dict[str, list[str]] = {
    "position": ["pos", "place"],
    "kart":     ["kart", "num", "n°", "no.", "bib"],
    "team":     ["équipe", "equipe", "team", "driver", "pilote"],
    "gap":      ["gap", "écart", "ecart"],
    "interval": ["int.", "interval"],
    "s1":       ["s1", "sect 1", "sect.1"],
    "s2":       ["s2", "sect 2", "sect.2"],
    "s3":       ["s3", "sect 3", "sect.3"],
    "last_lap": ["dernier tour", "last lap", "last time", "dernier", "last"],
    "best_lap": ["meilleur tour", "best lap", "best time", "meilleur", "best"],
    "laps":     ["tours", "laps", "nb tour"],
    "pits":     ["stands", "pits", "pit"],
    "penalty":  ["pénalité", "penalite", "penalty"],
}


def _match_header(text: str) -> Optional[str]:
    t = text.lower().strip()
    # Sort by descending keyword length so more-specific patterns win first
    for field_name, keywords in _HEADER_KEYWORDS.items():
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in t:
                return field_name
    return None


def detect_column_map(html: str) -> ColumnMap:
    """
    Parse the header row of the Apex Timing grid to detect column positions.
    Falls back to hardcoded defaults (Karting de Saintes format) if not found.
    """
    defaults = ColumnMap()

    head_m = re.search(r'<tr[^>]*\bhead\b[^>]*>([\s\S]*?)</tr>', html, re.IGNORECASE)
    if not head_m:
        return defaults

    head_html = head_m.group(1)
    detected: dict[str, int] = {}

    # Method 1: cells have data-id="r*c{N}" → direct column number
    for cell_m in re.finditer(
        r'data-id="r\d+c(\d+)"[^>]*>([\s\S]*?)(?=<(?:td|th|/tr))', head_html, re.IGNORECASE
    ):
        col_num = int(cell_m.group(1))
        cell_text = re.sub(r'<[^>]+>', '', cell_m.group(2)).strip()
        if cell_text:
            fn = _match_header(cell_text)
            if fn and fn not in detected:
                detected[fn] = col_num

    # Method 2: no data-id — count th/td cells positionally (1-based)
    if not detected:
        cells = re.findall(r'<t[hd][^>]*>([\s\S]*?)</t[hd]>', head_html, re.IGNORECASE)
        for idx, cell_content in enumerate(cells, start=1):
            cell_text = re.sub(r'<[^>]+>', '', cell_content).strip()
            fn = _match_header(cell_text)
            if fn and fn not in detected:
                detected[fn] = idx

    if not detected:
        return defaults

    return ColumnMap(
        position = detected.get("position", defaults.position),
        kart     = detected.get("kart",     defaults.kart),
        team     = detected.get("team",     defaults.team),
        gap      = detected.get("gap",      defaults.gap),
        interval = detected.get("interval", defaults.interval),
        s1       = detected.get("s1",       defaults.s1),
        s2       = detected.get("s2",       defaults.s2),
        s3       = detected.get("s3",       defaults.s3),
        last_lap = detected.get("last_lap", defaults.last_lap),
        best_lap = detected.get("best_lap", defaults.best_lap),
        on_track = detected.get("on_track", defaults.on_track),
        pits     = detected.get("pits",     defaults.pits),
        penalty  = detected.get("penalty",  defaults.penalty),
    )


# CSS class names that belong to lap timing, not team categories
_TIMING_CLASSES = {"best", "sb", "pb", "improved", "last", "head", "odd", "even", ""}

# Pattern matching category prefixes in team names: "1 - Name", "A. Name", "2: Name", etc.
_CAT_NAME_RE = re.compile(r'^([A-Za-z0-9]{1,3})\s*[-.:)]\s+(.+)$')


def _extract_cell_class(tag_soup: str, row_id: str, col: int) -> str:
    """Return the first non-timing CSS class from a cell's opening tag."""
    m = re.search(
        rf'<t[hd]([^>]*data-id="r{row_id}c{col}"[^>]*)>',
        tag_soup, re.IGNORECASE,
    )
    if not m:
        return ""
    class_m = re.search(r'class="([^"]*)"', m.group(1), re.IGNORECASE)
    if not class_m:
        return ""
    classes = [c for c in class_m.group(1).split() if c not in _TIMING_CLASSES]
    return classes[0] if classes else ""


def _detect_categories(drivers: dict[str, LiveDriver], html: str, col_map: ColumnMap) -> None:
    """
    Assign a category string to each driver.

    Method 1 — CSS class on the kart-number cell: if two or more distinct
    non-timing classes appear on that column, each class is a category.

    Method 2 — Name prefix pattern (fallback): if ≥60 % of team names match
    a leading token like "1 - Name" or "A. Name", use that token.
    """
    if not drivers:
        return

    row_re = re.compile(r'<tr[^>]*data-id="r(\d+)"[^>]*>([\s\S]*?)</tr>', re.IGNORECASE)

    # --- Method 1 ---
    css_by_driver: dict[str, str] = {}
    for m in row_re.finditer(html):
        row_id, row_html = m.group(1), m.group(2)
        if row_id not in drivers:
            continue
        css = _extract_cell_class(row_html, row_id, col_map.kart)
        if css:
            css_by_driver[row_id] = css

    if len(set(css_by_driver.values())) >= 2:
        for row_id, css in css_by_driver.items():
            drivers[row_id].category = css
        return

    # --- Method 2 ---
    prefix_by_driver: dict[str, str] = {}
    for row_id, d in drivers.items():
        pm = _CAT_NAME_RE.match(d.team)
        if pm:
            prefix_by_driver[row_id] = pm.group(1)

    if len(prefix_by_driver) >= len(drivers) * 0.6:
        for row_id, prefix in prefix_by_driver.items():
            drivers[row_id].category = prefix


def parse_grid_html(html: str) -> tuple[dict[str, LiveDriver], ColumnMap]:
    """
    Parse the initial full-grid HTML dump sent on WebSocket connect.
    Driver names and kart numbers ONLY appear in this initial dump.
    Returns (drivers dict, detected ColumnMap).
    """
    col_map = detect_column_map(html)
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

        _cell(row_html, row_id, col_map.position,  lambda v: setattr(d, "position", int(v)) if v.isdigit() else None)
        _cell(row_html, row_id, col_map.kart,      lambda v: setattr(d, "kart", v))
        _cell(row_html, row_id, col_map.team,      lambda v: setattr(d, "team", _clean_team(v)))
        _cell(row_html, row_id, col_map.gap,       lambda v: setattr(d, "gap", v))
        _cell(row_html, row_id, col_map.interval,  lambda v: setattr(d, "interval", v))
        _cell(row_html, row_id, col_map.s1,        lambda v: setattr(d, "s1", v))
        _cell(row_html, row_id, col_map.s2,        lambda v: setattr(d, "s2", v))
        _cell(row_html, row_id, col_map.s3,        lambda v: setattr(d, "s3", v))
        _cell(row_html, row_id, col_map.last_lap,  lambda v: setattr(d, "last_lap", v))
        _cell(row_html, row_id, col_map.best_lap,  lambda v: setattr(d, "best_lap", v))
        _cell(row_html, row_id, col_map.on_track,  lambda v: setattr(d, "on_track", v))
        _cell(row_html, row_id, col_map.pits,      lambda v: setattr(d, "pits", int(v)) if v.isdigit() else None)
        _cell(row_html, row_id, col_map.penalty,   lambda v: setattr(d, "penalty", v))

        # laps count: prefer CSS-class based detection (more robust across layouts)
        laps_m = re.search(r'class="[^"]*laps[^"]*"[^>]*>(\d+)', row_html, re.IGNORECASE)
        if laps_m:
            d.laps = int(laps_m.group(1))

        if d.kart or d.team:
            drivers[row_id] = d

    _detect_categories(drivers, html, col_map)
    return drivers, col_map


def apply_update(
    drivers: dict[str, LiveDriver],
    element_id: str,
    css_class: str,
    raw_val: str,
    col_map: Optional[ColumnMap] = None,
) -> Optional[tuple[str, int]]:
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
    cm = col_map or ColumnMap()

    if col == cm.position and val.isdigit():
        d.position = int(val)
    elif col == cm.gap:
        d.gap = val
    elif col == cm.interval:
        d.interval = val
    elif col == cm.s1:
        d.s1 = val
    elif col == cm.s2:
        d.s2 = val
    elif col == cm.s3:
        d.s3 = val
    elif col == cm.last_lap:
        d.last_lap = val
        d.last_lap_class = css_class
    elif col == cm.best_lap:
        d.best_lap = val
    elif col == cm.on_track:
        d.on_track = val
    elif col == cm.pits and val.isdigit():
        new_pits = int(val)
        if new_pits > d.pits:
            old = d.pits
            d.pits = new_pits
            return (row_id, old)
        d.pits = new_pits
    elif col == cm.penalty:
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
