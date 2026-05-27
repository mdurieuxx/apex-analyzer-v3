"""
SQLite master store for circuits — stdlib sqlite3, no external deps.

DB path: $CIRCUITS_DIR/circuits.db  (default: /data/circuits/circuits.db)
Seeded from SEED_CIRCUITS at first startup if the table is empty.
"""
import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("CIRCUITS_DIR", "/data/circuits")) / "circuits.db"

# ── Seed data ─────────────────────────────────────────────────────────────────
SEED_CIRCUITS = [
    # ── France ──────────────────────────────────────────────────────────────────
    {"name": "Karting de Saintes",          "slug": "saintes",                 "url": "https://www.apex-timing.com/live-timing/karting-de-saintes/",        "port": 8583, "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "ACO Le Mans Karting 2",       "slug": "lemans-karting2",         "url": "https://www.apex-timing.com/live-timing/lemans-karting2/",           "port": 8013, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Paris Kart Indoor",           "slug": "paris-kart",              "url": "https://www.apex-timing.com/live-timing/paris-kart/",                "port": 8213, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit de l'Europe",         "slug": "circuit-europe",          "url": "https://www.apex-timing.com/live-timing/circuit-europe/",            "port": 8203, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Karting Haute-Picardie",      "slug": "karting-haute-picardie",  "url": "https://www.apex-timing.com/live-timing/karting-haute-picardie/",    "port": 9153, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit de Bresse",           "slug": "capkarting",              "url": "https://www.apex-timing.com/live-timing/capkarting/",                "port": 7953, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Kartland",                    "slug": "kartland",                "url": "https://www.apex-timing.com/live-timing/kartland/",                  "port": 7733, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Ouest Karting",               "slug": "ouestkarting",            "url": "https://www.apex-timing.com/live-timing/ouestkarting/",              "port": 7983, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit Paul Ricard Karting", "slug": "circuitpaulricardkarting","url": "https://www.apex-timing.com/live-timing/circuitpaulricardkarting/",  "port": 7923, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Racing Kart Cormeilles",      "slug": "rkc",                     "url": "https://www.apex-timing.com/live-timing/rkc/",                       "port": 7913, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Ligue Karting IDF",           "slug": "ligue-karting-idf",       "url": "https://www.apex-timing.com/live-timing/ligue-karting-idf/",         "port": 7363, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "FFSA Karting",                "slug": "ffsa-karting",            "url": "https://www.apex-timing.com/live-timing/ffsa-karting/",              "port": 7263, "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Korridas",                    "slug": "korridas",                "url": "https://www.apex-timing.com/live-timing/korridas/",                  "port": 7633, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Brignoles Karting",           "slug": "brignoles-karting-loisir","url": "https://www.apex-timing.com/live-timing/brignoles-karting-loisir/",  "port": 8603, "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Laval Loisirs Kart",          "slug": "lavalloisirskart",        "url": "https://www.apex-timing.com/live-timing/lavalloisirskart/",          "port": 8123, "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Karting 45",                  "slug": "karting-45",              "url": "https://www.apex-timing.com/live-timing/karting-45/",                "port": 8373, "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "CKB Besançon",                "slug": "ckbesancon",              "url": "https://live.apex-timing.com/ckbesancon/",                           "port": 9643, "ws_host": "live.apex-timing.com",      "country": "France"},
    # ── Belgique ─────────────────────────────────────────────────────────────────
    {"name": "Karting des Fagnes (Mariembourg)", "slug": "mariembourg",        "url": "https://www.apex-timing.com/live-timing/karting-mariembourg/",       "port": 8313, "ws_host": "www.apex-timing.com",       "country": "Belgique"},
    {"name": "Karting de Genk",             "slug": "genk",                    "url": "https://www.apex-timing.com/live-timing/karting-genk/",              "port": 8243, "ws_host": "www.apex-timing.com",       "country": "Belgique"},
    {"name": "Karting Eupen",               "slug": "eupen",                   "url": "https://www.apex-timing.com/live-timing/karting-eupen/",             "port": 8523, "ws_host": "www.apex-timing.com",       "country": "Belgique"},
    {"name": "Spa Francorchamps Karting",   "slug": "spa",                     "url": "https://live.apex-timing.com/spa-francorchamps-karting/",            "port": 9723, "ws_host": "live.apex-timing.com",      "country": "Belgique"},
    {"name": "Wavre Indoor Karting (WIK)",  "slug": "wik",                     "url": "https://www.apex-timing.com/live-timing/wik/",                       "port": 8553, "ws_host": "live-data.apex-timing.com", "country": "Belgique"},
    # ── Maroc ────────────────────────────────────────────────────────────────────
    {"name": "MRK Agadir",                  "slug": "agadir",                  "url": "https://www.apex-timing.com/live-timing/mrkagadir/",                 "port": 8023, "ws_host": "www.apex-timing.com",       "country": "Maroc"},
    # ── Italie ───────────────────────────────────────────────────────────────────
    {"name": "Misanino",                    "slug": "misanino",                "url": "https://www.apex-timing.com/live-timing/misanino/",                  "port": 8043, "ws_host": "www.apex-timing.com",       "country": "Italie"},
    # ── Royaume-Uni ──────────────────────────────────────────────────────────────
    {"name": "Cornwall Karting",            "slug": "cornwall-karting",        "url": "https://www.apex-timing.com/live-timing/cornwall-karting/",          "port": 8593, "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Xtreme Karting Edinburgh",    "slug": "xtremekarting-edinburgh", "url": "https://www.apex-timing.com/live-timing/xtremekarting-edinburgh/",   "port": 8833, "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Xtreme Karting Falkirk",      "slug": "xtremekarting-falkirk",   "url": "https://www.apex-timing.com/live-timing/xtremekarting-falkirk/",     "port": 8843, "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Larkhall / WSKC",             "slug": "larkhall-circuit",        "url": "https://www.apex-timing.com/live-timing/larkhall-circuit/",          "port": 7323, "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    # ── Pays-Bas ─────────────────────────────────────────────────────────────────
    {"name": "Dutch Racing Series",         "slug": "dutchracingseries",       "url": "https://www.apex-timing.com/live-timing/dutchracingseries/",         "port": 9463, "ws_host": "www.apex-timing.com",       "country": "Pays-Bas"},
    # ── Espagne ──────────────────────────────────────────────────────────────────
    {"name": "Karting Sevilla",             "slug": "karting-sevilla",         "url": "https://live.apex-timing.com/karting-sevilla/",                      "port": 9863, "ws_host": "live.apex-timing.com",      "country": "Espagne"},
    # ── International / Compétition ──────────────────────────────────────────────
    {"name": "FIA Karting",                 "slug": "fiakarting",              "url": "https://www.apex-timing.com/live-timing/fiakarting/",                "port": 7813, "ws_host": "live-data.apex-timing.com", "country": "International"},
    {"name": "WSK",                         "slug": "wsk",                     "url": "https://www.apex-timing.com/live-timing/wsk/",                       "port": 7433, "ws_host": "www.apex-timing.com",       "country": "International"},
    {"name": "RGMMC",                       "slug": "rgmmc",                   "url": "https://www.apex-timing.com/live-timing/rgmmc/",                     "port": 7683, "ws_host": "www.apex-timing.com",       "country": "International"},
    {"name": "TVKC",                        "slug": "tvkc",                    "url": "https://www.apex-timing.com/live-timing/tvkc/",                      "port": 7873, "ws_host": "www.apex-timing.com",       "country": "International"},
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS circuits (
                slug     TEXT PRIMARY KEY,
                name     TEXT NOT NULL,
                url      TEXT NOT NULL UNIQUE,
                port     INTEGER NOT NULL,
                ws_host  TEXT NOT NULL,
                country  TEXT NOT NULL DEFAULT ''
            )
        """)
        if conn.execute("SELECT COUNT(*) FROM circuits").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO circuits (slug, name, url, port, ws_host, country) VALUES (?, ?, ?, ?, ?, ?)",
                [(c["slug"], c["name"], c["url"], c["port"], c["ws_host"], c.get("country", ""))
                 for c in SEED_CIRCUITS],
            )


def get_all() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM circuits ORDER BY country, name").fetchall()
    return [_to_dict(r) for r in rows]


def get_by_url(url: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM circuits WHERE url = ?", (url,)).fetchone()
    return _to_dict(row) if row else None


def get_by_slug(slug: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM circuits WHERE slug = ?", (slug,)).fetchone()
    return _to_dict(row) if row else None


def upsert(circuit: dict) -> dict:
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO circuits (slug, name, url, port, ws_host, country)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name    = excluded.name,
                url     = excluded.url,
                port    = excluded.port,
                ws_host = excluded.ws_host,
                country = excluded.country
            """,
            (circuit["slug"], circuit["name"], circuit["url"],
             circuit["port"], circuit["ws_host"], circuit.get("country", "")),
        )
    return get_by_slug(circuit["slug"])


def delete(slug: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM circuits WHERE slug = ?", (slug,))
    return cur.rowcount > 0
