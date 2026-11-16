from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


@dataclass(slots=True)
class AppConfig:
    refresh_seconds: int = 2
    ping_host: str = "1.1.1.1"
    ping_timeout_ms: int = 1200
    database_url: str = f"sqlite:///{(DATA_DIR / 'wifi_guardian.db').as_posix()}"
    history_limit: int = 180


CONFIG = AppConfig()

