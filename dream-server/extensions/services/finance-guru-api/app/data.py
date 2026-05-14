"""Read-only TimescaleDB queries for prices and news.

Strategies receive pandas DataFrames from these helpers; everything is
read-only — finance-guru-api never writes back to the time-series.

The DB connection is pooled via psycopg_pool.
"""
from __future__ import annotations

import datetime as dt
import logging
from contextlib import contextmanager
from typing import Iterable

import pandas as pd
from psycopg_pool import ConnectionPool

from .config import CFG

log = logging.getLogger("finance-guru.data")


_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        log.info("Opening read-only TimescaleDB pool to %s:%s/%s",
                 CFG.db_host, CFG.db_port, CFG.db_name)
        _pool = ConnectionPool(
            CFG.db_conninfo,
            min_size=1, max_size=4,
            kwargs={"autocommit": True},
            open=True,
        )
    return _pool


@contextmanager
def conn():
    with get_pool().connection() as c:
        yield c


def wait_until_ready(retries: int = 20, sleep: float = 3.0) -> bool:
    import time
    for i in range(retries):
        try:
            with conn() as c, c.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("DB not ready (%s) — retry %d/%d", exc, i + 1, retries)
            time.sleep(sleep)
    return False


# --------------------------------------------------------------------------- #
# Universe (cheap — small static set per strategy)
# --------------------------------------------------------------------------- #
def list_symbols(asset_type: str | None = None,
                 since: dt.timedelta = dt.timedelta(hours=24)) -> list[str]:
    """Symbols that have at least one tick in the recent window —
    everything else is dead-weight for live decisions."""
    with conn() as c, c.cursor() as cur:
        if asset_type:
            cur.execute(
                """SELECT DISTINCT symbol FROM finance.prices_intraday
                   WHERE asset_type = %s AND ts >= now() - %s
                   ORDER BY symbol""",
                (asset_type, since),
            )
        else:
            cur.execute(
                """SELECT DISTINCT symbol FROM finance.prices_intraday
                   WHERE ts >= now() - %s ORDER BY symbol""",
                (since,),
            )
        return [r[0] for r in cur.fetchall()]


# --------------------------------------------------------------------------- #
# Prices
# --------------------------------------------------------------------------- #
def latest_prices(symbols: Iterable[str] | None = None) -> dict[str, float]:
    """Most recent close per symbol (intraday hypertable). Returns
    {sym: close}. If symbols=None, returns *all* tickers seen in the
    last hour."""
    syms = list(symbols) if symbols else None
    sql = """
        SELECT DISTINCT ON (symbol) symbol, close
        FROM finance.prices_intraday
        WHERE ts >= now() - INTERVAL '6 hours'
    """
    args: tuple = ()
    if syms:
        sql += " AND symbol = ANY(%s)"
        args = (syms,)
    sql += " ORDER BY symbol, ts DESC"
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, args)
        return {sym: float(close) for sym, close in cur.fetchall()}


def price_history(symbols: Iterable[str], lookback: dt.timedelta) -> pd.DataFrame:
    """Returns a long-format DataFrame: (ts, symbol, open, high, low, close, volume)."""
    syms = list(symbols)
    if not syms:
        return pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT ts, symbol, open, high, low, close, volume
               FROM finance.prices_intraday
               WHERE symbol = ANY(%s) AND ts >= now() - %s
               ORDER BY symbol, ts""",
            (syms, lookback),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def price_history_at(symbols: Iterable[str], end: dt.datetime,
                      lookback: dt.timedelta) -> pd.DataFrame:
    """Same as price_history() but anchored at a historical timestamp
    (used by backtests)."""
    syms = list(symbols)
    if not syms:
        return pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
    start = end - lookback
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT ts, symbol, open, high, low, close, volume
               FROM finance.prices_intraday
               WHERE symbol = ANY(%s) AND ts BETWEEN %s AND %s
               ORDER BY symbol, ts""",
            (syms, start, end),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows, columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


# --------------------------------------------------------------------------- #
# News
# --------------------------------------------------------------------------- #
def recent_news(lookback: dt.timedelta = dt.timedelta(hours=24),
                symbols: Iterable[str] | None = None,
                min_sentiment_abs: float | None = None) -> pd.DataFrame:
    """Headlines from news.events with optional sentiment filter."""
    sql = ["""SELECT id, ts, source, channel, symbols, sentiment, urgency, title, url
              FROM news.events
              WHERE ts >= now() - %s"""]
    args: list = [lookback]
    if symbols:
        sql.append("AND symbols && %s")
        args.append(list(symbols))
    if min_sentiment_abs is not None:
        sql.append("AND abs(sentiment) >= %s")
        args.append(min_sentiment_abs)
    sql.append("ORDER BY ts DESC")
    with conn() as c, c.cursor() as cur:
        cur.execute(" ".join(sql), tuple(args))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=[
        "id", "ts", "source", "channel", "symbols", "sentiment", "urgency", "title", "url"
    ])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def news_at(end: dt.datetime, lookback: dt.timedelta,
            symbols: Iterable[str] | None = None) -> pd.DataFrame:
    sql = ["""SELECT id, ts, source, channel, symbols, sentiment, urgency, title, url
              FROM news.events
              WHERE ts BETWEEN %s AND %s"""]
    args: list = [end - lookback, end]
    if symbols:
        sql.append("AND symbols && %s")
        args.append(list(symbols))
    sql.append("ORDER BY ts")
    with conn() as c, c.cursor() as cur:
        cur.execute(" ".join(sql), tuple(args))
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=[
        "id", "ts", "source", "channel", "symbols", "sentiment", "urgency", "title", "url"
    ])
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def history_extent() -> dict:
    """Reports the available time range of prices_intraday — used by
    /backtest defaults."""
    with conn() as c, c.cursor() as cur:
        cur.execute("SELECT min(ts), max(ts), count(DISTINCT symbol) FROM finance.prices_intraday")
        mn, mx, n = cur.fetchone()
    return {
        "min_ts": mn.isoformat() if mn else None,
        "max_ts": mx.isoformat() if mx else None,
        "symbols": int(n or 0),
    }

