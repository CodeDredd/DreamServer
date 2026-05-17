"""Strategy plugin framework + auto-discovery.

Each strategy lives in its own module under app/strategies/ and
exposes a `STRATEGY` instance built from the @strategy() decorator.
At service startup we import every module in this package and pull
out their `STRATEGY` objects into a registry.

Adding a new strategy: drop a new file like
`app/strategies/my_idea.py`, decorate one function with `@strategy(...)`,
and that's it — no scheduler edits, no API edits, no DB edits. The
new plugin shows up under GET /strategies and gets seeded with
FINANCE_GURU_SEED_EUR on first scheduler tick.
"""
from __future__ import annotations

import datetime as dt
import importlib
import logging
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Literal

import pandas as pd

log = logging.getLogger("finance-guru.strategies")

Action = Literal["buy", "sell", "hold"]


@dataclass
class DecisionContext:
    """What the orchestrator hands every strategy on each cycle.
    Strategies are pure-ish functions: they get the world, return
    signals. The orchestrator does the trade execution."""
    now: dt.datetime
    universe: list[str]                    # symbols available right now
    latest_prices: dict[str, float]        # {sym: last close}
    asset_types: dict[str, str]            # {sym: 'stock'|'crypto'}
    cash_eur: float                         # the strategy's free cash
    positions: dict[str, dict]             # {sym: {qty, avg_entry, asset_type, opened_at}}
    # Phase H-2: equity_eur = cash + mark-to-market(positions). Sizing
    # now uses equity (not cash) as the per-position-cap denominator so
    # a max_position_frac of 0.10 means "10 % of total equity" instead
    # of "10 % of currently-free cash" (which shrinks with every buy
    # and quickly starves the portfolio of new positions). Defaults to
    # 0.0 so callers that haven't been migrated yet (e.g. legacy unit
    # tests) keep compiling — orchestrator + backtest always populate
    # it correctly.
    equity_eur: float = 0.0
    # Phase H-4: per-symbol sector lookup, used by the orchestrator's
    # diversification gate (max N buys per sector per cycle) and
    # available to strategies that want sector context.
    # Until Phase K wires real sector metadata, the orchestrator
    # populates this as a copy of asset_types ("stock" / "crypto" as
    # the two coarse buckets). Strategies that need finer granularity
    # should fall back to ctx.asset_types[sym] when ctx.asset_sectors
    # has no entry for the symbol.
    asset_sectors: dict[str, str] = field(default_factory=dict)

    # Lazy lookups — strategies pull what they need.
    get_price_history: Callable[[list[str], dt.timedelta], pd.DataFrame] = field(default=None)  # type: ignore
    get_news:          Callable[[dt.timedelta, list[str] | None], pd.DataFrame] = field(default=None)  # type: ignore
    # Optional — only populated when finance-social has been deployed.
    # Strategies should treat an empty DataFrame as "no signal", not error.
    get_social:        Callable[[dt.timedelta, list[str] | None], pd.DataFrame] = field(default=None)  # type: ignore
    # Enrichment lookups (populated by orchestrator; may return [] / None
    # if the n8n enrichment workflows haven't run yet — strategies must
    # degrade gracefully).
    get_asset_analysis: Callable[[str, int], list[dict]] = field(default=None)  # type: ignore
    get_source_weight:  Callable[[str], dict | None] = field(default=None)      # type: ignore

    # ── RAG read-helpers (Phase B) ──────────────────────────────────────
    # All return list[dict] of `{score, ...payload}`; empty list if the
    # backing collection is unreachable or hasn't been populated yet.
    # Signatures use kwargs-only on the callable to keep call-sites
    # self-documenting:
    #   ctx.get_news_rag("Iran tanker disruption", symbols=["BP","XOM"])
    #   ctx.get_relations_rag("rate cut", min_confidence=0.4)
    get_assets_rag:           Callable[..., list[dict]] = field(default=None)  # type: ignore
    get_news_rag:             Callable[..., list[dict]] = field(default=None)  # type: ignore
    get_social_rag:           Callable[..., list[dict]] = field(default=None)  # type: ignore
    get_analysis_rag:         Callable[..., list[dict]] = field(default=None)  # type: ignore
    get_relations_rag:        Callable[..., list[dict]] = field(default=None)  # type: ignore
    get_strategy_lessons_rag: Callable[..., list[dict]] = field(default=None)  # type: ignore


@dataclass
class Signal:
    symbol: str
    action: Action
    qty: float                             # in shares/units, NOT EUR
    confidence: float                      # 0..1
    risk: float                            # 0..1
    reason: str
    extra: dict = field(default_factory=dict)


@dataclass
class StrategyDef:
    name: str
    description: str
    decide: Callable[[DecisionContext], list[Signal]]
    asset_types: tuple[str, ...] = ("stock", "crypto")
    # Optional per-strategy max-position-fraction override (None = use global).
    max_position_frac: float | None = None


# --------------------------------------------------------------------------- #
# Registry + decorator
# --------------------------------------------------------------------------- #
REGISTRY: dict[str, StrategyDef] = {}


def strategy(*, name: str, description: str = "",
             asset_types: tuple[str, ...] = ("stock", "crypto"),
             max_position_frac: float | None = None):
    def deco(fn: Callable[[DecisionContext], list[Signal]]) -> StrategyDef:
        sd = StrategyDef(
            name=name,
            description=description or (fn.__doc__ or "").strip().split("\n")[0],
            decide=fn,
            asset_types=asset_types,
            max_position_frac=max_position_frac,
        )
        REGISTRY[name] = sd
        log.info("Registered strategy %r (asset_types=%s)", name, asset_types)
        return sd
    return deco


def discover_strategies() -> dict[str, StrategyDef]:
    """Import every submodule of app.strategies — each one self-registers
    via the @strategy decorator."""
    import app.strategies as pkg
    for _, modname, _ in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"app.strategies.{modname}")
    log.info("Strategy discovery done: %d total", len(REGISTRY))
    return dict(REGISTRY)

