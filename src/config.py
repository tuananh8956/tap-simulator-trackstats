from dataclasses import dataclass
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

@dataclass
class Settings:
    port: int = 3883
    host: str = "0.0.0.0"
    db_path: str = str(BASE_DIR / "trackstats.db")
    stale_timeout_sec: float = 15.0
    disconnect_timeout_sec: float = 60.0
    poller_interval_sec: float = 5.0
    rate_window_max_sec: int = 900  # 15 minutes
    target_place_id: int = 72858262610964  # Tap Simulator REBORN
    target_universe_id: int = 10629695169

settings = Settings()
