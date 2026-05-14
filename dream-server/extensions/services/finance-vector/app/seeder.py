"""Finance vector seeder.

Pulls top-N stocks (Wikipedia + yfinance) and top-N cryptos (CoinGecko)
and upserts them into Qdrant via the local TEI embeddings service.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd
import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-vector.seeder")

# Stable namespace for deterministic point IDs.
# Derived from a fixed DNS name so it never drifts across deployments.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "finance-assets.dreamserver.local")
HTTP_HEADERS = {"User-Agent": "DreamServer-FinanceSeeder/1.0 (+local)"}

WIKI_TABLES = [
    # (url, ticker_col, name_col, sector_col, exchange, country, currency, yf_suffix)
    ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
     "Symbol", "Security", "GICS Sector", "NYSE/NASDAQ", "US", "USD", ""),
    ("https://en.wikipedia.org/wiki/Nasdaq-100",
     "Ticker", "Company", "GICS Sector", "NASDAQ", "US", "USD", ""),
    ("https://en.wikipedia.org/wiki/DAX",
     "Ticker", "Company", "Prime Standard Sector", "XETRA", "DE", "EUR", ".DE"),
]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass
class SeederConfig:
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    embeddings_url: str = field(default_factory=lambda: os.getenv("EMBEDDINGS_URL", "http://embeddings:80"))
    collection: str = field(default_factory=lambda: os.getenv("FINANCE_COLLECTION", "finance_assets"))
    top_stocks: int = field(default_factory=lambda: int(os.getenv("FINANCE_TOP_STOCKS", "250")))
    top_crypto: int = field(default_factory=lambda: int(os.getenv("FINANCE_TOP_CRYPTO", "250")))
    coingecko_api_key: str | None = field(default_factory=lambda: os.getenv("COINGECKO_API_KEY") or None)
    embed_batch: int = 32
    yf_sleep_secs: float = field(
        default_factory=lambda: float(os.getenv("FINANCE_YF_SLEEP", "0.25")))


# --------------------------------------------------------------------------- #
# Stocks — primary source: NASDAQ screener API (free, no key, single call)
# Fallback: Wikipedia + yfinance.fast_info (used only if NASDAQ unreachable)
# --------------------------------------------------------------------------- #
NASDAQ_SCREENER_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=9999&download=true"
)
NASDAQ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
def _parse_market_cap(raw) -> float:
    if raw is None or raw == "" or raw == "N/A":
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace("$", "").replace(",", "").strip()
    mult = 1.0
    if s.endswith("B"):
        mult, s = 1e9, s[:-1]
    elif s.endswith("M"):
        mult, s = 1e6, s[:-1]
    elif s.endswith("K"):
        mult, s = 1e3, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0.0
def _parse_price(raw) -> float:
    if raw is None or raw == "" or raw == "N/A":
        return 0.0
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return 0.0
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
def _fetch_nasdaq_screener() -> list[dict]:
    r = requests.get(NASDAQ_SCREENER_URL, headers=NASDAQ_HEADERS, timeout=30)
    r.raise_for_status()
    payload = r.json()
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    if not rows:
        raise RuntimeError("NASDAQ screener returned no rows")
    return rows
def fetch_top_stocks_via_nasdaq(top_n: int) -> list[dict]:
    """Single-call source for the US top-N by market cap.
    Returns rows already shaped like the Qdrant payload (no further enrichment
    needed). Sector / industry / country come from NASDAQ; no per-ticker call.
    """
    rows = _fetch_nasdaq_screener()
    log.info("NASDAQ screener returned %d rows", len(rows))
    out: list[dict] = []
    for r in rows:
        mcap = _parse_market_cap(r.get("marketCap"))
        if not mcap:
            continue
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        out.append({
            "symbol": sym,
            "name": (r.get("name") or sym).strip(),
            "sector": (r.get("sector") or "Unknown").strip() or "Unknown",
            "country": (r.get("country") or "US").strip() or "US",
            "currency": "USD",
            "exchange": "NASDAQ" if (r.get("url") or "").startswith("/market-activity/stocks") else "US",
            "market_cap": mcap,
            "price": _parse_price(r.get("lastsale")),
            "description": "",
            "website": "",
        })
    out.sort(key=lambda x: x["market_cap"], reverse=True)
    return out[:top_n]
# --- Fallback (Wikipedia + yfinance) -------------------------------------- #
WIKI_TABLES = [
    # (url, ticker_col, name_col, sector_col, exchange, country, currency, yf_suffix)
    ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
     "Symbol", "Security", "GICS Sector", "NYSE/NASDAQ", "US", "USD", ""),
    ("https://en.wikipedia.org/wiki/DAX",
     "Ticker", "Company", "Prime Standard Sector", "XETRA", "DE", "EUR", ".DE"),
]
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _read_wiki_tables(url: str) -> list[pd.DataFrame]:
    from io import StringIO  # silence pandas literal-html FutureWarning
    r = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_html(StringIO(r.text))
def fetch_stock_universe_wiki() -> pd.DataFrame:
    rows: list[dict] = []
    for url, t_col, n_col, s_col, exch, country, ccy, suffix in WIKI_TABLES:
        try:
            tables = _read_wiki_tables(url)
        except Exception as exc:  # pragma: no cover
            log.warning("Wikipedia fetch failed for %s: %s", url, exc)
            continue
        df = next((t for t in tables if t_col in t.columns), None)
        if df is None:
            log.warning("No ticker column %s in %s", t_col, url)
            continue
        for _, r in df.iterrows():
            sym = str(r[t_col]).strip().replace(".", "-")
            if not sym or sym.lower() == "nan":
                continue
            rows.append({
                "symbol": sym,
                "yf_symbol": f"{sym}{suffix}",
                "name": str(r.get(n_col, sym)).strip(),
                "sector": str(r.get(s_col, "")).strip() or "Unknown",
                "exchange": exch,
                "country": country,
                "currency": ccy,
            })
    return pd.DataFrame(rows).drop_duplicates(subset=["yf_symbol"])
def enrich_stocks_with_yf(df: pd.DataFrame, top_n: int,
                          sleep_secs: float = 0.25) -> list[dict]:
    """Fallback enrichment via yfinance.fast_info.
    Used only when the NASDAQ screener API is unreachable. Keep the request
    rate low and tolerate empty responses (Yahoo throttles aggressively).
    """
    import yfinance as yf
    enriched: list[dict] = []
    tickers = df["yf_symbol"].tolist()
    log.info("fast_info fallback for %d tickers (sleep=%.2fs) ...",
             len(tickers), sleep_secs)
    fail_streak = 0
    for i, row in enumerate(df.itertuples(index=False), 1):
        try:
            fi = yf.Ticker(row.yf_symbol).fast_info
            mcap = float(getattr(fi, "market_cap", 0) or 0)
            price = float(getattr(fi, "last_price", 0) or 0)
            currency = getattr(fi, "currency", None) or row.currency
            exchange = getattr(fi, "exchange", None) or row.exchange
        except Exception as exc:  # noqa: BLE001
            log.debug("fast_info failed for %s: %s", row.yf_symbol, exc)
            fail_streak += 1
            if fail_streak >= 5:
                time.sleep(min(5.0, sleep_secs * 4))
                fail_streak = 0
            continue
        fail_streak = 0
        if not mcap:
            continue
        enriched.append({
            "symbol": row.symbol,
            "name": row.name,
            "sector": row.sector,
            "country": row.country,
            "currency": currency,
            "exchange": exchange,
            "market_cap": mcap,
            "price": price,
            "description": "",
            "website": "",
        })
        if sleep_secs > 0:
            time.sleep(sleep_secs)
    enriched.sort(key=lambda x: x["market_cap"], reverse=True)
    return enriched[:top_n]
def fetch_stocks(cfg: "SeederConfig") -> list[dict]:
    """Try NASDAQ screener first; fall back to yfinance enrichment."""
    try:
        stocks = fetch_top_stocks_via_nasdaq(cfg.top_stocks)
        if stocks:
            log.info("Stocks via NASDAQ screener: kept %d (largest: %s, $%.0fB)",
                     len(stocks), stocks[0]["symbol"], stocks[0]["market_cap"] / 1e9)
            return stocks
        log.warning("NASDAQ screener returned 0 usable rows -- falling back to yfinance")
    except Exception as exc:  # noqa: BLE001
        log.warning("NASDAQ screener failed (%s) -- falling back to yfinance", exc)
    universe = fetch_stock_universe_wiki()
    log.info("Wiki universe: %d candidates", len(universe))
    stocks = enrich_stocks_with_yf(universe, cfg.top_stocks, sleep_secs=cfg.yf_sleep_secs)
    log.info("Stocks via yfinance fallback: %d", len(stocks))
    return stocks

# --------------------------------------------------------------------------- #
# Crypto (CoinGecko free tier; optional Demo API key)
# --------------------------------------------------------------------------- #
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _coingecko_page(page: int, per_page: int, api_key: str | None) -> list[dict]:
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
            "price_change_percentage": "24h",
        },
        headers=headers,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_top_crypto(top_n: int, api_key: str | None) -> list[dict]:
    out: list[dict] = []
    pages = (top_n + 99) // 100
    for p in range(1, pages + 1):
        out.extend(_coingecko_page(p, per_page=100, api_key=api_key))
        time.sleep(2.0 if not api_key else 0.5)  # be gentle on free tier
    log.info("CoinGecko coins fetched: %d", len(out))
    coins: list[dict] = []
    for c in out[:top_n]:
        coins.append({
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name") or "",
            "sector": "Cryptocurrency",
            "country": "-",
            "currency": "USD",
            "exchange": "-",
            "market_cap": float(c.get("market_cap") or 0.0),
            "price": float(c.get("current_price") or 0.0),
            "description": (
                f"{c.get('name')} ({(c.get('symbol') or '').upper()}) is a cryptocurrency. "
                f"Rank #{c.get('market_cap_rank')} by market capitalization. "
                f"Circulating supply: {c.get('circulating_supply')}, "
                f"total supply: {c.get('total_supply')}, "
                f"all-time high: {c.get('ath')} USD."
            ),
            "website": f"https://www.coingecko.com/en/coins/{c.get('id')}",
        })
    return coins


# --------------------------------------------------------------------------- #
# Embedding text + TEI
# --------------------------------------------------------------------------- #
def build_embedding_text(asset: dict, kind: str) -> str:
    parts = [
        f"{asset['name']} ({asset['symbol']})",
        f"Type: {kind}",
        f"Sector/Category: {asset['sector']}",
        f"Country: {asset['country']}",
        f"Exchange: {asset['exchange']}",
        f"Currency: {asset['currency']}",
        f"Market cap (USD): {asset['market_cap']:.0f}",
        f"Price (USD): {asset['price']:.4f}",
    ]
    if asset.get("description"):
        parts.append(asset["description"])
    return " | ".join(parts)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def tei_embed(base_url: str, texts: list[str]) -> list[list[float]]:
    r = requests.post(
        f"{base_url.rstrip('/')}/embed",
        json={"inputs": texts, "truncate": True},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def chunked(it: list, n: int) -> Iterable[list]:
    for i in range(0, len(it), n):
        yield it[i:i + n]


# --------------------------------------------------------------------------- #
# Qdrant
# --------------------------------------------------------------------------- #
def ensure_collection(client: QdrantClient, name: str, dim: int, recreate: bool) -> None:
    exists = client.collection_exists(name)
    if exists and recreate:
        log.warning("Recreating collection '%s' (delete + create)", name)
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        for field_name, schema in [
            ("type", qm.PayloadSchemaType.KEYWORD),
            ("symbol", qm.PayloadSchemaType.KEYWORD),
            ("sector", qm.PayloadSchemaType.KEYWORD),
            ("country", qm.PayloadSchemaType.KEYWORD),
        ]:
            client.create_payload_index(name, field_name=field_name, field_schema=schema)
        log.info("Collection '%s' created (dim=%d, cosine)", name, dim)
    else:
        log.info("Collection '%s' exists -- upserting", name)


def upsert(client: QdrantClient, collection: str, items: list[dict],
           kind: str, embeddings: list[list[float]], now: str) -> None:
    points: list[qm.PointStruct] = []
    for asset, vec in zip(items, embeddings):
        pid = str(uuid.uuid5(NAMESPACE, f"finance:{kind}:{asset['symbol']}"))
        payload = {**asset, "type": kind, "last_updated": now}
        points.append(qm.PointStruct(id=pid, vector=vec, payload=payload))
    client.upsert(collection_name=collection, points=points, wait=True)
    log.info("Upserted %d %s points", len(points), kind)


# --------------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------------- #
def run_seed(cfg: SeederConfig, recreate: bool = False) -> dict:
    """Run a full refresh. Returns a summary dict."""
    t0 = time.monotonic()
    stocks = fetch_stocks(cfg)
    cryptos = fetch_top_crypto(cfg.top_crypto, cfg.coingecko_api_key)

    if not stocks and not cryptos:
        raise RuntimeError("No data fetched -- aborting (sources unreachable?)")

    stock_texts = [build_embedding_text(a, "stock") for a in stocks]
    crypto_texts = [build_embedding_text(a, "crypto") for a in cryptos]

    log.info("Embedding %d stocks + %d cryptos via %s",
             len(stock_texts), len(crypto_texts), cfg.embeddings_url)
    stock_vecs: list[list[float]] = []
    for batch in chunked(stock_texts, cfg.embed_batch):
        stock_vecs.extend(tei_embed(cfg.embeddings_url, batch))
    crypto_vecs: list[list[float]] = []
    for batch in chunked(crypto_texts, cfg.embed_batch):
        crypto_vecs.extend(tei_embed(cfg.embeddings_url, batch))

    dim = len(stock_vecs[0]) if stock_vecs else len(crypto_vecs[0])

    client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, timeout=60)
    ensure_collection(client, cfg.collection, dim, recreate)

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if stocks:
        upsert(client, cfg.collection, stocks, "stock", stock_vecs, now)
    if cryptos:
        upsert(client, cfg.collection, cryptos, "crypto", crypto_vecs, now)

    info = client.get_collection(cfg.collection)
    return {
        "collection": cfg.collection,
        "dim": dim,
        "stocks_upserted": len(stocks),
        "crypto_upserted": len(cryptos),
        "points_total": info.points_count,
        "duration_seconds": round(time.monotonic() - t0, 2),
        "completed_at": now,
    }


def collection_point_count(cfg: SeederConfig) -> int | None:
    """Return current point count, or None if collection missing."""
    try:
        client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, timeout=10)
        if not client.collection_exists(cfg.collection):
            return None
        return int(client.get_collection(cfg.collection).points_count or 0)
    except Exception as exc:  # pragma: no cover
        log.warning("Could not query collection: %s", exc)
        return None

