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

    # ── Lifecycle (Phase C) ────────────────────────────────────────────
    # Weekly audit fires sundays 23:55 in the service's TZ; %-PnL of the
    # last 7 d (first→last equity_history reading) must clear this
    # number or the strategy gets retired + lesson-embedded.
    weekly_audit_cron: str = field(default_factory=lambda: os.getenv(
        "FINANCE_GURU_WEEKLY_AUDIT_CRON", "55 23 * * 0").strip())
    weekly_audit_target_pct: float = field(default_factory=lambda: float(os.getenv(
        "FINANCE_GURU_TARGET_WEEK_PCT", "10.0")))
    weekly_audit_min_samples: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_AUDIT_MIN_SAMPLES", "50")))
    # Auto-archive housekeeping cron (daily at 04:10).
    auto_archive_cron: str = field(default_factory=lambda: os.getenv(
        "FINANCE_GURU_AUTO_ARCHIVE_CRON", "10 4 * * *").strip())
    # The lesson model is intentionally on the heavy alias — cost is
    # disciplined to <= 1 call per retired strategy per week (§10
    # AGENT-OPERATIONS).
    lesson_llm_model: str = field(default_factory=lambda: os.getenv(
        "FINANCE_GURU_LESSON_LLM_MODEL", "reasoning"))
    lesson_llm_timeout: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_LESSON_LLM_TIMEOUT", "300")))

    # ── Strategy genesis (Phase D) ─────────────────────────────────────
    # When n8n posts a DSL proposal, finance-guru-api auto-backtests it
    # over the last N days. If the realised PnL clears the gate AND
    # produced enough trades, the strategy gets auto-promoted to live;
    # otherwise it's archived with a deterministic reason. Set
    # genesis_min_backtest_pct to a NEGATIVE number to disable the
    # promotion gate (every proposal becomes live — useful for the
    # initial run when no relations have been built yet).
    genesis_backtest_days: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_GENESIS_BT_DAYS", "30")))
    genesis_backtest_step_minutes: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_GENESIS_BT_STEP_MIN", "60")))
    genesis_backtest_universe_limit: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_GENESIS_BT_UNIVERSE", "40")))
    genesis_min_backtest_pct: float = field(default_factory=lambda: float(os.getenv(
        "FINANCE_GURU_GENESIS_MIN_BT_PCT", "4.0")))
    genesis_min_backtest_trades: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_GENESIS_MIN_BT_TRADES", "5")))
    # Genesis safety quota: maximum number of `kind='generated'` proposals
    # accepted within a rolling window. 0 disables the quota (back-compat
    # for the original Phase D ship). The default 25/7d matches the cron
    # cadence (4/day × 7d ≈ 28) with a small margin for manual retries.
    genesis_quota_per_window: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_GENESIS_QUOTA", "25")))
    genesis_quota_window_days: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_GENESIS_QUOTA_WINDOW_DAYS", "7")))

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

