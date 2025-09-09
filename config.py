from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict

_CONFIG_PATH = "config.json"

@dataclass
class BotConfig:
    league_id: str | None = None
    announce_channel_id: int | None = None
    announce_role_id: int | None = None
    default_days: int = 7

    # preview scheduling
    schedule_enabled: bool = False
    schedule_dow: int = 2          # Wed
    schedule_hour: int = 9
    schedule_minute: int = 0

    # results scheduling
    results_enabled: bool = False
    results_dow: int = 1           # Tue
    results_hour: int = 9
    results_minute: int = 0

def load_config() -> BotConfig:
    if not os.path.exists(_CONFIG_PATH):
        return BotConfig()
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return BotConfig(**data)
    except Exception:
        return BotConfig()

def save_config(cfg: BotConfig) -> None:
    tmp = _CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, indent=2)
    os.replace(tmp, _CONFIG_PATH)
