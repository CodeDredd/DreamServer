#!/usr/bin/env python3
"""
Seed Qdrant collection 'finance_assets' with the top-N stocks (by market cap)
and top-N cryptocurrencies (by market cap).

Embeddings are produced locally via the Text-Embeddings-Inference (TEI)
service that ships with DreamServer (`dream-embeddings`, default model
BAAI/bge-base-en-v1.5 -> 768 dim).

Run:
    python seed_finance_collection.py --recreate

The script is idempotent (deterministic UUID5 IDs), so a daily cron will
just refresh prices / market-caps via upsert.
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import sys
import time
import uuid
from typing import Iterable

import pandas as pd
import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-seed")

NAMESPACE = uuid.UUID("4f3b9f6e-1c1a-4d6c-9a55-financeassets00")
WIKI_HEADERS = {"User-Agent": "DreamServer-FinanceSeeder/1.0 (+local)"}


# --------------------------------------------------------------------------- #
# Stocks
# --------------------------------------------------------------------------- #
WIKI_TABLES = [
    # (url, ticker_col, name_col, sector_col, exchange, country, currency, yf_suffix)
    ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
     "Symbol", "Security", "GICS Sector", "NYSE/NASDAQ", "US", "USD", ""),
    ("https://en.wikipedia.org/wiki/Nasdaq-100",
     "Ticker", "Company", "GICS Sector", "NASDAQ", "US", "USD", ""),
    ("https://en.wikipedia.org/wiki/DAX",
     "Ticker", "Company", "Prime Standard Sector", "XETRA", "DE", "EUR", ".DE"),
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _read_wiki_tables(url: str) -> list[pd.DataFrame]:
    r = requests.get(url, headers=WIKI_HEADERS, timeout=30)
    r.raise_for_status()
    return pd.read_html(r.text)


def fetch_stock_universe() -> pd.DataFrame:
    """Build a candidate stock universe from Wikipedia index lists."""
    rows: list[dict] = []
    for url, t_col, n_col, s_col, exch, country, ccy, suffix in WIKI_TABLES:
        try:
            tables = _read_wiki_tables(url)
        except Exception as exc:  # pragma: no cover
            log.warning("Wikipedia fetch failed for %s: %s", url, exc)
            continue
        # Pick the first table that has the expected ticker column
        df = next((t for t in tables if t_col in t.columns), None)
        if df is None:
            log.warning("No ticker column %s in %s", t_col, url)
            continue
        for _, r in df.iterrows():
            sym = str(r[t_col]).strip().replace(".", "-")  # BRK.B -> BRK-B for yf
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
    df = pd.DataFrame(rows).drop_duplicates(subset=["yf_symbol"])
    log.info("Stock universe candidates: %d", len(df))
    return df


def enrich_stocks_with_yf(df: pd.DataFrame, top_n: int) -> list[dict]:
    """Pull market cap / price / description via yfinance and keep top-N."""
    import yfinance as yf

    enriched: list[dict] = []
    tickers = df["yf_symbol"].tolist()
    log.info("Fetching yfinance info for %d tickers (this can take a while)...", len(tickers))
    for i, row in enumerate(df.itertuples(index=False), 1):
        try:
            info = yf.Ticker(row.yf_symbol).info or {}
        except Exception as exc:  # pragma: no cover
            log.debug("yf failed for %s: %s", row.yf_symbol, exc)
            continue
        mcap = info.get("marketCap") or 0
        if not mcap:
            continue
        enriched.append({
            "symbol": row.symbol,
            "name": info.get("longName") or row.name,
            "sector": info.get("sector") or row.sector,
            "country": info.get("country") or row.country,
            "currency": info.get("currency") or row.currency,
            "exchange": info.get("exchange") or row.exchange,
            "market_cap": float(mcap),
            "price": float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0),
            "description": (info.get("longBusinessSummary") or "").strip()[:1500],
            "website": info.get("website") or "",
        })
        if i % 25 == 0:
            log.info("  ... %d/%d processed, %d kept", i, len(tickers), len(enriched))
        time.sleep(0.05)  # be nice to Yahoo
    enriched.sort(key=lambda x: x["market_cap"], reverse=True)
    return enriched[:top_n]


# --------------------------------------------------------------------------- #
# Crypto
# --------------------------------------------------------------------------- #
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _coingecko_page(page: int, per_page: int = 100) -> list[dict]:
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
        headers=WIKI_HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_top_crypto(top_n: int) -> list[dict]:
    out: list[dict] = []
    pages = (top_n + 99) // 100
    for p in range(1, pages + 1):
        out.extend(_coingecko_page(p))
        time.sleep(1.2)  # CoinGecko free-tier rate limit
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
# Embedding text + TEI client
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
        for field, schema in [
            ("type", qm.PayloadSchemaType.KEYWORD),
            ("symbol", qm.PayloadSchemaType.KEYWORD),
            ("sector", qm.PayloadSchemaType.KEYWORD),
            ("country", qm.PayloadSchemaType.KEYWORD),
        ]:
            client.create_payload_index(name, field_name=field, field_schema=schema)
        log.info("Collection '%s' created (dim=%d, cosine)", name, dim)
    else:
        log.info("Collection '%s' already exists -- upserting", name)


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
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://127.0.0.1:6333"))
    p.add_argument("--qdrant-api-key", default=os.getenv("QDRANT_API_KEY") or None)
    p.add_argument("--embeddings-url", default=os.getenv("EMBEDDINGS_URL", "http://127.0.0.1:8090"))
    p.add_argument("--collection", default="finance_assets")
    p.add_argument("--top-stocks", type=int, default=250)
    p.add_argument("--top-crypto", type=int, default=250)
    p.add_argument("--recreate", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--batch", type=int, default=32)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    # 1) gather
    stock_universe = fetch_stock_universe()
    stocks = enrich_stocks_with_yf(stock_universe, args.top_stocks)
    log.info("Top stocks selected: %d (largest: %s)", len(stocks),
             stocks[0]["symbol"] if stocks else "-")

    cryptos = fetch_top_crypto(args.top_crypto)
    log.info("Top cryptos selected: %d (largest: %s)", len(cryptos),
             cryptos[0]["symbol"] if cryptos else "-")

    if not stocks and not cryptos:
        log.error("Nothing to ingest. Aborting.")
        return 1

    # 2) embed
    stock_texts = [build_embedding_text(a, "stock") for a in stocks]
    crypto_texts = [build_embedding_text(a, "crypto") for a in cryptos]

    if args.dry_run:
        log.info("Dry-run: skipping embeddings + Qdrant writes")
        for s in stocks[:3] + cryptos[:3]:
            print("---")
            print(s["symbol"], "|", s["name"], "|", s["sector"], "|", s["market_cap"])
        return 0

    log.info("Requesting embeddings from %s", args.embeddings_url)
    stock_vecs: list[list[float]] = []
    for batch in chunked(stock_texts, args.batch):
        stock_vecs.extend(tei_embed(args.embeddings_url, batch))
    crypto_vecs: list[list[float]] = []
    for batch in chunked(crypto_texts, args.batch):
        crypto_vecs.extend(tei_embed(args.embeddings_url, batch))

    dim = len(stock_vecs[0]) if stock_vecs else len(crypto_vecs[0])
    log.info("Embedding dimensionality: %d", dim)

    # 3) write
    client = QdrantClient(url=args.qdrant_url, api_key=args.qdrant_api_key, timeout=60)
    ensure_collection(client, args.collection, dim, args.recreate)

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    if stocks:
        upsert(client, args.collection, stocks, "stock", stock_vecs, now)
    if cryptos:
        upsert(client, args.collection, cryptos, "crypto", crypto_vecs, now)

    info = client.get_collection(args.collection)
    log.info("Done. Collection '%s' now has %s points.",
             args.collection, info.points_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())

