"""Lotto Oracle FastAPI service.

Endpoints
---------
GET  /health
GET  /games
GET  /games/{game_id}/strategies     — strategy descriptors for the UI
GET  /draws?game=…&limit=&offset=
GET  /stats?game=…                   — frequency / gap analytics
GET  /tips?game=…                    — most recent generated tip-run
POST /refresh                        — incremental fetch (bearer)
POST /refresh/full                   — backfill full archive (bearer)
POST /tips/generate                  — run all strategies once (bearer)
POST /admin/import                   — import operator-provided CSV (bearer)
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from collections import Counter
from contextlib import asynccontextmanager
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import (
    BackgroundTasks, Body, FastAPI, Header, HTTPException, Query, status,
)
from pydantic import BaseModel, Field

from . import fetchers, store
from .analytics import (
    jackpot_backtest_all, recency_overlap_distribution, recency_sweet_spot,
    score_all_strategies,
)
from .config import CFG
from .games import GAMES, get_game
from .optimal import (
    DEFAULT_FIELDS, FieldSpec, build_custom_schein, build_optimal_schein,
)
from .strategies import (
    RECENCY_K_DEFAULT, RECENCY_K_MAX, RECENCY_K_MIN,
    generate_tips, list_strategies, make_recency_strategy, strategies_for,
)

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("lotto-oracle.api")


_state: dict = {
    "last_fetch_started":   None,
    "last_fetch_completed": None,
    "last_fetch_summary":   None,
    "last_generate":        None,
    "next_run":             None,
    "running":              False,
}


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def _bootstrap_seed_if_empty() -> None:
    """If the SQLite DB is brand-new (no draws), import bundled CSVs.

    Iterates every offline-capable parser (``CsvSeedParser`` +
    ``OfficialArchiveParser``) so an operator can drop a multi-year
    ``LOTTO_*.csv`` / ``EJ_*.csv`` archive into ``seed_data/`` and have
    it picked up on the first start without needing a manual
    ``POST /admin/import``.
    """
    for gid in GAMES:
        if store.draw_count(gid) > 0:
            continue
        log.info("[%s] db empty — attempting offline seed import", gid)
        for parser in fetchers.PARSERS.get(gid, []):
            if not getattr(parser, "offline", False):
                continue
            try:
                draws = parser.fetch_archive()
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] %s parser failed: %s", gid, parser.name, exc)
                continue
            if not draws:
                continue
            n = store.bulk_upsert(gid, draws)
            log.info("[%s] %s imported %d draw(s)", gid, parser.name, n)


def _bootstrap_tips_if_missing() -> None:
    """Generate an initial tip set for every game at startup so the
    dashboard always has something to render — even on cold boot before
    the first cron tick. Spiel 77 / Super 6 in particular usually have
    no live source, so without this they would stay empty until the
    operator manually triggers /tips/generate."""
    for gid in GAMES:
        latest = store.latest_tip_run(gid) if hasattr(store, "latest_tip_run") else None
        if latest:
            continue
        try:
            info = _do_generate(gid)
            log.info("[%s] bootstrap tips: n=%d (run_id=%s)",
                     gid, info.get("n_tips", 0), info.get("run_id"))
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s] bootstrap tip generation failed: %s", gid, exc)



def _do_fetch(full_archive: bool = False) -> dict:
    if _state["running"]:
        return {"accepted": False, "reason": "another run in progress"}
    _state["running"] = True
    _state["last_fetch_started"] = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        summary = fetchers.fetch_into(store, full_archive=full_archive)
        store.prune_history(CFG.retention_years)
        _state["last_fetch_summary"] = summary
        _state["last_fetch_completed"] = dt.datetime.now(dt.timezone.utc).isoformat()

        if CFG.auto_generate:
            for gid in GAMES:
                _do_generate(gid)
        return {"accepted": True, "summary": summary}
    finally:
        _state["running"] = False


def _do_generate(game_id: str, rows_per_strategy: int = 3,
                 recency_k: int = RECENCY_K_DEFAULT) -> dict:
    recency_k = max(RECENCY_K_MIN, min(RECENCY_K_MAX, int(recency_k)))
    history = list(store.all_draws(game_id))
    tips = generate_tips(game_id, history,
                         rows_per_strategy=rows_per_strategy,
                         recency_k=recency_k)
    if not tips:
        return {"game_id": game_id, "n_tips": 0, "recency_k": recency_k}
    based_on = history[0]["draw_date"] if history else None

    # Empirical analytics: empirical recency-overlap distribution + per-
    # strategy backtest score.  Both are persisted with the tip_run so the
    # dashboard can sort cards by edge and surface the "wie oft kamen
    # noch Zahlen aus den letzten N Ziehungen?" histogram.  See
    # analytics.py for the maths.
    g = get_game(game_id)
    strategy_meta: dict = {}
    recency_stats: dict | None = None
    try:
        recency_stats = recency_overlap_distribution(g, history)
        strategy_meta = score_all_strategies(
            g, history, strategies_for(game_id, recency_k=recency_k),
            rows=rows_per_strategy)
    except Exception as exc:  # noqa: BLE001
        log.warning("[%s] analytics computation failed: %s", game_id, exc)

    run_id = store.save_tip_run(game_id, based_on, tips,
                                strategy_meta=strategy_meta,
                                recency_stats=recency_stats,
                                params={"recency_k": recency_k})
    store.cleanup_old_tip_runs()
    info = {
        "game_id":      game_id,
        "run_id":       run_id,
        "n_tips":       len(tips),
        "based_on":     based_on,
        "recency_k":    recency_k,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    _state["last_generate"] = info
    return info


async def _do_fetch_async(full: bool = False) -> None:
    await asyncio.to_thread(_do_fetch, full)


# --------------------------------------------------------------------------- #
# Lifespan
# --------------------------------------------------------------------------- #
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Initialising SQLite store at %s", CFG.db_path)
    store.init_db(CFG.db_path)
    _bootstrap_seed_if_empty()
    _bootstrap_tips_if_missing()

    scheduler = AsyncIOScheduler(timezone=CFG.tz)
    try:
        trigger = CronTrigger.from_crontab(CFG.fetch_cron, timezone=CFG.tz)
    except Exception as exc:  # noqa: BLE001
        log.error("Invalid fetch cron %r: %s — falling back to '30 3 * * 1,4'",
                  CFG.fetch_cron, exc)
        trigger = CronTrigger.from_crontab("30 3 * * 1,4", timezone=CFG.tz)
    scheduler.add_job(_do_fetch_async, trigger, id="fetch_cycle",
                      coalesce=True, max_instances=1, misfire_grace_time=600)
    scheduler.start()
    job = scheduler.get_job("fetch_cycle")
    if job and job.next_run_time:
        _state["next_run"] = job.next_run_time.isoformat()
    log.info("Scheduler started: cron=%r tz=%s", CFG.fetch_cron, CFG.tz)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="Dream Server Lotto Oracle (Tip Engine)",
              version="0.1.0", lifespan=lifespan)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def _check_token(authorization: str | None) -> None:
    if not CFG.api_token:
        return
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    if authorization.split(" ", 1)[1].strip() != CFG.api_token:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid token")


# --------------------------------------------------------------------------- #
# Read endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {
        "status":  "ok",
        "running": _state["running"],
        "games":   list(GAMES.keys()),
        "schedule": {"cron": CFG.fetch_cron, "tz": CFG.tz, "next_run": _state["next_run"]},
        "submission_api": {
            "supported": False,
            "note": (
                "Es existiert keine offizielle/öffentliche REST-API zur "
                "Tipp-Abgabe in Deutschland. Lotto24 / Tipp24 / Lotto.de "
                "verlangen ein registriertes Kundenkonto mit Bezahlmittel "
                "und bieten keinen programmgesteuerten Zugang. "
                "Die generierten Tipps sind zum manuellen Übertragen "
                "(z.B. via Copy-Paste oder Druck des Spielscheins) "
                "vorgesehen."
            ),
        },
    }


@app.get("/games")
def games_overview() -> dict:
    return {"games": store.games_overview(),
            "next_run": _state["next_run"],
            "schedule": {"cron": CFG.fetch_cron, "tz": CFG.tz}}


@app.get("/games/{game_id}/strategies")
def strategies_for_game(
    game_id: str,
    recency_k: int = Query(RECENCY_K_DEFAULT, ge=RECENCY_K_MIN, le=RECENCY_K_MAX),
) -> dict:
    if game_id not in GAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown game {game_id!r}")
    return {
        "game_id": game_id,
        "recency_k": recency_k,
        "recency_k_range": [RECENCY_K_MIN, RECENCY_K_MAX],
        "strategies": list_strategies(game_id, recency_k=recency_k),
    }


@app.get("/games/{game_id}/sweet-spot")
def sweet_spot(game_id: str) -> dict:
    """Backtest recency_exclude for K = 1..5 and surface the empirical
    sweet spot.  Used by the dashboard to annotate the K selector with
    `(empfohlen)`.  Computation is cheap (~1 backtest per K, ~5 calls
    total) so we don't cache.
    """
    if game_id not in GAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown game {game_id!r}")
    g = get_game(game_id)
    history = list(store.all_draws(game_id))
    result = recency_sweet_spot(
        g, history, lambda k: make_recency_strategy(game_id, k),
        ks=range(RECENCY_K_MIN, RECENCY_K_MAX + 1),
    )
    return {"game_id": game_id, **result}


@app.get("/draws")
def draws(game: str = Query(..., min_length=1),
          limit: int = Query(100, ge=1, le=1000),
          offset: int = Query(0, ge=0)) -> dict:
    if game not in GAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown game {game!r}")
    return {
        "game":    game,
        "limit":   limit,
        "offset":  offset,
        "extent":  store.history_extent(game),
        "draws":   store.list_draws(game, limit=limit, offset=offset),
    }


@app.get("/stats")
def stats(game: str = Query(..., min_length=1)) -> dict:
    g = get_game(game)
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown game {game!r}")
    history = list(store.all_draws(game))
    if not history:
        return {"game": game, "n": 0}
    out: dict = {"game": game, "n": len(history)}
    if g.kind == "combinatorial":
        for p in g.pools:
            counts = Counter()
            gaps = {n: len(history) for n in range(p.low, p.high + 1)}
            for i, draw in enumerate(history):
                seq = draw.get(p.name) or []
                counts.update(seq)
                for n in seq:
                    if gaps[n] == len(history):
                        gaps[n] = i
            out[p.name] = {
                "frequency": [
                    {"number": n, "count": counts.get(n, 0), "gap": gaps.get(n, len(history))}
                    for n in range(p.low, p.high + 1)
                ],
            }
    else:
        # Per-digit-position frequency (for spiel77 / super6).
        per_pos = []
        for pos in range(g.digits):
            c = Counter()
            for h in history:
                d = h.get("digits") or ""
                if len(d) > pos:
                    c.update(d[pos])
            per_pos.append({"position": pos,
                            "frequency": [{"digit": d, "count": c.get(str(d), 0)}
                                          for d in range(10)]})
        out["per_position"] = per_pos
    return out


@app.get("/tips")
def get_tips(game: str = Query(..., min_length=1)) -> dict:
    if game not in GAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown game {game!r}")
    run = store.latest_tip_run(game)
    return {"game": game, "run": run}


# --------------------------------------------------------------------------- #
# Write endpoints (bearer-guarded)
# --------------------------------------------------------------------------- #
class GenerateReq(BaseModel):
    game: str | None = Field(None, description="Game id or null/'all'")
    rows_per_strategy: int = Field(2, ge=1, le=10)
    recency_k: int = Field(
        RECENCY_K_DEFAULT, ge=RECENCY_K_MIN, le=RECENCY_K_MAX,
        description="How many of the most recent draws the recency_exclude "
                    "strategy must avoid (1..5).",
    )


@app.post("/tips/generate", status_code=status.HTTP_202_ACCEPTED)
def post_generate(req: GenerateReq, background: BackgroundTasks,
                  authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    target = (req.game or "").strip().lower() or None
    if target == "all":
        target = None
    if target and target not in GAMES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"unknown game {target!r}; have {list(GAMES.keys())}")
    targets = [target] if target else list(GAMES.keys())
    results = []
    for gid in targets:
        results.append(_do_generate(gid,
                                    rows_per_strategy=req.rows_per_strategy,
                                    recency_k=req.recency_k))
    return {"accepted": True, "results": results}


@app.post("/refresh", status_code=status.HTTP_202_ACCEPTED)
def post_refresh(background: BackgroundTasks,
                 authorization: str | None = Header(default=None),
                 full: bool = Query(False)) -> dict:
    _check_token(authorization)
    background.add_task(_do_fetch, full)
    return {"accepted": True, "full_archive": full,
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}


@app.post("/refresh/full", status_code=status.HTTP_202_ACCEPTED)
def post_refresh_full(background: BackgroundTasks,
                      authorization: str | None = Header(default=None)) -> dict:
    _check_token(authorization)
    background.add_task(_do_fetch, True)
    return {"accepted": True, "full_archive": True,
            "queued_at": dt.datetime.now(dt.timezone.utc).isoformat()}


class ImportReq(BaseModel):
    game: str
    csv: str = Field(..., description="CSV body — same format as seed_data/<game>.csv")


@app.post("/admin/import", status_code=status.HTTP_202_ACCEPTED)
def post_import(req: ImportReq,
                authorization: str | None = Header(default=None)) -> dict:
    """Operator-provided CSV bootstrap. Use when the live fetchers can't
    reach the upstream archives (corp proxies, blocked DNS, etc.).
    Format identical to seed_data/<game>.csv — see README.
    """
    _check_token(authorization)
    if req.game not in GAMES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown game {req.game!r}")
    parser = fetchers.CsvSeedParser(req.game)
    # Write to a temp file so we can reuse the existing parser path.
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
        f.write(req.csv)
        tmp = f.name
    parser.path = type(parser.path)(tmp)  # Path object pointing at temp
    try:
        draws = parser.fetch_archive()
        n = store.bulk_upsert(req.game, draws)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return {"accepted": True, "game": req.game, "imported": n}


# --------------------------------------------------------------------------- #
# Optimal-Schein + Custom-Schein + Jackpot-Backtest
# --------------------------------------------------------------------------- #
@app.get("/optimal-schein")
def optimal_schein(
    recency_k: int = Query(RECENCY_K_DEFAULT, ge=RECENCY_K_MIN, le=RECENCY_K_MAX),
) -> dict:
    """Auto-generated Spielschein with the top-N strategies per game.
    Recomputed on every call (cheap; no DB writes)."""
    return build_optimal_schein(recency_k=recency_k)


class CustomFieldSpec(BaseModel):
    game: str
    strategy: str | None = Field(None, description="Strategy name or null/'auto'")
    recency_k: int = Field(RECENCY_K_DEFAULT, ge=RECENCY_K_MIN, le=RECENCY_K_MAX)
    count: int = Field(1, ge=1, le=12, description="How many fields with these settings")


class CustomScheinReq(BaseModel):
    fields: list[CustomFieldSpec]


@app.post("/scheine/generate")
def post_custom_schein(req: CustomScheinReq) -> dict:
    """Custom Spielschein generator — operator picks any combination of
    (game, strategy) per field. Returns immediately, no persistence.
    Unauthenticated (no DB side-effect; rate-limited by the proxy).
    """
    if not req.fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "no fields provided")
    expanded: list[FieldSpec] = []
    for f in req.fields:
        if f.game not in GAMES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"unknown game {f.game!r}")
        for _ in range(f.count):
            expanded.append(FieldSpec(
                game=f.game, strategy=f.strategy, recency_k=f.recency_k,
            ))
    return build_custom_schein(expanded)


@app.get("/games/{game_id}/jackpot-backtest")
def jackpot_backtest(
    game_id: str,
    years: int = Query(10, ge=1, le=30,
                       description="Backtest window in years"),
    rows: int = Query(1, ge=1, le=4,
                      description="Tips per strategy per draw"),
    recency_k: int = Query(RECENCY_K_DEFAULT, ge=RECENCY_K_MIN, le=RECENCY_K_MAX),
) -> dict:
    """Replay every strategy across the last <years> years and report
    how often it would have hit each prize tier. Used by the dashboard
    chart "Wäre Hauptgewinn / Klasse-2 dabei gewesen?".
    """
    if game_id not in GAMES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown game {game_id!r}")
    g = get_game(game_id)
    history = list(store.all_draws(game_id))
    res = jackpot_backtest_all(
        g, history, strategies_for(game_id, recency_k=recency_k),
        years=years, rows=rows,
    )
    res["game_id"]   = game_id
    res["recency_k"] = recency_k
    return res


@app.get("/state")
def state() -> dict:
    """Diagnostic snapshot."""
    return _state | {
        "submission_api_supported": False,
        "history_overview": {
            gid: store.history_extent(gid) for gid in GAMES
        },
    }

