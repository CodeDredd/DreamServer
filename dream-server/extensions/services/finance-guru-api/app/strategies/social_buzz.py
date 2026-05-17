"""Social-buzz strategy.

Premise: a sudden spike in Reddit chatter about a symbol — combined
with positive sentiment from the LiteLLM `fast` classifier — is a
short-term tradeable signal *before* it shows up in mainstream news.

Single-cycle logic (no historical buzz baseline yet — that's a
follow-up):

  buzz_score(sym) =  Σ post.score
                   + 5 × Σ (post.sentiment * post.urgency)
                   over the last 6h, normalised by post count.

  BUY  signal  when buzz_score(sym) >= BUY_THRESHOLD AND mean
               sentiment >= +0.3 AND we don't already hold the symbol.

  SELL signal  when we hold the symbol AND either:
                 (a) mean sentiment over the last 4h <= -0.3
                 (b) we're already up >= TAKE_PROFIT_PCT.

The strategy degrades gracefully: if `get_social` is missing (older
finance-guru-api before step 6) or returns an empty frame
(finance-social not deployed yet, or Reddit unconfigured), it returns
no signals and skips.
"""
from __future__ import annotations

import datetime as dt
import logging

import pandas as pd

from .. import llm
from ..config import CFG
from . import DecisionContext, Signal, strategy

log = logging.getLogger("finance-guru.strat.social_buzz")

LOOKBACK_BUY        = dt.timedelta(hours=6)
LOOKBACK_SELL       = dt.timedelta(hours=4)
BUY_THRESHOLD       = 50.0     # tuned for r/wallstreetbets-grade scores
BUY_MEAN_SENT       = 0.30
SELL_MEAN_SENT      = -0.30
TAKE_PROFIT_PCT     = 0.05
MIN_POSTS_FOR_BUY   = 3        # one upvoted post is not a trend
# Phase H-4: the per-strategy fresh-buy cap is now driven by CFG so a
# single env var (FINANCE_GURU_MAX_FRESH_BUYS) controls both this
# strategy's emission ceiling and the orchestrator's diversification
# gate. Kept as a module-level constant for back-compat with any
# notebook/import that referenced it; resolved lazily at decide-time.


def _summarise_reason(symbol: str, action: str, posts: pd.DataFrame) -> str:
    """One-liner for the dashboard. LLM-polished if available, else
    a deterministic template — same pattern as news_sentiment."""
    titles = posts["title"].head(3).tolist() if not posts.empty else []
    template = f"{action.upper()} {symbol}: " + " | ".join(t[:80] for t in titles[:3])
    if not titles:
        return f"{action.upper()} {symbol}: no post context"
    try:
        msg = [
            {"role": "system",
             "content": "You explain a paper-trade decision in one short sentence (<=20 words). "
                        "Mention 'Reddit buzz' explicitly so the operator knows the source."},
            {"role": "user",
             "content": f"Action: {action.upper()} {symbol}\nReddit posts:\n- " + "\n- ".join(titles[:3])},
        ]
        text = llm.chat(msg, max_tokens=60).strip().replace("\n", " ")
        return text[:180] if text else template
    except Exception as exc:  # noqa: BLE001
        log.debug("LLM reason failed for %s (%s) — using template", symbol, exc)
        return template


def _posts_for(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if df.empty:
        return df
    mask = df["symbols"].apply(lambda arr: symbol in (arr or []))
    out = df[mask].copy()
    out.sort_values("ts", ascending=False, inplace=True)
    return out


def _buzz_score(posts: pd.DataFrame) -> float:
    if posts.empty:
        return 0.0
    score_sum = float(posts["score"].fillna(0).sum())
    sent_sum = float((posts["sentiment"].fillna(0) * posts["urgency"].fillna(0)).sum())
    n = max(1, len(posts))
    # Normalising by sqrt(n) rewards trending volume without being
    # dominated by a single 5-comment thread.
    return (score_sum + 5.0 * sent_sum) / (n ** 0.5)


@strategy(name="social_buzz",
          description="Buy on Reddit-buzz spikes for a symbol with positive sentiment; sell on negative buzz or +5%.",
          asset_types=("stock", "crypto"))
def decide(ctx: DecisionContext) -> list[Signal]:
    if not ctx.universe or ctx.get_social is None:
        return []

    posts = ctx.get_social(LOOKBACK_BUY, ctx.universe)
    if posts is None or posts.empty:
        return []

    # Drop posts the LLM didn't manage to score — they have no
    # actionable polarity for this strategy.
    posts = posts.dropna(subset=["sentiment"])
    if posts.empty:
        return []

    signals: list[Signal] = []

    # ── SELL side: any held symbol with negative buzz, or take-profit.
    sell_window = posts[posts["ts"] >= ctx.now - LOOKBACK_SELL]
    for sym, pos in ctx.positions.items():
        mark = ctx.latest_prices.get(sym)
        if mark is None:
            continue
        pnl_pct = (mark - pos["avg_entry"]) / pos["avg_entry"] if pos["avg_entry"] else 0.0
        sym_posts = _posts_for(sell_window, sym)
        sell_reason: str | None = None
        if pnl_pct >= TAKE_PROFIT_PCT:
            sell_reason = f"take-profit at +{pnl_pct*100:.1f}%"
        elif not sym_posts.empty:
            mean_sent = float(sym_posts["sentiment"].mean())
            if mean_sent <= SELL_MEAN_SENT:
                sell_reason = f"negative buzz (mean sentiment={mean_sent:.2f})"
        if sell_reason:
            signals.append(Signal(
                symbol=sym,
                action="sell",
                qty=pos["qty"],
                confidence=min(1.0, abs(pnl_pct) * 5 + 0.3),
                risk=0.3,
                reason=_summarise_reason(sym, "sell", sym_posts),
                extra={"pnl_pct": round(pnl_pct, 4), "trigger": sell_reason},
            ))

    # ── BUY side: pick the top-N un-held symbols by buzz_score.
    held = set(ctx.positions.keys())
    candidates: list[tuple[float, str, pd.DataFrame]] = []
    for sym in ctx.universe:
        if sym in held:
            continue
        if not ctx.latest_prices.get(sym):
            continue
        sym_posts = _posts_for(posts, sym)
        if len(sym_posts) < MIN_POSTS_FOR_BUY:
            continue
        mean_sent = float(sym_posts["sentiment"].mean())
        if mean_sent < BUY_MEAN_SENT:
            continue
        score = _buzz_score(sym_posts)
        if score < BUY_THRESHOLD:
            continue
        candidates.append((score, sym, sym_posts))

    candidates.sort(reverse=True, key=lambda t: t[0])
    for score, sym, rows in candidates[:CFG.max_fresh_buys]:
        signals.append(Signal(
            symbol=sym,
            action="buy",
            qty=1.0,                         # placeholder; orchestrator rewrites via eur_target
            confidence=min(1.0, score / (BUY_THRESHOLD * 4)),
            risk=1.0 - min(1.0, score / (BUY_THRESHOLD * 4)),
            reason=_summarise_reason(sym, "buy", rows),
            extra={
                "buzz_score":  round(score, 2),
                "n_posts":     int(len(rows)),
                "mean_sent":   round(float(rows["sentiment"].mean()), 3),
                "eur_target":  "max_position_frac",
            },
        ))
    return signals

