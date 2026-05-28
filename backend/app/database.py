from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
import os

DB_PATH = os.environ.get("DB_PATH", "/data/karting.db")
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations(eng=None):
    """Add missing columns to existing tables (SQLite ALTER TABLE ADD COLUMN)."""
    target = eng or engine
    with target.connect() as conn:
        _add_cols(conn, "events", {
            "best_lap_ms": "INTEGER",
            "best_lap_bib": "TEXT DEFAULT ''",
            "best_lap_pilot_name": "TEXT DEFAULT ''",
        })
        _add_cols(conn, "circuits", {
            "best_lap_ms": "INTEGER",
        })
        _add_cols(conn, "events", {
            "source": "TEXT DEFAULT 'live'",
            "proxy_ws_url": "TEXT DEFAULT ''",
        })
        _add_cols(conn, "event_pit_stops", {
            "kart_in_label": "TEXT DEFAULT ''",
            "kart_out_label": "TEXT",
        })
        _add_cols(conn, "events", {
            "circuit_id": "INTEGER REFERENCES circuits(id)",
        })
        _add_cols(conn, "circuits", {
            "min_pit_duration_s": "INTEGER",
            "min_relay_s":        "INTEGER",
            "max_relay_s":        "INTEGER",
        })
        _add_cols(conn, "events", {
            "event_key": "TEXT",
        })
        _add_cols(conn, "events", {
            "imported_through_t": "REAL",
        })
        conn.commit()


def _add_cols(conn, table: str, cols: dict):
    existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
    for col, definition in cols.items():
        if col not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {definition}"))
