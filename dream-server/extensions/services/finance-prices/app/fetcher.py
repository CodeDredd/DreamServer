"""Universe + price fetchers for finance-prices.

Universe
--------
The set of symbols to fetch is read from the Qdrant `finance_assets`
collection populated by the `finance-vector` service. That keeps the
"what's worth tracking" decision in one place (the daily Stammdaten
seeder) and lets this intraday service stay narrow.

Fetchers
--------
* Stocks  -> yfinance batch download (`yf.download(tickers, period='1d',
  interval='15m')`). Free, well-supported, and one HTTP roundtrip per
  ~50 symbols.
* Crypto  -> CoinGecko `/coins/{id}/ohlc?vs_currency=usd&days=1`. Free
  Demo tier = 30 req/min — top-100 over a 5-min cadence ≈ 100 req per
  cycle, so we paginate the universe over multiple cycles when no API
  key is set.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterable

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-prices.fetcher")

HTTP_HEADERS = {"User-Agent": "DreamServer-FinancePrices/0.1 (+local)"}

# yfinance ".DE" / similar suffixes for non-US exchanges, mirrored from
# finance-vector's seeder. We'd ideally read these back from the
# Qdrant payload but the seeder doesn't store the suffix; for now the
# top US tickers are the primary target.
EXCHANGE_SUFFIX = {
    "XETRA": ".DE",
}


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass
class FetcherConfig:
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    collection: str = field(default_factory=lambda: os.getenv("FINANCE_COLLECTION", "finance_assets"))
    top_stocks: int = field(default_factory=lambda: int(os.getenv("FINANCE_PRICES_TOP_STOCKS", "100")))
    top_crypto: int = field(default_factory=lambda: int(os.getenv("FINANCE_PRICES_TOP_CRYPTO", "100")))
    coingecko_api_key: str | None = field(default_factory=lambda: os.getenv("COINGECKO_API_KEY") or None)
    yf_batch_size: int = 50
    interval: str = "15m"  # yfinance interval string


# --------------------------------------------------------------------------- #
# Universe (Qdrant-backed, with sane fallback)
# --------------------------------------------------------------------------- #
def _scroll_universe(cfg: FetcherConfig, asset_type: str, limit: int) -> list[dict]:
    client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, timeout=15)
    if not client.collection_exists(cfg.collection):
        log.warning("Qdrant collection %s missing — universe will be empty", cfg.collection)
        return []
    flt = qm.Filter(must=[qm.FieldCondition(key="type", match=qm.MatchValue(value=asset_type))])
    out: list[dict] = []
    next_page = None
    # Pull in pages of 500, sort client-side by market_cap.
    while len(out) < max(limit * 3, 200):
        points, next_page = client.scroll(
            collection_name=cfg.collection,
            scroll_filter=flt,
            with_payload=True,
            with_vectors=False,
            limit=500,
            offset=next_page,
        )
        out.extend(p.payload for p in points if p.payload)
        if not next_page:
            break
    out.sort(key=lambda p: float(p.get("market_cap") or 0.0), reverse=True)
    return out[:limit]


def universe_stocks(cfg: FetcherConfig) -> list[dict]:
    rows = _scroll_universe(cfg, "stock", cfg.top_stocks)
    log.info("Universe (stocks) from Qdrant: %d", len(rows))
    return rows


def universe_crypto(cfg: FetcherConfig) -> list[dict]:
    rows = _scroll_universe(cfg, "crypto", cfg.top_crypto)
    log.info("Universe (crypto) from Qdrant: %d", len(rows))
    return rows


# --------------------------------------------------------------------------- #
# Stocks via yfinance (batched)
# --------------------------------------------------------------------------- #
def _yf_symbol(payload: dict) -> str:
    """Reconstruct yfinance ticker from Qdrant payload."""
    sym = (payload.get("symbol") or "").strip()
    suffix = EXCHANGE_SUFFIX.get(payload.get("exchange") or "", "")
    return f"{sym}{suffix}" if sym else sym


def fetch_stock_bars(cfg: FetcherConfig, payloads: list[dict]) -> list[tuple]:
    """Returns rows ready for db.upsert_bars()."""
    import yfinance as yf

    rows: list[tuple] = []
    if not payloads:
        return rows

    by_symbol: dict[str, dict] = {}
    yf_tickers: list[str] = []
    for p in payloads:
        yfs = _yf_symbol(p)
        if not yfs:
            continue
        by_symbol[yfs] = p
        yf_tickers.append(yfs)

    for batch_start in range(0, len(yf_tickers), cfg.yf_batch_size):
        batch = yf_tickers[batch_start: batch_start + cfg.yf_batch_size]
        try:
            df = yf.download(
                tickers=" ".join(batch),
                period="1d",
                interval=cfg.interval,
                group_by="ticker",
                threads=False,
                progress=False,
                auto_adjust=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("yfinance batch failed (%d tickers): %s", len(batch), exc)
            continue

        if df is None or df.empty:
            log.info("yfinance batch returned empty (likely market closed)")
            continue

        # When more than one ticker is requested, df has a 2-level column
        # index: (ticker, OHLCV-field). Single-ticker responses use a
        # flat 1-level index — handle both.
        is_multi = hasattr(df.columns, "levels") and len(df.columns.levels) == 2

        for yfs in batch:
            payload = by_symbol[yfs]
            sym = (payload.get("symbol") or "").strip().upper()
            ccy = (payload.get("currency") or "USD").upper()
            try:
                sub = df[yfs] if is_multi else df
            except KeyError:
                continue
            for ts, row in sub.iterrows():
                close = row.get("Close")
                if close is None or close != close:  # NaN guard
                    continue
                ts_utc = ts.tz_convert("UTC") if ts.tzinfo else ts.tz_localize("UTC")
                rows.append((
                    sym, "stock", ts_utc.to_pydatetime(),
                    _f(row.get("Open")), _f(row.get("High")), _f(row.get("Low")),
                    _f(close), _f(row.get("Volume")),
                    "yfinance", ccy,
                ))
        # Tiny pause between batches; yfinance shares an upstream pool.
        time.sleep(0.4)
    return rows


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


# --------------------------------------------------------------------------- #
# Crypto via CoinGecko OHLC
# --------------------------------------------------------------------------- #
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _coingecko_markets(per_page: int, page: int, api_key: str | None) -> list[dict]:
    headers = dict(HTTP_HEADERS)
    if api_key:
        headers["x-cg-demo-api-key"] = api_key
    r = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
        },
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_crypto_bars(cfg: FetcherConfig, payloads: list[dict]) -> list[tuple]:
    """For crypto we ask CoinGecko for the latest snapshot per coin and
    create a single bar per cycle (open=high=low=close=current_price).
    That's the right granularity for a 5-min cadence on the free tier
    — true OHLC requires `/coins/{id}/ohlc` which is 1 request per coin
    (too many calls for top-100/5min)."""
    if not payloads:
        return []

    # Build a name→symbol map from the universe so we can match
    # CoinGecko's response (which uses lowercase ticker codes).
    want = { (p.get("symbol") or "").upper(): p for p in payloads }

    rows: list[tuple] = []
    pages = (cfg.top_crypto + 99) // 100
    for page in range(1, pages + 1):
        try:
            coins = _coingecko_markets(per_page=100, page=page, api_key=cfg.coingecko_api_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("CoinGecko page %d failed: %s", page, exc)
            continue
        now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
        for c in coins:
            sym = (c.get("symbol") or "").upper()
            if sym not in want:
                continue
            price = _f(c.get("current_price"))
            if price is None:
                continue
            volume = _f(c.get("total_volume"))
            rows.append((
                sym, "crypto", now,
                price, price, price, price, volume,
                "coingecko", "USD",
            ))
        # Be polite on the free tier.
        time.sleep(2.0 if not cfg.coingecko_api_key else 0.3)
    return rows

