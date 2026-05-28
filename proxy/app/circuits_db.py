"""
SQLite master store for circuits — stdlib sqlite3, no external deps.

DB path: $CIRCUITS_DIR/circuits.db  (default: /data/circuits/circuits.db)

tested column: NULL = jamais testé, 1 = port joignable, 0 = port injoignable.
"""
import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.environ.get("CIRCUITS_DIR", "/data/circuits")) / "circuits.db"

# IANA timezone par pays — utilisé pour convertir started_at UTC en heure locale
COUNTRY_TZ: dict[str, str] = {
    "France":        "Europe/Paris",
    "Belgique":      "Europe/Brussels",
    "Maroc":         "Africa/Casablanca",
    "Italie":        "Europe/Rome",
    "Royaume-Uni":   "Europe/London",
    "Pays-Bas":      "Europe/Amsterdam",
    "Espagne":       "Europe/Madrid",
    "États-Unis":    "America/New_York",
    "Portugal":      "Europe/Lisbon",
    "Allemagne":     "Europe/Berlin",
    "Slovaquie":     "Europe/Bratislava",
    "Suède":         "Europe/Stockholm",
    "International": "UTC",
}

# ── Seed data ─────────────────────────────────────────────────────────────────
# INSERT OR IGNORE — ajout des nouveaux circuits à chaque démarrage sans écraser les existants.
SEED_CIRCUITS = [
    # ── France ──────────────────────────────────────────────────────────────────
    {"name": "Karting de Saintes",           "slug": "saintes",                  "url": "https://www.apex-timing.com/live-timing/karting-de-saintes/",        "port": 8583,  "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "ACO Le Mans Karting 2",        "slug": "lemans-karting2",          "url": "https://www.apex-timing.com/live-timing/lemans-karting2/",           "port": 8013,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Paris Kart Indoor",            "slug": "paris-kart",               "url": "https://www.apex-timing.com/live-timing/paris-kart/",                "port": 8213,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit de l'Europe",          "slug": "circuit-europe",           "url": "https://www.apex-timing.com/live-timing/circuit-europe/",            "port": 8203,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Karting Haute-Picardie",       "slug": "karting-haute-picardie",   "url": "https://www.apex-timing.com/live-timing/karting-haute-picardie/",    "port": 9153,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit de Bresse",            "slug": "capkarting",               "url": "https://www.apex-timing.com/live-timing/capkarting/",                "port": 7953,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Kartland",                     "slug": "kartland",                 "url": "https://www.apex-timing.com/live-timing/kartland/",                  "port": 7733,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Ouest Karting",                "slug": "ouestkarting",             "url": "https://www.apex-timing.com/live-timing/ouestkarting/",              "port": 7983,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit Paul Ricard Karting",  "slug": "circuitpaulricardkarting", "url": "https://www.apex-timing.com/live-timing/circuitpaulricardkarting/",  "port": 7923,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Racing Kart Cormeilles",       "slug": "rkc",                      "url": "https://www.apex-timing.com/live-timing/rkc/",                       "port": 7913,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Ligue Karting IDF",            "slug": "ligue-karting-idf",        "url": "https://www.apex-timing.com/live-timing/ligue-karting-idf/",         "port": 7363,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "FFSA Karting",                 "slug": "ffsa-karting",             "url": "https://www.apex-timing.com/live-timing/ffsa-karting/",              "port": 7263,  "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Korridas",                     "slug": "korridas",                 "url": "https://www.apex-timing.com/live-timing/korridas/",                  "port": 7633,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Brignoles Karting",            "slug": "brignoles-karting-loisir", "url": "https://www.apex-timing.com/live-timing/brignoles-karting-loisir/",  "port": 8603,  "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Laval Loisirs Kart",           "slug": "lavalloisirskart",         "url": "https://www.apex-timing.com/live-timing/lavalloisirskart/",          "port": 8123,  "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Karting 45",                   "slug": "karting-45",               "url": "https://www.apex-timing.com/live-timing/karting-45/",                "port": 8373,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "CKB Besançon",                 "slug": "ckbesancon",               "url": "https://live.apex-timing.com/ckbesancon/",                           "port": 9643,  "ws_host": "live.apex-timing.com",      "country": "France"},
    {"name": "MK Circuit",                   "slug": "mk-circuit",               "url": "https://www.apex-timing.com/live-timing/mk-circuit/",                "port": 8083,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "First Kart Inn",               "slug": "firstkartinn",             "url": "https://www.apex-timing.com/live-timing/firstkartinn/",              "port": 8113,  "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Sport Karting Vallée",         "slug": "sportkarting",             "url": "https://www.apex-timing.com/live-timing/sportkarting/",              "port": 8163,  "ws_host": "live-data.apex-timing.com", "country": "France"},
    {"name": "Circuit de l'Enclos",          "slug": "circuit-de-lenclos",       "url": "https://www.apex-timing.com/live-timing/circuit-de-lenclos/",        "port": 8493,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Kart Planet",                  "slug": "kartplanet",               "url": "https://live.apex-timing.com/kartplanet/",                           "port": 10223, "ws_host": "live.apex-timing.com",      "country": "France"},
    {"name": "Karting Loisirs Neuilly",      "slug": "kln",                      "url": "https://live.apex-timing.com/kln/",                                  "port": 10053, "ws_host": "live.apex-timing.com",      "country": "France"},
    {"name": "PKS Loisirs",                 "slug": "pks-loisirs",              "url": "https://live.apex-timing.com/pks-loisirs/",                          "port": 9253,  "ws_host": "live.apex-timing.com",      "country": "France"},
    {"name": "Karting Espoey",              "slug": "karting-espoey",           "url": "https://www.apex-timing.com/live-timing/karting-espoey/",            "port": 9453,  "ws_host": "www.apex-timing.com",       "country": "France"},
    {"name": "Circuit du Bugey",            "slug": "circuit-du-bugey",         "url": "https://live.apex-timing.com/circuit-du-bugey/",                     "port": 9078,  "ws_host": "live.apex-timing.com",      "country": "France"},
    {"name": "Circuit de l'Indre",         "slug": "circuit-indre",            "url": "https://live.apex-timing.com/circuit-indre/",                        "port": 10363, "ws_host": "live.apex-timing.com",      "country": "France"},
    # ── Belgique ─────────────────────────────────────────────────────────────────
    {"name": "Karting des Fagnes (Mariembourg)", "slug": "mariembourg",          "url": "https://www.apex-timing.com/live-timing/karting-mariembourg/",       "port": 8313,  "ws_host": "www.apex-timing.com",       "country": "Belgique"},
    {"name": "Karting de Genk",              "slug": "genk",                     "url": "https://www.apex-timing.com/live-timing/karting-genk/",              "port": 8243,  "ws_host": "www.apex-timing.com",       "country": "Belgique"},
    {"name": "Karting Eupen",                "slug": "eupen",                    "url": "https://www.apex-timing.com/live-timing/karting-eupen/",             "port": 8523,  "ws_host": "www.apex-timing.com",       "country": "Belgique"},
    {"name": "Spa Francorchamps Karting",    "slug": "spa",                      "url": "https://live.apex-timing.com/spa-francorchamps-karting/",            "port": 9723,  "ws_host": "live.apex-timing.com",      "country": "Belgique"},
    {"name": "Wavre Indoor Karting (WIK)",   "slug": "wik",                      "url": "https://www.apex-timing.com/live-timing/wik/",                       "port": 8553,  "ws_host": "live-data.apex-timing.com", "country": "Belgique"},
    {"name": "Brussels South Karting",      "slug": "brusselssouth",            "url": "https://live.apex-timing.com/brusselssouth/",                        "port": 10253, "ws_host": "live.apex-timing.com",      "country": "Belgique"},
    # ── Maroc ────────────────────────────────────────────────────────────────────
    {"name": "MRK Agadir",                   "slug": "mrkagadir",                "url": "https://www.apex-timing.com/live-timing/mrkagadir/",                "port": 8023,  "ws_host": "www.apex-timing.com",       "country": "Maroc"},
    # ── Italie ───────────────────────────────────────────────────────────────────
    {"name": "Misanino",                     "slug": "misanino",                 "url": "https://www.apex-timing.com/live-timing/misanino/",                  "port": 8043,  "ws_host": "www.apex-timing.com",       "country": "Italie"},
    {"name": "Onlykart",                     "slug": "onlykart",                 "url": "https://live.apex-timing.com/onlykart/",                             "port": 9323,  "ws_host": "live.apex-timing.com",      "country": "Italie"},
    {"name": "Circuito Internazionale Triscina", "slug": "circuito-internazionale-triscina", "url": "https://live.apex-timing.com/circuito-internazionale-triscina/", "port": 10293, "ws_host": "live.apex-timing.com", "country": "Italie"},
    # ── Royaume-Uni ──────────────────────────────────────────────────────────────
    {"name": "Cornwall Karting",             "slug": "cornwall-karting",         "url": "https://www.apex-timing.com/live-timing/cornwall-karting/",          "port": 8593,  "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Xtreme Karting Edinburgh",     "slug": "xtremekarting-edinburgh",  "url": "https://www.apex-timing.com/live-timing/xtremekarting-edinburgh/",   "port": 8833,  "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Xtreme Karting Falkirk",       "slug": "xtremekarting-falkirk",    "url": "https://www.apex-timing.com/live-timing/xtremekarting-falkirk/",     "port": 8843,  "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Larkhall / WSKC",              "slug": "larkhall-circuit",         "url": "https://www.apex-timing.com/live-timing/larkhall-circuit/",          "port": 7323,  "ws_host": "www.apex-timing.com",       "country": "Royaume-Uni"},
    {"name": "Fastlane Indoor Racing",       "slug": "fastlane-indoor-racing",   "url": "https://www.apex-timing.com/live-timing/fastlane-indoor-racing/",    "port": 8673,  "ws_host": "live-data.apex-timing.com", "country": "Royaume-Uni"},
    # ── Pays-Bas ─────────────────────────────────────────────────────────────────
    {"name": "Dutch Racing Series",          "slug": "dutchracingseries",        "url": "https://www.apex-timing.com/live-timing/dutchracingseries/",         "port": 9463,  "ws_host": "www.apex-timing.com",       "country": "Pays-Bas"},
    # ── Espagne ──────────────────────────────────────────────────────────────────
    {"name": "Karting Sevilla",              "slug": "karting-sevilla",          "url": "https://live.apex-timing.com/karting-sevilla/",                      "port": 9863,  "ws_host": "live.apex-timing.com",      "country": "Espagne"},
    {"name": "Kartódromo Lucas Guerrero",   "slug": "kartodromo-lucas-guerrero","url": "https://live.apex-timing.com/kartodromo-lucas-guerrero/",            "port": 9953,  "ws_host": "live.apex-timing.com",      "country": "Espagne"},
    {"name": "Karting Club Los Santos",     "slug": "karting-lossantos",        "url": "https://live.apex-timing.com/karting-lossantos/",                    "port": 8093,  "ws_host": "live.apex-timing.com",      "country": "Espagne"},
    # ── Portugal ─────────────────────────────────────────────────────────────────
    {"name": "Kartódromo de Évora",         "slug": "kartevora",                "url": "https://www.apex-timing.com/live-timing/kartevora/",                 "port": 9653,  "ws_host": "www.apex-timing.com",       "country": "Portugal"},
    # ── Allemagne ────────────────────────────────────────────────────────────────
    {"name": "Arena E, Mülsen",             "slug": "muelsen",                  "url": "https://www.apex-timing.com/live-timing/muelsen/",                   "port": 9963,  "ws_host": "www.apex-timing.com",       "country": "Allemagne"},
    {"name": "Kartbahn Lüneburg / Embsen",  "slug": "kartbahn-lueneburg",       "url": "https://live.apex-timing.com/kartbahn-lueneburg/",                   "port": 9353,  "ws_host": "live.apex-timing.com",      "country": "Allemagne"},
    # ── Slovaquie ────────────────────────────────────────────────────────────────
    {"name": "Slovak Karting Center",       "slug": "slovak-karting-center",    "url": "https://www.apex-timing.com/live-timing/slovak-karting-center/",     "port": 8533,  "ws_host": "live-data.apex-timing.com", "country": "Slovaquie"},
    # ── Suède ────────────────────────────────────────────────────────────────────
    {"name": "Gokartcentralen Kungälv",     "slug": "gokartcentralen-kungalv",  "url": "https://www.apex-timing.com/live-timing/gokartcentralen-kungalv/",   "port": 9433,  "ws_host": "www.apex-timing.com",       "country": "Suède"},
    # ── États-Unis ───────────────────────────────────────────────────────────────
    {"name": "Champions of the Future America", "slug": "cof-us",               "url": "https://live.apex-timing.com/cof-us/",                               "port": 6923,  "ws_host": "live.apex-timing.com",      "country": "États-Unis"},
    # ── International / Compétition ──────────────────────────────────────────────
    {"name": "FIA Karting",                  "slug": "fiakarting",               "url": "https://www.apex-timing.com/live-timing/fiakarting/",                "port": 7813,  "ws_host": "live-data.apex-timing.com", "country": "International"},
    {"name": "WSK",                          "slug": "wsk",                      "url": "https://www.apex-timing.com/live-timing/wsk/",                       "port": 7433,  "ws_host": "www.apex-timing.com",       "country": "International"},
    {"name": "RGMMC",                        "slug": "rgmmc",                    "url": "https://www.apex-timing.com/live-timing/rgmmc/",                     "port": 7683,  "ws_host": "www.apex-timing.com",       "country": "International"},
    {"name": "TVKC",                         "slug": "tvkc",                     "url": "https://www.apex-timing.com/live-timing/tvkc/",                      "port": 7873,  "ws_host": "www.apex-timing.com",       "country": "International"},
    # ── Pays inconnu ─────────────────────────────────────────────────────────────
    {"name": "WorldKarts",                   "slug": "worldkarts",               "url": "https://www.apex-timing.com/live-timing/worldkarts/",                "port": 8143,  "ws_host": "live-data.apex-timing.com", "country": ""},
    {"name": "Sports Timing Systems 2",      "slug": "sportstimingsystems2",     "url": "https://www.apex-timing.com/live-timing/sportstimingsystems2/",      "port": 7503,  "ws_host": "www.apex-timing.com",       "country": ""},
    {"name": "ELK Motorsport",               "slug": "elk-motorsport",           "url": "https://www.apex-timing.com/live-timing/elk-motorsport/",            "port": 8263,  "ws_host": "www.apex-timing.com",       "country": ""},
    {"name": "Apex Kart Timing",             "slug": "karttiming",               "url": "https://live.apex-timing.com/karttiming/",                           "port": 9583,  "ws_host": "live.apex-timing.com",      "country": ""},
    {"name": "WFR",                          "slug": "wfr",                      "url": "https://live.apex-timing.com/wfr/",                                  "port": 7153,  "ws_host": "live.apex-timing.com",      "country": ""},
]

# ── Circuits www.apex-timing.com — ports à découvrir (port=0) ──────────────────
# INSERT OR IGNORE : les circuits déjà présents (SEED_CIRCUITS avec port connu) ne sont pas écrasés.
def _make_apex(slug: str, country: str, name: str = "") -> dict:
    return {
        "slug": slug,
        "name": name or slug.replace("-", " ").replace("_", " ").title(),
        "url": f"https://www.apex-timing.com/live-timing/{slug}/",
        "port": 0,
        "ws_host": "www.apex-timing.com",
        "country": country,
    }

SEED_CIRCUITS_LIVE: list[dict] = [
    # ── Belgique ─────────────────────────────────────────────────────────────────
    _make_apex("karting-mariembourg",  "Belgique",  "Karting des Fagnes"),
    _make_apex("karting-genk",         "Belgique",  "Karting Genk"),
    _make_apex("jmk-namur",            "Belgique",  "JMK Namur Indoor"),
    _make_apex("worldkarts",           "Belgique",  "WorldKarts Poperinge"),
    _make_apex("inkart",               "Belgique",  "Inkart Puurs"),
    _make_apex("karting-spa",          "Belgique",  "RACB Karting Spa-Francorchamps"),
    _make_apex("firstkarting",         "Belgique",  "First Kart Inn Machelen"),
    _make_apex("eupen-karting",        "Belgique",  "Eupen Karting Indoor"),
    _make_apex("formula-karting",      "Belgique",  "Formula Karting"),
    # ── Pays-Bas ─────────────────────────────────────────────────────────────────
    _make_apex("karting-eindhoven",    "Pays-Bas",  "De Landsard"),
    _make_apex("circuit-vledderveen",  "Pays-Bas",  "Kartbaan Vledderveen"),
    # ── France ───────────────────────────────────────────────────────────────────
    _make_apex("rkc",                  "France",    "Racing Kart de Cormeilles"),
    _make_apex("circuit-europe",       "France",    "Circuit de l'Europe, Rouen"),
    _make_apex("capkarting",           "France",    "Cap Karting, Mer"),
    _make_apex("salbris",              "France",    "Circuit International de Salbris"),
    _make_apex("karting-soucy",        "France",    "Karting International de Soucy"),
    _make_apex("karting-pers",         "France",    "Circuit de Pers, Cantal"),
    _make_apex("circuit-angerville",   "France",    "Circuit International d'Angerville"),
    _make_apex("karting-le-mans",      "France",    "Karting Le Mans / Alain Prost"),
    _make_apex("kartland",             "France",    "Kartland, Moissy-Cramayel"),
    _make_apex("aunay-les-bois",       "France",    "Circuit d'Essay / Aunay-les-Bois"),
    _make_apex("lyon-karting",         "France",    "Actua Kart, Lyon"),
    _make_apex("karting-valence",      "France",    "Arena 45, Valence"),
    _make_apex("solokart",             "France",    "Solokart, Plessé"),
    _make_apex("laval",                "France",    "Circuit Beausoleil, Laval"),
    _make_apex("sens-espaces-karting", "France",    "Sens Espaces Karting"),
    _make_apex("karting-ploemel",      "France",    "Kart 56, Morbihan"),
    _make_apex("angers-karting",       "France",    "Espace Karting Angers"),
    _make_apex("wissous",              "France",    "Paris Kart Indoor"),
    # ── Allemagne ────────────────────────────────────────────────────────────────
    _make_apex("muelsen",              "Allemagne", "Arena E, Mülsen"),
    _make_apex("wackersdorf",          "Allemagne", "Prokart Raceland"),
    _make_apex("kerpen",               "Allemagne", "Erftlandring / Michael Schumacher"),
    _make_apex("ampfing",              "Allemagne", "Kartshop Ampfing"),
    _make_apex("liedolsheim",          "Allemagne", "Arena of Speed"),
    _make_apex("kartbahn-bispingen",   "Allemagne", "Ralf Schumacher Kartcenter"),
    # ── Espagne ──────────────────────────────────────────────────────────────────
    _make_apex("campillos",            "Espagne",   "Kart Center Campillos, Malaga"),
    _make_apex("zuera",                "Espagne",   "Circuito Internacional de Zuera"),
    _make_apex("kartodromovalencia",   "Espagne",   "Kartódromo Lucas Guerrero, Chiva"),
    _make_apex("karting-motorland",    "Espagne",   "MotorLand Aragón Karting"),
    _make_apex("karting-recas",        "Espagne",   "Circuito Correcaminos, Recas"),
    # ── Italie ───────────────────────────────────────────────────────────────────
    _make_apex("southgardakarting",    "Italie",    "South Garda Karting, Lonato"),
    _make_apex("napoli",               "Italie",    "Circuito Internazionale Napoli, Sarno"),
    _make_apex("franciacorta",         "Italie",    "Franciacorta Karting Track"),
    _make_apex("7laghikart",           "Italie",    "Castelletto di Branduzzo"),
    _make_apex("cremona-circuit",      "Italie",    "Cremona"),
    _make_apex("ala-karting",          "Italie",    "Ala Karting Circuit, Trente"),
    _make_apex("lignano",              "Italie",    "Circuit International de Lignano"),
    _make_apex("siena",                "Italie",    "Circuito di Siena"),
    # ── Royaume-Uni ──────────────────────────────────────────────────────────────
    _make_apex("pfi",                  "Royaume-Uni", "Paul Fletcher International"),
    _make_apex("whiltonmill",          "Royaume-Uni", "Whilton Mill Karting"),
    _make_apex("buckmore",             "Royaume-Uni", "Buckmore Park Kart Circuit"),
    _make_apex("gyg",                  "Royaume-Uni", "Glan Y Gors, Pays de Galles"),
    _make_apex("claypigeon",           "Royaume-Uni", "Clay Pigeon Raceway"),
    _make_apex("larkhall",             "Royaume-Uni", "Larkhall Circuit, Écosse"),
    # ── États-Unis ───────────────────────────────────────────────────────────────
    _make_apex("orlandokartcenter",    "États-Unis",  "Orlando Kart Center, Floride"),
    _make_apex("gopro-motorplex",      "États-Unis",  "GoPro Motorplex, Mooresville"),
    _make_apex("amrmotorplex",         "États-Unis",  "AMR Motorplex, Homestead-Miami"),
    _make_apex("nola-motorsports-kart","États-Unis",  "NOLA Motorsports Park"),
    _make_apex("karting-palm-beach",   "États-Unis",  "Palm Beach Karting"),
    # ── Maroc ────────────────────────────────────────────────────────────────────
    _make_apex("marrakech-kart",       "Maroc",     "Atlas Karting Marrakech"),
    # ── Portugal ─────────────────────────────────────────────────────────────────
    _make_apex("algarve",              "Portugal",  "Kartódromo Internacional do Algarve"),
    # ── Autres ───────────────────────────────────────────────────────────────────
    _make_apex("steelring",            "République Tchèque", "Steel Ring, Třinec"),
    _make_apex("dubai-autodrome",      "Émirats Arabes Unis", "Dubai Autodrome Kartdrome"),
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["tested"] = {1: True, 0: False}.get(d.get("tested"))
    # has_tracks: remplace tracks_json dans les vues liste (tracks_json peut être volumineux)
    tracks_raw = d.pop("tracks_json", None)
    d["has_tracks"] = tracks_raw not in (None, "")
    return d


def _circuit_tz(c: dict) -> str:
    return COUNTRY_TZ.get(c.get("country", ""), "UTC")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS circuits (
                slug        TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                url         TEXT NOT NULL UNIQUE,
                port        INTEGER NOT NULL,
                ws_host     TEXT NOT NULL,
                country     TEXT NOT NULL DEFAULT '',
                timezone    TEXT NOT NULL DEFAULT 'UTC',
                tested      INTEGER DEFAULT NULL,
                tracks_json TEXT DEFAULT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS circuit_test_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                slug      TEXT NOT NULL,
                tested_at TEXT NOT NULL,
                reachable INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_testlog_slug ON circuit_test_log(slug)")
        # Migrations: colonnes ajoutées après la v1
        for col, defn in [
            ("tested",      "INTEGER DEFAULT NULL"),
            ("timezone",    "TEXT NOT NULL DEFAULT 'UTC'"),
            ("tracks_json", "TEXT DEFAULT NULL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE circuits ADD COLUMN {col} {defn}")
            except Exception:
                pass
        # Nettoyer les orphelins live.apex-timing.com jamais découverts (port=0)
        # Ne pas supprimer ceux avec un port valide — ça réinitialiserait tested=NULL à chaque restart
        conn.execute("DELETE FROM circuits WHERE url LIKE '%live.apex-timing.com%' AND port <= 0")
        # Migrations de slug (ancienne valeur → nouvelle)
        conn.execute("UPDATE circuits SET slug='mrkagadir' WHERE slug='agadir' AND url LIKE '%mrkagadir%'")
        # UPSERT: update URL/host/name/country, préserve port et tracks déjà découverts
        # Déduplique par URL (SEED_CIRCUITS en premier — port déjà connu prioritaire)
        _seen_urls: set = set()
        all_seeds = []
        for _c in SEED_CIRCUITS + SEED_CIRCUITS_LIVE:
            if _c["url"] not in _seen_urls:
                _seen_urls.add(_c["url"])
                all_seeds.append(_c)
        conn.executemany(
            """
            INSERT INTO circuits (slug, name, url, port, ws_host, country, timezone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                url      = excluded.url,
                ws_host  = excluded.ws_host,
                name     = CASE WHEN excluded.name != '' THEN excluded.name ELSE circuits.name END,
                country  = CASE WHEN excluded.country != '' THEN excluded.country ELSE circuits.country END,
                timezone = excluded.timezone,
                port     = CASE WHEN excluded.port > 0 THEN excluded.port ELSE circuits.port END
            """,
            [(c["slug"], c["name"], c["url"], c["port"], c["ws_host"], c.get("country", ""), _circuit_tz(c))
             for c in all_seeds],
        )
        # Backfill timezone pour les circuits existants encore à 'UTC' par défaut
        for c in SEED_CIRCUITS:
            tz = _circuit_tz(c)
            if tz != "UTC":
                conn.execute(
                    "UPDATE circuits SET timezone = ? WHERE slug = ? AND timezone = 'UTC'",
                    (tz, c["slug"]),
                )


def get_all() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM circuits ORDER BY country, name").fetchall()
    return [_to_dict(r) for r in rows]


def get_untested() -> list[dict]:
    """Circuits jamais testés (tested IS NULL) ou en échec (tested = 0)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM circuits WHERE tested IS NULL OR tested = 0"
        ).fetchall()
    return [_to_dict(r) for r in rows]


def get_undiscovered(limit: int = 5) -> list[dict]:
    """Circuits avec port=0 (jamais tenté) ou port=-1 (échec précédent, à réessayer)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM circuits WHERE port <= 0 ORDER BY port DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_to_dict(r) for r in rows]


def update_port(slug: str, port: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE circuits SET port = ? WHERE slug = ?", (port, slug))


def get_tracks(slug: str) -> Optional[str]:
    """Retourne le JSON brut de tracks_json pour un slug, ou None si absent."""
    with _conn() as conn:
        row = conn.execute("SELECT tracks_json FROM circuits WHERE slug = ?", (slug,)).fetchone()
    return row[0] if row else None


def update_tracks(slug: str, tracks_json: str) -> None:
    with _conn() as conn:
        conn.execute("UPDATE circuits SET tracks_json = ? WHERE slug = ?", (tracks_json, slug))


def get_without_tracks(limit: int = 10) -> list[dict]:
    """Circuits sans tracks_json encore récupérés (NULL), port != -1."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM circuits WHERE tracks_json IS NULL AND port != -1 LIMIT ?",
            (limit,),
        ).fetchall()
    return [_to_dict(r) for r in rows]


def get_stats() -> dict:
    with _conn() as conn:
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN port > 0 THEN 1 ELSE 0 END) as discovered,
                SUM(CASE WHEN port = 0 THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN port = -1 THEN 1 ELSE 0 END) as failed
            FROM circuits
        """).fetchone()
        recent = conn.execute(
            "SELECT * FROM circuits WHERE port > 0 ORDER BY rowid DESC LIMIT 30"
        ).fetchall()
    return {
        "total": row[0],
        "discovered": row[1] or 0,
        "pending": row[2] or 0,
        "failed": row[3] or 0,
        "recent": [_to_dict(r) for r in recent],
    }


def set_tested(slug: str, reachable: bool) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _conn() as conn:
        conn.execute(
            "UPDATE circuits SET tested = ? WHERE slug = ?",
            (1 if reachable else 0, slug),
        )
        conn.execute(
            "INSERT INTO circuit_test_log (slug, tested_at, reachable) VALUES (?, ?, ?)",
            (slug, now, 1 if reachable else 0),
        )


def get_test_log(limit: int = 200) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("""
            SELECT l.id, l.slug, c.name, l.tested_at, l.reachable
            FROM circuit_test_log l
            LEFT JOIN circuits c ON c.slug = l.slug
            ORDER BY l.id DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_by_url(url: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM circuits WHERE url = ?", (url,)).fetchone()
        if not row:
            # Fallback: le dernier segment de l'URL peut correspondre au slug
            # ex: /live-timing/mariembourg/ → slug "mariembourg" → trouve karting-mariembourg
            seg = url.rstrip("/").split("/")[-1]
            row = conn.execute("SELECT * FROM circuits WHERE slug = ?", (seg,)).fetchone()
    return _to_dict(row) if row else None


def get_by_slug(slug: str) -> Optional[dict]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM circuits WHERE slug = ?", (slug,)).fetchone()
    return _to_dict(row) if row else None


def upsert(circuit: dict) -> dict:
    tz = circuit.get("timezone") or _circuit_tz(circuit)
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO circuits (slug, name, url, port, ws_host, country, timezone)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name     = excluded.name,
                url      = excluded.url,
                port     = excluded.port,
                ws_host  = excluded.ws_host,
                country  = excluded.country,
                timezone = excluded.timezone
            """,
            (circuit["slug"], circuit["name"], circuit["url"],
             circuit["port"], circuit["ws_host"], circuit.get("country", ""), tz),
        )
    return get_by_slug(circuit["slug"])


def get_by_slug_full(slug: str) -> Optional[dict]:
    """Comme get_by_slug mais inclut tracks_json brut (non strippé)."""
    with _conn() as conn:
        row = conn.execute("SELECT * FROM circuits WHERE slug = ?", (slug,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["tested"] = {1: True, 0: False}.get(d.get("tested"))
    return d


def delete(slug: str) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM circuits WHERE slug = ?", (slug,))
    return cur.rowcount > 0
