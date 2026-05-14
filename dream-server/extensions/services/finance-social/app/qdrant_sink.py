"""Qdrant sink for finance-social.

Mirrors finance-news/qdrant_sink.py — separate collection
`finance_social` so payload schemas stay clean (one collection per
logical document type) and retention can be tuned independently.

Cosine distance, dimension determined on first write from the local
TEI service so the dimension stays in lock-step with whatever model
the embeddings container is currently running.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Sequence

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from tenacity import retry, stop_after_attempt, wait_exponential

log = logging.getLogger("finance-social.qdrant")


@dataclass
class QdrantConfig:
    url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://qdrant:6333"))
    api_key: str | None = field(default_factory=lambda: os.getenv("QDRANT_API_KEY") or None)
    collection: str = field(default_factory=lambda: os.getenv(
        "FINANCE_SOCIAL_COLLECTION", "finance_social"))
    embeddings_url: str = field(default_factory=lambda: os.getenv(
        "EMBEDDINGS_URL", "http://embeddings:80"))
    embed_batch: int = 32


_client: QdrantClient | None = None


def get_client(cfg: QdrantConfig) -> QdrantClient:
    global _client
    if _client is None:
        _client = QdrantClient(url=cfg.url, api_key=cfg.api_key, timeout=30)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def tei_embed(base_url: str, texts: list[str]) -> list[list[float]]:
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
    for field_name, schema in (
        ("symbols",   qm.PayloadSchemaType.KEYWORD),
        ("source",    qm.PayloadSchemaType.KEYWORD),
        ("channel",   qm.PayloadSchemaType.KEYWORD),
        ("ts_unix",   qm.PayloadSchemaType.INTEGER),
        ("sentiment", qm.PayloadSchemaType.FLOAT),
        ("score",     qm.PayloadSchemaType.INTEGER),
    ):
        try:
            client.create_payload_index(cfg.collection,
                                        field_name=field_name, field_schema=schema)
        except Exception as exc:  # noqa: BLE001
            log.warning("payload index %s failed (already exists?): %s", field_name, exc)


def build_embedding_text(ev: dict) -> str:
    title = (ev.get("title") or "").strip()
    body = ((ev.get("payload") or {}).get("selftext") or "").strip()
    syms = ev.get("symbols") or []
    parts = [title]
    if syms:
        parts.append("Symbols: " + ", ".join(syms))
    if body:
        parts.append(body)
    return "\n".join(p for p in parts if p)[:2000]


def upsert_events(cfg: QdrantConfig, events: Sequence[dict]) -> int:
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
            "doc_id":       ev["id"],
            "ts":           ev["ts"].isoformat() if hasattr(ev["ts"], "isoformat") else ev["ts"],
            "ts_unix":      int(ev["ts"].timestamp()) if hasattr(ev["ts"], "timestamp") else 0,
            "source":       ev["source"],
            "channel":      ev.get("channel"),
            "author":       ev.get("author"),
            "title":        ev.get("title"),
            "url":          ev.get("url"),
            "symbols":      ev.get("symbols") or [],
            "score":        ev.get("score"),
            "num_comments": ev.get("num_comments"),
            "sentiment":    ev.get("sentiment"),
            "urgency":      ev.get("urgency"),
        }
        points.append(qm.PointStruct(id=pid, vector=vec, payload=payload))

    client = get_client(cfg)
    client.upsert(collection_name=cfg.collection, points=points, wait=False)
    return len(points)


def search(cfg: QdrantConfig, query: str, limit: int = 10,
           symbols: list[str] | None = None) -> list[dict]:
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
        "vector_size": (info.config.params.vectors.size
                        if info.config and info.config.params.vectors else None),
    }

