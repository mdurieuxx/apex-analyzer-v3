import re
from dataclasses import dataclass
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
    category: str = ""      # detected from CSS class or name prefix
    driver_name: str = ""   # current driver (if grid has a driver column)
    last_lap_ms: int = 0              # last lap time in ms (from * signal, 0 if unknown)
    last_lap_received_at: float = 0.0 # unix timestamp (s) when last_lap_ms was set


@dataclass
class ColumnMap:
    """Maps driver field names to Apex Timing grid column indices.

    0 = column not present in this grid.
    Populated by detect_column_map(); non-zero defaults are last-resort
    fallback for grids where no header row is found.
    """
    position:  int = 2
    kart:      int = 3
    team:      int = 4
    gap:       int = 5
    interval:  int = 0
    s1:        int = 0
    s2:        int = 0
    s3:        int = 0
    last_lap:  int = 10
    best_lap:  int = 11
    laps:      int = 0
    on_track:  int = 0
    pits:      int = 0
    penalty:   int = 0
    driver:    int = 0

    def reverse(self) -> dict[int, str]:
        return {v: k for k, v in self.__dict__.items() if v != 0}


# Apex Timing data-type attribute → field name (most reliable detection method)
_DATA_TYPE_MAP: dict[str, str] = {
    "rk":  "position",
    "no":  "kart",
    "dr":  "team",
    "drv": "driver",
    "llp": "last_lap",
    "blp": "best_lap",
    "gap": "gap",
    "int": "interval",
    "s1":  "s1",
    "s2":  "s2",
    "s3":  "s3",
    "tlp": "laps",
    "otr": "on_track",
    "pit": "pits",
    "pen": "penalty",
}

# Keywords (lowercase) that identify each column from its header text (fallback)
_HEADER_KEYWORDS: dict[str, list[str]] = {
    "position": ["pos", "place", "clt", "cl.", "classement", "rk", "rank"],
    "kart":     ["kart", "num", "n°", "no.", "bib"],
    "team":     ["équipe", "equipe", "team"],
    "driver":   ["pilote", "driver", "nom pilote", "pilotes"],
    "gap":      ["gap", "écart", "ecart", "distacco"],
    "interval": ["int.", "interval", "interv."],
    "s1":       ["s1", "sect 1", "sect.1"],
    "s2":       ["s2", "sect 2", "sect.2"],
    "s3":       ["s3", "sect 3", "sect.3"],
    "last_lap": ["dernier tour", "last lap", "last time", "dernier", "ultimo", "last"],
    "best_lap": ["meilleur tour", "best lap", "best time", "meilleur", "migliore", "giro mig", "best"],
    "laps":     ["tours", "laps", "nb tour", "giri", "tlp"],
    "on_track": ["en piste", "in pista", "on track", "pista"],
    "pits":     ["stands", "pits", "pit stop", "pit"],
    "penalty":  ["pénalité", "penalite", "penalty", "péna", "pena"],
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
    Parse the Apex Timing grid header to detect column positions.

    Detection order (first match wins per field):
      Method 0 — data-id="c{N}" + data-type attribute (all known circuits)
      Method 1 — data-id="r{row}c{N}" with text matching (legacy fallback)
      Method 2 — positional th/td counting with text matching (last resort)

    Falls back to ColumnMap() defaults only when no header row is found.
    When a header is found, absent optional fields are set to 0 (not present).
    """
    defaults = ColumnMap()

    head_m = re.search(r'<tr[^>]*\bhead\b[^>]*>([\s\S]*?)</tr>', html, re.IGNORECASE)
    if not head_m:
        return defaults

    head_html = head_m.group(1)
    detected: dict[str, int] = {}

    # Method 0: data-id="c{N}" + data-type (standard Apex Timing format)
    for cell_m in re.finditer(r'<td[^>]*>', head_html, re.IGNORECASE):
        tag = cell_m.group(0)
        id_m = re.search(r'data-id="c(\d+)"', tag, re.IGNORECASE)
        type_m = re.search(r'data-type="([^"]*)"', tag, re.IGNORECASE)
        if id_m and type_m:
            col_num = int(id_m.group(1))
            fn = _DATA_TYPE_MAP.get(type_m.group(1).lower())
            if fn and fn not in detected:
                detected[fn] = col_num

    # Method 1: data-id="r{row}c{N}" with header text
    if not detected:
        for cell_m in re.finditer(
            r'data-id="r\d+c(\d+)"[^>]*>([\s\S]*?)(?=<(?:td|th|/tr))', head_html, re.IGNORECASE
        ):
            col_num = int(cell_m.group(1))
            cell_text = re.sub(r'<[^>]+>', '', cell_m.group(2)).strip()
            if cell_text:
                fn = _match_header(cell_text)
                if fn and fn not in detected:
                    detected[fn] = col_num

    # Method 2: positional counting with text (last resort)
    if not detected:
        cells = re.findall(r'<t[hd][^>]*>([\s\S]*?)</t[hd]>', head_html, re.IGNORECASE)
        for idx, cell_content in enumerate(cells, start=1):
            cell_text = re.sub(r'<[^>]+>', '', cell_content).strip()
            fn = _match_header(cell_text)
            if fn and fn not in detected:
                detected[fn] = idx

    if not detected:
        return defaults

    # Mandatory fields fall back to defaults; optional fields default to 0 (absent)
    return ColumnMap(
        position = detected.get("position", defaults.position),
        kart     = detected.get("kart",     defaults.kart),
        team     = detected.get("team",     defaults.team),
        last_lap = detected.get("last_lap", defaults.last_lap),
        best_lap = detected.get("best_lap", defaults.best_lap),
        gap      = detected.get("gap",      0),
        interval = detected.get("interval", 0),
        s1       = detected.get("s1",       0),
        s2       = detected.get("s2",       0),
        s3       = detected.get("s3",       0),
        laps     = detected.get("laps",     0),
        on_track = detected.get("on_track", 0),
        pits     = detected.get("pits",     0),
        penalty  = detected.get("penalty",  0),
        driver   = detected.get("driver",   0),
    )


# CSS class names that belong to lap timing, not team categories
_TIMING_CLASSES = {"best", "sb", "pb", "improved", "last", "head", "odd", "even", ""}

# Pattern matching category prefixes in team names: "1 - Name", "A. Name", "2: Name", etc.
_CAT_NAME_RE = re.compile(r'^([A-Za-z0-9]{1,3})\s*[-.:)]\s+(.+)$')

# Trailing [M:SS] suffix sent by the server in drteam updates: "MORIN Grégory [0:35]"
_DRIVER_TIME_RE = re.compile(r'\s*\[\d+:\d{2}\]\s*$')


def _extract_cell_class(tag_soup: str, row_id: str, col: int) -> str:
    """Return the first non-timing CSS class for the cell identified by data-id.

    data-id may be on the <td> itself or on an inner <div>/<p>. We search
    backward to the opening tag boundary, then forward to its closing '>',
    so attributes both before and after data-id are captured.
    """
    attr_m = re.search(
        rf'data-id="r{row_id}c{col}"',
        tag_soup, re.IGNORECASE,
    )
    if not attr_m:
        return ""
    tag_start = tag_soup.rfind('<', 0, attr_m.start())
    if tag_start == -1:
        return ""
    tag_end = tag_soup.find('>', attr_m.end())
    if tag_end == -1:
        return ""
    full_tag = tag_soup[tag_start:tag_end + 1]
    class_m = re.search(r'class="([^"]*)"', full_tag, re.IGNORECASE)
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
        if col_map.driver:
            _cell(row_html, row_id, col_map.driver, lambda v: setattr(d, "driver_name", _clean_team(v)))
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

        # Laps: try dedicated column first, then CSS-class "laps" fallback
        if col_map.laps:
            _cell(row_html, row_id, col_map.laps, lambda v: setattr(d, "laps", n) if (n := _parse_laps(v)) is not None else None)
        if not d.laps:
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
    # to = current state chrono (on-track time or pit time) — update on_track, skip full chain
    if css_class == "to":
        tm = re.match(r'^r(\d+)c\d+$', element_id)
        if tm:
            d = drivers.get(tm.group(1))
            if d:
                d.on_track = _strip(raw_val)
        return None

    m = re.match(r'^r(\d+)c(\d+)$', element_id)
    if not m:
        return None

    row_id, col = m.group(1), int(m.group(2))
    d = drivers.get(row_id)
    if not d:
        return None

    val = _strip(raw_val)
    cm = col_map or ColumnMap()

    # Kart number + category change: rNcX|notc65535|21 or rNcX|no1|14
    if css_class.startswith("notc") or (
        css_class.startswith("no") and len(css_class) > 2 and css_class[2:].isdigit()
    ):
        d.category = css_class
        if val:
            d.kart = val
        return None

    if col == cm.position and val.isdigit():
        d.position = int(val)
    elif col == cm.last_lap:
        d.last_lap = val
        d.last_lap_class = css_class
    elif col == cm.best_lap:
        d.best_lap = val
    elif col == cm.pits and val.isdigit():
        new_pits = int(val)
        if new_pits > d.pits:
            old = d.pits
            d.pits = new_pits
            return (row_id, old)
        d.pits = new_pits
    elif col == cm.team:
        if css_class == "drteam":
            # Driver name with relay time: "MORIN Grégory [0:35]" → strip [M:SS]
            d.driver_name = _DRIVER_TIME_RE.sub('', _strip(raw_val)).strip()
        elif css_class == "dr" and val:
            # Team name refresh after session reset — apply it
            d.team = val
    elif cm.driver and col == cm.driver:
        d.driver_name = _clean_team(val)
    elif cm.gap and col == cm.gap:
        d.gap = val
    elif cm.interval and col == cm.interval:
        d.interval = val
    elif cm.s1 and col == cm.s1:
        d.s1 = val
    elif cm.s2 and col == cm.s2:
        d.s2 = val
    elif cm.s3 and col == cm.s3:
        d.s3 = val
    elif cm.laps and col == cm.laps:
        if (n := _parse_laps(val)) is not None:
            d.laps = n
    elif cm.on_track and col == cm.on_track:
        d.on_track = val
    elif cm.penalty and col == cm.penalty:
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


def _parse_laps(val: str) -> Optional[int]:
    if val.isdigit():
        return int(val)
    if val == "0:00":  # Apex resets laps to "0:00" at race start
        return 0
    return None


def _strip(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text).strip()


def _clean_team(name: str) -> str:
    return re.sub(r'\s*\[[^\]]*\]\s*$', '', name).strip()


def canonical_team_name(name: str) -> str:
    """Strip category prefix (e.g. '1 - ', '2 - ', 'A. ') for cross-event stats matching.

    Display names keep the prefix; only use this for DB keys and ranker lookups.
    """
    m = _CAT_NAME_RE.match(name)
    return m.group(2).strip() if m else name
