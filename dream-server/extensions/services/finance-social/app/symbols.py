"""Symbol universe + extractor for finance-social.

Mirrors finance-news/app/feeds.py pieces — see that file's docstring for
the rationale (one source of truth = the Qdrant `finance_assets`
collection populated by finance-vector daily).

Kept as a separate module here because each compose service has its
own pip install — we cannot import across containers. The logic is
small and stable enough to duplicate.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Iterable

from qdrant_client import QdrantClient

log = logging.getLogger("finance-social.symbols")


@dataclass
class UniverseCfg:
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    qdrant_api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    collection: str = field(default_factory=lambda: os.getenv("FINANCE_COLLECTION", "finance_assets"))
    refresh_seconds: int = 3600


@dataclass
class Universe:
    by_symbol: dict[str, dict] = field(default_factory=dict)
    name_index: dict[str, set[str]] = field(default_factory=dict)
    refreshed_at: float = 0.0


_LOCK = threading.Lock()
_UNIV: Universe = Universe()


def _name_tokens(name: str) -> Iterable[str]:
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
        if not next_page:
            break

    log.info("Universe refreshed: %d symbols, %d name tokens",
             len(by_symbol), len(name_index))
    return Universe(by_symbol=by_symbol, name_index=name_index, refreshed_at=time.time())


def get_universe(cfg: UniverseCfg) -> Universe:
    global _UNIV
    with _LOCK:
        if not _UNIV.by_symbol or (time.time() - _UNIV.refreshed_at) > cfg.refresh_seconds:
            try:
                _UNIV = refresh_universe(cfg)
            except Exception as exc:  # noqa: BLE001
                log.warning("universe refresh failed: %s — keeping previous (%d syms)",
                            exc, len(_UNIV.by_symbol))
        return _UNIV


# ──────────────────────────────────────────────────────────────────────
# Symbol extraction. WSB convention: cashtag prefix `$AAPL`. We honor
# both `$AAPL` and bare `AAPL`, then fall back to lowercase company
# name tokens (same as finance-news).
# ──────────────────────────────────────────────────────────────────────
CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})\b")
TICKER_RE  = re.compile(r"\b([A-Z]{2,6})\b")
WORD_RE    = re.compile(r"[a-z]{3,}")
STOP_TICKERS = {
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "CNY",
    "CEO", "CFO", "CTO", "COO", "IPO", "ETF", "GDP", "CPI", "PMI",
    "FED", "ECB", "BOE", "BOJ", "OECD", "EU", "USA", "UK", "AI", "ML",
    "PR", "PE", "ESG", "CES", "Q1", "Q2", "Q3", "Q4",
    "AND", "THE", "FOR", "WITH", "FROM", "INTO", "OVER", "AFTER",
    "NEW", "TOP", "BIG", "BEST", "WORST", "REPORT", "NEWS", "MARKET",
    # Reddit-specific noise.
    "DD", "TLDR", "YOLO", "FOMO", "FUD", "WSB", "ATH", "PT", "EOD",
    "OP", "EDIT", "TLDR", "TLDR;", "IMO", "IMHO", "AMA",
}


def extract_symbols(title: str, body: str, univ: Universe,
                    max_syms: int = 8) -> list[str]:
    text = f"{title or ''} {body or ''}"
    found: list[str] = []
    seen: set[str] = set()

    # 1. Cashtags first — highest signal on social.
    for m in CASHTAG_RE.finditer(text):
        sym = m.group(1).upper()
        if sym in STOP_TICKERS:
            continue
        if sym in univ.by_symbol and sym not in seen:
            seen.add(sym)
            found.append(sym)
            if len(found) >= max_syms:
                return found

    # 2. Bare uppercase tickers.
    for m in TICKER_RE.finditer(text):
        sym = m.group(1)
        if sym in STOP_TICKERS or sym in seen:
            continue
        if sym in univ.by_symbol:
            seen.add(sym)
            found.append(sym)
            if len(found) >= max_syms:
                return found

    # 3. Lowercase company / coin name tokens.
    lower = text.lower()
    for tok in set(WORD_RE.findall(lower)):
        for sym in univ.name_index.get(tok, ()):
            if sym not in seen:
                seen.add(sym)
                found.append(sym)
                if len(found) >= max_syms:
                    return found
    return found

