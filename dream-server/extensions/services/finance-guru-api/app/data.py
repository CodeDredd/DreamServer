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


def recent_movers(window: dt.timedelta,
                  *,
                  min_abs_return_pct: float = 3.0,
                  asset_type: str | None = None,
                  limit: int = 10) -> list[dict]:
    """Symbols whose close moved at least ±`min_abs_return_pct` over
    the last `window`. Phase P-4 driver for the Price-Move-Causal-
    Explainer workflow.

    Per row:
      symbol, asset_type, window_start_close, latest_close,
      return_pct (signed), volume_ratio (latest-bar volume divided by
      median bar-volume of last 96 bars of same symbol — 1.0 ≈ normal,
      >2 ≈ unusual), latest_ts.

    Sorted by abs(return_pct) DESC. Returns at most `limit` rows.

    Implementation notes:
    * We compute the start price as the *latest tick ≤ now-window*
      (not the first tick after `now-window`) so a 1h window genuinely
      spans 1h even if the symbol just resumed trading 5 minutes in.
    * Volume baseline = median of last 96 bars (= 24h at 15-min cadence
      for stocks, ≈ 8h at 5-min for crypto). Cheap; one window-function
      pass.
    * Pure SQL on `finance.prices_intraday`. No Python aggregation per
      symbol → scales linearly with universe size, not with bar count.
    """
    # Clamp window to a sane range so SQL doesn't OOM on a freak input.
    win_seconds = max(60, min(int(window.total_seconds()), 7 * 24 * 3600))
    args: list = [win_seconds, win_seconds]
    type_filter = ""
    if asset_type:
        type_filter = "AND asset_type = %s"
        args.append(asset_type)
    args.extend([float(min_abs_return_pct), int(max(1, min(limit, 100)))])

    sql = f"""
        WITH win AS (
          SELECT symbol, asset_type,
                 -- latest tick within the window
                 (ARRAY_AGG(close ORDER BY ts DESC))[1] AS latest_close,
                 (ARRAY_AGG(volume ORDER BY ts DESC))[1] AS latest_volume,
                 MAX(ts) AS latest_ts,
                 -- close at the start of the window (nearest tick AT or BEFORE
                 -- now-window — fallback to first tick inside the window if no
                 -- earlier tick exists)
                 COALESCE(
                   (SELECT close FROM finance.prices_intraday p2
                      WHERE p2.symbol = p.symbol
                        AND p2.ts <= now() - make_interval(secs => %s)
                      ORDER BY p2.ts DESC LIMIT 1),
                   (ARRAY_AGG(close ORDER BY ts ASC))[1]
                 ) AS start_close
          FROM finance.prices_intraday p
          WHERE ts >= now() - make_interval(secs => %s)
                {type_filter}
          GROUP BY symbol, asset_type
        ),
        vol_base AS (
          SELECT symbol,
                 -- median of last 96 bars per symbol (TimescaleDB
                 -- has percentile_cont; fallback to AVG on plain PG)
                 percentile_cont(0.5) WITHIN GROUP (ORDER BY volume)
                   AS median_vol
          FROM (
            SELECT symbol, volume,
                   row_number() OVER (PARTITION BY symbol ORDER BY ts DESC) AS rn
            FROM finance.prices_intraday
            WHERE ts >= now() - INTERVAL '7 days'
          ) s
          WHERE rn <= 96
          GROUP BY symbol
        )
        SELECT w.symbol, w.asset_type, w.start_close, w.latest_close,
               ((w.latest_close - w.start_close) / NULLIF(w.start_close, 0) * 100.0)::float8
                 AS return_pct,
               CASE WHEN COALESCE(vb.median_vol, 0) > 0
                    THEN (w.latest_volume / vb.median_vol)::float8
                    ELSE NULL END AS volume_ratio,
               w.latest_ts
        FROM win w
        LEFT JOIN vol_base vb ON vb.symbol = w.symbol
        WHERE w.start_close IS NOT NULL
          AND w.latest_close IS NOT NULL
          AND ABS((w.latest_close - w.start_close) / NULLIF(w.start_close, 0) * 100.0)
              >= %s
        ORDER BY ABS((w.latest_close - w.start_close) / NULLIF(w.start_close, 0)) DESC
        LIMIT %s
    """
    with conn() as c, c.cursor() as cur:
        cur.execute(sql, tuple(args))
        rows = cur.fetchall()
    out: list[dict] = []
    for sym, at, sc, lc, rp, vr, lts in rows:
        out.append({
            "symbol":       sym,
            "asset_type":   at,
            "start_close":  float(sc) if sc is not None else None,
            "latest_close": float(lc) if lc is not None else None,
            "return_pct":   round(float(rp), 3) if rp is not None else None,
            "volume_ratio": round(float(vr), 3) if vr is not None else None,
            "latest_ts":    lts.isoformat() if lts is not None else None,
        })
    return out


# --------------------------------------------------------------------------- #
# Social — written by finance-social. Same column shape as news.events
# minus the sentiment-only quirks.
# --------------------------------------------------------------------------- #
def recent_social(lookback: dt.timedelta = dt.timedelta(hours=12),
                  symbols: Iterable[str] | None = None,
                  min_score: int = 1) -> pd.DataFrame:
    """Reddit posts from social.events. Returns columns (id, ts, source,
    channel, author, symbols, score, num_comments, sentiment, urgency,
    title, url).

    The table may not exist (finance-social isn't deployed yet). In that
    case we return an empty DataFrame so strategies degrade gracefully.
    """
    cols = ["id", "ts", "source", "channel", "author", "symbols",
            "score", "num_comments", "sentiment", "urgency", "title", "url"]
    sql = [f"""SELECT {', '.join(cols)}
              FROM social.events
              WHERE ts >= now() - %s
                AND COALESCE(score, 0) >= %s"""]
    args: list = [lookback, int(min_score)]
    if symbols:
        sql.append("AND symbols && %s")
        args.append(list(symbols))
    sql.append("ORDER BY ts DESC")
    try:
        with conn() as c, c.cursor() as cur:
            cur.execute(" ".join(sql), tuple(args))
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        # Most likely cause: social.events doesn't exist yet because
        # finance-social hasn't run. Strategies should treat "no social
        # data" as a no-signal cycle, not as an error.
        log.debug("recent_social query failed (%s) — returning empty", exc)
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def social_at(end: dt.datetime, lookback: dt.timedelta,
              symbols: Iterable[str] | None = None,
              min_score: int = 1) -> pd.DataFrame:
    """Backtest variant of recent_social() anchored at a historical ts."""
    cols = ["id", "ts", "source", "channel", "author", "symbols",
            "score", "num_comments", "sentiment", "urgency", "title", "url"]
    sql = [f"""SELECT {', '.join(cols)}
              FROM social.events
              WHERE ts BETWEEN %s AND %s
                AND COALESCE(score, 0) >= %s"""]
    args: list = [end - lookback, end, int(min_score)]
    if symbols:
        sql.append("AND symbols && %s")
        args.append(list(symbols))
    sql.append("ORDER BY ts")
    try:
        with conn() as c, c.cursor() as cur:
            cur.execute(" ".join(sql), tuple(args))
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        log.debug("social_at query failed (%s) — returning empty", exc)
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


