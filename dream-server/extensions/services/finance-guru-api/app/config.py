"""Centralised env-driven config for the finance-guru-api service.

Anything tunable lives here so individual modules don't sprinkle
os.getenv calls across the codebase.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class GuruConfig:
    # ── DB (read-only against TimescaleDB built in step 1) ─────────────
    db_host: str       = field(default_factory=lambda: os.getenv("TIMESCALEDB_HOST", "timescaledb"))
    db_port: int       = field(default_factory=lambda: int(os.getenv("TIMESCALEDB_PORT_INTERNAL", "5432")))
    db_user: str       = field(default_factory=lambda: os.getenv("TIMESCALEDB_USER", "finance"))
    db_password: str   = field(default_factory=lambda: os.getenv("TIMESCALEDB_PASSWORD", ""))
    db_name: str       = field(default_factory=lambda: os.getenv("TIMESCALEDB_DB", "finance"))

    # ── Ledger (SQLite, persistent on /data) ───────────────────────────
    ledger_path: str   = field(default_factory=lambda: os.getenv("FINANCE_GURU_LEDGER_PATH", "/data/ledger.sqlite"))
    seed_eur: float    = field(default_factory=lambda: float(os.getenv("FINANCE_GURU_SEED_EUR", "1000")))

    # ── LLM (used by news_sentiment etc.) ──────────────────────────────
    llm_url: str       = field(default_factory=lambda: os.getenv("LITELLM_URL", "http://litellm:4000/v1"))
    llm_api_key: str   = field(default_factory=lambda: os.getenv("LITELLM_API_KEY", ""))
    llm_model: str     = field(default_factory=lambda: os.getenv("FINANCE_GURU_LLM_MODEL", "fast"))

    # ── Scheduler ───────────────────────────────────────────────────────
    cron: str          = field(default_factory=lambda: os.getenv("FINANCE_GURU_CRON", "*/30 * * * *").strip())
    tz: str            = field(default_factory=lambda: os.getenv("FINANCE_GURU_TZ", "UTC"))

    # ── Strategy plugin selection ──────────────────────────────────────
    strategies_raw: str = field(default_factory=lambda: os.getenv("FINANCE_GURU_STRATEGIES", "all"))

    # ── Risk / sizing ──────────────────────────────────────────────────
    max_position_frac: float = field(default_factory=lambda: float(os.getenv("FINANCE_GURU_MAX_POSITION_FRAC", "0.10")))
    fee_bps: float           = field(default_factory=lambda: float(os.getenv("FINANCE_GURU_FEE_BPS", "10")))

    # ── API auth ───────────────────────────────────────────────────────
    api_token: str     = field(default_factory=lambda: os.getenv("FINANCE_GURU_TOKEN", "").strip())

    @property
    def enabled_strategies(self) -> set[str] | None:
        """Returns the explicit allow-list, or None for 'all'."""
        raw = self.strategies_raw.strip().lower()
        if raw in ("", "all", "*"):
            return None
        return {s.strip() for s in raw.split(",") if s.strip()}

    @property
    def db_conninfo(self) -> str:
        return (
            f"host={self.db_host} port={self.db_port} user={self.db_user} "
            f"password={self.db_password} dbname={self.db_name} application_name=finance-guru"
        )


CFG = GuruConfig()

