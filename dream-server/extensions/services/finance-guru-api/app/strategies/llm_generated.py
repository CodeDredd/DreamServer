"""Loader that materialises every `strategies_meta.kind='generated'`
row whose status is in the selected set into a callable StrategyDef
and registers it in the in-process REGISTRY.

Phase D of FINANCE-GURU-IMPROVEMENT-PLAN.md.

Why a separate module from `dsl`:
    - `dsl.compile_spec()` is pure (no DB, no REGISTRY mutation).
    - This loader is the side-effecting glue (reads strategies_meta,
      writes REGISTRY, seeds the ledger). Keeping them separate makes
      the DSL trivially unit-testable and lets the propose endpoint
      compile + backtest a candidate WITHOUT polluting the live loop.

`load_generated_strategies()` is called once at service startup
(after `discover_strategies()`) and again on demand whenever lifecycle
transitions promote a generated strategy to live so the new strategy
joins the cron loop without a process restart.
"""
from __future__ import annotations

import json
import logging
from typing import Iterable

from .. import ledger, lifecycle
from . import REGISTRY, StrategyDef
from .dsl import DslError, compile_spec

log = logging.getLogger("finance-guru.strat.generated")


def _decode_source(raw) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None


def load_generated_strategies(*, statuses: Iterable[str] = ("live",)) -> dict[str, StrategyDef]:
    """Rebuild every generated StrategyDef from strategies_meta.

    Returns the dict of {name: StrategyDef} actually registered in
    REGISTRY (skipping invalid DSL rows; the bad rows stay in the
    table but are logged so an operator can inspect via
    `GET /strategies/lifecycle?kind=generated`).
    """
    out: dict[str, StrategyDef] = {}
    rows: list[dict] = []
    for st in statuses:
        rows.extend(lifecycle.list_meta(status=st, kind="generated", limit=500))
    seen: set[str] = set()
    for row in rows:
        name = row["name"]
        if name in seen:
            continue
        seen.add(name)
        spec = _decode_source(row.get("source_json"))
        if not spec:
            log.warning("generated strategy %s has empty/invalid source_json — skipping", name)
            continue
        try:
            sd = compile_spec(spec, name=name,
                              description=spec.get("description") or "")
        except DslError as exc:
            log.warning("generated strategy %s has invalid DSL (%s) — skipping", name, exc)
            continue
        REGISTRY[name] = sd
        out[name] = sd
        # Ensure the ledger has a row so the next decide cycle has cash
        # to spend. ensure_strategy() is idempotent — repeating it on
        # every startup is harmless.
        ledger.ensure_strategy(sd.name, sd.description)
    if out:
        log.info("loaded %d generated strategies (%s)", len(out), ",".join(sorted(out)))
    return out


def compile_proposal(name: str, source: dict) -> StrategyDef:
    """Used by the propose endpoint to materialise a freshly-saved DSL
    row for the auto-backtest. Does NOT register in REGISTRY — only the
    promote path (or load_generated_strategies on next startup) does
    that.
    """
    return compile_spec(source, name=name,
                        description=(source or {}).get("description") or "")


def register_generated(name: str, source: dict) -> StrategyDef:
    """Compile + register one specific generated row — used right after
    auto-promote so the new strategy is immediately schedulable."""
    sd = compile_proposal(name, source)
    REGISTRY[name] = sd
    ledger.ensure_strategy(sd.name, sd.description)
    log.info("registered generated strategy %s into live REGISTRY", name)
    return sd


def unregister_generated(name: str) -> bool:
    """Remove a generated row from REGISTRY (called when retire/archive
    transitions a `generated` strategy away from `live`)."""
    if name in REGISTRY:
        del REGISTRY[name]
        log.info("unregistered generated strategy %s from REGISTRY", name)
        return True
    return False

