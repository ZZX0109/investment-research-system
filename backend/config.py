from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PASSWORD_POLICY_TEXT = "Password must be at least 8 characters and include lowercase, uppercase, digit, and special character."
SYNTHETIC_HISTORY_SOURCE = "synthetic_demo_price_path"
DATA_MODES = {"demo", "sandbox", "real"}


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_db_path() -> Path:
    explicit = os.getenv("INVESTMENT_RESEARCH_DB_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    return DATA_DIR / "investment_research.sqlite3"


def resolve_data_mode() -> str:
    value = os.getenv("INVESTMENT_RESEARCH_DATA_MODE", "demo").strip().lower()
    return value if value in DATA_MODES else "demo"
