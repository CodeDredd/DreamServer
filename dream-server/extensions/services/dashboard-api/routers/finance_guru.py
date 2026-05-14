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

