import json
from sqlalchemy.orm import Session
from models import Config, ConfigSchema

_DEFAULTS = ConfigSchema().model_dump()


def get_config(db: Session) -> ConfigSchema:
    rows = db.query(Config).all()
    data = dict(_DEFAULTS)
    for row in rows:
        if row.key in data:
            raw = row.value
            if isinstance(data[row.key], bool):
                data[row.key] = raw.lower() == "true"
            elif isinstance(data[row.key], int):
                data[row.key] = int(raw)
            elif isinstance(data[row.key], float):
                data[row.key] = float(raw)
            else:
                data[row.key] = raw
    return ConfigSchema(**data)


def set_config(db: Session, updates: dict) -> ConfigSchema:
    for key, val in updates.items():
        if key not in _DEFAULTS:
            continue
        row = db.query(Config).filter(Config.key == key).first()
        str_val = str(val)
        if row:
            row.value = str_val
        else:
            db.add(Config(key=key, value=str_val))
    db.commit()
    return get_config(db)
