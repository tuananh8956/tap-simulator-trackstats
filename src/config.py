from dataclasses import dataclass
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _parse_bool(val: str, default: bool = True) -> bool:
    raw = (val or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


@dataclass
class Settings:
    port: int = int(os.environ.get("PORT", os.environ.get("TRACKSTATS_PORT", "3883")))
    host: str = os.environ.get("HOST", "0.0.0.0")
    db_path: str = os.environ.get("TRACKSTATS_DB_PATH", str(BASE_DIR / "trackstats.db"))
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    ingest_key: str = os.environ.get("TRACKSTATS_INGEST_KEY", "").strip()
    admin_password: str = os.environ.get("TRACKSTATS_ADMIN_PASSWORD", "").strip()
    public_read: bool = _parse_bool(os.environ.get("TRACKSTATS_PUBLIC_READ", "true"), default=True)
    stale_timeout_sec: float = 15.0
    disconnect_timeout_sec: float = 60.0
    poller_interval_sec: float = 5.0
    rate_window_max_sec: int = 900  # 15 minutes
    target_place_id: int = 72858262610964  # Tap Simulator REBORN
    target_universe_id: int = 10629695169


settings = Settings()
