"""Strategy genesis — auto-backtest + auto-promote for DSL proposals.

Phase D of FINANCE-GURU-IMPROVEMENT-PLAN.md.

Called from the `/strategies/propose` endpoint after the row is saved.
Runs the backtest in a background thread so the HTTP caller gets an
immediate 201 + `queued_backtest=true`; the result is reflected in
`strategies_meta` (status flip from `proposed` → `live` or
`archived`) and a row in `strategy_audits` so the dashboard's
genesis-history panel can render the outcome.

State machine (orchestrated here):

    proposed ──auto-backtest──┬── PASS ──▶ live      (register_generated)
                              ├── FAIL ──▶ archived  (reason captured)
                              └── ERROR ─▶ archived  (reason captured)

Cost discipline (§10 AGENT-OPERATIONS): the LLM is NOT called here.
This module only runs deterministic backtests against TimescaleDB.
The reasoning model has already been consumed once by the n8n genesis
workflow at proposal time.
"""
from __future__ import annotations

import datetime as dt
import logging

from . import backtest, lifecycle, qdrant_rag
from .config import CFG
from .strategies import REGISTRY
from .strategies.dsl import DslError
from .strategies.llm_generated import compile_proposal, register_generated

log = logging.getLogger("finance-guru.genesis")


def evaluate_proposal(name: str, *, actor: str = "genesis") -> dict:
    """Run the backtest gate for one proposed strategy and apply the
    promote/archive transition. Returns a summary dict suitable for
    surfacing in `/strategies/audits` and the dashboard.

    Safe to call from a BackgroundTask — does its own error capture.
    """
    meta = lifecycle.get_meta(name)
    if not meta:
        return {"strategy": name, "outcome": "missing",
                "note": "no strategies_meta row"}
    if meta.get("status") != "proposed":
        return {"strategy": name, "outcome": "skip",
                "note": f"status={meta.get('status')} (only 'proposed' is auto-evaluated)"}

    import json
    source_raw = meta.get("source_json") or "{}"
    if isinstance(source_raw, str):
        try:
            source = json.loads(source_raw)
        except json.JSONDecodeError as exc:
            return _archive_with_reason(
                name, f"invalid source_json ({exc})", actor=actor)
    else:
        source = source_raw or {}

    # Compile (validates the DSL again — propose-time validation may
    # have been against a different universe).
    try:
        sd = compile_proposal(name, source)
    except DslError as exc:
        return _archive_with_reason(
            name, f"DSL compile failed: {exc}", actor=actor)

    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=max(1, CFG.genesis_backtest_days))
    step = dt.timedelta(minutes=max(5, CFG.genesis_backtest_step_minutes))
    universe_limit = max(1, CFG.genesis_backtest_universe_limit)

    try:
        bt = backtest.run_backtest(
            sd, start=start, end=end, step=step,
            universe_limit=universe_limit,
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("genesis backtest crashed for %s", name)
        return _archive_with_reason(
            name, f"backtest crashed: {exc}", actor=actor)

    if "error" in bt:
        return _archive_with_reason(
            name, f"backtest: {bt['error']}", actor=actor,
            extra={"backtest": bt})

    pnl = float(bt.get("total_pnl_pct") or 0.0)
    n_trades = int(bt.get("n_trades") or 0)
    min_pct    = CFG.genesis_min_backtest_pct
    min_trades = max(0, CFG.genesis_min_backtest_trades)

    pass_pnl    = pnl    >= min_pct
    pass_trades = n_trades >= min_trades
    if pass_pnl and pass_trades:
        return _promote(name, source=source, bt=bt, actor=actor)
    reason = (
        f"backtest pnl={pnl:+.2f}% (need {min_pct:+.2f}%), "
        f"trades={n_trades} (need {min_trades})"
    )
    if not pass_pnl:
        return _archive_with_reason(name, reason, actor=actor,
                                    extra={"backtest": _trim_bt(bt)})
    # passed PnL but too few trades — same archive path, different note.
    return _archive_with_reason(name, reason, actor=actor,
                                 extra={"backtest": _trim_bt(bt)})


def _trim_bt(bt: dict) -> dict:
    """Don't drag the full equity_curve through the audit log."""
    keep = ("strategy", "start", "end", "step_hours", "universe_size",
            "seeded_eur", "final_cash", "final_holdings_eur",
            "final_equity_eur", "total_pnl_pct", "n_signals", "n_trades")
    return {k: bt[k] for k in keep if k in bt}


def _promote(name: str, *, source: dict, bt: dict, actor: str) -> dict:
    """Mark live in lifecycle, register the compiled strategy into
    REGISTRY so the next cron tick picks it up, and ensure the ledger
    is seeded. lifecycle.promote() is the one that records the audit
    transition."""
    try:
        lifecycle.promote(
            name=name,
            bt_pnl_pct=float(bt.get("total_pnl_pct") or 0.0),
            bt_n_trades=int(bt.get("n_trades") or 0),
            actor=actor,
        )
        # Re-load from DB so the description reflects whatever
        # promote() may have rewritten.
        register_generated(name, source)
    except Exception as exc:  # noqa: BLE001
        log.exception("genesis promote failed for %s", name)
        return {"strategy": name, "outcome": "error",
                "note": f"promote failed: {exc}",
                "backtest": _trim_bt(bt)}
    return {
        "strategy":  name,
        "outcome":   "promoted",
        "bt_pnl_pct": float(bt.get("total_pnl_pct") or 0.0),
        "n_trades":   int(bt.get("n_trades") or 0),
        "backtest":   _trim_bt(bt),
    }


def _archive_with_reason(name: str, reason: str, *, actor: str,
                          extra: dict | None = None) -> dict:
    try:
        lifecycle.archive(name=name, reason=reason, actor=actor)
    except Exception as exc:  # noqa: BLE001
        log.exception("genesis archive failed for %s", name)
        return {"strategy": name, "outcome": "error",
                "note": f"archive failed: {exc}"}
    # Emit a tiny lesson so the next genesis cycle can RAG-query
    # "what archtype already failed?". Best-effort.
    try:
        qdrant_rag.upsert_strategy_lesson(
            strategy=name, outcome="archived", pnl_pct=None,
            lesson_text=f"Generated proposal {name} archived at genesis time. "
                        f"Reason: {reason}",
            keywords=[name, "genesis", "archived"],
            extra={"genesis_reason": reason[:240]},
        )
    except Exception:  # noqa: BLE001
        pass
    # And drop from REGISTRY if it had somehow been pre-registered.
    REGISTRY.pop(name, None)
    out = {"strategy": name, "outcome": "archived", "note": reason}
    if extra:
        out.update(extra)
    return out

