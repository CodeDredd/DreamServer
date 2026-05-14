"""FastAPI entrypoint for the finance-guru-api strategy engine.

Wires together:
  - data.py        — read-only TimescaleDB queries
  - ledger.py      — SQLite paper-trade ledger
  - llm.py         — LiteLLM client (uses 'fast' alias by default)
  - strategies/*   — auto-discovered strategy plugins
  - orchestrator   — the per-cycle decide+execute loop
  - backtest       — historical replay (no live ledger writes)

Endpoints
---------
GET  /health             liveness
GET  /strategies         registered plugins + last-cycle KPIs
GET  /ledger?strategy=…  cash/positions/trades/KPI for a strategy
POST /decide             trigger a live cycle (bearer-guarded)
                         body: {"strategy": "name"|null|"all"}
POST /backtest           replay history through a strategy (bearer-guarded)
                         body: {"strategy":..., "start":..., "end":..., "step_minutes":60}

Cron default: */30 * * * * — see AGENT-OPERATIONS.md §11.
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
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from . import backtest, data, ledger, orchestrator
from .config import CFG
from .strategies import REGISTRY, discover_strategies

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("finance-guru.api")


_lock = threading.Lock()
_state: dict = {
    "running": False,
    "last_started": None,
    "last_completed": None,
    "last_error": None,
    "next_run": None,
    "last_cycle": {},        # {strategy: <run_strategy_once result>}
}


def _enabled_strategies() -> list[str]:
    allow = CFG.enabled_strategies
    return [name for name in REGISTRY if (allow is None or name in allow)]


def _decide_blocking(only: str | None = None) -> dict:
    if not _lock.acquire(blocking=False):
        return {"accepted": False, "reason": "another cycle is already running"}
    try:
        _state["running"] = True
        _state["last_started"] = dt.datetime.now(dt.timezone.utc).isoformat()
        _state["last_error"] = None

        targets = _enabled_strategies() if not only else [only]
        targets = [t for t in targets if t in REGISTRY]
        if not targets:
            _state["running"] = False
            return {"accepted": False, "reason": f"no enabled strategies match {only!r}"}

        atype_map = orchestrator.asset_type_map()
        results: dict = {}
        for name in targets:
            try:
                results[name] = orchestrator.run_strategy_once(REGISTRY[name], atype_map)
            except Exception as exc:  # noqa: BLE001
                log.exception("strategy %s crashed", name)
                results[name] = {"strategy": name, "error": str(exc)}

        _state["last_cycle"] = results
        _state["last_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()
        return {"accepted": True, "ran": list(results.keys()),
                "results": results}
    except Exception as exc:  # noqa: BLE001
        log.exception("decide cycle failed")
        _state["last_error"] = str(exc)
        return {"accepted": False, "error": str(exc)}
    finally:
        _state["running"] = False
        _lock.release()


async def _decide_async(only: str | None = None) -> None:
    await asyncio.to_thread(_decide_blocking, only)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initialising ledger at %s", CFG.ledger_path)
    ledger.init_db()
    log.info("Discovering strategy plugins")
    discover_strategies()
    enabled = _enabled_strategies()
    log.info("Plugins discovered: registered=%d enabled=%d (%s)",
             len(REGISTRY), len(enabled), ",".join(enabled))
    for name in enabled:
        sd = REGISTRY[name]
        ledger.ensure_strategy(sd.name, sd.description)

    if not data.wait_until_ready():
        log.error("TimescaleDB never became reachable — running anyway")

    scheduler = AsyncIOScheduler(timezone=CFG.tz)
    try:
        trigger = CronTrigger.from_crontab(CFG.cron, timezone=CFG.tz)
    except Exception as exc:  # noqa: BLE001
        log.error("Invalid cron %r: %s — falling back to */30", CFG.cron, exc)
        trigger = CronTrigger(minute="*/30", timezone=CFG.tz)
    scheduler.add_job(_decide_async, trigger, id="decide_cycle",
                      coalesce=True, max_instances=1, misfire_grace_time=600)
    scheduler.start()
    job = scheduler.get_job("decide_cycle")
    if job and job.next_run_time:
        _state["next_run"] = job.next_run_time.isoformat()
    log.info("Scheduler started: cron=%r tz=%s", CFG.cron, CFG.tz)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Dream Server Finance Guru (Strategy Engine)",
              version="0.1.0", lifespan=lifespan)


def _check_token(authorization: str | None) -> None:
    if not CFG.api_token:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    if authorization.split(" ", 1)[1].strip() != CFG.api_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token")


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {
        "status":   "ok",
        "running":  _state["running"],
        "registered_strategies": list(REGISTRY.keys()),
        "enabled_strategies":    _enabled_strategies(),
    }


@app.get("/strategies")
def list_strategies_endpoint() -> dict:
    out: list[dict] = []
    enabled = set(_enabled_strategies())
    for name, sd in REGISTRY.items():
        last = _state.get("last_cycle", {}).get(name) or {}
        out.append({
            "name":             name,
            "description":      sd.description,
            "asset_types":      list(sd.asset_types),
            "max_position_frac": sd.max_position_frac if sd.max_position_frac is not None else CFG.max_position_frac,
            "enabled":          name in enabled,
            "last_kpi":         last.get("kpi"),
            "last_signals":     last.get("signals"),
            "last_executed":    len(last.get("executed", []) or []),
            "last_skipped":     len(last.get("skipped", []) or []),
            "last_ts":          last.get("ts"),
        })
    return {
        "schedule":    {"cron": CFG.cron, "tz": CFG.tz},
        "next_run":    _state["next_run"],
        "strategies":  out,
        "history_extent": data.history_extent(),
    }


@app.get("/ledger")
def get_ledger(strategy: str = Query(..., min_length=1)) -> dict:
    if strategy not in REGISTRY:
        # Allow inspection of strategies that have a row in the SQLite
        # but have since been removed from the codebase.
        rows = ledger.list_strategies()
        if strategy not in {r["name"] for r in rows}:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown strategy {strategy!r}")
    mark = data.latest_prices()
    return {
        "strategy":  strategy,
        "kpi":       ledger.kpi(strategy, mark),
        "cash_eur":  ledger.get_cash(strategy),
        "positions": ledger.get_positions(strategy),
        "trades":    ledger.get_trades(strategy, limit=100),
    }


class DecideReq(BaseModel):
    strategy: str | None = Field(None, description="Strategy name, or null/'all' for every enabled strategy")


@app.post("/decide", status_code=status.HTTP_202_ACCEPTED)
def decide(req: DecideReq, background: BackgroundTasks,
           authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    target = (req.strategy or "").strip().lower() or None
    if target == "all":
        target = None
    if target and target not in REGISTRY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"unknown strategy {target!r}; have {list(REGISTRY.keys())}")
    background.add_task(_decide_blocking, target)
    return {"accepted": True, "queued_for": target or "all-enabled",
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}


class BacktestReq(BaseModel):
    strategy: str
    start: dt.datetime | None = None
    end:   dt.datetime | None = None
    step_minutes: int = Field(60, ge=5, le=24 * 60)
    universe_limit: int = Field(30, ge=1, le=200)


@app.post("/backtest")
def backtest_endpoint(req: BacktestReq,
                      authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    if req.strategy not in REGISTRY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"unknown strategy {req.strategy!r}")
    extent = data.history_extent()
    end   = req.end or dt.datetime.now(dt.timezone.utc)
    start = req.start or (end - dt.timedelta(days=7))
    # If user gave naive datetimes, coerce to UTC.
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt.timezone.utc)
    if end.tzinfo is None:
        end   = end.replace(tzinfo=dt.timezone.utc)
    return backtest.run_backtest(
        REGISTRY[req.strategy],
        start=start, end=end,
        step=dt.timedelta(minutes=req.step_minutes),
        universe_limit=req.universe_limit,
    ) | {"history_extent": extent}

