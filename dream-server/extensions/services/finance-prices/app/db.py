"""TimescaleDB access for finance-prices.

Owns the connection pool and the (idempotent) startup migration.
The init SQL inside `extensions/services/timescaledb/init/01-schema.sql`
runs ONCE on first DB boot; everything in here must be safe to run on
every container restart.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import psycopg
from psycopg_pool import ConnectionPool

log = logging.getLogger("finance-prices.db")


@dataclass
class DbConfig:
    host: str = field(default_factory=lambda: os.getenv("TIMESCALEDB_HOST", "timescaledb"))
    port: int = field(default_factory=lambda: int(os.getenv("TIMESCALEDB_PORT_INTERNAL", "5432")))
    user: str = field(default_factory=lambda: os.getenv("TIMESCALEDB_USER", "finance"))
    password: str = field(default_factory=lambda: os.getenv("TIMESCALEDB_PASSWORD", ""))
    dbname: str = field(default_factory=lambda: os.getenv("TIMESCALEDB_DB", "finance"))
    min_size: int = 1
    max_size: int = 4

    @property
    def conninfo(self) -> str:
        return (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.dbname} application_name=finance-prices"
        )


_pool: ConnectionPool | None = None


def get_pool(cfg: DbConfig) -> ConnectionPool:
    global _pool
    if _pool is None:
        log.info("Opening TimescaleDB pool to %s:%s/%s", cfg.host, cfg.port, cfg.dbname)
        _pool = ConnectionPool(
            cfg.conninfo,
            min_size=cfg.min_size,
            max_size=cfg.max_size,
            kwargs={"autocommit": False},
            open=True,
        )
    return _pool


@contextmanager
def conn(cfg: DbConfig):
    pool = get_pool(cfg)
    with pool.connection() as c:
        yield c


# --------------------------------------------------------------------------- #
# Idempotent startup migration
# --------------------------------------------------------------------------- #
# The init SQL handles a fresh DB. This block tolerates an upgrade where a
# previous version of the service ran against a DB that already exists but
# is missing newer columns/policies.
STARTUP_MIGRATION_SQL = """
CREATE SCHEMA IF NOT EXISTS finance;

CREATE TABLE IF NOT EXISTS finance.prices_intraday (
    symbol      TEXT        NOT NULL,
    asset_type  TEXT        NOT NULL CHECK (asset_type IN ('stock', 'crypto')),
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION,
    source      TEXT        NOT NULL,
    currency    TEXT        NOT NULL DEFAULT 'USD',
    PRIMARY KEY (symbol, asset_type, ts)
);

SELECT create_hypertable(
    'finance.prices_intraday', 'ts',
    chunk_time_interval => INTERVAL '1 day',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_prices_intraday_symbol_ts
    ON finance.prices_intraday (symbol, ts DESC);
"""


def ensure_schema(cfg: DbConfig) -> None:
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.execute(STARTUP_MIGRATION_SQL)
        c.commit()
    log.info("Schema ensured (finance.prices_intraday)")


# --------------------------------------------------------------------------- #
# Bulk upsert
# --------------------------------------------------------------------------- #
UPSERT_SQL = """
INSERT INTO finance.prices_intraday
    (symbol, asset_type, ts, open, high, low, close, volume, source, currency)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (symbol, asset_type, ts) DO UPDATE SET
    open     = EXCLUDED.open,
    high     = EXCLUDED.high,
    low      = EXCLUDED.low,
    close    = EXCLUDED.close,
    volume   = EXCLUDED.volume,
    source   = EXCLUDED.source,
    currency = EXCLUDED.currency
"""


def upsert_bars(cfg: DbConfig, rows: Sequence[tuple]) -> int:
    """rows: (symbol, asset_type, ts, open, high, low, close, volume, source, currency).
    Returns the number of rows submitted."""
    if not rows:
        return 0
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
        c.commit()
    return len(rows)


def row_count(cfg: DbConfig) -> int:
    """Approximate row count via TimescaleDB chunk metadata (cheap)."""
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(SUM(num_rows), 0)::bigint
                FROM (
                    SELECT (approximate_row_count('finance.prices_intraday')) AS num_rows
                ) AS t
                """
            )
            (n,) = cur.fetchone()
            return int(n or 0)


def latest_ts(cfg: DbConfig) -> str | None:
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.execute("SELECT max(ts) FROM finance.prices_intraday")
            (ts,) = cur.fetchone()
            return ts.isoformat() if ts else None

