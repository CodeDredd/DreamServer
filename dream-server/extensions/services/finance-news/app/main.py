"""FastAPI wrapper around the finance-news aggregator.

Pipeline (one cycle):
  1. fetch all configured RSS feeds (parallel, per-feed errors tolerated)
  2. dedup against TimescaleDB news.events (last 7 days)
  3. tag with symbols from the cached finance_assets universe
  4. classify sentiment + urgency via LiteLLM qwen3-4b (optional)
  5. write to TimescaleDB (news.events hypertable)
  6. embed + write to Qdrant (finance_news collection)

Cron default: */10 * * * * — see AGENT-OPERATIONS.md §11 cadence table.

Endpoints
---------
GET  /health      liveness
GET  /status      job state + DB/Qdrant stats + per-feed counters
POST /refresh     trigger ad-hoc fetch (bearer-token guarded)
POST /search      semantic search over Qdrant
                  body: {"q": "...", "limit": 10, "symbols": ["AAPL"]}
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from . import db, feeds, qdrant_sink, sentiment

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("finance-news.api")

DB_CFG = db.DbConfig()
QDRANT_CFG = qdrant_sink.QdrantConfig()
UNIV_CFG = feeds.UniverseCfg()
LLM_CFG = sentiment.LlmConfig()

TOKEN = os.getenv("FINANCE_NEWS_TOKEN", "").strip()
TZ_NAME = os.getenv("FINANCE_NEWS_TZ", "UTC")
CRON = os.getenv("FINANCE_NEWS_CRON", "*/10 * * * *").strip()
RUN_ON_START = os.getenv("FINANCE_NEWS_RUN_ON_START", "auto").lower()
MAX_PER_FEED = int(os.getenv("FINANCE_NEWS_MAX_PER_FEED", "50"))
DEDUP = os.getenv("FINANCE_NEWS_DEDUP", "true").lower() == "true"

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "last_started": None,
    "last_completed": None,
    "last_error": None,
    "next_run": None,
    "last_counts": {},
    "feeds": {},
}


def _run_cycle_blocking() -> None:
    if not _lock.acquire(blocking=False):
        log.info("cycle already running, skipping")
        return
    try:
        _state["running"] = True
        _state["last_started"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _state["last_error"] = None

        feed_list = feeds.configured_feeds()
        univ = feeds.get_universe(UNIV_CFG)

        # 1. fetch all feeds in parallel
        all_events: list[dict] = []
        per_feed: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(feed_list)))) as pool:
            futures = {
                pool.submit(feeds.fetch_feed, ch, url, MAX_PER_FEED): (ch, url)
                for ch, url in feed_list
            }
            for fut in as_completed(futures):
                ch, _url = futures[fut]
                try:
                    items = fut.result()
                    per_feed[ch] = {"fetched": len(items), "error": None}
                    all_events.extend(items)
                except Exception as exc:  # noqa: BLE001
                    per_feed[ch] = {"fetched": 0, "error": str(exc)}
                    log.warning("feed %s error: %s", ch, exc)

        if not all_events:
            log.info("no items pulled from any feed this cycle")
            _state["feeds"] = per_feed
            _state["last_counts"] = {"fetched": 0, "new": 0,
                                     "tagged_with_symbols": 0,
                                     "scored": 0, "db_rows": 0, "qdrant_points": 0}
            _state["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
            return

        # 2. dedup
        if DEDUP:
            ids = [ev["id"] for ev in all_events]
            already = db.existing_ids(DB_CFG, ids, dt.timedelta(days=14))
            new_events = [ev for ev in all_events if ev["id"] not in already]
        else:
            new_events = all_events
        log.info("fetched=%d  new_after_dedup=%d", len(all_events), len(new_events))

        if not new_events:
            _state["feeds"] = per_feed
            _state["last_counts"] = {"fetched": len(all_events), "new": 0,
                                     "tagged_with_symbols": 0,
                                     "scored": 0, "db_rows": 0, "qdrant_points": 0}
            _state["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
            return

        # 3. tag symbols
        tagged = 0
        for ev in new_events:
            syms = feeds.extract_symbols(
                ev.get("title") or "",
                (ev.get("payload") or {}).get("summary") or "",
                univ,
            )
            ev["symbols"] = syms
            if syms:
                tagged += 1

        # 4. sentiment / urgency via LiteLLM
        sentiment.classify(new_events, LLM_CFG)
        scored = sum(1 for ev in new_events if ev.get("sentiment") is not None)

        # 5. write to TimescaleDB
        db_rows = db.upsert_events(DB_CFG, new_events)

        # 6. write to Qdrant (embeds happen here)
        try:
            qd_points = qdrant_sink.upsert_events(QDRANT_CFG, new_events)
        except Exception as exc:  # noqa: BLE001
            log.exception("qdrant upsert failed: %s", exc)
            qd_points = 0

        _state["feeds"] = per_feed
        _state["last_counts"] = {
            "fetched": len(all_events),
            "new": len(new_events),
            "tagged_with_symbols": tagged,
            "scored": scored,
            "db_rows": db_rows,
            "qdrant_points": qd_points,
        }
        _state["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
        log.info("cycle done: %s", _state["last_counts"])
    except Exception as exc:  # noqa: BLE001
        log.exception("cycle failed")
        _state["last_error"] = str(exc)
    finally:
        _state["running"] = False
        _lock.release()


async def _cycle_async() -> None:
    await asyncio.to_thread(_run_cycle_blocking)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wait for the DB then ensure schema (mirrors the init SQL).
    for attempt in range(20):
        try:
            db.ensure_schema(DB_CFG)
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("DB not ready (%s) — retry %d/20", exc, attempt + 1)
            await asyncio.sleep(3)
    else:
        log.error("Could not ensure schema after 20 attempts; continuing anyway")

    scheduler = AsyncIOScheduler(timezone=TZ_NAME)
    try:
        trigger = CronTrigger.from_crontab(CRON, timezone=TZ_NAME)
    except Exception as exc:  # noqa: BLE001
        log.error("Invalid cron %r: %s — falling back to */10", CRON, exc)
        trigger = CronTrigger(minute="*/10", timezone=TZ_NAME)
    scheduler.add_job(_cycle_async, trigger, id="news_cycle",
                      coalesce=True, max_instances=1, misfire_grace_time=300)
    scheduler.start()
    job = scheduler.get_job("news_cycle")
    if job and job.next_run_time:
        _state["next_run"] = job.next_run_time.isoformat()
    log.info("Scheduler started: cron=%r tz=%s", CRON, TZ_NAME)

    if RUN_ON_START in ("always", "auto"):
        rows = 0
        if RUN_ON_START == "auto":
            try:
                rows = db.stats(DB_CFG).get("rows_estimate", 0)
            except Exception:
                rows = 0
        if RUN_ON_START == "always" or rows == 0:
            log.info("Kicking initial cycle (RUN_ON_START=%s, rows=%d)",
                     RUN_ON_START, rows)
            asyncio.create_task(_cycle_async())

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Dream Server Finance News Aggregator",
              version="0.1.0", lifespan=lifespan)


def _check_token(authorization: str | None) -> None:
    if not TOKEN:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    if authorization.split(" ", 1)[1].strip() != TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "running": _state["running"]}


@app.get("/status")
def get_status() -> dict:
    out = {
        "schedule": {"cron": CRON, "timezone": TZ_NAME, "dedup": DEDUP},
        "job":      _state,
        "feeds_configured": [c for c, _ in feeds.configured_feeds()],
    }
    try:
        out["db"] = db.stats(DB_CFG)
    except Exception as exc:  # noqa: BLE001
        out["db"] = {"error": str(exc)}
    try:
        out["qdrant"] = qdrant_sink.stats(QDRANT_CFG)
    except Exception as exc:  # noqa: BLE001
        out["qdrant"] = {"error": str(exc)}
    out["llm"] = {
        "enabled":  LLM_CFG.enabled,
        "model":    LLM_CFG.model,
        "base_url": LLM_CFG.base_url,
    }
    out["universe"] = {
        "symbols": len(feeds.get_universe(UNIV_CFG).by_symbol),
    }
    return out


@app.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh(background: BackgroundTasks,
            authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    background.add_task(_run_cycle_blocking)
    return {"accepted": True,
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}


class SearchRequest(BaseModel):
    q: str = Field(..., min_length=2, max_length=500)
    limit: int = Field(10, ge=1, le=50)
    symbols: list[str] | None = None


@app.post("/search")
def search(req: SearchRequest) -> dict:
    hits = qdrant_sink.search(QDRANT_CFG, req.q, limit=req.limit,
                              symbols=req.symbols)
    return {"q": req.q, "count": len(hits), "results": hits}

