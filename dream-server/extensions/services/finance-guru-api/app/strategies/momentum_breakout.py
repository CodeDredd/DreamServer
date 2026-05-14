"""20-bar momentum-breakout (pure-Python, no LLM).

For each symbol with at least 20 prior intraday bars:

    BUY  if the latest close is the highest of the last 20 bars AND
         the latest volume is >= 1.5x the average of the prior 19,
         AND we don't already hold the symbol.
    SELL if we hold the symbol AND the latest close is the LOWEST of
         the last 20 bars (stop-out) OR we're up >= 8% (trailing
         take-profit, more aggressive than news_sentiment because
         momentum reverses faster).

Confidence is the breakout strength = (latest - mean(prior 19)) /
stddev(prior 19), clamped to [0,1] after dividing by 3.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np
import pandas as pd

from . import DecisionContext, Signal, strategy

log = logging.getLogger("finance-guru.strat.momentum")

LOOKBACK_BARS = 20
VOLUME_MULT   = 1.5
TRAIL_PROFIT  = 0.08


@strategy(name="momentum_breakout",
          description="20-bar high + volume-spike breakout; stop on 20-bar low or +8% trail.",
          asset_types=("stock", "crypto"))
def decide(ctx: DecisionContext) -> list[Signal]:
    if not ctx.universe:
        return []

    # Pull enough history for a 20-bar window. 15-min bars × 20 = 5 hours
    # for stocks; crypto is 5-min so we ask for the same 5 hours and
    # downsample below.
    df = ctx.get_price_history(ctx.universe, dt.timedelta(hours=10))
    if df.empty:
        return []

    signals: list[Signal] = []
    held = set(ctx.positions.keys())

    for sym, sym_df in df.groupby("symbol"):
        sym_df = sym_df.sort_values("ts")
        if len(sym_df) < LOOKBACK_BARS:
            continue
        window = sym_df.tail(LOOKBACK_BARS)
        latest = window.iloc[-1]
        prior  = window.iloc[:-1]
        last_close = float(latest["close"])
        last_vol   = float(latest["volume"] or 0.0)

        prior_max  = float(prior["close"].max())
        prior_min  = float(prior["close"].min())
        prior_mean = float(prior["close"].mean())
        prior_std  = float(prior["close"].std() or 1e-9)
        vol_mean   = float(prior["volume"].mean() or 0.0)

        # ── SELL on stop-out or trailing profit
        if sym in held:
            pos = ctx.positions[sym]
            mark = ctx.latest_prices.get(sym, last_close)
            pnl_pct = (mark - pos["avg_entry"]) / pos["avg_entry"] if pos["avg_entry"] else 0.0
            if last_close <= prior_min:
                signals.append(Signal(
                    symbol=sym, action="sell", qty=pos["qty"],
                    confidence=0.7, risk=0.4,
                    reason=f"momentum stop-out: 20-bar low ({last_close:.4f} <= {prior_min:.4f})",
                    extra={"pnl_pct": round(pnl_pct, 4)},
                ))
            elif pnl_pct >= TRAIL_PROFIT:
                signals.append(Signal(
                    symbol=sym, action="sell", qty=pos["qty"],
                    confidence=0.6, risk=0.3,
                    reason=f"momentum trail-profit at +{pnl_pct*100:.1f}%",
                    extra={"pnl_pct": round(pnl_pct, 4)},
                ))
            continue

        # ── BUY on fresh breakout
        if last_close > prior_max and vol_mean > 0 and last_vol >= VOLUME_MULT * vol_mean:
            strength = (last_close - prior_mean) / prior_std
            confidence = float(np.clip(strength / 3.0, 0.0, 1.0))
            if confidence < 0.3:
                continue
            signals.append(Signal(
                symbol=sym, action="buy", qty=1.0,
                confidence=confidence,
                risk=1.0 - confidence,
                reason=f"breakout {last_close:.4f} > 20-bar high {prior_max:.4f}, vol {last_vol/vol_mean:.1f}x",
                extra={
                    "strength_sigma": round(strength, 2),
                    "vol_ratio":      round(last_vol / vol_mean, 2),
                    "eur_target":     "max_position_frac",
                },
            ))
    return signals

