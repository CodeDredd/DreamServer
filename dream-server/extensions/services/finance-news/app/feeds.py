"""RSS feed list, parsing, and symbol-tagging for finance-news.

Three jobs:
  1. Provide a curated default RSS feed list (overridable via
     FINANCE_NEWS_FEEDS env var, comma-separated).
  2. Parse each feed with feedparser and normalize entries to a
     common dict shape: {id, ts, source, channel, title, url, payload, ...}.
  3. Tag each headline with the finance symbols / coin tickers it
     mentions, using the Stammdaten universe from the Qdrant
     finance_assets collection (refreshed every hour, cached in-memory).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

import feedparser
import requests
from dateutil import parser as dtparser
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

log = logging.getLogger("finance-news.feeds")

USER_AGENT = "DreamServer-FinanceNews/0.1 (+local)"

# ──────────────────────────────────────────────────────────────────────
# Curated default RSS feeds. Per-feed failures are tolerated. To
# override, set FINANCE_NEWS_FEEDS to a comma-separated list — the
# feed name is derived from the URL host.
# ──────────────────────────────────────────────────────────────────────
DEFAULT_FEEDS: list[tuple[str, str]] = [
    # (channel, url)
    ("yahoo-finance",   "https://finance.yahoo.com/news/rssindex"),
    # Reuters Agency moved to a paywalled feed in 2025; the open
    # business news feed lives on the consumer site instead.
    ("reuters-business", "https://www.reuters.com/world/business/rss"),
    ("handelsblatt",    "https://www.handelsblatt.com/contentexport/feed/finanzen"),
    ("cnbc-top",        "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("marketwatch-top", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("seekingalpha",    "https://seekingalpha.com/market_currents.xml"),
    ("coindesk",        "https://www.coindesk.com/arc/outboundfeeds/rss/"),
]


def _parse_feeds_env(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for item in raw.split(","):
        url = item.strip()
        if not url or not url.startswith("http"):
            continue
        try:
            host = url.split("//", 1)[1].split("/", 1)[0]
        except Exception:
            host = url[:32]
        out.append((host, url))
    return out


def configured_feeds() -> list[tuple[str, str]]:
    raw = os.getenv("FINANCE_NEWS_FEEDS", "").strip()
    return _parse_feeds_env(raw) if raw else list(DEFAULT_FEEDS)


# ──────────────────────────────────────────────────────────────────────
# Symbol universe — read from Qdrant finance_assets, cached.
# ──────────────────────────────────────────────────────────────────────
@dataclass
class UniverseCfg:
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    collection: str = field(default_factory=lambda: os.getenv("FINANCE_COLLECTION", "finance_assets"))
    refresh_seconds: int = 3600


@dataclass
class Universe:
    # ticker uppercase -> {"name": company/coin name, "type": stock|crypto}
    by_symbol: dict[str, dict] = field(default_factory=dict)
    # lowercased name token -> set of tickers (for fuzzy company-name match)
    name_index: dict[str, set[str]] = field(default_factory=dict)
    refreshed_at: float = 0.0


_UNIV_LOCK = threading.Lock()
_UNIV: Universe = Universe()


def _name_tokens(name: str) -> Iterable[str]:
    """Split a company name into searchable tokens. Drops punctuation
    and the usual suffixes (Inc, Corp, AG, ...) so 'Apple Inc.' yields
    {'apple'}."""
    name = re.sub(r"[^A-Za-z0-9 ]+", " ", name or "")
    drop = {"inc", "corp", "corporation", "ltd", "plc", "ag", "se", "co",
            "company", "holdings", "group", "limited", "the", "and"}
    out = []
    for t in name.lower().split():
        if t and t not in drop and len(t) >= 3:
            out.append(t)
    return out


def refresh_universe(cfg: UniverseCfg) -> Universe:
    client = QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key, timeout=30)
    if not client.collection_exists(cfg.collection):
        log.warning("Universe collection %s missing", cfg.collection)
        return Universe(refreshed_at=time.time())

    by_symbol: dict[str, dict] = {}
    name_index: dict[str, set[str]] = {}
    next_page = None
    pulled = 0
    while True:
        points, next_page = client.scroll(
            collection_name=cfg.collection,
            with_payload=True,
            with_vectors=False,
            limit=500,
            offset=next_page,
        )
        for p in points:
            payload = p.payload or {}
            sym = (payload.get("symbol") or "").upper().strip()
            if not sym:
                continue
            kind = payload.get("type") or "stock"
            name = payload.get("name") or payload.get("company") or sym
            by_symbol[sym] = {"name": name, "type": kind}
            for tok in _name_tokens(name):
                name_index.setdefault(tok, set()).add(sym)
            pulled += 1
        if not next_page:
            break

    log.info("Universe refreshed: %d symbols, %d name tokens", len(by_symbol), len(name_index))
    return Universe(by_symbol=by_symbol, name_index=name_index, refreshed_at=time.time())


def get_universe(cfg: UniverseCfg) -> Universe:
    global _UNIV
    with _UNIV_LOCK:
        if not _UNIV.by_symbol or (time.time() - _UNIV.refreshed_at) > cfg.refresh_seconds:
            try:
                _UNIV = refresh_universe(cfg)
            except Exception as exc:  # noqa: BLE001
                log.warning("universe refresh failed: %s — keeping previous (%d syms)",
                            exc, len(_UNIV.by_symbol))
        return _UNIV


# ──────────────────────────────────────────────────────────────────────
# Symbol extraction
# ──────────────────────────────────────────────────────────────────────
TICKER_RE = re.compile(r"\b([A-Z]{2,6})\b")
WORD_RE   = re.compile(r"[a-z]{3,}")
# Common stop-tickers — uppercase 2-6 letter words that aren't tickers.
STOP_TICKERS = {
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY",
    "CEO", "CFO", "CTO", "COO", "IPO", "ETF", "GDP", "CPI", "PMI",
    "FED", "ECB", "BOE", "BOJ", "OECD", "EU", "USA", "UK", "AI", "ML",
    "PR", "PE", "ESG", "CES", "Q1", "Q2", "Q3", "Q4",
    "AND", "THE", "FOR", "WITH", "FROM", "INTO", "OVER", "AFTER",
    "NEW", "TOP", "BIG", "BEST", "WORST", "REPORT", "NEWS", "MARKET",
}


def extract_symbols(title: str, summary: str, univ: Universe,
                    max_syms: int = 8) -> list[str]:
    text = f"{title} {summary or ''}"
    found: list[str] = []
    seen: set[str] = set()

    # Direct ticker match (uppercase tokens).
    for m in TICKER_RE.finditer(text):
        sym = m.group(1)
        if sym in STOP_TICKERS:
            continue
        if sym in univ.by_symbol and sym not in seen:
            seen.add(sym)
            found.append(sym)
            if len(found) >= max_syms:
                return found

    # Company / coin name token match (lowercase).
    lower = text.lower()
    for tok in set(WORD_RE.findall(lower)):
        for sym in univ.name_index.get(tok, ()):
            if sym not in seen:
                seen.add(sym)
                found.append(sym)
                if len(found) >= max_syms:
                    return found
    return found


# ──────────────────────────────────────────────────────────────────────
# Feed fetching
# ──────────────────────────────────────────────────────────────────────
def _stable_id(channel: str, link: str | None, guid: str | None,
               title: str | None) -> str:
    seed = (channel or "") + "\n" + (guid or link or title or "")
    return hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()


def _to_utc(when) -> dt.datetime:
    if isinstance(when, dt.datetime):
        d = when
    elif isinstance(when, str) and when:
        try:
            d = dtparser.parse(when)
        except Exception:
            d = dt.datetime.now(dt.timezone.utc)
    elif isinstance(when, time.struct_time):
        d = dt.datetime(*when[:6], tzinfo=dt.timezone.utc)
    else:
        d = dt.datetime.now(dt.timezone.utc)
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def fetch_feed(channel: str, url: str, max_items: int) -> list[dict]:
    """Returns normalized event dicts (no symbols / sentiment yet —
    those are filled by the orchestrator)."""
    try:
        # feedparser will fall back to its own UA if we don't pass one,
        # which Cloudflare-fronted feeds (Yahoo) sometimes block. Pull
        # via requests + pass bytes to feedparser for control.
        r = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as exc:  # noqa: BLE001
        log.warning("feed %s failed: %s", channel, exc)
        return []

    events: list[dict] = []
    for entry in (parsed.entries or [])[:max_items]:
        title = (entry.get("title") or "").strip()
        link = entry.get("link") or ""
        guid = entry.get("id") or entry.get("guid") or link
        published = entry.get("published_parsed") or entry.get("updated_parsed") \
            or entry.get("published") or entry.get("updated")
        ts = _to_utc(published)
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        # feedparser sometimes leaves HTML in summary; trim hard.
        if summary and len(summary) > 800:
            summary = summary[:800] + "…"
        events.append({
            "id":       _stable_id(channel, link, guid, title),
            "ts":       ts,
            "source":   "rss",
            "channel":  channel,
            "title":    title,
            "url":      link,
            "payload":  {
                "summary": re.sub(r"<[^>]+>", " ", summary).strip(),
                "feed_url": url,
            },
        })
    return events

