"""Qdrant sink for finance-news.

Owns the `finance_news` collection (created on demand at the dimension
the local TEI service reports) and a thin search wrapper.

The sibling `finance-vector` service stores Stammdaten in
`finance_assets`; here we keep a separate collection for *events*.
That keeps payload schemas clean (one collection = one logical
document type) and lets retention be tuned independently.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-news.qdrant")


@dataclass
class QdrantConfig:
    url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    collection: str = field(default_factory=lambda: os.getenv("FINANCE_NEWS_COLLECTION", "finance_news"))
    embeddings_url: str = field(default_factory=lambda: os.getenv("EMBEDDINGS_URL", "http://embeddings:80"))
    embed_batch: int = 32


_client: QdrantClient | None = None


def get_client(cfg: QdrantConfig) -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=cfg.url, api_key=cfg.api_key, timeout=30)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def tei_embed(base_url: str, texts: list[str]) -> list[list[float]]:
    """POST /embed → list of vectors. TEI's response shape is
    `[[..vec..], [..vec..]]`."""
    if not texts:
        return []
    r = requests.post(
        f"{base_url.rstrip('/')}/embed",
        json={"inputs": texts, "truncate": True},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


def ensure_collection(cfg: QdrantConfig, dim: int) -> None:
    client = get_client(cfg)
    if client.collection_exists(cfg.collection):
        return
    log.info("Creating Qdrant collection %s (dim=%d, cosine)", cfg.collection, dim)
    client.create_collection(
        collection_name=cfg.collection,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )
    # Payload indexes — make symbol filtering cheap for strategy queries.
    for field_name, schema in (
        ("symbols", qm.PayloadSchemaType.KEYWORD),
        ("source", qm.PayloadSchemaType.KEYWORD),
        ("ts_unix", qm.PayloadSchemaType.INTEGER),
        ("sentiment", qm.PayloadSchemaType.FLOAT),
    ):
        try:
            client.create_payload_index(cfg.collection, field_name=field_name, field_schema=schema)
        except Exception as exc:  # noqa: BLE001
            log.warning("payload index %s failed (already exists?): %s", field_name, exc)


def upsert_events(cfg: QdrantConfig, events: Sequence[dict]) -> int:
    """Embed (title + summary) and upsert into Qdrant.

    `events[i]['id']` is the stable hash already used as the TimescaleDB
    primary key. We hash it into a deterministic UUID for Qdrant's
    point id (Qdrant requires int or UUID).
    """
    if not events:
        return 0

    texts = [build_embedding_text(e) for e in events]
    vectors: list[list[float]] = []
    for i in range(0, len(texts), cfg.embed_batch):
        batch = texts[i: i + cfg.embed_batch]
        vectors.extend(tei_embed(cfg.embeddings_url, batch))

    if not vectors:
        return 0

    dim = len(vectors[0])
    ensure_collection(cfg, dim)

    points: list[qm.PointStruct] = []
    for ev, vec in zip(events, vectors):
        pid = str(uuid.uuid5(uuid.NAMESPACE_URL, ev["id"]))
        payload = {
            "doc_id":     ev["id"],
            "ts":         ev["ts"].isoformat() if hasattr(ev["ts"], "isoformat") else ev["ts"],
            "ts_unix":    int(ev["ts"].timestamp()) if hasattr(ev["ts"], "timestamp") else 0,
            "source":     ev["source"],
            "channel":    ev.get("channel"),
            "title":      ev.get("title"),
            "summary":    (ev.get("payload") or {}).get("summary"),
            "url":        ev.get("url"),
            "symbols":    ev.get("symbols") or [],
            "sentiment":  ev.get("sentiment"),
            "urgency":    ev.get("urgency"),
        }
        points.append(qm.PointStruct(id=pid, vector=vec, payload=payload))

    client = get_client(cfg)
    client.upsert(collection_name=cfg.collection, points=points, wait=False)
    return len(points)


def build_embedding_text(ev: dict) -> str:
    title = (ev.get("title") or "").strip()
    summary = ((ev.get("payload") or {}).get("summary") or "").strip()
    syms = ev.get("symbols") or []
    parts = [title]
    if syms:
        parts.append("Symbols: " + ", ".join(syms))
    if summary:
        parts.append(summary)
    return "\n".join(p for p in parts if p)[:2000]


def search(cfg: QdrantConfig, query: str, limit: int = 10,
           symbols: list[str] | None = None) -> list[dict]:
    """Used by /search — embed the query then run an ANN lookup."""
    vec = tei_embed(cfg.embeddings_url, [query])
    if not vec:
        return []
    client = get_client(cfg)
    flt = None
    if symbols:
        flt = qm.Filter(must=[qm.FieldCondition(
            key="symbols", match=qm.MatchAny(any=[s.upper() for s in symbols]))])
    hits = client.search(
        collection_name=cfg.collection,
        query_vector=vec[0],
        query_filter=flt,
        limit=limit,
        with_payload=True,
    )
    return [{"score": h.score, **(h.payload or {})} for h in hits]


def stats(cfg: QdrantConfig) -> dict:
    client = get_client(cfg)
    if not client.collection_exists(cfg.collection):
        return {"collection": cfg.collection, "exists": False, "points": 0}
    info = client.get_collection(cfg.collection)
    return {
        "collection": cfg.collection,
        "exists": True,
        "points": info.points_count or 0,
        "vector_size": info.config.params.vectors.size if info.config and info.config.params.vectors else None,
    }

