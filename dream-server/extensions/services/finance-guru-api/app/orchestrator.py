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

    # Phase H-1+H-2: pre-resolve qty for every buy-with-sizer signal so
    # the fill-to-target pass below can reason about uniform per-symbol
    # EUR values, then upscale qty proportional to confidence until the
    # FINANCE_GURU_TARGET_INVESTED_FRAC cash-utilization target is met.
    resolved: list[Signal] = []
    for sig in signals:
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
    skipped: list[dict] = []
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


def asset_type_map() -> dict[str, str]:
    """Build a {symbol: asset_type} lookup from the prices table."""
    with data.conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, asset_type FROM finance.prices_intraday "
            "WHERE ts >= now() - INTERVAL '24 hours'"
        )
        return {sym: at for sym, at in cur.fetchall()}

