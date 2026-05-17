"""Orchestrator — wraps a strategy.decide() call with sizing + paper
trade execution + KPI logging."""
from __future__ import annotations

import datetime as dt
import functools
import logging
from typing import Iterable

from . import cycle_log, data, enrichment, ledger, qdrant_rag
from .config import CFG
from .strategies import DecisionContext, Signal, StrategyDef

log = logging.getLogger("finance-guru.orchestrator")


def _build_context(strategy_name: str, asset_types: Iterable[str],
                   asset_type_map: dict[str, str]) -> DecisionContext:
    universe = []
    for at in asset_types:
        universe.extend(data.list_symbols(at))
    universe = sorted(set(universe))

    prices = data.latest_prices(universe) if universe else {}
    cash = ledger.get_cash(strategy_name)
    pos_rows = ledger.get_positions(strategy_name)
    positions = {p["symbol"]: p for p in pos_rows}

    # Phase H-2: equity = cash + mark-to-market(positions). We compute
    # it once here so strategies that read ctx.equity_eur AND the
    # downstream sizer in _size_buy share the exact same number.
    holdings_value = 0.0
    for sym, p in positions.items():
        mark = prices.get(sym) or float(p.get("avg_entry") or 0.0)
        holdings_value += float(p.get("qty") or 0.0) * float(mark)
    equity = cash + holdings_value

    return DecisionContext(
        now=dt.datetime.now(dt.timezone.utc),
        universe=universe,
        latest_prices=prices,
        asset_types={s: asset_type_map.get(s, "stock") for s in universe},
        cash_eur=cash,
        positions=positions,
        equity_eur=equity,
        # Phase H-4: until Phase K wires real per-symbol sector
        # metadata, fall back to asset_type ("stock" / "crypto") as
        # the diversification bucket. The orchestrator gate already
        # treats each symbol-without-a-known-sector as its own bucket
        # so this is a defensive-but-permissive default.
        asset_sectors={s: asset_type_map.get(s, "stock") for s in universe},
        get_price_history=data.price_history,
        get_news=data.recent_news,
        get_social=data.recent_social,
        get_asset_analysis=enrichment.latest_asset_analysis,
        get_source_weight=_source_weight_lookup,
        # Phase B — RAG read-helpers. Strategies opt into them; the
        # plain SQL-based lookups above stay for cheap, non-vector
        # queries.
        get_assets_rag=qdrant_rag.search_assets,
        get_news_rag=qdrant_rag.search_news,
        get_social_rag=qdrant_rag.search_social,
        get_analysis_rag=qdrant_rag.search_asset_analyses,
        get_relations_rag=qdrant_rag.search_relations,
        get_strategy_lessons_rag=qdrant_rag.search_strategy_lessons,
    )


def _source_weight_lookup(source: str) -> dict | None:
    """Tiny helper so strategies can do `ctx.get_source_weight("reuters")
    → {"reliability": 0.92, "weight": 1.8, ...}` without paying for a
    full table scan every call. Cached in-process; cleared each cycle by
    run_strategy_once() so updates from n8n appear quickly."""
    return _cached_source_weight(source.strip().lower())


@functools.lru_cache(maxsize=256)
def _cached_source_weight(source: str) -> dict | None:
    rows = enrichment.list_source_reliability(limit=1000)
    for r in rows:
        if r["source"] == source:
            return r
    return None


def _apply_diversification_gate(
        buy_signals: list[Signal], ctx: DecisionContext,
        max_fresh_buys: int, max_per_sector: int
    ) -> tuple[list[Signal], list[dict]]:
    """Phase H-4: cap total fresh buys per cycle and per sector.

    * Strategies still emit their best candidates (each strategy has
      its own internal cap, also raised to CFG.max_fresh_buys), but
      the orchestrator enforces a global ceiling on TOTAL fresh buys
      per cycle and on per-sector concentration.
    * Existing open positions contribute to the sector count so we
      don't keep stacking into the same sector across multiple
      cycles.
    * Ordering: highest-confidence buys win. Ties broken by symbol
      lex order for determinism.
    * Returns (accepted_buys, rejected_dicts) where each rejected
      dict has the same shape the run_strategy_once skipped-list
      uses ({symbol, action, why}).
    """
    if not buy_signals:
        return buy_signals, []
    max_fresh_buys  = max(1, int(max_fresh_buys))
    max_per_sector  = max(1, int(max_per_sector))

    # Seed sector counter from existing OPEN positions — that's what
    # makes the cap actually limit concentration over time, not just
    # per-cycle. Defensive fallback to asset_type when no sector data.
    sector_count: dict[str, int] = {}
    for sym, pos in (ctx.positions or {}).items():
        if not pos or float(pos.get("qty") or 0.0) <= 0:
            continue
        sec = (ctx.asset_sectors.get(sym)
               or ctx.asset_types.get(sym)
               or pos.get("asset_type")
               or "unknown")
        sector_count[sec] = sector_count.get(sec, 0) + 1

    ordered = sorted(buy_signals,
                     key=lambda s: (-(s.confidence or 0.0), s.symbol))
    accepted: list[Signal] = []
    rejected: list[dict] = []
    accepted_syms: set[str] = set()
    for sig in ordered:
        # Implicit per-symbol cap (1 buy per cycle) — strategies
        # generally already do this, but be defensive.
        if sig.symbol in accepted_syms:
            rejected.append({"symbol": sig.symbol, "action": "buy",
                             "why": "duplicate symbol in this cycle"})
            continue
        if len(accepted) >= max_fresh_buys:
            rejected.append({"symbol": sig.symbol, "action": "buy",
                             "why": f"max_fresh_buys={max_fresh_buys} reached"})
            continue
        sec = (ctx.asset_sectors.get(sig.symbol)
               or ctx.asset_types.get(sig.symbol)
               or "unknown")
        if sector_count.get(sec, 0) >= max_per_sector:
            rejected.append({"symbol": sig.symbol, "action": "buy",
                             "why": f"sector cap {max_per_sector} reached for sector={sec!r}"})
            continue
        accepted.append(sig)
        accepted_syms.add(sig.symbol)
        sector_count[sec] = sector_count.get(sec, 0) + 1
    return accepted, rejected


def _size_buy(signal: Signal, ctx: DecisionContext, max_frac: float) -> float:
    """Convert a placeholder buy signal (qty=1.0, extra.eur_target=...)
    into an actual unit count based on price + max-position cap.

    Phase H-2: the per-position cap is `max_position_frac * equity`
    (not `* cash`), because anchoring to cash starves the portfolio of
    new positions after a few buys — every fill shrinks the
    denominator. Existing position value in the same symbol is
    subtracted so we never exceed the cap when topping up. Cash is
    still a hard constraint applied at the end.

    Returns 0.0 if we can't afford even 1 cent's worth."""
    price = ctx.latest_prices.get(signal.symbol, 0.0)
    if price <= 0:
        return 0.0
    equity = ctx.equity_eur if ctx.equity_eur > 0 else ctx.cash_eur
    if equity <= 0:
        return 0.0
    cap_eur = equity * max_frac
    existing_val = 0.0
    pos = ctx.positions.get(signal.symbol)
    if pos:
        existing_val = float(pos.get("qty") or 0.0) * price
    target_eur = max(0.0, cap_eur - existing_val)
    # Hard cash cap — can't spend more than we have.
    target_eur = min(target_eur, ctx.cash_eur)
    if target_eur <= 0:
        return 0.0
    units = target_eur / price
    return round(units, 6)


def _fill_to_target(buy_signals: list[Signal], ctx: DecisionContext,
                    max_frac: float, target_frac: float) -> list[Signal]:
    """Phase H-1: Cash-Utilization-Target. If `invested / equity` falls
    below `target_frac`, scale up the buy quantities (proportional to
    confidence) until the target is reached, the per-position cap is
    hit, or we run out of cash. Buy signals must already carry their
    base qty (set by _size_buy). SELL/HOLD signals are NOT passed here.

    The function is a no-op if `target_frac <= 0` (legacy mode) or if
    there are no buys to scale. Mutates the returned list only; input
    signals are replaced with new Signal instances so we don't surprise
    callers that captured references to the originals."""
    if target_frac <= 0 or not buy_signals or ctx.equity_eur <= 0:
        return buy_signals

    equity = ctx.equity_eur
    invested = equity - ctx.cash_eur
    target_invested = equity * target_frac
    gap_eur = target_invested - invested
    if gap_eur <= 0:
        return buy_signals
    # Can't spend what we don't have. After paying for the base buys,
    # the remaining cash bounds what we can still distribute.
    base_eurs: list[float] = []
    prices:    list[float] = []
    caps:      list[float] = []
    for sig in buy_signals:
        price = ctx.latest_prices.get(sig.symbol, 0.0)
        prices.append(price)
        base_eurs.append(float(sig.qty) * price if price > 0 else 0.0)
        # Per-position cap = max_frac*equity minus EXISTING holding only.
        # The base_eur already counts toward "what we'll spend now", so
        # the headroom for extra is cap_total − existing − base.
        pos = ctx.positions.get(sig.symbol) or {}
        existing_val = float(pos.get("qty") or 0.0) * price
        cap_total = max(0.0, max_frac * equity - existing_val)
        caps.append(cap_total)
    cash_after_base = max(0.0, ctx.cash_eur - sum(base_eurs))
    # The amount we may still distribute on top of the base buys.
    headroom = sum(max(0.0, caps[i] - base_eurs[i]) for i in range(len(buy_signals)))
    extra_to_distribute = max(0.0, min(gap_eur, cash_after_base, headroom))
    if extra_to_distribute <= 0:
        return buy_signals

    weights = [float(sig.confidence or 0.0) for sig in buy_signals]
    if sum(weights) <= 0:
        weights = [1.0] * len(buy_signals)
    extras = [0.0] * len(buy_signals)
    active = {i for i in range(len(buy_signals)) if prices[i] > 0}
    remaining = extra_to_distribute
    # Iterative water-filling: distribute by confidence; whenever a
    # position saturates its per-position cap, remove it from the pool
    # and redistribute the leftover to the rest. 6 rounds are plenty
    # for typical MAX_FRESH_BUYS values (≤ 8).
    for _ in range(6):
        if remaining <= 1e-6 or not active:
            break
        wsum = sum(weights[i] for i in active)
        if wsum <= 0:
            break
        added = 0.0
        for i in list(active):
            share = remaining * (weights[i] / wsum)
            headroom_i = max(0.0, caps[i] - (base_eurs[i] + extras[i]))
            if share >= headroom_i:
                extras[i] += headroom_i
                added += headroom_i
                active.discard(i)
            else:
                extras[i] += share
                added += share
        remaining -= added

    out: list[Signal] = []
    for i, sig in enumerate(buy_signals):
        if prices[i] <= 0 or extras[i] <= 0:
            out.append(sig)
            continue
        new_qty = round(float(sig.qty) + extras[i] / prices[i], 6)
        new_extra = dict(sig.extra) if sig.extra else {}
        new_extra["fill_to_target_eur"] = round(extras[i], 2)
        out.append(Signal(symbol=sig.symbol, action=sig.action, qty=new_qty,
                          confidence=sig.confidence, risk=sig.risk,
                          reason=sig.reason, extra=new_extra))
    return out


def run_strategy_once(sd: StrategyDef, asset_type_map: dict[str, str],
                      *, trigger: str = "scheduler") -> dict:
    ledger.ensure_strategy(sd.name, sd.description)
    # Drop stale source-weight cache so any new reliability score the
    # source_reliability workflow just wrote takes effect immediately.
    _cached_source_weight.cache_clear()
    ctx = _build_context(sd.name, sd.asset_types, asset_type_map)
    started = ctx.now

    log.info("[%s] cycle: universe=%d cash=%.2f equity=%.2f positions=%d",
             sd.name, len(ctx.universe), ctx.cash_eur, ctx.equity_eur,
             len(ctx.positions))

    signals: list[Signal] = []
    try:
        signals = sd.decide(ctx) or []
    except Exception as exc:  # noqa: BLE001
        log.exception("[%s] decide() crashed", sd.name)
        finished = dt.datetime.now(dt.timezone.utc)
        result = {"strategy": sd.name, "error": str(exc),
                  "signals": 0, "executed": [], "skipped": [],
                  "universe": len(ctx.universe), "ts": started.isoformat()}
        try:
            cycle_log.record(strategy=sd.name, started=started, finished=finished,
                             trigger=trigger, result=result, error=str(exc))
        except Exception:  # noqa: BLE001
            log.exception("cycle_log.record failed (decide crash)")
        return result

    max_frac = sd.max_position_frac if sd.max_position_frac is not None else CFG.max_position_frac

    # Phase H-4: diversification gate runs BEFORE sizing/fill-to-target
    # so we don't waste H-1 headroom on buys we'd reject anyway. The
    # gate enforces max_fresh_buys total + max_buys_per_sector.
    # Non-buy signals pass through unchanged.
    raw_buys = [s for s in signals if s.action == "buy"]
    other    = [s for s in signals if s.action != "buy"]
    gate_skipped: list[dict] = []
    if raw_buys:
        gated_buys, gate_skipped = _apply_diversification_gate(
            raw_buys, ctx,
            max_fresh_buys=CFG.max_fresh_buys,
            max_per_sector=CFG.max_buys_per_sector,
        )
        signals_post_gate = other + gated_buys
    else:
        signals_post_gate = signals

    # Phase H-1+H-2: pre-resolve qty for every buy-with-sizer signal so
    # the fill-to-target pass below can reason about uniform per-symbol
    # EUR values, then upscale qty proportional to confidence until the
    # FINANCE_GURU_TARGET_INVESTED_FRAC cash-utilization target is met.
    resolved: list[Signal] = []
    for sig in signals_post_gate:
        if (sig.action == "buy"
                and sig.extra.get("eur_target") == "max_position_frac"):
            qty = _size_buy(sig, ctx, max_frac)
            if qty <= 0:
                # Pass through as-is; the execute loop below logs the
                # skip with the same reason it used pre-H.
                resolved.append(sig)
                continue
            new_extra = dict(sig.extra) if sig.extra else {}
            new_extra.pop("eur_target", None)  # already sized
            resolved.append(Signal(symbol=sig.symbol, action=sig.action,
                                   qty=qty, confidence=sig.confidence,
                                   risk=sig.risk, reason=sig.reason,
                                   extra=new_extra))
        else:
            resolved.append(sig)

    # Pull the buys out, fill-to-target, then re-merge in original order.
    buys = [s for s in resolved if s.action == "buy" and s.qty > 0]
    if buys and CFG.target_invested_frac > 0:
        upscaled = _fill_to_target(buys, ctx, max_frac, CFG.target_invested_frac)
        scaled_by_sym = {s.symbol: s for s in upscaled}
        resolved = [scaled_by_sym.get(s.symbol, s) if s.action == "buy" else s
                    for s in resolved]

    executed: list[dict] = []
    skipped: list[dict] = list(gate_skipped)  # Phase H-4 rejections show up as skips
    for sig in resolved:
        if sig.action == "hold":
            continue
        qty = float(sig.qty)
        # Re-check sizer skip path for buys whose base qty came back 0.
        if sig.action == "buy" and qty <= 0:
            skipped.append({"symbol": sig.symbol, "action": sig.action,
                            "why": "sizer returned 0 (no cash or no price)"})
            continue
        price = ctx.latest_prices.get(sig.symbol)
        if price is None or price <= 0:
            skipped.append({"symbol": sig.symbol, "action": sig.action,
                            "why": "no live price"})
            continue
        result = ledger.execute_trade(
            strategy=sd.name,
            symbol=sig.symbol,
            asset_type=ctx.asset_types.get(sig.symbol, "stock"),
            action=sig.action,
            qty=qty,
            price=price,
            reason=sig.reason,
            signal={
                "confidence": sig.confidence,
                "risk":       sig.risk,
                "extra":      sig.extra,
            },
            ts=ctx.now,
        )
        if result.accepted:
            executed.append({
                "trade_id":  result.trade_id,
                "symbol":    sig.symbol,
                "action":    sig.action,
                "qty":       qty,
                "price":     price,
                "realised_pnl": result.realised_pnl,
                "reason":    sig.reason,
                # Phase B: surface RAG hits / structured signal extras so
                # the dashboard's cycle drill-down + the weekly retrospective
                # have the evidence that supported each trade.
                "extra":     dict(sig.extra) if sig.extra else {},
            })
        else:
            skipped.append({"symbol": sig.symbol, "action": sig.action,
                            "why": f"{result.reason_code}: {result.note}"})

    # KPI snapshot
    final_prices = data.latest_prices()
    kpi = ledger.kpi(sd.name, final_prices)

    log.info("[%s] cycle done: signals=%d executed=%d skipped=%d equity=%.2f pnl=%.2f%%",
             sd.name, len(signals), len(executed), len(skipped),
             kpi["equity_eur"], kpi["total_pnl_pct"] or 0.0)

    result = {
        "strategy": sd.name,
        "ts":       ctx.now.isoformat(),
        "universe": len(ctx.universe),
        "signals":  len(signals),
        "executed": executed,
        "skipped":  skipped,
        "kpi":      kpi,
    }
    try:
        cycle_log.record(strategy=sd.name, started=started,
                         finished=dt.datetime.now(dt.timezone.utc),
                         trigger=trigger, result=result)
    except Exception:  # noqa: BLE001
        log.exception("cycle_log.record failed")
    return result


def run_strategy_rebalance_once(sd: StrategyDef,
                                asset_type_map: dict[str, str],
                                *, trigger: str = "rebalance") -> dict:
    """Phase H-5: top up EXISTING positions with cash that's still
    idle between regular decide cycles.

    Pipeline (intentionally narrower than run_strategy_once):
      1. Build context (same as the full cycle).
      2. Defensive guard: skip unless cash/equity > 1 - target * trigger
         (avoids churn when already near the H-1 target).
      3. Run sd.decide(ctx).
      4. Keep only buy-signals whose:
            * symbol is already in ctx.positions, AND
            * confidence >= CFG.rebalance_min_confidence.
         All SELL / HOLD / new-symbol BUY signals are dropped — they're
         handled by the regular 30-min decide cycle.
      5. Resolve qty via _size_buy (equity-based, subtracts existing
         position value → the resulting top-up respects the per-
         position cap).
      6. _fill_to_target distributes any remaining headroom
         proportional to confidence, just like the normal cycle.
      7. Execute.

    The diversification gate is intentionally NOT applied: we're not
    opening new symbols, so the global/sector caps would never trip.
    Per-symbol uniqueness is implicit since decide() typically emits
    at most one buy per symbol per cycle.
    """
    ledger.ensure_strategy(sd.name, sd.description)
    _cached_source_weight.cache_clear()
    ctx = _build_context(sd.name, sd.asset_types, asset_type_map)
    started = ctx.now

    if ctx.equity_eur <= 0:
        log.info("[%s] rebalance skip: zero equity", sd.name)
        return {"strategy": sd.name, "skipped": True,
                "reason": "zero equity", "ts": started.isoformat()}

    cash_share = ctx.cash_eur / ctx.equity_eur
    trigger_floor = 1.0 - (CFG.target_invested_frac * CFG.rebalance_cash_trigger_frac)
    if cash_share <= trigger_floor:
        log.info("[%s] rebalance skip: cash_share=%.3f <= trigger=%.3f",
                 sd.name, cash_share, trigger_floor)
        return {"strategy": sd.name, "skipped": True,
                "reason": f"cash_share={cash_share:.3f} <= trigger={trigger_floor:.3f}",
                "ts": started.isoformat()}

    log.info("[%s] rebalance: cash=%.2f equity=%.2f cash_share=%.1f%% (trigger>%.1f%%) positions=%d",
             sd.name, ctx.cash_eur, ctx.equity_eur, cash_share * 100,
             trigger_floor * 100, len(ctx.positions))

    signals: list[Signal] = []
    try:
        signals = sd.decide(ctx) or []
    except Exception as exc:  # noqa: BLE001
        log.exception("[%s] rebalance decide() crashed", sd.name)
        finished = dt.datetime.now(dt.timezone.utc)
        result = {"strategy": sd.name, "error": str(exc),
                  "signals": 0, "executed": [], "skipped": [],
                  "ts": started.isoformat()}
        try:
            cycle_log.record(strategy=sd.name, started=started, finished=finished,
                             trigger=trigger, result=result, error=str(exc))
        except Exception:  # noqa: BLE001
            log.exception("cycle_log.record failed (rebalance decide crash)")
        return result

    held = set(ctx.positions.keys())
    min_conf = float(CFG.rebalance_min_confidence)
    qualifying = [s for s in signals
                  if s.action == "buy"
                  and s.symbol in held
                  and float(s.confidence or 0.0) >= min_conf]
    if not qualifying:
        log.info("[%s] rebalance: no qualifying top-up signals "
                 "(buys=%d, held=%d, min_conf=%.2f)",
                 sd.name, sum(1 for s in signals if s.action == "buy"),
                 len(held), min_conf)
        finished = dt.datetime.now(dt.timezone.utc)
        result = {"strategy": sd.name, "skipped": True,
                  "reason": "no qualifying top-up signals",
                  "signals": len(signals), "executed": [],
                  "ts": started.isoformat()}
        try:
            cycle_log.record(strategy=sd.name, started=started, finished=finished,
                             trigger=trigger, result=result)
        except Exception:  # noqa: BLE001
            log.exception("cycle_log.record failed (rebalance no-op)")
        return result

    max_frac = sd.max_position_frac if sd.max_position_frac is not None else CFG.max_position_frac

    # Resolve base qty (H-2 equity-aware sizing already accounts for
    # existing position value).
    resolved: list[Signal] = []
    for sig in qualifying:
        if sig.extra.get("eur_target") == "max_position_frac":
            qty = _size_buy(sig, ctx, max_frac)
            if qty <= 0:
                continue
            new_extra = dict(sig.extra) if sig.extra else {}
            new_extra.pop("eur_target", None)
            new_extra["rebalance_top_up"] = True
            resolved.append(Signal(symbol=sig.symbol, action="buy", qty=qty,
                                   confidence=sig.confidence, risk=sig.risk,
                                   reason=f"[rebalance] {sig.reason}",
                                   extra=new_extra))
        else:
            # Strategy emitted an explicit qty/fixed_eur sizing — honour
            # it, but flag the top-up reason.
            new_extra = dict(sig.extra) if sig.extra else {}
            new_extra["rebalance_top_up"] = True
            resolved.append(Signal(symbol=sig.symbol, action="buy",
                                   qty=float(sig.qty), confidence=sig.confidence,
                                   risk=sig.risk,
                                   reason=f"[rebalance] {sig.reason}",
                                   extra=new_extra))

    # H-1 fill-to-target distribution still applies — useful when
    # several positions qualify and we want to push toward the target.
    if resolved and CFG.target_invested_frac > 0:
        resolved = _fill_to_target(resolved, ctx, max_frac, CFG.target_invested_frac)

    executed: list[dict] = []
    skipped: list[dict] = []
    for sig in resolved:
        qty = float(sig.qty)
        if qty <= 0:
            skipped.append({"symbol": sig.symbol, "action": "buy",
                            "why": "sizer returned 0"})
            continue
        price = ctx.latest_prices.get(sig.symbol)
        if price is None or price <= 0:
            skipped.append({"symbol": sig.symbol, "action": "buy",
                            "why": "no live price"})
            continue
        result = ledger.execute_trade(
            strategy=sd.name, symbol=sig.symbol,
            asset_type=ctx.asset_types.get(sig.symbol, "stock"),
            action="buy", qty=qty, price=price,
            reason=sig.reason,
            signal={"confidence": sig.confidence, "risk": sig.risk,
                    "extra": sig.extra},
            ts=ctx.now,
        )
        if result.accepted:
            executed.append({
                "trade_id": result.trade_id,
                "symbol":   sig.symbol, "action": "buy",
                "qty":      qty, "price": price,
                "realised_pnl": result.realised_pnl,
                "reason":   sig.reason,
                "extra":    dict(sig.extra) if sig.extra else {},
            })
        else:
            skipped.append({"symbol": sig.symbol, "action": "buy",
                            "why": f"{result.reason_code}: {result.note}"})

    final_prices = data.latest_prices()
    kpi = ledger.kpi(sd.name, final_prices)
    log.info("[%s] rebalance done: signals=%d executed=%d skipped=%d equity=%.2f cash_share=%.1f%%",
             sd.name, len(signals), len(executed), len(skipped),
             kpi["equity_eur"],
             (kpi["cash_eur"] / kpi["equity_eur"] * 100) if kpi["equity_eur"] else 0)

    result = {
        "strategy": sd.name,
        "ts":       ctx.now.isoformat(),
        "signals":  len(signals),
        "executed": executed,
        "skipped":  skipped,
        "kpi":      kpi,
        "rebalance": True,
    }
    try:
        cycle_log.record(strategy=sd.name, started=started,
                         finished=dt.datetime.now(dt.timezone.utc),
                         trigger=trigger, result=result)
    except Exception:  # noqa: BLE001
        log.exception("cycle_log.record failed (rebalance)")
    return result


def asset_type_map() -> dict[str, str]:
    """Build a {symbol: asset_type} lookup from the prices table."""
    with data.conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, asset_type FROM finance.prices_intraday "
            "WHERE ts >= now() - INTERVAL '24 hours'"
        )
        return {sym: at for sym, at in cur.fetchall()}

