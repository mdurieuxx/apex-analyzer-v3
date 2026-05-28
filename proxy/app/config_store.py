"""
Persistent settings for the proxy — backed by a JSON file in RECORDINGS_DIR.
All values fall back to DEFAULTS when missing or on read error.
"""
import json
import logging
import os
from pathlib import Path

_SETTINGS_FILE = Path(os.environ.get("RECORDINGS_DIR", "/data/recordings")) / "settings.json"

DEFAULTS: dict = {
    # Session active scan
    "scan_interval_s": 60,
    "probe_timeout_s": 5.0,
    "ws_connect_timeout_s": 3,
    "scan_workers": 30,
    # Port discovery
    "discovery_interval_s": 60,
    "discovery_batch_size": 5,
    "discovery_idle_s": 3600,
    # Circuit connectivity tester
    "tester_retry_s": 1800,
    # Logging
    "log_level": "INFO",
}

_current: dict = {}

logger = logging.getLogger(__name__)


def load() -> dict:
    global _current
    try:
        data = json.loads(_SETTINGS_FILE.read_text())
        _current = {**DEFAULTS, **{k: data[k] for k in DEFAULTS if k in data}}
    except Exception:
        _current = dict(DEFAULTS)
    return _current


def get(key: str):
    if not _current:
        load()
    return _current.get(key, DEFAULTS[key])


def get_all() -> dict:
    if not _current:
        load()
    return {**DEFAULTS, **_current}


def save(updates: dict) -> dict:
    global _current
    if not _current:
        load()
    for k, v in updates.items():
        if k in DEFAULTS:
            _current[k] = v
    try:
        _SETTINGS_FILE.write_text(json.dumps(_current, indent=2))
    except Exception as e:
        logger.warning("config_store save failed: %s", e)
    return get_all()
