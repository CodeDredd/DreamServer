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

from . import backtest, cycle_log, data, enrichment, ledger, orchestrator
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


def _decide_blocking(only: str | None = None, trigger: str = "scheduler") -> dict:
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
                results[name] = orchestrator.run_strategy_once(
                    REGISTRY[name], atype_map, trigger=trigger,
                )
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
    cycle_log.init_db()
    enrichment.init_db()
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
    background.add_task(_decide_blocking, target, "manual")
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


# --------------------------------------------------------------------------- #
# Cycle log / equity history — drives the "Updates" log + chart in the UI
# --------------------------------------------------------------------------- #
@app.get("/cycles")
def list_cycles(
    strategy: str | None = Query(default=None, description="Filter by strategy"),
    status_filter: str | None = Query(default=None, alias="status",
                                      description="Filter by 'ok'|'empty'|'error'"),
    limit: int = Query(default=50, ge=1, le=500),
) -> dict:
    rows = cycle_log.list_cycles(strategy=strategy, limit=limit,
                                 status_filter=status_filter)
    return {
        "summary":  cycle_log.summary(strategy),
        "next_run": _state["next_run"],
        "cycles":   rows,
    }


@app.get("/equity-history")
def equity_history(
    strategy: str = Query(..., min_length=1),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=500, ge=10, le=5000),
) -> dict:
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    points = cycle_log.equity_history(strategy=strategy, since=since, limit=limit)
    return {"strategy": strategy, "since": since.isoformat(), "points": points}


# --------------------------------------------------------------------------- #
# Enrichment ingest (called by n8n workflows — bearer-guarded)
# --------------------------------------------------------------------------- #
class AssetAnalysisIn(BaseModel):
    symbol: str
    asset_type: Literal["stock", "crypto"] = "stock"
    period_start: dt.datetime
    period_end:   dt.datetime
    summary: str
    keywords: list[str] = Field(default_factory=list)
    drivers:  list[dict] = Field(default_factory=list)
    news_ids: list = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    contradictions: str | None = None
    model: str = "default"
    prompt: dict | None = None
    raw_response: str | None = None


class SourceReliabilityIn(BaseModel):
    source: str
    reliability: float = Field(..., ge=0.0, le=1.0)
    weight: float = Field(1.0, ge=0.0, le=2.0)
    sample_size: int = Field(0, ge=0)
    methodology: str = ""
    model: str = "default"
    raw_response: str | None = None


class RunReportIn(BaseModel):
    workflow: Literal["asset_behaviour", "source_reliability"]
    target: str | None = None
    status: Literal["ok", "error", "skipped"] = "ok"
    duration_ms: int = Field(0, ge=0)
    note: str | None = None


class NextCandidateReq(BaseModel):
    asset_type: Literal["stock", "crypto"] | None = None
    stale_after_hours: int = Field(168, ge=1, le=24 * 90)
    universe: list[str] = Field(default_factory=list)


@app.post("/enrichment/asset-analysis", status_code=status.HTTP_201_CREATED)
def store_asset_analysis(payload: AssetAnalysisIn,
                          authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    if payload.period_end < payload.period_start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "period_end < period_start")
    rid = enrichment.upsert_asset_analysis(
        symbol=payload.symbol.upper().strip(),
        asset_type=payload.asset_type,
        period_start=payload.period_start,
        period_end=payload.period_end,
        summary=payload.summary,
        keywords=payload.keywords,
        drivers=payload.drivers,
        news_ids=payload.news_ids,
        confidence=payload.confidence,
        contradictions=payload.contradictions,
        model=payload.model,
        prompt=payload.prompt,
        raw_response=payload.raw_response,
    )
    return {"id": rid, "symbol": payload.symbol.upper().strip()}


@app.get("/enrichment/asset-analysis")
def get_asset_analysis(symbol: str = Query(..., min_length=1),
                        limit: int = Query(10, ge=1, le=100)) -> dict:
    rows = enrichment.latest_asset_analysis(symbol.upper().strip(), limit=limit)
    return {"symbol": symbol.upper().strip(), "analyses": rows}


@app.get("/enrichment/asset-analysis/coverage")
def asset_analysis_coverage(limit: int = Query(200, ge=1, le=1000)) -> dict:
    return {"symbols": enrichment.list_analysed_symbols(limit=limit)}


@app.post("/enrichment/next-candidate")
def next_candidate(req: NextCandidateReq,
                   authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    sym = enrichment.next_candidate(
        asset_type=req.asset_type,
        stale_after_hours=req.stale_after_hours,
        universe=req.universe,
    )
    return {"next": sym}


@app.post("/enrichment/source-reliability", status_code=status.HTTP_201_CREATED)
def store_source_reliability(payload: SourceReliabilityIn,
                              authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    res = enrichment.upsert_source_reliability(
        source=payload.source,
        reliability=payload.reliability,
        weight=payload.weight,
        sample_size=payload.sample_size,
        methodology=payload.methodology,
        model=payload.model,
        raw_response=payload.raw_response,
    )
    return res


@app.get("/enrichment/source-reliability")
def list_source_reliability(limit: int = Query(200, ge=1, le=1000)) -> dict:
    return {"sources": enrichment.list_source_reliability(limit=limit)}


@app.post("/enrichment/run", status_code=status.HTTP_201_CREATED)
def report_run(payload: RunReportIn,
                authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    rid = enrichment.record_run(
        workflow=payload.workflow,
        target=payload.target,
        status=payload.status,
        duration_ms=payload.duration_ms,
        note=payload.note,
    )
    return {"id": rid}


@app.get("/enrichment/runs")
def list_runs(workflow: str | None = Query(default=None),
              limit: int = Query(100, ge=1, le=500)) -> dict:
    return {"runs": enrichment.list_runs(workflow=workflow, limit=limit)}


# --------------------------------------------------------------------------- #
# History query endpoints — consumed by n8n enrichment workflows so they
# don't need direct Postgres access. Read-only, no auth (dream-network only).
# --------------------------------------------------------------------------- #
@app.get("/history/symbols")
def history_symbols(asset_type: str | None = Query(default=None),
                    hours: int = Query(default=24, ge=1, le=24 * 90)) -> dict:
    """Symbols that have recent ticks — used by workflows to pick the
    universe of analysable assets."""
    syms = data.list_symbols(asset_type=asset_type, since=dt.timedelta(hours=hours))
    return {"asset_type": asset_type, "since_hours": hours, "symbols": syms}


@app.get("/history/prices")
def history_prices(symbol: str = Query(..., min_length=1),
                   days: int = Query(default=180, ge=1, le=365 * 2),
                   sample: int = Query(default=400, ge=10, le=5000)) -> dict:
    """OHLCV for one symbol over `days`. Down-samples evenly to `sample`
    rows so the LLM prompt doesn't blow up on long windows.

    Per the user's spec the asset-behaviour workflow starts with 6
    months (days=180) and is later increased.
    """
    df = data.price_history([symbol.upper().strip()],
                             lookback=dt.timedelta(days=days))
    if df.empty:
        return {"symbol": symbol, "days": days, "rows": []}
    df = df.sort_values("ts")
    if len(df) > sample:
        step = max(1, len(df) // sample)
        df = df.iloc[::step].copy()
    # Compact JSON output (n8n-friendly).
    out = [{
        "ts":     ts.isoformat(),
        "open":   float(row["open"])   if row["open"]   is not None else None,
        "high":   float(row["high"])   if row["high"]   is not None else None,
        "low":    float(row["low"])    if row["low"]    is not None else None,
        "close":  float(row["close"])  if row["close"]  is not None else None,
        "volume": float(row["volume"]) if row["volume"] is not None else None,
    } for ts, row in zip(df["ts"], df.to_dict("records"))]
    # Derive headline stats so the LLM step can quote them deterministically.
    closes = [r["close"] for r in out if r["close"] is not None]
    stats: dict[str, float | None] = {
        "first":      closes[0]  if closes else None,
        "last":       closes[-1] if closes else None,
        "min":        min(closes) if closes else None,
        "max":        max(closes) if closes else None,
        "return_pct": ((closes[-1] - closes[0]) / closes[0] * 100.0)
                       if closes and closes[0] else None,
    }
    # Top-5 single-day moves — these are the candidates the LLM gets
    # asked to *explain*, NOT speculate about.
    moves: list[dict] = []
    for i in range(1, len(out)):
        prev, cur = out[i - 1], out[i]
        if prev["close"] and cur["close"]:
            pct = (cur["close"] - prev["close"]) / prev["close"] * 100.0
            moves.append({"date": cur["ts"], "move_pct": round(pct, 2),
                          "close": cur["close"], "prev_close": prev["close"]})
    biggest = sorted(moves, key=lambda m: abs(m["move_pct"]), reverse=True)[:8]
    return {
        "symbol":   symbol.upper().strip(),
        "days":     days,
        "rows":     out,
        "stats":    stats,
        "biggest":  biggest,
    }


@app.get("/history/news")
def history_news(symbol: str | None = Query(default=None),
                  days: int = Query(default=180, ge=1, le=365 * 2),
                  limit: int = Query(default=200, ge=1, le=1000),
                  min_sentiment_abs: float | None = Query(default=None,
                                                          ge=0.0, le=1.0)) -> dict:
    """Headlines for the asset-behaviour workflow. Symbol filter is
    optional — sometimes the workflow wants macro context too."""
    syms = [symbol.upper().strip()] if symbol else None
    df = data.recent_news(lookback=dt.timedelta(days=days), symbols=syms,
                           min_sentiment_abs=min_sentiment_abs)
    if df.empty:
        return {"symbol": symbol, "days": days, "rows": []}
    df = df.sort_values("ts", ascending=False).head(limit)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            "id":        r["id"],
            "ts":        r["ts"].isoformat() if r["ts"] is not None else None,
            "source":    r["source"],
            "channel":   r["channel"],
            "symbols":   list(r["symbols"]) if r["symbols"] is not None else [],
            "sentiment": float(r["sentiment"]) if r["sentiment"] is not None else None,
            "urgency":   int(r["urgency"]) if r["urgency"] is not None else None,
            "title":     r["title"],
            "url":       r["url"],
        })
    # Per-source aggregates (drives the reliability workflow's denominator).
    by_source: dict[str, dict] = {}
    for r in rows:
        s = (r.get("source") or "unknown").strip().lower()
        bs = by_source.setdefault(s, {"source": s, "n": 0, "sum_sent": 0.0, "n_sent": 0})
        bs["n"] += 1
        if r.get("sentiment") is not None:
            bs["sum_sent"] += r["sentiment"]
            bs["n_sent"]   += 1
    for bs in by_source.values():
        bs["avg_sentiment"] = (bs["sum_sent"] / bs["n_sent"]) if bs["n_sent"] else None
        bs.pop("sum_sent", None)
    return {
        "symbol":      symbol,
        "days":        days,
        "rows":        rows,
        "by_source":   list(by_source.values()),
    }


