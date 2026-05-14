"""TimescaleDB sink for finance-social.

Owns the Postgres connection pool, an idempotent startup migration that
mirrors `social.events` (the init SQL inside the timescaledb service
runs only on first boot — this block is the rolling-upgrade safety
net), and bulk upsert helpers.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Sequence

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

log = logging.getLogger("finance-social.db")


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
            f"password={self.password} dbname={self.dbname} application_name=finance-social"
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
# Idempotent startup migration — must stay byte-equivalent to the
# corresponding block in
#   extensions/services/timescaledb/init/01-schema.sql
# --------------------------------------------------------------------------- #
STARTUP_MIGRATION_SQL = """
CREATE SCHEMA IF NOT EXISTS social;

CREATE TABLE IF NOT EXISTS social.events (
    id            TEXT        NOT NULL,
    ts            TIMESTAMPTZ NOT NULL,
    source        TEXT        NOT NULL,
    channel       TEXT,
    author        TEXT,
    symbols       TEXT[]      NOT NULL DEFAULT '{}',
    score         INTEGER,
    num_comments  INTEGER,
    sentiment     REAL,
    urgency       REAL,
    title         TEXT,
    url           TEXT,
    payload       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, ts)
);

SELECT create_hypertable(
    'social.events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_social_symbols_ts
    ON social.events USING GIN (symbols);
CREATE INDEX IF NOT EXISTS idx_social_source_ts
    ON social.events (source, channel, ts DESC);
"""


def ensure_schema(cfg: DbConfig) -> None:
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.execute(STARTUP_MIGRATION_SQL)
        c.commit()
    log.info("Schema ensured (social.events)")


# --------------------------------------------------------------------------- #
# Dedup
# --------------------------------------------------------------------------- #
def existing_ids(cfg: DbConfig, ids: Sequence[str], lookback: dt.timedelta) -> set[str]:
    if not ids:
        return set()
    cutoff = dt.datetime.now(dt.timezone.utc) - lookback
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.execute(
                "SELECT id FROM social.events WHERE id = ANY(%s) AND ts >= %s",
                (list(ids), cutoff),
            )
            return {r[0] for r in cur.fetchall()}


# --------------------------------------------------------------------------- #
# Bulk upsert
# --------------------------------------------------------------------------- #
UPSERT_SQL = """
INSERT INTO social.events
    (id, ts, source, channel, author, symbols,
     score, num_comments, sentiment, urgency, title, url, payload)
VALUES (%s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id, ts) DO UPDATE SET
    source       = EXCLUDED.source,
    channel      = EXCLUDED.channel,
    author       = EXCLUDED.author,
    symbols      = EXCLUDED.symbols,
    score        = COALESCE(EXCLUDED.score,        social.events.score),
    num_comments = COALESCE(EXCLUDED.num_comments, social.events.num_comments),
    sentiment    = COALESCE(EXCLUDED.sentiment,    social.events.sentiment),
    urgency      = COALESCE(EXCLUDED.urgency,      social.events.urgency),
    title        = EXCLUDED.title,
    url          = EXCLUDED.url,
    payload      = EXCLUDED.payload
"""


def upsert_events(cfg: DbConfig, events: Sequence[dict]) -> int:
    if not events:
        return 0
    rows = []
    for e in events:
        rows.append((
            e["id"],
            e["ts"],
            e["source"],
            e.get("channel"),
            e.get("author"),
            e.get("symbols") or [],
            e.get("score"),
            e.get("num_comments"),
            e.get("sentiment"),
            e.get("urgency"),
            e.get("title"),
            e.get("url"),
            Jsonb(e.get("payload") or {}),
        ))
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.executemany(UPSERT_SQL, rows)
        c.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Stats for /status
# --------------------------------------------------------------------------- #
def stats(cfg: DbConfig) -> dict:
    with conn(cfg) as c:
        with c.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT approximate_row_count('social.events'))::bigint AS rows_estimate,
                    (SELECT max(ts) FROM social.events)                     AS latest_ts,
                    (SELECT count(*) FROM social.events
                       WHERE ts >= now() - INTERVAL '24 hours')             AS rows_last_24h
                """
            )
            row = cur.fetchone()
    return {
        "rows_estimate": int(row[0] or 0),
        "latest_ts": row[1].isoformat() if row[1] else None,
        "rows_last_24h": int(row[2] or 0),
    }

