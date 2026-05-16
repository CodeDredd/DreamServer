"""Read-side RAG helpers across every finance collection in Qdrant.

Phase B of FINANCE-GURU-IMPROVEMENT-PLAN.md: until now the only
collection any strategy actually *read* was the SQLite-backed
enrichment table; vector data written by finance-{vector,news,social}
and by `qdrant_sink.upsert_asset_analysis` was dead capital.

This module unifies the read-side so strategies and the dashboard can
ask vector-shaped questions ("which assets have ETF-inflow drivers in
the past two weeks?", "which retired strategies lost on news-sentiment
signals?", "which causal themes touch AAPL right now?") without each
caller re-implementing TEI + Qdrant glue.

Two new collections are also defined here so Phase D/E can write to
them via guarded endpoints:

* `finance_relations`         — causal themes (event → mechanism →
  affected sectors/symbols). Written by Phase E's
  `13-finance-causal-extraction` n8n workflow.
* `finance_strategy_lessons`  — lesson texts emitted by the weekly
  strategy auditor (Phase C) when a strategy is retired. Written by
  `weekly_audit()` directly from this service.

Every write/read here is best-effort: Qdrant or TEI outages MUST NOT
crash the orchestrator. Strategies see empty lists and degrade
gracefully.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Iterable

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-guru.qdrant-rag")


# --------------------------------------------------------------------------- #
# Config — env-driven; all collection names overridable so an operator
# can run a second guru against a sandbox Qdrant without redeploys.
# --------------------------------------------------------------------------- #
@dataclass
class RagConfig:
    url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    embeddings_url: str = field(default_factory=lambda: os.getenv(
        "EMBEDDINGS_URL", "http://embeddings:80"))
    enabled: bool = field(default_factory=lambda:
        os.getenv("FINANCE_GURU_QDRANT_SINK", "1").strip() not in ("0", "false", "no", ""))

    # Collections written by sibling services.
    assets_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_ASSETS_COLLECTION", "finance_assets"))
    news_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_NEWS_COLLECTION", "finance_news"))
    social_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_SOCIAL_COLLECTION", "finance_social"))
    analysis_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_ASSET_ANALYSIS_COLLECTION", "finance_asset_analysis"))

    # Collections owned by finance-guru-api (Phase B/D/E).
    relations_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_RELATIONS_COLLECTION", "finance_relations"))
    lessons_collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_STRATEGY_LESSONS_COLLECTION", "finance_strategy_lessons"))

    # Default top-K for strategy-facing RAG calls.
    default_topk: int = field(default_factory=lambda: int(os.getenv(
        "FINANCE_GURU_RAG_TOPK", "10")))


CFG = RagConfig()
_client: QdrantClient | None = None


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=CFG.url, api_key=CFG.api_key, timeout=20)
    return _client


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=6), reraise=True)
def _embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    r = requests.post(
        f"{CFG.embeddings_url.rstrip('/')}/embed",
        json={"inputs": texts, "truncate": True},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()


def _safe_search(*, collection: str, vector: list[float],
                 flt: qm.Filter | None, limit: int) -> list[dict]:
    """Wrap `client.search()` with the standard guards used by every
    read helper: collection-exists check, exception logging, normalised
    `{score, ...payload}` shape."""
    try:
        client = get_client()
        if not client.collection_exists(collection):
            return []
        hits = client.search(
            collection_name=collection,
            query_vector=vector,
            query_filter=flt,
            limit=max(1, min(int(limit), 100)),
            with_payload=True,
        )
        return [{"score": float(h.score), **(h.payload or {})} for h in hits]
    except Exception as exc:  # noqa: BLE001
        log.warning("qdrant search on %s failed: %s", collection, exc)
        return []


def _embed_or_empty(query: str) -> list[float] | None:
    if not query or not query.strip():
        return None
    try:
        v = _embed([query.strip()])
    except Exception as exc:  # noqa: BLE001
        log.warning("TEI embed failed for RAG query (%s): %s", query[:60], exc)
        return None
    return v[0] if v else None


# --------------------------------------------------------------------------- #
# Collection bootstrap — for the two collections owned here, plus
# defensive bootstrap for sibling-owned collections so RAG status &
# filtered scrolls don't fail when an upstream service hasn't written
# its first point yet (Phase P-3.3).
# --------------------------------------------------------------------------- #
def ensure_social_collection(dim: int | None = None) -> None:
    """Defensive bootstrap so /rag/status, /assets/canonical and the
    Phase P-2 health endpoint don't return error-shaped rows just
    because finance-social hasn't seen a single Reddit/StockTwits post
    yet (e.g. missing credentials). Idempotent; safe to call repeatedly.

    When `dim` is None we probe a sibling collection (`finance_news`
    then `finance_assets`) to inherit the live embedding dimension, so
    a future real finance-social upsert against TEI won't fail with a
    dim mismatch. Falls back to 768 if no sibling exists yet.
    """
    client = get_client()
    if client.collection_exists(CFG.social_collection):
        return
    if dim is None:
        for probe in (CFG.news_collection, CFG.assets_collection,
                      CFG.analysis_collection):
            try:
                if client.collection_exists(probe):
                    info = client.get_collection(probe)
                    if (info.config and info.config.params
                            and info.config.params.vectors):
                        dim = int(info.config.params.vectors.size)
                        log.info("ensure_social_collection: inherited dim=%d from %s",
                                 dim, probe)
                        break
            except Exception:  # noqa: BLE001
                continue
    if dim is None:
        dim = 768  # safe default matching the BGE base used by TEI
    log.info("Creating Qdrant collection %s (defensive bootstrap, dim=%d, cosine)",
             CFG.social_collection, dim)
    try:
        client.create_collection(
            collection_name=CFG.social_collection,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        for field_name, schema in (
            ("symbols",  qm.PayloadSchemaType.KEYWORD),
            ("source",   qm.PayloadSchemaType.KEYWORD),
            ("score",    qm.PayloadSchemaType.INTEGER),
            ("ts_unix",  qm.PayloadSchemaType.INTEGER),
        ):
            try:
                client.create_payload_index(
                    CFG.social_collection, field_name=field_name, field_schema=schema,
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("payload index %s/%s: %s",
                          CFG.social_collection, field_name, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("ensure_social_collection failed: %s", exc)


def ensure_relations_collection(dim: int) -> None:
    client = get_client()
    if client.collection_exists(CFG.relations_collection):
        return
    log.info("Creating Qdrant collection %s (dim=%d, cosine)",
             CFG.relations_collection, dim)
    client.create_collection(
        collection_name=CFG.relations_collection,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )
    for field_name, schema in (
        ("theme",      qm.PayloadSchemaType.KEYWORD),
        ("entities",   qm.PayloadSchemaType.KEYWORD),
        ("sectors",    qm.PayloadSchemaType.KEYWORD),
        ("symbols",    qm.PayloadSchemaType.KEYWORD),
        ("mechanism",  qm.PayloadSchemaType.KEYWORD),
        ("confidence", qm.PayloadSchemaType.FLOAT),
        ("ts_unix",    qm.PayloadSchemaType.INTEGER),
    ):
        try:
            client.create_payload_index(
                CFG.relations_collection, field_name=field_name, field_schema=schema,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("payload index %s/%s: %s",
                      CFG.relations_collection, field_name, exc)


def ensure_lessons_collection(dim: int) -> None:
    client = get_client()
    if client.collection_exists(CFG.lessons_collection):
        return
    log.info("Creating Qdrant collection %s (dim=%d, cosine)",
             CFG.lessons_collection, dim)
    client.create_collection(
        collection_name=CFG.lessons_collection,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )
    for field_name, schema in (
        ("strategy",   qm.PayloadSchemaType.KEYWORD),
        ("outcome",    qm.PayloadSchemaType.KEYWORD),
        ("pnl_pct",    qm.PayloadSchemaType.FLOAT),
        ("ts_unix",    qm.PayloadSchemaType.INTEGER),
    ):
        try:
            client.create_payload_index(
                CFG.lessons_collection, field_name=field_name, field_schema=schema,
            )
        except Exception as exc:  # noqa: BLE001
            log.debug("payload index %s/%s: %s",
                      CFG.lessons_collection, field_name, exc)


# --------------------------------------------------------------------------- #
# Write helpers — used by guarded endpoints / weekly_audit / Phase E
# --------------------------------------------------------------------------- #
def upsert_strategy_lesson(
    *,
    strategy: str,
    outcome: str,                 # 'retired' | 'promoted' | 'archived' | 'note'
    pnl_pct: float | None,
    lesson_text: str,
    keywords: Iterable[str] = (),
    ts: dt.datetime | None = None,
    extra: dict | None = None,
) -> bool:
    if not CFG.enabled or not lesson_text.strip():
        return False
    vec = _embed_or_empty(lesson_text)
    if vec is None:
        return False
    ts_dt = ts or dt.datetime.now(dt.timezone.utc)
    try:
        ensure_lessons_collection(len(vec))
        pid = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"strategy-lesson:{strategy}:{ts_dt.isoformat()}",
        ))
        payload: dict = {
            "strategy":   strategy,
            "outcome":    outcome,
            "pnl_pct":    float(pnl_pct) if pnl_pct is not None else None,
            "lesson":     lesson_text[:4000],
            "keywords":   sorted({str(k).strip().lower() for k in keywords if str(k).strip()})[:24],
            "ts":         ts_dt.isoformat(),
            "ts_unix":    int(ts_dt.timestamp()),
        }
        if extra:
            payload["extra"] = extra
        get_client().upsert(
            collection_name=CFG.lessons_collection,
            points=[qm.PointStruct(id=pid, vector=vec, payload=payload)],
            wait=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("strategy-lesson upsert failed for %s: %s", strategy, exc)
        return False


def upsert_relation(
    *,
    theme: str,
    summary: str,
    entities: Iterable[str] = (),
    sectors: Iterable[str] = (),
    symbols: Iterable[str] = (),
    mechanism: str | None = None,
    evidence_ids: Iterable[str | int] = (),
    confidence: float = 0.5,
    ts: dt.datetime | None = None,
    model: str | None = None,
) -> bool:
    """Upsert a causal-chain row. The Phase E `13-finance-causal-
    extraction` workflow drives this; we ship the helper now so the
    collection bootstraps on first manual write."""
    if not CFG.enabled or not theme.strip():
        return False
    text_parts = [f"Theme: {theme.strip()}"]
    if mechanism:
        text_parts.append(f"Mechanism: {mechanism.strip()}")
    if summary:
        text_parts.append(summary.strip())
    if symbols:
        text_parts.append("Symbols: " + ", ".join(sorted({s.upper() for s in symbols})))
    if sectors:
        text_parts.append("Sectors: " + ", ".join(sorted(set(sectors))))
    text = "\n".join(p for p in text_parts if p)[:2400]
    vec = _embed_or_empty(text)
    if vec is None:
        return False
    ts_dt = ts or dt.datetime.now(dt.timezone.utc)
    try:
        ensure_relations_collection(len(vec))
        pid = str(uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"relation:{theme.strip().lower()}:{ts_dt.isoformat()}",
        ))
        payload: dict = {
            "theme":        theme.strip(),
            "summary":      (summary or "")[:2000],
            "mechanism":    (mechanism or "")[:240] or None,
            "entities":     sorted({str(e).strip() for e in entities if str(e).strip()})[:24],
            "sectors":      sorted({str(s).strip() for s in sectors if str(s).strip()})[:24],
            "symbols":      sorted({str(s).upper().strip() for s in symbols if str(s).strip()})[:32],
            "evidence_ids": [str(x) for x in evidence_ids][:64],
            "confidence":   max(0.0, min(1.0, float(confidence))),
            "model":        model,
            "ts":           ts_dt.isoformat(),
            "ts_unix":      int(ts_dt.timestamp()),
        }
        get_client().upsert(
            collection_name=CFG.relations_collection,
            points=[qm.PointStruct(id=pid, vector=vec, payload=payload)],
            wait=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("relation upsert failed for theme=%s: %s", theme, exc)
        return False


# --------------------------------------------------------------------------- #
# Canonical universe — Phase P-1
# --------------------------------------------------------------------------- #
def list_assets(*, asset_type: str | None = None,
                limit: int = 2000) -> list[dict]:
    """Scroll the `finance_assets` collection and return the canonical
    universe — symbol/name/sector/country/type — *independent* of
    market hours, finance-prices cron, or any live-tick freshness.

    This is the source of truth for n8n workflows that pick which
    assets to enrich/cluster/causally-extract. Replaces the prior
    `GET /history/symbols?hours=168` coupling that silently emptied
    the stock universe on weekends + holidays + after-hours
    (Phase P-1 of FINANCE-GURU-IMPROVEMENT-PLAN.md).

    Returns an empty list on any Qdrant outage (best-effort, like every
    other RAG read here)."""
    try:
        client = get_client()
        if not client.collection_exists(CFG.assets_collection):
            return []
        must: list = []
        if asset_type:
            must.append(qm.FieldCondition(
                key="type",
                match=qm.MatchValue(value=asset_type.strip().lower())))
        flt = qm.Filter(must=must) if must else None
        out: list[dict] = []
        next_offset = None
        page = max(64, min(int(limit), 1000))
        while True:
            points, next_offset = client.scroll(
                collection_name=CFG.assets_collection,
                scroll_filter=flt,
                limit=page,
                with_payload=True,
                with_vectors=False,
                offset=next_offset,
            )
            for p in points:
                pl = p.payload or {}
                sym = (pl.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                out.append({
                    "symbol":     sym,
                    "name":       pl.get("name"),
                    "type":       pl.get("type"),
                    "sector":     pl.get("sector"),
                    "country":    pl.get("country"),
                    "market_cap": pl.get("market_cap"),
                })
                if len(out) >= int(limit):
                    return out
            if next_offset is None or not points:
                return out
    except Exception as exc:  # noqa: BLE001
        log.warning("list_assets(asset_type=%s) failed: %s", asset_type, exc)
        return []


# --------------------------------------------------------------------------- #
# Read helpers — strategy-facing
# --------------------------------------------------------------------------- #
def search_assets(query: str, *, limit: int | None = None,
                  sectors: list[str] | None = None,
                  countries: list[str] | None = None,
                  asset_types: list[str] | None = None,
                  min_market_cap: float | None = None) -> list[dict]:
    """RAG over the daily-refreshed `finance_assets` Stammdaten."""
    vec = _embed_or_empty(query)
    if vec is None:
        return []
    must: list = []
    if sectors:
        must.append(qm.FieldCondition(key="sector",
                                      match=qm.MatchAny(any=list(sectors))))
    if countries:
        must.append(qm.FieldCondition(key="country",
                                      match=qm.MatchAny(any=list(countries))))
    if asset_types:
        must.append(qm.FieldCondition(key="type",
                                      match=qm.MatchAny(any=list(asset_types))))
    if min_market_cap is not None:
        must.append(qm.FieldCondition(key="market_cap",
                                      range=qm.Range(gte=float(min_market_cap))))
    flt = qm.Filter(must=must) if must else None
    return _safe_search(collection=CFG.assets_collection, vector=vec,
                        flt=flt, limit=limit or CFG.default_topk)


def search_news(query: str, *, limit: int | None = None,
                symbols: list[str] | None = None,
                since: dt.datetime | None = None,
                min_sentiment_abs: float | None = None,
                min_source_weight: float | None = None) -> list[dict]:
    """RAG over `finance_news` — symbol filter is a MatchAny so the
    caller can pass the universe slice for the cycle."""
    vec = _embed_or_empty(query)
    if vec is None:
        return []
    must: list = []
    if symbols:
        must.append(qm.FieldCondition(
            key="symbols", match=qm.MatchAny(any=[s.upper() for s in symbols])))
    if since:
        must.append(qm.FieldCondition(
            key="ts_unix", range=qm.Range(gte=int(since.timestamp()))))
    if min_source_weight is not None:
        must.append(qm.FieldCondition(
            key="source_weight",
            range=qm.Range(gte=float(min_source_weight))))
    flt = qm.Filter(must=must) if must else None
    hits = _safe_search(collection=CFG.news_collection, vector=vec,
                        flt=flt, limit=limit or CFG.default_topk)
    if min_sentiment_abs is not None:
        thr = float(min_sentiment_abs)
        hits = [h for h in hits
                if h.get("sentiment") is not None and abs(h["sentiment"]) >= thr]
    return hits


def search_social(query: str, *, limit: int | None = None,
                  symbols: list[str] | None = None,
                  since: dt.datetime | None = None,
                  min_score: int | None = None) -> list[dict]:
    """RAG over `finance_social` (Reddit posts written by
    finance-social)."""
    vec = _embed_or_empty(query)
    if vec is None:
        return []
    must: list = []
    if symbols:
        must.append(qm.FieldCondition(
            key="symbols", match=qm.MatchAny(any=[s.upper() for s in symbols])))
    if since:
        must.append(qm.FieldCondition(
            key="ts_unix", range=qm.Range(gte=int(since.timestamp()))))
    if min_score is not None:
        must.append(qm.FieldCondition(
            key="score", range=qm.Range(gte=int(min_score))))
    flt = qm.Filter(must=must) if must else None
    return _safe_search(collection=CFG.social_collection, vector=vec,
                        flt=flt, limit=limit or CFG.default_topk)


def search_asset_analyses(query: str, *, limit: int | None = None,
                          symbols: list[str] | None = None,
                          min_confidence: float = 0.0) -> list[dict]:
    """RAG over `finance_asset_analysis` (the per-symbol LLM verdicts
    written by `enrichment.upsert_asset_analysis` → `qdrant_sink`).

    Duplicates the behaviour of `qdrant_sink.search_similar_analyses`
    but lives in the unified RAG module so DecisionContext only needs
    one import."""
    vec = _embed_or_empty(query)
    if vec is None:
        return []
    must: list = []
    if symbols:
        must.append(qm.FieldCondition(
            key="symbol", match=qm.MatchAny(any=[s.upper() for s in symbols])))
    if min_confidence > 0:
        must.append(qm.FieldCondition(
            key="confidence", range=qm.Range(gte=float(min_confidence))))
    flt = qm.Filter(must=must) if must else None
    return _safe_search(collection=CFG.analysis_collection, vector=vec,
                        flt=flt, limit=limit or CFG.default_topk)


def search_relations(query: str, *, limit: int | None = None,
                     symbols: list[str] | None = None,
                     sectors: list[str] | None = None,
                     min_confidence: float = 0.0,
                     since: dt.datetime | None = None) -> list[dict]:
    """RAG over `finance_relations` — causal themes. Returns empty
    until Phase E's workflow starts writing."""
    vec = _embed_or_empty(query)
    if vec is None:
        return []
    must: list = []
    if symbols:
        must.append(qm.FieldCondition(
            key="symbols", match=qm.MatchAny(any=[s.upper() for s in symbols])))
    if sectors:
        must.append(qm.FieldCondition(
            key="sectors", match=qm.MatchAny(any=list(sectors))))
    if min_confidence > 0:
        must.append(qm.FieldCondition(
            key="confidence", range=qm.Range(gte=float(min_confidence))))
    if since:
        must.append(qm.FieldCondition(
            key="ts_unix", range=qm.Range(gte=int(since.timestamp()))))
    flt = qm.Filter(must=must) if must else None
    return _safe_search(collection=CFG.relations_collection, vector=vec,
                        flt=flt, limit=limit or CFG.default_topk)


def search_strategy_lessons(query: str, *, limit: int | None = None,
                            strategies: list[str] | None = None,
                            outcomes: list[str] | None = None) -> list[dict]:
    """RAG over `finance_strategy_lessons`. Used by the (Phase D)
    strategy-generator workflow to avoid re-proposing patterns that
    already retired with negative PnL."""
    vec = _embed_or_empty(query)
    if vec is None:
        return []
    must: list = []
    if strategies:
        must.append(qm.FieldCondition(
            key="strategy", match=qm.MatchAny(any=list(strategies))))
    if outcomes:
        must.append(qm.FieldCondition(
            key="outcome", match=qm.MatchAny(any=list(outcomes))))
    flt = qm.Filter(must=must) if must else None
    return _safe_search(collection=CFG.lessons_collection, vector=vec,
                        flt=flt, limit=limit or CFG.default_topk)


# --------------------------------------------------------------------------- #
# Status — drives /enrichment/rag/status for the dashboard panel.
# --------------------------------------------------------------------------- #
def collection_status() -> list[dict]:
    """One row per RAG collection — exists?, points, dim. Used by the
    dashboard "Vector-DB" tile (Phase F) and `dream doctor` later."""
    out: list[dict] = []
    client = get_client()
    for label, name in (
        ("assets",        CFG.assets_collection),
        ("news",          CFG.news_collection),
        ("social",        CFG.social_collection),
        ("asset_analysis", CFG.analysis_collection),
        ("relations",     CFG.relations_collection),
        ("lessons",       CFG.lessons_collection),
    ):
        try:
            exists = client.collection_exists(name)
            if not exists:
                out.append({"label": label, "collection": name,
                            "exists": False, "points": 0, "dim": None})
                continue
            info = client.get_collection(name)
            dim = (info.config.params.vectors.size
                   if info.config and info.config.params and info.config.params.vectors
                   else None)
            out.append({
                "label":      label,
                "collection": name,
                "exists":     True,
                "points":     int(info.points_count or 0),
                "dim":        dim,
            })
        except Exception as exc:  # noqa: BLE001
            log.debug("collection_status(%s) failed: %s", name, exc)
            out.append({"label": label, "collection": name, "exists": False,
                        "points": 0, "dim": None, "error": str(exc)[:160]})
    return out

