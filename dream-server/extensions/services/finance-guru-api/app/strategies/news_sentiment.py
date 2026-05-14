"""News-driven sentiment strategy.

Logic — kept deliberately simple for the skeleton step:

    BUY  signal  when there's at least one news.events row in the last
                 60 minutes for a symbol with sentiment >= +0.5 AND
                 urgency >= 0.4 AND we don't already hold the symbol.
                 Confidence = max(sentiment) * max(urgency).

    SELL signal  when we hold the symbol AND either:
                   (a) most recent news in the last 4h has sentiment <= -0.5
                   (b) we're already up >= +5% on the position
                       (lock in the gain — the 10%/week target is
                        cumulative, but small wins compound).

The LLM is only consulted to summarise the *reason* once we've
decided to act — we never burn an LLM call to re-classify what
finance-news already classified at ingest time.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from .. import llm
from . import DecisionContext, Signal, strategy

log = logging.getLogger("finance-guru.strat.news_sentiment")

BUY_SENT  = 0.5
BUY_URG   = 0.4
SELL_SENT = -0.5
TAKE_PROFIT_PCT = 0.05


def _summarise_reason(symbol: str, action: str, headlines: list[str]) -> str:
    """Optional LLM polish — short one-liner for the dashboard.
    Falls back to a deterministic template on any LLM error."""
    if not headlines:
        return f"{action.upper()} {symbol}: no headline context"
    template = f"{action.upper()} {symbol}: " + " | ".join(h[:80] for h in headlines[:3])
    try:
        msg = [
            {"role": "system",
             "content": "You explain a paper-trade decision in one short sentence (<=20 words). No filler."},
            {"role": "user",
             "content": f"Action: {action.upper()} {symbol}\nHeadlines:\n- " + "\n- ".join(headlines[:3])},
        ]
        text = llm.chat(msg, max_tokens=60).strip().replace("\n", " ")
        return text[:180] if text else template
    except Exception as exc:  # noqa: BLE001
        log.debug("LLM reason failed for %s (%s) — using template", symbol, exc)
        return template


@strategy(name="news_sentiment",
          description="Buy on strong+urgent positive news; sell on negative news or +5% take-profit.",
          asset_types=("stock", "crypto"))
def decide(ctx: DecisionContext) -> list[Signal]:
    if not ctx.universe:
        return []

    # Pull last 4h of scored news for our universe — narrow filter.
    news = ctx.get_news(dt.timedelta(hours=4), ctx.universe)
    if news.empty:
        return []
    news = news.dropna(subset=["sentiment"])  # only LLM-scored rows
    if news.empty:
        return []

    signals: list[Signal] = []

    # ── SELL side first: any held symbol with negative recent news, or
    #    take-profit threshold reached.
    for sym, pos in ctx.positions.items():
        mark = ctx.latest_prices.get(sym)
        if mark is None:
            continue
        pnl_pct = (mark - pos["avg_entry"]) / pos["avg_entry"] if pos["avg_entry"] else 0.0
        # Recent news for this symbol.
        sym_news = _news_for(news, sym)
        sell_reason: str | None = None
        if pnl_pct >= TAKE_PROFIT_PCT:
            sell_reason = f"take-profit at +{pnl_pct*100:.1f}%"
        elif not sym_news.empty:
            worst = sym_news["sentiment"].min()
            if worst <= SELL_SENT:
                sell_reason = f"negative news (sentiment={worst:.2f})"
        if sell_reason:
            headlines = sym_news.head(3)["title"].tolist() if not sym_news.empty else []
            signals.append(Signal(
                symbol=sym,
                action="sell",
                qty=pos["qty"],
                confidence=min(1.0, abs(pnl_pct) * 5 + 0.3),
                risk=0.3,
                reason=_summarise_reason(sym, "sell", headlines + [sell_reason]),
                extra={"pnl_pct": round(pnl_pct, 4), "trigger": sell_reason},
            ))

    # ── BUY side: strong+urgent positive news for un-held symbols.
    held = set(ctx.positions.keys())
    # Per cycle, at most 3 fresh buys to avoid blowing through cash.
    candidates: list[tuple[float, str, pd.DataFrame]] = []
    for sym in ctx.universe:
        if sym in held:
            continue
        mark = ctx.latest_prices.get(sym)
        if not mark:
            continue
        sym_news = _news_for(news, sym)
        if sym_news.empty:
            continue
        # Window the buy decision to last 60 minutes only.
        recent = sym_news[sym_news["ts"] >= ctx.now - dt.timedelta(hours=1)]
        if recent.empty:
            continue
        best = recent[(recent["sentiment"] >= BUY_SENT) & (recent["urgency"] >= BUY_URG)]
        if best.empty:
            continue
        score = float(best["sentiment"].max() * best["urgency"].max())
        candidates.append((score, sym, best))

    candidates.sort(reverse=True, key=lambda t: t[0])
    for score, sym, rows in candidates[:3]:
        mark = ctx.latest_prices[sym]
        # qty sizing handled by the orchestrator (it knows max_position_frac).
        # Passing qty=0 would be ambiguous — pass a sentinel of 1.0 unit and
        # let the orchestrator scale; here we instead set `extra.eur_target`
        # so the orchestrator can do max-frac sizing by EUR.
        signals.append(Signal(
            symbol=sym,
            action="buy",
            qty=1.0,                 # placeholder; orchestrator rewrites from eur_target
            confidence=min(1.0, score),
            risk=1.0 - min(1.0, score),
            reason=_summarise_reason(sym, "buy", rows["title"].head(3).tolist()),
            extra={"score": round(score, 3), "eur_target": "max_position_frac"},
        ))
    return signals


def _news_for(news_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Filter news rows where `symbol` appears in the symbols array.
    Returns rows sorted newest-first."""
    mask = news_df["symbols"].apply(lambda arr: symbol in (arr or []))
    out = news_df[mask].copy()
    out.sort_values("ts", ascending=False, inplace=True)
    return out

