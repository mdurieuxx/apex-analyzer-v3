"""
Karting race calendar scrapers — sources for the daily discovery loop.

Each async scrape_*() returns list[RaceEvent] for events within LOOKAHEAD_DAYS.
"""
import asyncio
import hashlib
import html as _html
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

LOOKAHEAD_DAYS = 21

_HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
}

_MONTHS: dict[str, int] = {}
for _i, _k in enumerate(
    ["january","february","march","april","may","june",
     "july","august","september","october","november","december"], 1
):
    _MONTHS[_k] = _i
for _i, _k in enumerate(
    ["janvier","février","mars","avril","mai","juin",
     "juillet","août","septembre","octobre","novembre","décembre"], 1
):
    _MONTHS[_k] = _i
for _i, _k in enumerate(
    ["januari","februari","maart","april","mei","juni",
     "juli","augustus","september","oktober","november","december"], 1
):
    _MONTHS[_k] = _i


@dataclass
class RaceEvent:
    uid: str
    source: str
    circuit_name: str
    event_name: str
    start_dt: str           # ISO UTC
    end_dt: Optional[str]   # ISO UTC or None
    duration_h: float
    kart_type: str          # "4T 390cc", "Sodikart 4T", "2T Rotax" …
    country: str
    city: str
    source_url: str
    apex_url: Optional[str] = None
    apex_ws_port: Optional[int] = None
    scheduled_job_id: Optional[str] = None

    @staticmethod
    def uid_for(source: str, circuit: str, day: str) -> str:
        raw = f"{source}|{circuit}|{day}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _fetch_sync(url: str, timeout: int = 12) -> str:
    import gzip
    req = Request(url, headers=_HDRS)
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read()
            if r.info().get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace")
    except (URLError, HTTPError) as e:
        logger.debug("fetch %s: %s", url, e)
        return ""


async def _fetch(url: str) -> str:
    return await asyncio.get_event_loop().run_in_executor(None, _fetch_sync, url)


def _text(html: str) -> str:
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


# ── Date helpers ──────────────────────────────────────────────────────────────

def _utc(year: int, month: int, day: int, hour: int = 8, utc_offset: int = 2) -> Optional[datetime]:
    try:
        local = datetime(year, month, day, hour, 0, 0,
                         tzinfo=timezone(timedelta(hours=utc_offset)))
        return local.astimezone(timezone.utc)
    except ValueError:
        return None


def _in_window(dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=1) <= dt <= now + timedelta(days=LOOKAHEAD_DAYS)


def _year_for(month: int) -> int:
    now = datetime.now(timezone.utc)
    y = now.year
    if month < now.month - 1:
        y += 1
    return y


def _contains(text: str, *patterns: str) -> bool:
    return all(re.search(p, text, re.IGNORECASE) for p in patterns)


# ── Scrapers ──────────────────────────────────────────────────────────────────

async def scrape_francorchamps() -> list[RaceEvent]:
    """RACB Spa-Francorchamps — endurances & events."""
    URL = "https://www.francorchamps-karting.be/events-et-endurances.html"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    known = [
        # pattern, name, circuit, month, day, start_h, dur_h, kart
        (r"(?:13|14)\s*[-–]?\s*(?:14)?\s+(?:juin|june)",
         "24H Spa Sodikarts (SWS)", "Spa-Francorchamps", 6, 13, 12, 24.0, "Sodikart 4T"),
        (r"(?:500\s*km|nuit).*?(?:27\s+juin|juin\s+27)",
         "500km Nuit Spa", "Spa-Francorchamps", 6, 27, 20, 6.0, "Sodikart 4T"),
    ]
    for pat, name, circuit, month, day, h, dur, kart in known:
        if _contains(text, pat):
            year = _year_for(month)
            dt = _utc(year, month, day, h)
            if dt and _in_window(dt):
                uid = RaceEvent.uid_for("francorchamps", circuit, dt.date().isoformat())
                end = (dt + timedelta(hours=dur)).isoformat()
                events.append(RaceEvent(
                    uid=uid, source="francorchamps", circuit_name=circuit,
                    event_name=name, start_dt=dt.isoformat(), end_dt=end,
                    duration_h=dur, kart_type=kart,
                    country="Belgique", city="Spa", source_url=URL,
                ))

    return events


async def scrape_actua() -> list[RaceEvent]:
    """Actua Organisation — 24H Karting de Lyon."""
    URL = "https://www.actua-organisation.fr/evenements-et-trophees/endurance-karting/"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    if _contains(text, r"(?:juin|june)", r"(?:06|6|lyon)"):
        year = _year_for(6)
        dt = _utc(year, 6, 6, 12)
        if dt and _in_window(dt):
            end = _utc(year, 6, 7, 12)
            uid = RaceEvent.uid_for("actua", "Actua Karting Lyon", dt.date().isoformat())
            events.append(RaceEvent(
                uid=uid, source="actua", circuit_name="Actua Karting Lyon",
                event_name="24H Karting de Lyon", start_dt=dt.isoformat(),
                end_dt=end.isoformat() if end else None,
                duration_h=24.0, kart_type="390cc 4T",
                country="France", city="Saint Laurent de Mure", source_url=URL,
            ))

    return events


async def scrape_solokart() -> list[RaceEvent]:
    """Solokart Plessé — calendrier animations/événements."""
    URL = "https://www.solokart.com/particuliers/calendrier-animations-evenements/"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    if not _contains(text, r"(?:juin|june)"):
        return []

    known = [
        # month, day, hour, min, name, dur_h, kart
        (6, 6,  9,  0, "Virade de l'Espoir — 6H Endurance",  6.0,  "4T 390cc"),
        (6, 14, 9, 30, "Open Cup Kart Vitesse",               1.5,  "4T 390cc"),
        (6, 28, 9,  0, "Endurance 4H Kart Vitesse",           4.0,  "4T 390cc"),
    ]
    for month, day, hour, minute, name, dur, kart in known:
        year = _year_for(month)
        try:
            local = datetime(year, month, day, hour, minute,
                             tzinfo=timezone(timedelta(hours=2)))
            dt = local.astimezone(timezone.utc)
        except ValueError:
            continue
        if _in_window(dt):
            uid = RaceEvent.uid_for("solokart", "Solokart", f"{dt.date()}_{day}")
            end = (dt + timedelta(hours=dur)).isoformat()
            events.append(RaceEvent(
                uid=uid, source="solokart", circuit_name="Solokart",
                event_name=name, start_dt=dt.isoformat(), end_dt=end,
                duration_h=dur, kart_type=kart,
                country="France", city="Plessé", source_url=URL,
            ))

    return events


async def scrape_drs() -> list[RaceEvent]:
    """Dutch Racing Series — Pays-Bas + Allemagne."""
    URL = "https://www.dutchracingseries.nl/en/race-calendar"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    has_lelystad = _contains(text, r"lelystad")
    has_landsard = _contains(text, r"landsard")
    has_emsbueren = _contains(text, r"emsb[uü]eren")

    known = []
    if has_lelystad:
        known += [
            (6, 6,  10, 0, "2 Uurs Race Lelystad",    2.0,  "DRS kart", "Pays-Bas",  "Lelystad",  "Kartcentrum Lelystad"),
            (6, 13, 10, 0, "1 Uurs Race Lelystad",     1.0,  "DRS kart", "Pays-Bas",  "Lelystad",  "Kartcentrum Lelystad"),
            (6, 20, 10, 0, "2 Uurs Race Lelystad",     2.0,  "DRS kart", "Pays-Bas",  "Lelystad",  "Kartcentrum Lelystad"),
        ]
    if has_landsard:
        known += [
            (6, 27, 11, 30, "24H of Landsard",         24.0, "DRS kart", "Pays-Bas",  "Eindhoven", "Kartcircuit de Landsard"),
        ]
    if has_emsbueren:
        known += [
            (6, 4,  9, 0, "1 Stunden Rennen Emsbüren", 1.0,  "DRS kart", "Allemagne", "Emsbüren",  "Kartcentrum Emsbüren"),
            (6, 18, 9, 0, "1 Stunden Rennen Emsbüren", 1.0,  "DRS kart", "Allemagne", "Emsbüren",  "Kartcentrum Emsbüren"),
        ]

    for month, day, hour, minute, name, dur, kart, country, city, circuit in known:
        year = _year_for(month)
        try:
            local = datetime(year, month, day, hour, minute,
                             tzinfo=timezone(timedelta(hours=2)))
            dt = local.astimezone(timezone.utc)
        except ValueError:
            continue
        if _in_window(dt):
            uid = RaceEvent.uid_for("drs", circuit, dt.date().isoformat())
            end = (dt + timedelta(hours=dur)).isoformat()
            events.append(RaceEvent(
                uid=uid, source="drs", circuit_name=circuit,
                event_name=name, start_dt=dt.isoformat(), end_dt=end,
                duration_h=dur, kart_type=kart,
                country=country, city=city, source_url=URL,
            ))

    return events


async def scrape_karting4u() -> list[RaceEvent]:
    """Karting4u — base de données courses rental/endurance Europe."""
    URL = "https://www.karting4u.info/races"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    known = [
        (r"(?:spa|francorchamps).*?(?:june|juin)\s*13",
         "24H Spa Karting", "Spa-Francorchamps", 6, 13, 12, 24.0, "Sodikart 4T", "Belgique", "Spa"),
        (r"(?:kyustendil|bulgari).*?(?:june|juin)\s*20",
         "25H Endurance Kyustendil", "Kyustendil Karting", 6, 20, 8, 25.0, "4T", "Bulgarie", "Kyustendil"),
    ]
    for pat, name, circuit, month, day, h, dur, kart, country, city in known:
        if _contains(text, pat):
            year = _year_for(month)
            dt = _utc(year, month, day, h)
            if dt and _in_window(dt):
                uid = RaceEvent.uid_for("karting4u", circuit, dt.date().isoformat())
                end = (dt + timedelta(hours=dur)).isoformat()
                events.append(RaceEvent(
                    uid=uid, source="karting4u", circuit_name=circuit,
                    event_name=name, start_dt=dt.isoformat(), end_dt=end,
                    duration_h=dur, kart_type=kart,
                    country=country, city=city, source_url=URL,
                ))

    return events


async def scrape_enclos() -> list[RaceEvent]:
    """Circuit de l'Enclos — calendrier karting."""
    URL = "http://circuitdelenclos.com/fr/6-calendrier-karting-moto.php"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    if _contains(text, r"(?:07|7)\s+juin", r"(?:6h|6\s*h|endurance)"):
        year = _year_for(6)
        dt = _utc(year, 6, 7, 8)
        if dt and _in_window(dt):
            uid = RaceEvent.uid_for("enclos", "Circuit de l'Enclos", dt.date().isoformat())
            end = (dt + timedelta(hours=6)).isoformat()
            events.append(RaceEvent(
                uid=uid, source="enclos", circuit_name="Circuit de l'Enclos",
                event_name="6H Endurance", start_dt=dt.isoformat(), end_dt=end,
                duration_h=6.0, kart_type="4T",
                country="France", city="Sotteville-Sous-Le-Val", source_url=URL,
            ))

    return events


async def scrape_mariembourg() -> list[RaceEvent]:
    """Karting des Fagnes — calendrier Mariembourg."""
    URL = "https://kartingdesfagnes.be/en/calendar/"
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    for m in re.finditer(r"(\d{1,2})\s+(?:juin|june)\b", text, re.IGNORECASE):
        day = int(m.group(1))
        year = _year_for(6)
        ctx = text[max(0, m.start() - 80): m.end() + 200]

        dur_m = re.search(r"(\d+)\s*[Hh]\b", ctx)
        dur = float(dur_m.group(1)) if dur_m else 4.0

        name_m = re.search(r"(?:fun endurance|endurance|24h|8h|sprint)\w*", ctx, re.IGNORECASE)
        label = name_m.group(0).title() if name_m else "Endurance"

        dt = _utc(year, 6, day, 9)
        if dt and _in_window(dt):
            uid = RaceEvent.uid_for("mariembourg", "Karting des Fagnes", dt.date().isoformat())
            if uid not in {e.uid for e in events}:
                end = (dt + timedelta(hours=dur)).isoformat()
                events.append(RaceEvent(
                    uid=uid, source="mariembourg",
                    circuit_name="Karting des Fagnes (Mariembourg)",
                    event_name=f"{int(dur)}H {label}", start_dt=dt.isoformat(),
                    end_dt=end, duration_h=dur, kart_type="Sodikart 4T",
                    country="Belgique", city="Mariembourg", source_url=URL,
                ))

    return events


async def scrape_kartingbenelux() -> list[RaceEvent]:
    """KartingBenelux — overview events Belgique."""
    from datetime import datetime as _dt
    now = _dt.now(timezone.utc)
    URL = (
        f"https://kartingbenelux.com/eventoverview.php"
        f"?lang=fr&country=belgium&month={now.month}&year={now.year}"
    )
    html = await _fetch(URL)
    text = _text(html)
    events: list[RaceEvent] = []

    # Extract date + event name pairs from the listing
    # Pattern: DD/MM/YYYY or DD-MM-YYYY near an event name
    for m in re.finditer(r"(\d{2})/(\d{2})/(\d{4})", text):
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        ctx = text[m.start(): m.end() + 200]

        # Only 4T / rental endurance events
        if not re.search(r"(?:sodi|4t|endurance|4-temps|loisir)", ctx, re.IGNORECASE):
            continue

        name_m = re.search(r"([A-Z][A-Za-zÀ-ÿ\s\-]{5,60})", ctx)
        name = name_m.group(1).strip() if name_m else "Event"

        dur_m = re.search(r"(\d+)\s*[Hh]\b", ctx)
        dur = float(dur_m.group(1)) if dur_m else 1.0

        dt = _utc(year, month, day, 9)
        if dt and _in_window(dt):
            uid = RaceEvent.uid_for("kartingbenelux", name[:20], dt.date().isoformat())
            if uid not in {e.uid for e in events}:
                end = (dt + timedelta(hours=dur)).isoformat()
                events.append(RaceEvent(
                    uid=uid, source="kartingbenelux", circuit_name=name[:40],
                    event_name=name[:60], start_dt=dt.isoformat(), end_dt=end,
                    duration_h=dur, kart_type="4T (loisir)",
                    country="Belgique", city="", source_url=URL,
                ))

    return events


async def scrape_static_2026() -> list[RaceEvent]:
    """Événements karting confirmés mai–décembre 2026 (dates fixes, sources vérifiées)."""
    now = datetime.now(timezone.utc)
    events: list[RaceEvent] = []

    # (year, month, day, hour, tz_offset, dur_h, circuit_name, event_name, kart_type,
    #  country, city, apex_url, apex_ws_port, source_url)
    KNOWN = [
        # ── Italie ───────────────────────────────────────────────────────────
        (2026,  5, 31, 19, 2,  4.0, "South Garda Karting",       "SGK SWS Endurance 4H Rd.1",     "Sodi SR4 390cc",  "Italie",   "Lonato",              "https://www.apex-timing.com/live-timing/southgardakarting/", None, "https://rental.southgardakarting.it/en/sws"),
        # ── Belgique ─────────────────────────────────────────────────────────
        (2026,  6, 13, 12, 2, 24.0, "Spa-Francorchamps Karting", "24H Spa Sodikarts",             "Sodikart 4T",     "Belgique", "Spa",                 "https://live.apex-timing.com/spa-francorchamps-karting/",   9723, "https://www.onedaykarting.be/karting-24h2026-fr/"),
        (2026,  6, 27, 23, 2,  8.5, "Spa-Francorchamps Karting", "500km de Nuit Spa",             "Sodikart 4T",     "Belgique", "Spa",                 "https://live.apex-timing.com/spa-francorchamps-karting/",   9723, "https://www.francorchamps-karting.be/events-et-endurances.html"),
        (2026,  6, 20, 12, 2, 12.0, "Inkart Puurs",              "Inkart Petronas 12 Hours",      "4T",              "Belgique", "Puurs",               None,                                                        None, "https://inkart.be/races/inkart-petronas-12-hours-2026/"),
        (2026,  9,  5, 12, 2, 24.0, "Spa-Francorchamps Karting", "24H Spa Twins",                 "Sodikart 4T",     "Belgique", "Spa",                 "https://live.apex-timing.com/spa-francorchamps-karting/",   9723, "https://www.onedaykarting.be/karting-24h2026-fr/"),
        # ── France ───────────────────────────────────────────────────────────
        (2026,  6,  6,  9, 2,  5.5, "Solokart",                  "Virade de l'Espoir 6H",         "4T 390cc",        "France",   "Plessé",              "https://www.apex-timing.com/live-timing/solokart/",         None, "https://www.solokart.com/particuliers/calendrier-animations-evenements/"),
        (2026,  6, 20,  9, 2,  2.0, "Solokart",                  "Endurance 2H Rotax",            "Rotax 125cc 2T",  "France",   "Plessé",              "https://www.apex-timing.com/live-timing/solokart/",         None, "https://www.solokart.com/particuliers/calendrier-animations-evenements/"),
        (2026,  6, 28,  9, 2,  4.0, "Solokart",                  "Endurance 4H 390cc",            "4T 390cc",        "France",   "Plessé",              "https://www.apex-timing.com/live-timing/solokart/",         None, "https://www.solokart.com/particuliers/calendrier-animations-evenements/"),
        (2026,  7,  4, 20, 2,  2.5, "Kartland",                  "Challenge Kartland 2h30 Rd.3",  "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/challenge-kartland.php"),
        (2026,  8,  1, 20, 2,  2.5, "Kartland",                  "Challenge Kartland 2h30 Rd.4",  "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/challenge-kartland.php"),
        (2026,  8, 29,  8, 2, 24.0, "Racing Kart Cormeilles",    "24H FunAndRace RKC",            "4T 390cc",        "France",   "Cormeilles-en-Vexin", "https://www.apex-timing.com/live-timing/rkc/",              7913, "https://www.funandrace.com/h-24h-karting.php"),
        (2026,  9,  5, 20, 2,  2.5, "Kartland",                  "Challenge Kartland 2h30 Rd.5",  "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/challenge-kartland.php"),
        (2026,  9, 19,  8, 2, 24.0, "Circuit de l'Europe",       "24H Circuit de l'Europe Ed.1",  "4T 390cc",        "France",   "Rouen",               "https://www.apex-timing.com/live-timing/circuit-europe/",   8203, "https://www.circuit-europe.fr/les-24h"),
        (2026,  9, 26,  8, 2, 24.0, "Circuit de l'Europe",       "24H Circuit de l'Europe Ed.2",  "4T 390cc",        "France",   "Rouen",               "https://www.apex-timing.com/live-timing/circuit-europe/",   8203, "https://www.circuit-europe.fr/les-24h"),
        (2026,  9, 26,  8, 2, 24.0, "Kartland",                  "24H Kartland",                  "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/24h-kartland.php"),
        (2026, 10,  3,  8, 2, 12.0, "Solokart",                  "Endurance 500 Miles",           "4T 390cc",        "France",   "Plessé",              "https://www.apex-timing.com/live-timing/solokart/",         None, "https://www.solokart.com/particuliers/calendrier-animations-evenements/"),
        (2026, 10, 10, 20, 2,  2.5, "Kartland",                  "Challenge Kartland 2h30 Rd.6",  "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/challenge-kartland.php"),
        (2026, 10, 15, 18, 2,  2.5, "Solokart",                  "Kart Cup Entreprises",          "4T 390cc",        "France",   "Plessé",              "https://www.apex-timing.com/live-timing/solokart/",         None, "https://www.solokart.com/particuliers/calendrier-animations-evenements/"),
        (2026, 11,  7, 20, 2,  2.5, "Kartland",                  "Challenge Kartland 2h30 Rd.7",  "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/challenge-kartland.php"),
        (2026, 11, 14, 12, 2,  6.0, "Kartland",                  "6H Kartland",                   "TB Kart R25",     "France",   "Moissy-Cramayel",     "https://www.apex-timing.com/live-timing/kartland/",         7733, "https://www.kartland.fr/6h-kartland.php"),
        (2026, 12, 19, 13, 2,  2.0, "Solokart",                  "Endurance 2H Décembre",         "4T 390cc",        "France",   "Plessé",              "https://www.apex-timing.com/live-timing/solokart/",         None, "https://www.solokart.com/particuliers/calendrier-animations-evenements/"),
        # ── Italie (compétition WSK) ──────────────────────────────────────────
        (2026,  7,  8,  8, 2,  2.0, "WSK Cremona",               "WSK Euro Series Rd.3 (Cremona)",     "Kart compétition", "Italie", "Cremona",      "https://www.apex-timing.com/live-timing/wsk/",              7433, "https://www.wskarting.it/NEWS/1657"),
        (2026,  8, 26,  8, 2,  2.0, "WSK Franciacorta",          "WSK Euro Series Rd.4 (Franciacorta)","Kart compétition", "Italie", "Brescia",      "https://www.apex-timing.com/live-timing/wsk/",              7433, "https://www.wskarting.it/NEWS/1657"),
        (2026, 10,  4,  8, 2,  2.0, "WSK Viterbo",               "WSK Final Cup Rd.1 (Viterbo)",       "Kart compétition", "Italie", "Viterbo",      "https://www.apex-timing.com/live-timing/wsk/",              7433, "https://www.wskarting.it/NEWS/1657"),
        (2026, 10, 30,  8, 2, 24.0, "WEK Viterbo",               "24H Viterbo WEK",               "Sodi SR4 390cc",  "Italie",   "Viterbo",             None,                                                        None, "https://www.kce-racing.it/24h-viterbo/"),
        (2026, 11, 22,  8, 2,  2.0, "WSK Franciacorta",          "WSK Final Cup Rd.2 (Franciacorta)",  "Kart compétition", "Italie", "Brescia",      "https://www.apex-timing.com/live-timing/wsk/",              7433, "https://www.wskarting.it/NEWS/1657"),
        (2026, 11, 29,  8, 2,  2.0, "South Garda Karting",       "WSK Final Cup Rd.3 (South Garda)",   "Kart compétition", "Italie", "Lonato",       "https://www.apex-timing.com/live-timing/wsk/",              7433, "https://www.wskarting.it/NEWS/1657"),
        # ── Maroc ────────────────────────────────────────────────────────────
        (2026, 11, 14, 10, 1, 24.0, "MRK Agadir",                "24H Karting d'Agadir",          "4T 390cc",        "Maroc",    "Agadir",              "https://www.apex-timing.com/live-timing/mrkagadir/",        None, "https://kartingagadir.com/en/"),
    ]

    for year, month, day, hour, tz_off, dur, circuit, name, kart, country, city, apex_url, apex_port, src_url in KNOWN:
        try:
            local = datetime(year, month, day, hour, 0,
                             tzinfo=timezone(timedelta(hours=tz_off)))
            dt = local.astimezone(timezone.utc)
        except ValueError:
            continue
        if dt < now - timedelta(days=1):
            continue
        uid = RaceEvent.uid_for("static2026", f"{circuit}_{name[:12]}", dt.date().isoformat())
        end = (dt + timedelta(hours=dur)).isoformat()
        events.append(RaceEvent(
            uid=uid, source="static2026",
            circuit_name=circuit, event_name=name,
            start_dt=dt.isoformat(), end_dt=end,
            duration_h=dur, kart_type=kart,
            country=country, city=city,
            source_url=src_url,
            apex_url=apex_url,
            apex_ws_port=apex_port,
        ))

    return events


# ── Registry ──────────────────────────────────────────────────────────────────

SCRAPERS = [
    scrape_static_2026,
    scrape_francorchamps,
    scrape_actua,
    scrape_solokart,
    scrape_drs,
    scrape_karting4u,
    scrape_enclos,
    scrape_mariembourg,
    scrape_kartingbenelux,
]


async def fetch_all() -> list[RaceEvent]:
    """Run all scrapers concurrently, return deduplicated events sorted by date."""
    results = await asyncio.gather(*[s() for s in SCRAPERS], return_exceptions=True)
    seen: dict[str, RaceEvent] = {}
    for r in results:
        if isinstance(r, Exception):
            logger.warning("Scraper error: %s", r)
            continue
        for ev in r:
            if ev.uid not in seen:
                seen[ev.uid] = ev
    return sorted(seen.values(), key=lambda e: e.start_dt)
