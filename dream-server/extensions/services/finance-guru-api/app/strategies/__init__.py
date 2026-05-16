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

