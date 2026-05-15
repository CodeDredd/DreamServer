"""Runtime config — env-driven."""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    port: int
    db_path: str
    fetch_cron: str
    tz: str
    auto_generate: bool
    api_token: str
    fetch_timeout_sec: int
    user_agent: str
    retention_years: int
    seed_dir: str


CFG = Config(
    port=_env_int("LOTTO_ORACLE_PORT", 8099),
    db_path=os.environ.get("LOTTO_ORACLE_DB_PATH", "/data/lotto.sqlite").strip(),
    fetch_cron=os.environ.get("LOTTO_ORACLE_FETCH_CRON", "30 3 * * 1,4").strip(),
    tz=os.environ.get("LOTTO_ORACLE_TZ", "Europe/Berlin").strip() or "Europe/Berlin",
    auto_generate=_env_bool("LOTTO_ORACLE_AUTO_GENERATE", True),
    api_token=os.environ.get("LOTTO_ORACLE_TOKEN", "").strip(),
    fetch_timeout_sec=_env_int("LOTTO_FETCH_TIMEOUT_SEC", 20),
    user_agent=os.environ.get(
        "LOTTO_FETCH_USER_AGENT",
        "DreamServerLottoOracle/0.1 (+https://github.com/Light-Heart-Labs/DreamServer)",
    ).strip(),
    retention_years=_env_int("LOTTO_RETENTION_YEARS", 30),
    seed_dir=os.environ.get("LOTTO_ORACLE_SEED_DIR", "/seed").strip(),
)

