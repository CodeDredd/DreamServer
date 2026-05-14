"""FastAPI wrapper around the finance vector seeder.

Endpoints
---------
GET  /health     liveness probe
GET  /status     last/next run, current point count
POST /refresh    trigger a seed run in the background (bearer-token guarded)

Scheduling
----------
APScheduler runs the cron defined by FINANCE_REFRESH_CRON (default
"17 3 * * *" UTC). On startup, FINANCE_RUN_ON_START controls whether
to seed immediately:
  * auto   -> seed if collection is empty (default)
  * always -> always seed
  * never  -> just schedule, don't seed at boot
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, status

from .seeder import SeederConfig, collection_point_count, run_seed

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("finance-vector.api")

CFG = SeederConfig()
TOKEN = os.getenv("FINANCE_VECTOR_TOKEN", "").strip()
TZ_NAME = os.getenv("FINANCE_REFRESH_TZ", "UTC")
CRON_EXPR = os.getenv("FINANCE_REFRESH_CRON", "17 3 * * *").strip()
RUN_ON_START = os.getenv("FINANCE_RUN_ON_START", "auto").lower()

_run_lock = threading.Lock()
_state: dict = {
    "running": False,
    "last_started_at": None,
    "last_completed_at": None,
    "last_error": None,
    "last_summary": None,
    "next_run_at": None,
}


def _seed_blocking(recreate: bool = False) -> None:
    if not _run_lock.acquire(blocking=False):
        log.info("Seed already in progress; skipping concurrent request")
        return
    try:
        _state["running"] = True
        _state["last_started_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_error"] = None
        log.info("Starting seed run (recreate=%s)", recreate)
        summary = run_seed(CFG, recreate=recreate)
        _state["last_summary"] = summary
        _state["last_completed_at"] = summary["completed_at"]
        log.info("Seed run complete: %s", summary)
    except Exception as exc:  # noqa: BLE001
        log.exception("Seed run failed")
        _state["last_error"] = str(exc)
    finally:
        _state["running"] = False
        _run_lock.release()


async def _seed_async(recreate: bool = False) -> None:
    # Run the (blocking) HTTP-heavy seeder in a worker thread so the
    # event loop stays responsive for /health etc.
    await asyncio.to_thread(_seed_blocking, recreate)


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler(timezone=TZ_NAME)
    try:
        trigger = CronTrigger.from_crontab(CRON_EXPR, timezone=TZ_NAME)
    except Exception as exc:
        log.error("Invalid FINANCE_REFRESH_CRON %r: %s -- using daily 03:17", CRON_EXPR, exc)
        trigger = CronTrigger(hour=3, minute=17, timezone=TZ_NAME)
    scheduler.add_job(_seed_async, trigger, id="finance-refresh", coalesce=True,
                      max_instances=1, misfire_grace_time=3600)
    scheduler.start()
    job = scheduler.get_job("finance-refresh")
    if job and job.next_run_time:
        _state["next_run_at"] = job.next_run_time.isoformat()
    log.info("Scheduler started, next run at %s (cron=%r tz=%s)",
             _state["next_run_at"], CRON_EXPR, TZ_NAME)

    if RUN_ON_START == "always":
        log.info("FINANCE_RUN_ON_START=always -> kicking initial seed")
        asyncio.create_task(_seed_async(recreate=False))
    elif RUN_ON_START == "auto":
        count = collection_point_count(CFG)
        if count in (None, 0):
            log.info("Collection empty/missing -> kicking initial seed")
            asyncio.create_task(_seed_async(recreate=False))
        else:
            log.info("Collection already has %d points -> skipping initial seed", count)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Dream Server Finance Vector Seeder", version="0.1.0", lifespan=lifespan)


def _check_token(authorization: str | None) -> None:
    if not TOKEN:
        return  # token disabled
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    provided = authorization.split(" ", 1)[1].strip()
    if provided != TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "running": _state["running"]}


@app.get("/status")
def get_status() -> dict:
    return {
        **_state,
        "collection": CFG.collection,
        "qdrant_url": CFG.qdrant_url,
        "embeddings_url": CFG.embeddings_url,
        "current_points": collection_point_count(CFG),
        "schedule": {"cron": CRON_EXPR, "timezone": TZ_NAME},
    }


@app.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh(background: BackgroundTasks,
            recreate: bool = False,
            authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    if _state["running"]:
        return {"accepted": False, "reason": "already_running",
                "started_at": _state["last_started_at"]}
    background.add_task(_seed_blocking, recreate)
    return {"accepted": True, "recreate": recreate,
            "queued_at": datetime.now(timezone.utc).isoformat()}

