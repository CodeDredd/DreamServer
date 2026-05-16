"""Qdrant sink for enrichment artefacts.

Two write paths:

1. **`finance_asset_analysis`** (new collection, 768-dim TEI) — every
   asset-behaviour analysis the n8n workflow stores via
   `POST /enrichment/asset-analysis` also gets embedded (`summary` +
   `keywords`) and upserted here. Strategies (and any RAG flow) can
   then semantic-search "which assets recently had ETF inflow drivers?"
   without joining SQLite.

2. **`finance_news` payload patch** — every source-reliability score
   stored via `POST /enrichment/source-reliability` is propagated as
   `payload.source_weight` (and `payload.source_reliability`) on **all**
   news points of that source. The Qdrant query `must` filter already
   used by strategies will then naturally benefit from the weighting
   (e.g. boost reliable wire-service sources). This is the lever the
   user asked for: "die vector database soll besser werden".

Both writes are **fire-and-forget** — if Qdrant or TEI is down we log
a warning, the SQLite write is unaffected. Keeps the n8n workflows
non-blocking on infra hiccups.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Iterable

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-guru.qdrant")


@dataclass
class QdrantSinkConfig:
    url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    analysis_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_ASSET_ANALYSIS_COLLECTION", "finance_asset_analysis"))
    news_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_NEWS_COLLECTION", "finance_news"))
    embeddings_url: str = field(default_factory=lambda: os.getenv(
        "EMBEDDINGS_URL", "http://embeddings:80"))
    enabled: bool = field(default_factory=lambda:
        os.getenv("FINANCE_GURU_QDRANT_SINK", "1").strip() not in ("0", "false", "no", ""))


CFG = QdrantSinkConfig()
_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=CFG.url, api_key=CFG.api_key, timeout=20)
    return _client


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=6), reraise=True)
def _tei_embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    r = requests.post(
        f"{CFG.embeddings_url.rstrip('/')}/embed",
        json={"inputs": texts, "truncate": True},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def ensure_analysis_collection(dim: int) -> None:
    client = get_client()
    if client.collection_exists(CFG.analysis_collection):
        return
    log.info("Creating Qdrant collection %s (dim=%d, cosine)",
             CFG.analysis_collection, dim)
    client.create_collection(
        collection_name=CFG.analysis_collection,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )
    for field_name, schema in (
        ("symbol",      qm.PayloadSchemaType.KEYWORD),
        ("asset_type",  qm.PayloadSchemaType.KEYWORD),
        ("keywords",    qm.PayloadSchemaType.KEYWORD),
        ("confidence",  qm.PayloadSchemaType.FLOAT),
        ("ts_unix",     qm.PayloadSchemaType.INTEGER),
    ):
        try:
            client.create_payload_index(
                CFG.analysis_collection, field_name=field_name, field_schema=schema,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("payload index %s: %s", field_name, exc)


# --------------------------------------------------------------------------- #
# Public sink functions — called from enrichment.py after the SQLite write
# --------------------------------------------------------------------------- #
def upsert_asset_analysis(
    *,
    analysis_id: int,
    symbol: str,
    asset_type: str,
    period_start: str,
    period_end: str,
    summary: str,
    keywords: list[str],
    drivers: list[dict],
    news_ids: list,
    confidence: float,
    model: str,
    ts: str,
) -> bool:
    """Embed (summary + keywords) and upsert one point into the
    `finance_asset_analysis` collection. Returns True on success."""
    if not CFG.enabled:
        return False
    text = _build_analysis_text(symbol, summary, keywords, drivers)
    try:
        vectors = _tei_embed([text])
    except Exception as exc:  # noqa: BLE001
        log.warning("TEI embed failed for analysis %s/%s: %s", symbol, analysis_id, exc)
        return False
    if not vectors:
        return False
    dim = len(vectors[0])
    try:
        ensure_analysis_collection(dim)
        import datetime as _dt
        ts_unix = int(_dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()) \
            if isinstance(ts, str) else 0
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                              f"asset-analysis:{symbol}:{period_start}:{period_end}:{analysis_id}"))
        payload = {
            "analysis_id": analysis_id,
            "symbol":      symbol.upper(),
            "asset_type":  asset_type,
            "period_start": period_start,
            "period_end":   period_end,
            "summary":      summary[:2000],
            "keywords":     keywords[:32],
            "driver_dates": [str(d.get("date") or "")[:10] for d in (drivers or [])][:16],
            "news_ids":     [str(x) for x in (news_ids or [])][:64],
            "confidence":   float(confidence),
            "model":        model,
            "ts":           ts,
            "ts_unix":      ts_unix,
        }
        get_client().upsert(
            collection_name=CFG.analysis_collection,
            points=[qm.PointStruct(id=pid, vector=vectors[0], payload=payload)],
            wait=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Qdrant upsert failed for analysis %s/%s: %s", symbol, analysis_id, exc)
        return False


def propagate_source_weight(*, source: str, reliability: float,
                             weight: float, model: str) -> int:
    """Patch every news point of `source` with the new reliability/weight.

    Uses Qdrant's `set_payload` so we don't re-embed anything. Strategies
    that already use the news collection get the weight for free.
    Returns the number of matched points (best-effort — Qdrant doesn't
    always return that, so we count via a probe query first).
    """
    if not CFG.enabled:
        return 0
    try:
        client = get_client()
        if not client.collection_exists(CFG.news_collection):
            log.debug("news collection %s does not exist yet — skipping payload patch",
                      CFG.news_collection)
            return 0
        flt = qm.Filter(must=[
            qm.FieldCondition(key="source",
                              match=qm.MatchValue(value=source.lower().strip()))
        ])
        # Count probe (cheap, no payload pulled).
        try:
            count = client.count(collection_name=CFG.news_collection,
                                 count_filter=flt, exact=False).count
        except Exception:  # noqa: BLE001
            count = -1
        client.set_payload(
            collection_name=CFG.news_collection,
            payload={
                "source_reliability": float(reliability),
                "source_weight":      float(weight),
                "source_scored_by":   model,
            },
            points=flt,
            wait=False,
        )
        log.info("Patched ~%s news points for source=%s (reliability=%.2f weight=%.2f)",
                 count, source, reliability, weight)
        return int(count or 0)
    except Exception as exc:  # noqa: BLE001
        log.warning("Qdrant source_weight propagation failed for %s: %s", source, exc)
        return 0


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _build_analysis_text(symbol: str, summary: str,
                         keywords: Iterable[str],
                         drivers: list[dict]) -> str:
    """Compact embedding text — the things you'd actually want to
    semantic-search for: the verdict, the keywords, and the per-driver
    reason lines. Avoids stuffing the prompt with raw news IDs."""
    kw_line = ", ".join(sorted({str(k).strip().lower() for k in keywords if str(k).strip()}))
    drv_lines = []
    for d in (drivers or [])[:6]:
        date = str(d.get("date") or "")[:10]
        pct = d.get("move_pct")
        reason = (d.get("reason") or "")[:160]
        if reason:
            drv_lines.append(f"{date} {pct:+.1f}%: {reason}" if pct is not None
                             else f"{date}: {reason}")
    parts = [f"Asset: {symbol.upper()}", (summary or "").strip()]
    if kw_line:
        parts.append(f"Keywords: {kw_line}")
    if drv_lines:
        parts.append("Drivers:\n" + "\n".join(drv_lines))
    return "\n".join(p for p in parts if p)[:2400]


# --------------------------------------------------------------------------- #
# Read-side helper — used by strategies via DecisionContext
# --------------------------------------------------------------------------- #
def search_similar_analyses(query: str, *, limit: int = 5,
                             symbols: list[str] | None = None,
                             min_confidence: float = 0.0) -> list[dict]:
    """Semantic search over `finance_asset_analysis` — returns up to
    `limit` analyses ranked by cosine similarity. Used by future RAG
    strategies / dashboards."""
    if not CFG.enabled:
        return []
    try:
        client = get_client()
        if not client.collection_exists(CFG.analysis_collection):
            return []
        vec = _tei_embed([query])
        if not vec:
            return []
        flt_terms: list = []
        if symbols:
            flt_terms.append(qm.FieldCondition(
                key="symbol", match=qm.MatchAny(any=[s.upper() for s in symbols])))
        if min_confidence > 0:
            flt_terms.append(qm.FieldCondition(
                key="confidence",
                range=qm.Range(gte=float(min_confidence))))
        flt = qm.Filter(must=flt_terms) if flt_terms else None
        hits = client.search(
            collection_name=CFG.analysis_collection,
            query_vector=vec[0], query_filter=flt,
            limit=limit, with_payload=True,
        )
        return [{"score": h.score, **(h.payload or {})} for h in hits]
    except Exception as exc:  # noqa: BLE001
        log.warning("similar-analyses search failed: %s", exc)
        return []

