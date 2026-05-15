"""Lotto Oracle router — proxies the lotto-oracle tip engine.

Mirrors the finance_guru.py pattern:
  * GET endpoints (`/health`, `/games`, `/draws`, `/stats`, `/tips`)
    are unauthenticated upstream (only reachable on the dream-network).
  * POST endpoints (`/refresh`, `/refresh/full`, `/tips/generate`,
    `/admin/import`) require the LOTTO_ORACLE_TOKEN bearer token,
    which is injected server-side here so the browser never sees it.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from config import LOTTO_ORACLE_TOKEN, LOTTO_ORACLE_URL
from security import verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(tags=["lotto"])

_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def _bearer_headers() -> dict:
    if not LOTTO_ORACLE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail=(
                "LOTTO_ORACLE_TOKEN is not set. Generate one with "
                "`openssl rand -hex 32` and add it to .env as "
                "LOTTO_ORACLE_TOKEN=… (the same token must be set on "
                "the lotto-oracle container)."
            ),
        )
    return {"Authorization": f"Bearer {LOTTO_ORACLE_TOKEN}"}


async def _lotto_request(
    method: str,
    path: str,
    *,
    json: Any = None,
    params: dict | None = None,
    bearer: bool = False,
) -> Any:
    url = f"{LOTTO_ORACLE_URL.rstrip('/')}{path}"
    headers = _bearer_headers() if bearer else {}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.request(method, url, headers=headers, json=json, params=params)
        except httpx.ConnectError as exc:
            raise HTTPException(status_code=503, detail=f"lotto-oracle unreachable at {url}") from exc
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="lotto-oracle request timed out") from exc

    if resp.status_code >= 400:
        detail = resp.text or f"upstream returned HTTP {resp.status_code}"
        raise HTTPException(status_code=resp.status_code, detail=detail)
    if not resp.content:
        return {}
    return resp.json()


# --- Health probe ----------------------------------------------------------

@router.get("/api/lotto/status")
async def lotto_status(api_key: str = Depends(verify_api_key)):
    url = f"{LOTTO_ORACLE_URL.rstrip('/')}/health"
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            resp = await client.get(url)
        except httpx.ConnectError:
            return {
                "available": False,
                "configured": bool(LOTTO_ORACLE_TOKEN),
                "url": LOTTO_ORACLE_URL,
                "message": "lotto-oracle unreachable",
            }
        except httpx.TimeoutException:
            return {
                "available": False,
                "configured": bool(LOTTO_ORACLE_TOKEN),
                "url": LOTTO_ORACLE_URL,
                "message": "lotto-oracle timed out",
            }

    healthy = resp.status_code == 200
    body = resp.json() if healthy else {}
    return {
        "available": healthy,
        "configured": bool(LOTTO_ORACLE_TOKEN),
        "url": LOTTO_ORACLE_URL,
        "games": body.get("games", []),
        "schedule": body.get("schedule"),
        "submission_api": body.get("submission_api"),
        "message": "ready" if healthy else f"HTTP {resp.status_code}",
    }


# --- Read endpoints --------------------------------------------------------

@router.get("/api/lotto/games")
async def lotto_games(api_key: str = Depends(verify_api_key)):
    return await _lotto_request("GET", "/games")


@router.get("/api/lotto/games/{game_id}/strategies")
async def lotto_strategies(
    game_id: str,
    recency_k: int = Query(1, ge=1, le=5),
    api_key: str = Depends(verify_api_key),
):
    return await _lotto_request("GET", f"/games/{game_id}/strategies",
                                params={"recency_k": recency_k})


@router.get("/api/lotto/games/{game_id}/sweet-spot")
async def lotto_sweet_spot(game_id: str, api_key: str = Depends(verify_api_key)):
    return await _lotto_request("GET", f"/games/{game_id}/sweet-spot")


@router.get("/api/lotto/draws")
async def lotto_draws(
    game: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    api_key: str = Depends(verify_api_key),
):
    return await _lotto_request("GET", "/draws",
                                params={"game": game, "limit": limit, "offset": offset})


@router.get("/api/lotto/stats")
async def lotto_stats(game: str = Query(..., min_length=1),
                      api_key: str = Depends(verify_api_key)):
    return await _lotto_request("GET", "/stats", params={"game": game})


@router.get("/api/lotto/tips")
async def lotto_tips(game: str = Query(..., min_length=1),
                     api_key: str = Depends(verify_api_key)):
    return await _lotto_request("GET", "/tips", params={"game": game})


# --- Write endpoints (bearer-guarded upstream) ----------------------------

@router.post("/api/lotto/refresh")
async def lotto_refresh(
    body: dict = Body(default_factory=dict),
    full: bool = Query(False),
    api_key: str = Depends(verify_api_key),
):
    return await _lotto_request("POST", "/refresh", params={"full": str(full).lower()}, bearer=True)


@router.post("/api/lotto/refresh/full")
async def lotto_refresh_full(api_key: str = Depends(verify_api_key)):
    return await _lotto_request("POST", "/refresh/full", bearer=True)


@router.post("/api/lotto/tips/generate")
async def lotto_generate(
    body: dict = Body(default_factory=dict),
    api_key: str = Depends(verify_api_key),
):
    return await _lotto_request("POST", "/tips/generate", json=body, bearer=True)


@router.post("/api/lotto/admin/import")
async def lotto_admin_import(body: dict = Body(...),
                             api_key: str = Depends(verify_api_key)):
    return await _lotto_request("POST", "/admin/import", json=body, bearer=True)

