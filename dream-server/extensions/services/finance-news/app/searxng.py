"""Phase P-6.1 — SearXNG fallback for empty/dnne RAG-Briefs.

The finance-guru workflows (causal_extraction, price_move_explainer)
build their LLM-brief from a deterministic mix of RSS-news (finance_news
collection) and tick data. When neither source yields material — e.g.
during a weekend stock-price move or a thinly-covered crypto symbol —
the LLM is left to invent a story or skip the run entirely. Neither is
useful for the long-tail learning loop.

This module wraps the internal SearXNG instance so finance-news can
expose a side-channel `/web-context` endpoint. The workflow nodes hit
that endpoint *only* when their primary brief is empty, then merge the
returned snippets into the brief as ordinary `evidence_ids` (prefixed
`web:`) so the existing `evidence_ids  brief` verifier picks them up
without any change.

DESIGN INVARIANTS
-----------------
1. **Deterministic pre-step, not an LLM tool-call**. The LLM never
   sees raw search-URLs and never decides whether to call out — the
   workflow does, before the model runs. This keeps the verifier
   honest (every evidence_id is a *known* id from the brief).
2. **Bounded blast-radius**. One synchronous HTTP request per call,
   hard timeout, max-results cap, no recursion. If SearXNG is down
   the endpoint returns `{"results": []}` and the workflow falls
   back to its existing "no_news" skip path — same observable
   behaviour as today.
3. **Stable evidence IDs**. The `id = "web:<sha1(url)[:10]>"` scheme
   ensures the same URL across multiple runs produces the same id,
   so de-dupe and downstream Qdrant persistence (P-6.3 if we ever
   get there) stay consistent.
4. **No persistence here**. Snippets are returned ephemeral. A future
   P-6.3 can persist them as `source=web:searxng` rows in the
   finance_news Qdrant collection; the workflow plumbing stays the
   same.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Iterable

import requests

log = logging.getLogger("finance-news.searxng")


@dataclass(frozen=True)
class SearxngConfig:
    url: str
    enabled: bool
    timeout_s: float
    user_agent: str

    @classmethod
    def from_env(cls) -> "SearxngConfig":
        return cls(
            url=os.getenv("SEARXNG_URL", "http://searxng:8080").rstrip("/"),
            enabled=os.getenv("FINANCE_NEWS_USE_SEARXNG", "false").strip().lower()
                    in ("1", "true", "yes", "on"),
            timeout_s=float(os.getenv("FINANCE_NEWS_SEARXNG_TIMEOUT_S", "6.0")),
            user_agent=os.getenv("FINANCE_NEWS_SEARXNG_UA",
                                 "DreamServer/finance-news (+searxng-fallback)"),
        )


def _evidence_id(url: str) -> str:
    """Stable, short id for a web snippet — used as `evidence_ids[*]`
    in the LLM brief so the verifier can check `evidence_ids  brief`
    just like for RSS items (`news:<id>`) or relation themes."""
    h = hashlib.sha1(url.encode("utf-8", errors="ignore")).hexdigest()
    return f"web:{h[:10]}"


def _build_query(symbol: str, asset_type: str | None,
                 hint: str | None) -> str:
    """Compose a focused search query.

    Examples:
      symbol=NVDA, asset_type=stock              "NVDA stock news"
      symbol=BTC,  asset_type=crypto, hint=move  "BTC crypto move news"
      symbol=HASH, asset_type=crypto             "HASH crypto news"
    """
    parts: list[str] = [symbol.strip()]
    at = (asset_type or "").strip().lower()
    if at in ("crypto", "stock", "etf", "commodity", "fx"):
        parts.append(at)
    if hint:
        parts.append(hint.strip())
    parts.append("news")
    return " ".join(p for p in parts if p)


def search_web(*, symbol: str, asset_type: str | None = None,
               query_hint: str | None = None, max_results: int = 5,
               time_range: str = "day",
               cfg: SearxngConfig | None = None) -> list[dict]:
    """Query SearXNG and return a small list of evidence-ready dicts.

    Returns `[]` on any failure (network, JSON shape, empty result)
    so the caller can treat "no fallback available" identically to
    "no RAG hits". `time_range` is one of SearXNG's accepted values:
    `day`, `week`, `month`, `year` (or empty for unrestricted).

    Each result dict has the shape:
      {
        "id":      "web:<sha1[:10]>",   # stable evidence id
        "url":     "<canonical url>",
        "source":  "<host or engine>",
        "title":   "<headline>",
        "snippet": "<excerpt>",
        "engine":  "<searxng engine name>",
      }
    """
    cfg = cfg or SearxngConfig.from_env()
    if not cfg.enabled:
        return []
    q = _build_query(symbol, asset_type, query_hint)
    params: dict[str, str] = {"q": q, "format": "json", "safesearch": "0"}
    if time_range:
        params["time_range"] = time_range
    try:
        resp = requests.get(
            f"{cfg.url}/search", params=params, timeout=cfg.timeout_s,
            headers={"User-Agent": cfg.user_agent, "Accept": "application/json"},
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        # SearXNG can hard-fail (rate-limit, captcha redirect on the
        # JSON endpoint, …) — log once at WARN and degrade silently
        # so the workflow keeps its "no_news skip" semantics.
        log.warning("searxng search %r failed: %s", q, exc)
        return []
    raw = payload.get("results") or []
    if not isinstance(raw, list):
        log.warning("searxng search %r returned non-list results: %r",
                    q, type(raw).__name__)
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        url = (item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        title = (item.get("title") or "").strip()
        snippet = (item.get("content") or item.get("snippet") or "").strip()
        source = (item.get("parsed_url") or [None, ""])[1] \
            if isinstance(item.get("parsed_url"), list) else ""
        if not source:
            # Fallback: derive host from url. Avoid urlparse overhead;
            # a coarse split is fine for display purposes.
            try:
                source = url.split("/", 3)[2]
            except Exception:  # noqa: BLE001
                source = ""
        out.append({
            "id":      _evidence_id(url),
            "url":     url,
            "source":  source,
            "title":   title[:300],
            "snippet": snippet[:600],
            "engine":  (item.get("engine") or "").strip(),
        })
        if len(out) >= max(1, int(max_results)):
            break
    return out


def evidence_ids(results: Iterable[dict]) -> list[str]:
    """Convenience helper — flat list of `web:*` ids in the order they
    appear in the result list. The n8n Code-Brief node uses this to
    merge the web snippets into the brief's `evidence_ids` array
    without re-implementing the id scheme."""
    return [r["id"] for r in results if r.get("id")]

