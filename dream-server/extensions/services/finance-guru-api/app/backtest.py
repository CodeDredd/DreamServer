"""Backtest engine — replays historical bars + news through a strategy
without touching the live SQLite ledger.

It builds a virtual `BacktestLedger` (in-memory dict) that mirrors the
SQLite contract and walks forward in `step` increments. Useful before
promoting a new strategy to live paper trading (per the README, this
is a *gate* — strategies that lose money in 2 years of history do not
get the live cron slot).
"""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

from . import data
from .config import CFG
from .strategies import DecisionContext, Signal, StrategyDef

log = logging.getLogger("finance-guru.backtest")


@dataclass
class BacktestLedger:
    cash: float
    positions: dict[str, dict] = field(default_factory=dict)
    trades:    list[dict] = field(default_factory=list)
    equity_curve: list[tuple[dt.datetime, float]] = field(default_factory=list)
    fee_bps: float = field(default_factory=lambda: CFG.fee_bps)

    def execute(self, *, ts: dt.datetime, symbol: str, asset_type: str,
                action: str, qty: float, price: float, reason: str = "") -> bool:
        if qty <= 0 or price <= 0:
            return False
        fee = abs(qty * price) * (self.fee_bps / 10_000.0)
        if action == "buy":
            cost = qty * price + fee
            if cost > self.cash:
                return False
            pos = self.positions.get(symbol, {"qty": 0.0, "avg_entry": 0.0,
                                              "asset_type": asset_type})
            new_qty = pos["qty"] + qty
            pos["avg_entry"] = ((pos["qty"] * pos["avg_entry"]) + (qty * price)) / new_qty
            pos["qty"] = new_qty
            pos["asset_type"] = asset_type
            self.positions[symbol] = pos
            self.cash -= cost
        elif action == "sell":
            pos = self.positions.get(symbol)
            if not pos or qty > pos["qty"] + 1e-9:
                return False
            proceeds = qty * price - fee
            realised = (price - pos["avg_entry"]) * qty - fee
            pos["qty"] -= qty
            if pos["qty"] < 1e-9:
                self.positions.pop(symbol)
            self.cash += proceeds
            self.trades.append({"ts": ts, "action": "sell", "symbol": symbol,
                                "qty": qty, "price": price, "fee": fee,
                                "realised_pnl": realised, "reason": reason})
            return True
        else:
            return False
        self.trades.append({"ts": ts, "action": action, "symbol": symbol,
                            "qty": qty, "price": price, "fee": fee,
                            "realised_pnl": None, "reason": reason})
        return True

    def equity(self, mark_prices: dict[str, float]) -> float:
        v = self.cash
        for sym, pos in self.positions.items():
            v += pos["qty"] * mark_prices.get(sym, pos["avg_entry"])
        return v


def _size_buy_eur(cash: float, equity: float, price: float, max_frac: float,
                  existing_qty: float = 0.0) -> float:
    """Phase H-2 backtest parity: anchor sizing on equity (cash + holdings)
    instead of cash alone. Existing position value is subtracted so we
    don't double-up past the per-position cap. Cash is still a hard
    constraint."""
    if price <= 0:
        return 0.0
    base = equity if equity > 0 else cash
    if base <= 0:
        return 0.0
    cap_eur = base * max_frac
    existing_val = existing_qty * price
    target = min(max(0.0, cap_eur - existing_val), cash)
    if target <= 0:
        return 0.0
    return round(target / price, 6)


def run_backtest(sd: StrategyDef, *, start: dt.datetime, end: dt.datetime,
                 step: dt.timedelta = dt.timedelta(hours=1),
                 universe_limit: int = 30) -> dict:
    """Walk-forward simulation. Picks a small universe (top-N most-traded
    symbols in the period) so backtests stay quick on the home box."""
    if start >= end:
        raise ValueError("start must be before end")

    # Pick universe: symbols with the most rows in the period.
    with data.conn() as c, c.cursor() as cur:
        cur.execute(
            """SELECT symbol, asset_type, count(*) AS n
               FROM finance.prices_intraday
               WHERE ts BETWEEN %s AND %s
               GROUP BY symbol, asset_type
               ORDER BY n DESC LIMIT %s""",
            (start, end, universe_limit),
        )
        rows = cur.fetchall()
    if not rows:
        return {"error": "no price history in range",
                "start": start.isoformat(), "end": end.isoformat()}

    universe   = [r[0] for r in rows]
    asset_map  = {r[0]: r[1] for r in rows}

    bt = BacktestLedger(cash=CFG.seed_eur)
    max_frac = sd.max_position_frac if sd.max_position_frac is not None else CFG.max_position_frac

    # Pre-pull all data once — much faster than re-querying per step.
    full_prices = data.price_history_at(universe, end, end - start)
    if full_prices.empty:
        return {"error": "price history query returned no rows"}
    full_prices.set_index("ts", inplace=True)
    full_prices.sort_index(inplace=True)

    full_news = data.news_at(end, end - start, universe)
    if not full_news.empty:
        full_news.set_index("ts", inplace=True)
        full_news.sort_index(inplace=True)

    n_signals = 0
    n_trades  = 0
    cursor_ts = start + step  # need at least one prior bar for any history lookup
    while cursor_ts <= end:
        # Snapshot up to cursor_ts.
        prices_so_far = full_prices.loc[:cursor_ts]
        if prices_so_far.empty:
            cursor_ts += step
            continue
        # Latest price per symbol.
        latest = (prices_so_far.reset_index()
                  .sort_values("ts")
                  .groupby("symbol")
                  .last()["close"]
                  .to_dict())
        latest = {s: float(p) for s, p in latest.items()}

        ctx = DecisionContext(
            now=cursor_ts.replace(tzinfo=dt.timezone.utc) if cursor_ts.tzinfo is None else cursor_ts,
            universe=[s for s in universe if s in latest],
            latest_prices=latest,
            asset_types=asset_map,
            cash_eur=bt.cash,
            positions={s: dict(p) for s, p in bt.positions.items()},
            # Phase H-2: mark-to-market equity (parity with live orchestrator).
            equity_eur=bt.equity(latest),
            get_price_history=_make_history_fn(full_prices, cursor_ts),
            get_news=_make_news_fn(full_news, cursor_ts),
        )

        try:
            sigs: list[Signal] = sd.decide(ctx) or []
        except Exception as exc:  # noqa: BLE001
            log.warning("backtest %s decide() crashed at %s: %s", sd.name, cursor_ts, exc)
            sigs = []
        n_signals += len(sigs)

        for sig in sigs:
            if sig.action == "hold":
                continue
            price = latest.get(sig.symbol)
            if price is None:
                continue
            qty = float(sig.qty)
            if sig.action == "buy":
                mode = sig.extra.get("eur_target")
                if mode in ("max_position_frac", "kelly_lite"):
                    # Phase H-3 backtest parity: kelly_lite scales the
                    # effective cap-fraction by clip(conf-risk, 0, 1).
                    effective_frac = max_frac
                    if mode == "kelly_lite":
                        conf = float(sig.confidence or 0.0)
                        risk = float(sig.risk or 0.0)
                        kelly = max(0.0, min(1.0, conf - risk))
                        if kelly <= 0:
                            continue
                        effective_frac = kelly * max_frac
                    existing = bt.positions.get(sig.symbol, {}).get("qty", 0.0)
                    qty = _size_buy_eur(bt.cash, ctx.equity_eur, price, effective_frac,
                                        existing_qty=float(existing or 0.0))
                    if qty <= 0:
                        continue
            ok = bt.execute(ts=ctx.now, symbol=sig.symbol,
                            asset_type=asset_map.get(sig.symbol, "stock"),
                            action=sig.action, qty=qty, price=price,
                            reason=sig.reason)
            if ok:
                n_trades += 1

        bt.equity_curve.append((ctx.now, bt.equity(latest)))
        cursor_ts += step

    final_mark = (full_prices.reset_index()
                  .sort_values("ts").groupby("symbol").last()["close"].to_dict())
    final_mark = {s: float(p) for s, p in final_mark.items()}
    final_equity = bt.equity(final_mark)

    return {
        "strategy":      sd.name,
        "start":         start.isoformat(),
        "end":           end.isoformat(),
        "step_hours":    step.total_seconds() / 3600,
        "universe_size": len(universe),
        "seeded_eur":    CFG.seed_eur,
        "final_cash":    round(bt.cash, 2),
        "final_holdings_eur": round(final_equity - bt.cash, 2),
        "final_equity_eur":   round(final_equity, 2),
        "total_pnl_pct":      round((final_equity - CFG.seed_eur) / CFG.seed_eur * 100.0, 2),
        "n_signals":     n_signals,
        "n_trades":      n_trades,
        "equity_curve":  [(ts.isoformat(), round(v, 2)) for ts, v in bt.equity_curve[-200:]],
        "open_positions": [{"symbol": s, **p} for s, p in bt.positions.items()],
    }


def _make_history_fn(full_prices: pd.DataFrame, cursor_ts: dt.datetime):
    def fn(symbols: Iterable[str], lookback: dt.timedelta) -> pd.DataFrame:
        start_ts = cursor_ts - lookback
        sub = full_prices.loc[start_ts:cursor_ts]
        if sub.empty:
            return pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
        sub = sub[sub["symbol"].isin(list(symbols))]
        return sub.reset_index()
    return fn


def _make_news_fn(full_news: pd.DataFrame, cursor_ts: dt.datetime):
    def fn(lookback: dt.timedelta, symbols: Iterable[str] | None = None) -> pd.DataFrame:
        if full_news.empty:
            return full_news
        start_ts = cursor_ts - lookback
        sub = full_news.loc[start_ts:cursor_ts]
        if symbols is not None and not sub.empty:
            wanted = set(symbols)
            sub = sub[sub["symbols"].apply(lambda arr: bool(wanted & set(arr or [])))]
        return sub.reset_index()
    return fn

