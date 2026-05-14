"""FastAPI wrapper around the finance-prices intraday fetcher.

Endpoints
---------
GET  /health      liveness
GET  /status      last/next runs per job, row count, latest timestamp
POST /refresh     trigger an ad-hoc fetch
                  (?kind=stocks|crypto|all, bearer-token guarded)

Scheduling
----------
Two APScheduler cron jobs:
  * stocks  default "*/15 * * * 1-5"   (every 15 min, Mon–Fri)
  * crypto  default "*/5  * * * *"     (every  5 min, every day)

If FINANCE_PRICES_RESPECT_MARKET_HOURS=true (default), the stocks job
skips ticks outside US regular hours (14:30 → 21:00 UTC). yfinance
returns nothing useful then anyway and we save the calls.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Literal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, status

from .db import DbConfig, ensure_schema, latest_ts, row_count, upsert_bars
from .fetcher import (
    FetcherConfig,
    fetch_crypto_bars,
    fetch_stock_bars,
    universe_crypto,
    universe_stocks,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("finance-prices.api")

DB_CFG = DbConfig()
FETCH_CFG = FetcherConfig()
TOKEN = os.getenv("FINANCE_PRICES_TOKEN", "").strip()
TZ_NAME = os.getenv("FINANCE_PRICES_TZ", "UTC")
STOCKS_CRON = os.getenv("FINANCE_PRICES_STOCKS_CRON", "*/15 * * * 1-5").strip()
CRYPTO_CRON = os.getenv("FINANCE_PRICES_CRYPTO_CRON", "*/5 * * * *").strip()
RUN_ON_START = os.getenv("FINANCE_PRICES_RUN_ON_START", "auto").lower()
RESPECT_MARKET_HOURS = os.getenv("FINANCE_PRICES_RESPECT_MARKET_HOURS", "true").lower() == "true"

Kind = Literal["stocks", "crypto", "all"]

_locks: dict[str, threading.Lock] = {"stocks": threading.Lock(), "crypto": threading.Lock()}
_state: dict = {
    "stocks": {"running": False, "last_started": None, "last_completed": None,
               "last_error": None, "last_rows": 0, "next_run": None},
    "crypto": {"running": False, "last_started": None, "last_completed": None,
               "last_error": None, "last_rows": 0, "next_run": None},
}


def _us_market_open(now: dt.datetime | None = None) -> bool:
    """Cheap regular-hours check (14:30–21:00 UTC, Mon–Fri).
    Doesn't account for half-days / holidays — yfinance handles that
    by returning empty data, which we already tolerate."""
    n = now or dt.datetime.now(dt.timezone.utc)
    if n.weekday() >= 5:
        return False
    minute_of_day = n.hour * 60 + n.minute
    return 14 * 60 + 30 <= minute_of_day <= 21 * 60


def _run_stocks_blocking() -> None:
    if not _locks["stocks"].acquire(blocking=False):
        log.info("stocks fetch already running, skipping")
        return
    s = _state["stocks"]
    try:
        s["running"] = True
        s["last_started"] = dt.datetime.now(dt.timezone.utc).isoformat()
        s["last_error"] = None
        if RESPECT_MARKET_HOURS and not _us_market_open():
            log.info("market closed -> skipping stocks fetch")
            s["last_rows"] = 0
            s["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
            return
        universe = universe_stocks(FETCH_CFG)
        bars = fetch_stock_bars(FETCH_CFG, universe)
        n = upsert_bars(DB_CFG, bars)
        s["last_rows"] = n
        s["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
        log.info("stocks fetch done: %d bars upserted (%d symbols)", n, len(universe))
    except Exception as exc:  # noqa: BLE001
        log.exception("stocks fetch failed")
        s["last_error"] = str(exc)
    finally:
        s["running"] = False
        _locks["stocks"].release()


def _run_crypto_blocking() -> None:
    if not _locks["crypto"].acquire(blocking=False):
        log.info("crypto fetch already running, skipping")
        return
    s = _state["crypto"]
    try:
        s["running"] = True
        s["last_started"] = dt.datetime.now(dt.timezone.utc).isoformat()
        s["last_error"] = None
        universe = universe_crypto(FETCH_CFG)
        bars = fetch_crypto_bars(FETCH_CFG, universe)
        n = upsert_bars(DB_CFG, bars)
        s["last_rows"] = n
        s["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
        log.info("crypto fetch done: %d bars upserted (%d symbols)", n, len(universe))
    except Exception as exc:  # noqa: BLE001
        log.exception("crypto fetch failed")
        s["last_error"] = str(exc)
    finally:
        s["running"] = False
        _locks["crypto"].release()


async def _stocks_async() -> None:
    await asyncio.to_thread(_run_stocks_blocking)


async def _crypto_async() -> None:
    await asyncio.to_thread(_run_crypto_blocking)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Wait for the DB then ensure schema. ensure_schema is a noop on a
    # freshly-init'd DB (the init SQL ran already) but is required for
    # rolling updates.
    for attempt in range(20):
        try:
            ensure_schema(DB_CFG)
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("DB not ready yet (%s) — retry %d/20", exc, attempt + 1)
            await asyncio.sleep(3)
    else:
        log.error("Could not ensure schema after 20 attempts; continuing anyway")

    scheduler = AsyncIOScheduler(timezone=TZ_NAME)
    for job_id, expr, fn in (
        ("stocks", STOCKS_CRON, _stocks_async),
        ("crypto", CRYPTO_CRON, _crypto_async),
    ):
        try:
            trigger = CronTrigger.from_crontab(expr, timezone=TZ_NAME)
        except Exception as exc:  # noqa: BLE001
            log.error("Invalid cron %r for %s: %s — falling back to */15", expr, job_id, exc)
            trigger = CronTrigger(minute="*/15", timezone=TZ_NAME)
        scheduler.add_job(fn, trigger, id=job_id, coalesce=True,
                          max_instances=1, misfire_grace_time=300)

    scheduler.start()
    for jid in ("stocks", "crypto"):
        job = scheduler.get_job(jid)
        if job and job.next_run_time:
            _state[jid]["next_run"] = job.next_run_time.isoformat()

    log.info("Scheduler started: stocks=%r crypto=%r tz=%s",
             STOCKS_CRON, CRYPTO_CRON, TZ_NAME)

    if RUN_ON_START in ("always", "auto"):
        rc = 0
        if RUN_ON_START == "auto":
            try:
                rc = row_count(DB_CFG)
            except Exception:
                rc = 0
        if RUN_ON_START == "always" or rc == 0:
            log.info("Kicking initial stocks + crypto fetch (RUN_ON_START=%s, rows=%d)",
                     RUN_ON_START, rc)
            asyncio.create_task(_stocks_async())
            asyncio.create_task(_crypto_async())

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Dream Server Finance Intraday Prices",
              version="0.1.0", lifespan=lifespan)


def _check_token(authorization: str | None) -> None:
    if not TOKEN:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    provided = authorization.split(" ", 1)[1].strip()
    if provided != TOKEN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok",
            "stocks_running": _state["stocks"]["running"],
            "crypto_running": _state["crypto"]["running"]}


@app.get("/status")
def get_status() -> dict:
    try:
        rows = row_count(DB_CFG)
    except Exception as exc:  # noqa: BLE001
        rows = -1
        log.warning("row_count failed: %s", exc)
    try:
        latest = latest_ts(DB_CFG)
    except Exception:
        latest = None
    return {
        "db": {"host": DB_CFG.host, "db": DB_CFG.dbname,
               "row_count_estimate": rows, "latest_ts": latest},
        "schedule": {"stocks_cron": STOCKS_CRON, "crypto_cron": CRYPTO_CRON,
                     "timezone": TZ_NAME, "respect_market_hours": RESPECT_MARKET_HOURS},
        "jobs": _state,
    }


@app.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def refresh(background: BackgroundTasks,
            kind: Kind = "all",
            authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    queued: list[str] = []
    if kind in ("stocks", "all"):
        background.add_task(_run_stocks_blocking)
        queued.append("stocks")
    if kind in ("crypto", "all"):
        background.add_task(_run_crypto_blocking)
        queued.append("crypto")
    return {"accepted": True, "queued": queued,
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}

