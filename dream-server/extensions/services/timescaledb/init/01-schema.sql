-- =====================================================================
-- TimescaleDB initial schema for the Dream Server finance pipeline.
--
-- Runs ONCE on first container boot (when /var/lib/postgresql/data is
-- empty). Subsequent schema changes belong in the producing services'
-- startup migrations (idempotent CREATE … IF NOT EXISTS), NOT here.
--
-- Conventions:
--   * One hypertable per "raw event stream" (prices_intraday, news,
--     social).
--   * Retention + compression policies sized for a free-tier home box
--     (Halo Strix); tune via env later if storage budget changes.
--   * All timestamps are TIMESTAMPTZ in UTC. Convert to local in the
--     dashboard layer.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------
-- 1. Schemas
-- ---------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS news;
CREATE SCHEMA IF NOT EXISTS guru;     -- reserved for finance-guru-api ledgers

-- ---------------------------------------------------------------------
-- 2. Intraday OHLCV (written by finance-prices, every 5–15 min)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS finance.prices_intraday (
    symbol      TEXT        NOT NULL,
    asset_type  TEXT        NOT NULL CHECK (asset_type IN ('stock', 'crypto')),
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION NOT NULL,
    volume      DOUBLE PRECISION,
    source      TEXT        NOT NULL,        -- 'yfinance' | 'coingecko'
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

-- Compression: chunks older than 7 days get compressed (~10x smaller).
ALTER TABLE finance.prices_intraday SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol, asset_type',
    timescaledb.compress_orderby   = 'ts DESC'
);

SELECT add_compression_policy('finance.prices_intraday', INTERVAL '7 days',
                              if_not_exists => TRUE);

-- Retention: drop intraday data older than 90 days.
-- Daily aggregates (below) keep the long history.
SELECT add_retention_policy('finance.prices_intraday', INTERVAL '90 days',
                            if_not_exists => TRUE);

-- ---------------------------------------------------------------------
-- 3. Daily OHLCV (continuous aggregate over intraday → kept 5y)
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS finance.prices_daily
WITH (timescaledb.continuous) AS
SELECT
    symbol,
    asset_type,
    time_bucket('1 day', ts)                AS day,
    first(open, ts)                          AS open,
    max(high)                                AS high,
    min(low)                                 AS low,
    last(close, ts)                          AS close,
    sum(volume)                              AS volume,
    count(*)                                 AS sample_count
FROM finance.prices_intraday
GROUP BY symbol, asset_type, day
WITH NO DATA;

SELECT add_continuous_aggregate_policy('finance.prices_daily',
    start_offset      => INTERVAL '7 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);

-- 5 years of daily candles is plenty for backtests on this hardware.
SELECT add_retention_policy('finance.prices_daily', INTERVAL '5 years',
                            if_not_exists => TRUE);

-- ---------------------------------------------------------------------
-- 4. News / social event timelines (written by finance-news/social later)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news.events (
    id         TEXT        NOT NULL,           -- stable hash of (source, url|guid)
    ts         TIMESTAMPTZ NOT NULL,
    source     TEXT        NOT NULL,           -- 'yahoo-rss' | 'reddit' | …
    channel    TEXT,                           -- subreddit, RSS feed, …
    symbols    TEXT[]      NOT NULL DEFAULT '{}',
    sentiment  REAL,                           -- -1.0 .. +1.0 (filled by qwen3-4b)
    urgency    REAL,                           --  0.0 ..  1.0
    title      TEXT,
    url        TEXT,
    payload    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, ts)
);

SELECT create_hypertable(
    'news.events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE
);

CREATE INDEX IF NOT EXISTS idx_news_symbols_ts
    ON news.events USING GIN (symbols);
CREATE INDEX IF NOT EXISTS idx_news_source_ts
    ON news.events (source, ts DESC);

ALTER TABLE news.events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source',
    timescaledb.compress_orderby   = 'ts DESC'
);

SELECT add_compression_policy('news.events', INTERVAL '14 days',
                              if_not_exists => TRUE);
SELECT add_retention_policy('news.events', INTERVAL '180 days',
                            if_not_exists => TRUE);

-- ---------------------------------------------------------------------
-- 5. Read-only role for the dashboard / external explorers
-- ---------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_ro') THEN
        CREATE ROLE finance_ro NOLOGIN;
    END IF;
END $$;

GRANT USAGE ON SCHEMA finance, news, guru TO finance_ro;
GRANT SELECT ON ALL TABLES    IN SCHEMA finance, news, guru TO finance_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance, news, guru
    GRANT SELECT ON TABLES TO finance_ro;

