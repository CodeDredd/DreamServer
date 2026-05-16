"""Finance Guru router — proxies the finance-guru-api strategy engine.

Acts as a thin pass-through so the React dashboard never has to hold the
FINANCE_GURU_TOKEN in the browser. The token lives only in `.env` (read
by config.py as FINANCE_GURU_TOKEN) and is injected server-side here for
the bearer-guarded endpoints (POST /decide, POST /backtest).

Read endpoints (/health, /strategies, /ledger) are unauthenticated on
finance-guru-api itself (only reachable on the dream-network), so the
proxy doesn't need to pass any token for those.

See AGENT-OPERATIONS.md §11 for the full pipeline architecture.
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from config import FINANCE_GURU_TOKEN, FINANCE_GURU_URL
from security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["finance-guru"])

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


def _bearer_headers() -> dict:
    if not FINANCE_GURU_TOKEN:
        raise HTTPException(
            status_code=503,
            detail=(
                "FINANCE_GURU_TOKEN is not set. Generate one with "
                "`openssl rand -hex 32` and add it to .env as "
                "FINANCE_GURU_TOKEN=… (the same token must already be "
                "set on the finance-guru-api container)."
            ),
        )
    return {"Authorization": f"Bearer {FINANCE_GURU_TOKEN}"}


async def _guru_request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict | None = None,
    bearer: bool = False,
) -> Any:
    url = f"{FINANCE_GURU_URL.rstrip('/')}{path}"
    headers = _bearer_headers() if bearer else {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.request(method, url, headers=headers, json=json, params=params)
        except httpx.ConnectError as exc:
            raise HTTPException(
                status_code=503,
                detail=f"finance-guru-api unreachable at {url}",
            ) from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail="finance-guru-api request timed out",
            ) from exc

    if resp.status_code >= 400:
        # Surface upstream message verbatim so the dashboard can show it
        detail = resp.text or f"upstream returned HTTP {resp.status_code}"
        raise HTTPException(status_code=resp.status_code, detail=detail)
    if not resp.content:
        return {}
    return resp.json()


# --- Health probe ----------------------------------------------------------

@router.get("/api/finance-guru/status")
async def finance_guru_status(api_key: str = Depends(verify_api_key)):
    """Lightweight probe used by the Finance Guru page banner."""
    url = f"{FINANCE_GURU_URL.rstrip('/')}/health"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url)
        except httpx.ConnectError:
            return {
                "available": False,
                "configured": bool(FINANCE_GURU_TOKEN),
                "url": FINANCE_GURU_URL,
                "message": "finance-guru-api unreachable",
            }
        except httpx.TimeoutException:
            return {
                "available": False,
                "configured": bool(FINANCE_GURU_TOKEN),
                "url": FINANCE_GURU_URL,
                "message": "finance-guru-api timed out",
            }

    healthy = resp.status_code == 200
    body = resp.json() if healthy else {}
    return {
        "available": healthy,
        "configured": bool(FINANCE_GURU_TOKEN),
        "url": FINANCE_GURU_URL,
        "registered_strategies": body.get("registered_strategies", []),
        "enabled_strategies": body.get("enabled_strategies", []),
        "message": "ready" if healthy else f"HTTP {resp.status_code}",
    }


# --- Read endpoints --------------------------------------------------------

@router.get("/api/finance-guru/strategies")
async def list_strategies(api_key: str = Depends(verify_api_key)):
    """Discovered plugins, schedule, history extent, and last-cycle stats."""
    return await _guru_request("GET", "/strategies")


@router.get("/api/finance-guru/ledger")
async def get_ledger(
    strategy: str = Query(..., description="Strategy plugin name"),
    api_key: str = Depends(verify_api_key),
):
    """Per-strategy paper-trade ledger: cash, positions, trades, KPI."""
    return await _guru_request("GET", "/ledger", params={"strategy": strategy})


# --- Write endpoints (bearer-guarded upstream) ----------------------------

@router.post("/api/finance-guru/decide")
async def trigger_decide(
    body: dict = Body(default_factory=dict),
    api_key: str = Depends(verify_api_key),
):
    """Run one decision cycle (all strategies if `strategy` omitted)."""
    return await _guru_request("POST", "/decide", json=body, bearer=True)


@router.post("/api/finance-guru/backtest")
async def trigger_backtest(
    body: dict = Body(...),
    api_key: str = Depends(verify_api_key),
):
    """Replay history for one strategy. Body: {"strategy": str, "days": int}."""
    return await _guru_request("POST", "/backtest", json=body, bearer=True)


# --- Cycle log / equity history -------------------------------------------

@router.get("/api/finance-guru/cycles")
async def list_cycles(
    strategy: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    api_key: str = Depends(verify_api_key),
):
    """Persistent log of every decide-cycle the scheduler ran."""
    params: dict = {"limit": limit}
    if strategy:
        params["strategy"] = strategy
    if status:
        params["status"] = status
    return await _guru_request("GET", "/cycles", params=params)


@router.get("/api/finance-guru/equity-history")
async def equity_history(
    strategy: str = Query(..., min_length=1),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=500, ge=10, le=5000),
    api_key: str = Depends(verify_api_key),
):
    """Time-series of (ts, equity_eur, pnl_pct) for the equity chart."""
    return await _guru_request(
        "GET", "/equity-history",
        params={"strategy": strategy, "days": days, "limit": limit},
    )


# --- Enrichment (read-only proxy — n8n posts directly upstream) ----------

@router.get("/api/finance-guru/enrichment/asset-analysis")
async def enrichment_asset_analysis(
    symbol: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    api_key: str = Depends(verify_api_key),
):
    return await _guru_request(
        "GET", "/enrichment/asset-analysis",
        params={"symbol": symbol, "limit": limit},
    )


@router.get("/api/finance-guru/enrichment/asset-analysis/coverage")
async def enrichment_coverage(
    limit: int = Query(default=200, ge=1, le=1000),
    api_key: str = Depends(verify_api_key),
):
    return await _guru_request(
        "GET", "/enrichment/asset-analysis/coverage", params={"limit": limit},
    )


@router.get("/api/finance-guru/enrichment/source-reliability")
async def enrichment_source_reliability(
    limit: int = Query(default=200, ge=1, le=1000),
    api_key: str = Depends(verify_api_key),
):
    return await _guru_request(
        "GET", "/enrichment/source-reliability", params={"limit": limit},
    )


@router.get("/api/finance-guru/enrichment/runs")
async def enrichment_runs(
    workflow: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    api_key: str = Depends(verify_api_key),
):
    params: dict = {"limit": limit}
    if workflow:
        params["workflow"] = workflow
    return await _guru_request("GET", "/enrichment/runs", params=params)


@router.post("/api/finance-guru/enrichment/asset-analysis/search")
async def search_analyses(
    body: dict = Body(...),
    api_key: str = Depends(verify_api_key),
):
    """Semantic search over the finance_asset_analysis Qdrant collection."""
    return await _guru_request("POST", "/enrichment/asset-analysis/search", json=body)


