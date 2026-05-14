"""Orchestrator — wraps a strategy.decide() call with sizing + paper
trade execution + KPI logging."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Iterable

from . import data, ledger
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

    return DecisionContext(
        now=dt.datetime.now(dt.timezone.utc),
        universe=universe,
        latest_prices=prices,
        asset_types={s: asset_type_map.get(s, "stock") for s in universe},
        cash_eur=cash,
        positions=positions,
        get_price_history=data.price_history,
        get_news=data.recent_news,
        get_social=data.recent_social,
    )


def _size_buy(signal: Signal, ctx: DecisionContext, max_frac: float) -> float:
    """Convert a placeholder buy signal (qty=1.0, extra.eur_target=...)
    into an actual unit count based on price + max-position cap.
    Returns 0.0 if we can't afford even 1 cent's worth."""
    price = ctx.latest_prices.get(signal.symbol, 0.0)
    if price <= 0:
        return 0.0
    target_eur = ctx.cash_eur * max_frac
    if target_eur <= 0:
        return 0.0
    units = target_eur / price
    return round(units, 6)


def run_strategy_once(sd: StrategyDef, asset_type_map: dict[str, str]) -> dict:
    ledger.ensure_strategy(sd.name, sd.description)
    ctx = _build_context(sd.name, sd.asset_types, asset_type_map)

    log.info("[%s] cycle: universe=%d cash=%.2f positions=%d",
             sd.name, len(ctx.universe), ctx.cash_eur, len(ctx.positions))

    signals: list[Signal] = []
    try:
        signals = sd.decide(ctx) or []
    except Exception as exc:  # noqa: BLE001
        log.exception("[%s] decide() crashed", sd.name)
        return {"strategy": sd.name, "error": str(exc),
                "signals": 0, "executed": 0}

    max_frac = sd.max_position_frac if sd.max_position_frac is not None else CFG.max_position_frac

    executed: list[dict] = []
    skipped: list[dict] = []
    for sig in signals:
        if sig.action == "hold":
            continue
        # Resolve qty for buy signals that asked the orchestrator to size.
        qty = float(sig.qty)
        if sig.action == "buy" and sig.extra.get("eur_target") == "max_position_frac":
            qty = _size_buy(sig, ctx, max_frac)
            if qty <= 0:
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

    return {
        "strategy": sd.name,
        "ts":       ctx.now.isoformat(),
        "signals":  len(signals),
        "executed": executed,
        "skipped":  skipped,
        "kpi":      kpi,
    }


def asset_type_map() -> dict[str, str]:
    """Build a {symbol: asset_type} lookup from the prices table."""
    with data.conn() as c, c.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT symbol, asset_type FROM finance.prices_intraday "
            "WHERE ts >= now() - INTERVAL '24 hours'"
        )
        return {sym: at for sym, at in cur.fetchall()}

