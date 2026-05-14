"""FastAPI wrapper around the finance-social aggregator.

Pipeline (one cycle):
  1. for each configured subreddit, fetch /new (parallel, per-sub
     errors tolerated)
  2. dedup against TimescaleDB social.events (last 14 days)
  3. tag with symbols from the cached finance_assets universe
  4. classify sentiment + urgency via LiteLLM `fast` (qwen3-4b)
  5. write to TimescaleDB (social.events hypertable)
  6. embed + write to Qdrant (finance_social collection)

Cron default: */15 * * * * — see AGENT-OPERATIONS.md §11 cadence.

Endpoints
---------
GET  /health      liveness
GET  /status      job state + DB/Qdrant stats + per-subreddit counters
POST /refresh     trigger ad-hoc fetch (bearer-token guarded)
POST /search      semantic search over Qdrant
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

from . import db, qdrant_sink, reddit_client, sentiment, symbols

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("finance-social.api")

DB_CFG       = db.DbConfig()
QDRANT_CFG   = qdrant_sink.QdrantConfig()
UNIV_CFG     = symbols.UniverseCfg()
LLM_CFG      = sentiment.LlmConfig()
REDDIT_CFG   = reddit_client.RedditConfig()

TOKEN          = os.getenv("FINANCE_SOCIAL_TOKEN", "").strip()
TZ_NAME        = os.getenv("FINANCE_SOCIAL_TZ", "UTC")
CRON           = os.getenv("FINANCE_SOCIAL_CRON", "*/15 * * * *").strip()
RUN_ON_START   = os.getenv("FINANCE_SOCIAL_RUN_ON_START", "auto").lower()
MAX_PER_SUB    = int(os.getenv("FINANCE_SOCIAL_MAX_PER_SUB", "50"))
DEDUP          = os.getenv("FINANCE_SOCIAL_DEDUP", "true").lower() == "true"

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "last_started": None,
    "last_completed": None,
    "last_error": None,
    "next_run": None,
    "last_counts": {},
    "subs": {},
}


def _run_cycle_blocking() -> None:
    if not _lock.acquire(blocking=False):
        log.info("cycle already running, skipping")
        return
    try:
        _state["running"] = True
        _state["last_started"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _state["last_error"] = None

        if not REDDIT_CFG.configured:
            log.warning("Reddit credentials missing — skipping fetch")
            _state["last_error"] = "reddit_unconfigured"
            _state["last_counts"] = {"fetched": 0, "new": 0,
                                     "tagged_with_symbols": 0,
                                     "scored": 0, "db_rows": 0, "qdrant_points": 0}
            _state["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
            return

        sub_list = reddit_client.configured_subreddits()
        univ = symbols.get_universe(UNIV_CFG)

        # 1. fetch all subs in parallel — PRAW is thread-safe, and
        #    we keep workers small to stay polite to Reddit's rate
        #    limit even though praw self-throttles.
        all_events: list[dict] = []
        per_sub: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(sub_list)))) as pool:
            futures = {
                pool.submit(reddit_client.fetch_subreddit, REDDIT_CFG, s, MAX_PER_SUB): s
                for s in sub_list
            }
            for fut in as_completed(futures):
                s = futures[fut]
                try:
                    items = fut.result()
                    per_sub[s] = {"fetched": len(items), "error": None}
                    all_events.extend(items)
                except Exception as exc:  # noqa: BLE001
                    per_sub[s] = {"fetched": 0, "error": str(exc)}
                    log.warning("subreddit %s error: %s", s, exc)

        if not all_events:
            log.info("no items pulled from any subreddit this cycle")
            _state["subs"] = per_sub
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
        log.info("fetched=%d new_after_dedup=%d", len(all_events), len(new_events))

        if not new_events:
            _state["subs"] = per_sub
            _state["last_counts"] = {"fetched": len(all_events), "new": 0,
                                     "tagged_with_symbols": 0,
                                     "scored": 0, "db_rows": 0, "qdrant_points": 0}
            _state["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
            return

        # 3. tag symbols
        tagged = 0
        for ev in new_events:
            body = (ev.get("payload") or {}).get("selftext") or ""
            syms = symbols.extract_symbols(ev.get("title") or "", body, univ)
            ev["symbols"] = syms
            if syms:
                tagged += 1

        # 4. sentiment / urgency via LiteLLM (only score posts that
        #    actually mention a known symbol — keeps the LLM bill
        #    in proportion to signal).
        scoreable = [ev for ev in new_events if ev.get("symbols")]
        sentiment.classify(scoreable, LLM_CFG)
        scored = sum(1 for ev in scoreable if ev.get("sentiment") is not None)

        # 5. write to TimescaleDB
        db_rows = db.upsert_events(DB_CFG, new_events)

        # 6. write to Qdrant — only embed scored items by default, since
        #    a Reddit post with no symbol mention is rarely worth a search hit.
        try:
            qd_points = qdrant_sink.upsert_events(QDRANT_CFG, scoreable)
        except Exception as exc:  # noqa: BLE001
            log.exception("qdrant upsert failed: %s", exc)
            qd_points = 0

        _state["subs"] = per_sub
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
        log.error("Invalid cron %r: %s — falling back to */15", CRON, exc)
        trigger = CronTrigger(minute="*/15", timezone=TZ_NAME)
    scheduler.add_job(_cycle_async, trigger, id="social_cycle",
                      coalesce=True, max_instances=1, misfire_grace_time=300)
    scheduler.start()
    job = scheduler.get_job("social_cycle")
    if job and job.next_run_time:
        _state["next_run"] = job.next_run_time.isoformat()
    log.info("Scheduler started: cron=%r tz=%s", CRON, TZ_NAME)

    if RUN_ON_START in ("always", "auto") and REDDIT_CFG.configured:
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


app = FastAPI(title="Dream Server Finance Social Aggregator",
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
    return {"status": "ok", "running": _state["running"],
            "reddit_configured": REDDIT_CFG.configured}


@app.get("/status")
def get_status() -> dict:
    out = {
        "schedule": {"cron": CRON, "timezone": TZ_NAME, "dedup": DEDUP},
        "job":      _state,
        "reddit": {
            "configured": REDDIT_CFG.configured,
            "subreddits": reddit_client.configured_subreddits(),
            "user_agent": REDDIT_CFG.user_agent,
        },
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
        "symbols": len(symbols.get_universe(UNIV_CFG).by_symbol),
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

