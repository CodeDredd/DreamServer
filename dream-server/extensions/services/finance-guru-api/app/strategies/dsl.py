"""Strategy DSL — minimal JSON-schema for LLM-generated strategies.

Phase D of FINANCE-GURU-IMPROVEMENT-PLAN.md.

Design goals
------------
* **Deterministic + auditable**: every rule must reference exactly the
  signals listed in `ALLOWED_SIGNALS`; freeform Python is rejected.
  That keeps the LLM-genesis path safe even when the reasoning model
  hallucinates feature names.
* **Cheap to evaluate**: signal computations are memoised per cycle so
  a 10-rule strategy over 200 symbols does at most one news/price/social
  pull (the same calls a hand-coded strategy would do).
* **Universe-aware**: bare `symbols`/`universe_filter` references are
  validated against the live universe at propose-time and at every
  cycle — the strategy silently no-ops on symbols that have left the
  universe instead of crashing.

Spec shape (v1)
---------------
```jsonc
{
  "version": 1,
  "description": "Buy on strong sentiment, take profit at +5%, stop at -4%.",
  "asset_types": ["stock"],          // default ["stock","crypto"]
  "max_position_frac": 0.08,          // optional override; falls back to CFG
  "universe_filter": {                // optional
    "symbols": ["XOM","CVX","BP"]
  },
  "rules": [
    {
      "id": "entry",
      "action": "buy",
      "when": { "all": [
        {"signal":"news.sentiment_max","lookback_h":4,"op":">=","value":0.5},
        {"signal":"news.urgency_max","lookback_h":4,"op":">=","value":0.4}
      ]},
      "sizing": {"mode": "max_position_frac"},
      "reason": "Strong positive news for {symbol}"
    },
    {
      "id": "tp",
      "action": "sell",
      "when": { "all": [
        {"signal":"position.pnl_pct","op":">=","value":0.05}
      ]},
      "reason": "Take profit"
    }
  ]
}
```

Sells are always full closes — the orchestrator already handles that
elsewhere. Buy sizing supports `max_position_frac` (existing path,
orchestrator rewrites qty from `extra.eur_target`) and `fixed_eur`.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from . import DecisionContext, Signal, StrategyDef

log = logging.getLogger("finance-guru.dsl")

DSL_VERSION = 1
ALLOWED_OPS = {"==", "!=", ">", ">=", "<", "<="}
ALLOWED_ACTIONS = {"buy", "sell"}
ALLOWED_SIZING = {"max_position_frac", "fixed_eur"}
ALLOWED_SIGNALS: dict[str, str] = {
    # name → short doc (also surfaced to the LLM in the genesis prompt)
    "news.sentiment_max":   "max sentiment among news rows for symbol in the last lookback_h hours (-1..+1)",
    "news.sentiment_min":   "min sentiment for symbol in window (-1..+1)",
    "news.urgency_max":     "max urgency for symbol in window (0..1)",
    "news.count":           "number of news rows mentioning the symbol in the window",
    "social.sentiment_mean":"mean sentiment of social posts mentioning symbol in window (-1..+1)",
    "social.count":         "number of social posts mentioning the symbol in the window",
    "price.return_pct":     "(latest_close / close `bars` bars ago) - 1 as fraction (0.05 = +5%)",
    "price.breakout_high":  "1 if latest close > max(prior `bars` closes), else 0",
    "price.volume_ratio":   "latest_volume / mean(prior `bars` volumes) — 1.5 = 50% above avg",
    "position.holds":       "1 if the strategy already holds the symbol, else 0",
    "position.pnl_pct":     "(mark - avg_entry) / avg_entry — only valid when holding",
    "rag.relations_count":  "# matching causal-relation hits from finance_relations (Phase E collection)",
}
MAX_RULES = 12
MAX_PREDICATES_PER_RULE = 8
MAX_NESTING_DEPTH = 4


class DslError(ValueError):
    """Raised by validate_spec()/compile_spec() on any structural
    problem. The propose endpoint maps these to HTTP 400."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_spec(spec: dict, *,
                  allowed_symbols: set[str] | None = None) -> None:
    """Raises DslError on any rejection. When `allowed_symbols` is
    given, every `symbols`/`universe_filter.symbols` entry must be a
    member — useful at propose-time to reject obvious hallucinations
    before the backtest is ever run."""
    if not isinstance(spec, dict):
        raise DslError("spec must be a JSON object")
    if int(spec.get("version", DSL_VERSION)) != DSL_VERSION:
        raise DslError(f"unsupported DSL version {spec.get('version')!r}")
    rules = spec.get("rules")
    if not isinstance(rules, list) or not rules:
        raise DslError("spec.rules must be a non-empty list")
    if len(rules) > MAX_RULES:
        raise DslError(f"too many rules ({len(rules)} > {MAX_RULES})")
    asset_types = spec.get("asset_types") or ["stock", "crypto"]
    if not isinstance(asset_types, list) or not all(
            a in ("stock", "crypto") for a in asset_types):
        raise DslError("asset_types must be a list of 'stock'/'crypto'")
    if "max_position_frac" in spec and spec["max_position_frac"] is not None:
        try:
            mpf = float(spec["max_position_frac"])
        except (TypeError, ValueError):
            raise DslError("max_position_frac not numeric") from None
        if not (0.0 < mpf <= 1.0):
            raise DslError("max_position_frac must be in (0, 1]")
    seen_ids: set[str] = set()
    has_buy = False
    for i, r in enumerate(rules):
        ctx = f"rules[{i}]"
        if not isinstance(r, dict):
            raise DslError(f"{ctx}: not an object")
        action = r.get("action")
        if action not in ALLOWED_ACTIONS:
            raise DslError(f"{ctx}.action must be one of {sorted(ALLOWED_ACTIONS)}")
        if action == "buy":
            has_buy = True
        rid = r.get("id")
        if rid is not None:
            if not isinstance(rid, str) or not rid.strip():
                raise DslError(f"{ctx}.id must be a non-empty string")
            if rid in seen_ids:
                raise DslError(f"{ctx}.id duplicate {rid!r}")
            seen_ids.add(rid)
        when = r.get("when")
        if not isinstance(when, dict):
            raise DslError(f"{ctx}.when must be an object")
        _validate_when(when, ctx + ".when", depth=0)
        sizing = r.get("sizing") or {"mode": "max_position_frac"}
        if not isinstance(sizing, dict):
            raise DslError(f"{ctx}.sizing must be an object")
        mode = sizing.get("mode", "max_position_frac")
        if mode not in ALLOWED_SIZING:
            raise DslError(f"{ctx}.sizing.mode {mode!r} not in {sorted(ALLOWED_SIZING)}")
        if mode == "fixed_eur":
            try:
                if float(sizing.get("eur", 0)) <= 0:
                    raise DslError(f"{ctx}.sizing.eur must be > 0 for fixed_eur")
            except (TypeError, ValueError):
                raise DslError(f"{ctx}.sizing.eur not numeric") from None
        syms = r.get("symbols")
        if syms is not None:
            if not isinstance(syms, list):
                raise DslError(f"{ctx}.symbols must be a list")
            if allowed_symbols is not None:
                bad = [s for s in syms if str(s).upper() not in allowed_symbols]
                if bad:
                    raise DslError(f"{ctx}.symbols not in universe: {bad[:5]}")
    if not has_buy:
        raise DslError("spec.rules must contain at least one 'buy' rule")
    uf = spec.get("universe_filter") or {}
    if uf:
        if not isinstance(uf, dict):
            raise DslError("universe_filter must be an object")
        uf_syms = uf.get("symbols")
        if uf_syms is not None:
            if not isinstance(uf_syms, list) or not uf_syms:
                raise DslError("universe_filter.symbols must be a non-empty list")
            if allowed_symbols is not None:
                bad = [s for s in uf_syms if str(s).upper() not in allowed_symbols]
                if bad:
                    raise DslError(f"universe_filter.symbols not in universe: {bad[:5]}")


def _validate_when(node: dict, ctx: str, *, depth: int) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise DslError(f"{ctx}: nesting too deep (> {MAX_NESTING_DEPTH})")
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        kids = node[key]
        if not isinstance(kids, list) or not kids:
            raise DslError(f"{ctx}.{key} must be a non-empty list")
        if len(kids) > MAX_PREDICATES_PER_RULE:
            raise DslError(f"{ctx}.{key} too many predicates ({len(kids)})")
        for j, k in enumerate(kids):
            if not isinstance(k, dict):
                raise DslError(f"{ctx}.{key}[{j}] must be an object")
            _validate_when(k, f"{ctx}.{key}[{j}]", depth=depth + 1)
        return
    sig = node.get("signal")
    if sig not in ALLOWED_SIGNALS:
        raise DslError(f"{ctx}.signal {sig!r} not in allowed list")
    if node.get("op") not in ALLOWED_OPS:
        raise DslError(f"{ctx}.op {node.get('op')!r} not in {sorted(ALLOWED_OPS)}")
    if "value" not in node:
        raise DslError(f"{ctx}.value required")


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def _apply_op(op: str, lhs: float, rhs: float) -> bool:
    if op == "==": return lhs == rhs
    if op == "!=": return lhs != rhs
    if op == ">":  return lhs >  rhs
    if op == ">=": return lhs >= rhs
    if op == "<":  return lhs <  rhs
    if op == "<=": return lhs <= rhs
    return False


def _eval_signal(name: str, params: dict, *, symbol: str,
                  ctx: DecisionContext, cache: dict) -> float | bool | None:
    """Compute one signal for one symbol. None means "data unavailable"
    and short-circuits the rule to False — never a trade on missing
    data."""
    if name == "position.holds":
        return symbol in ctx.positions
    if name == "position.pnl_pct":
        pos = ctx.positions.get(symbol)
        mark = ctx.latest_prices.get(symbol)
        if not pos or not mark or not pos.get("avg_entry"):
            return None
        ae = float(pos["avg_entry"])
        if ae <= 0:
            return None
        return (float(mark) - ae) / ae

    if name.startswith("news."):
        if ctx.get_news is None:
            return None
        hours = max(1, int(params.get("lookback_h", 4)))
        key = ("news", hours)
        df = cache.get(key)
        if df is None:
            try:
                df = ctx.get_news(dt.timedelta(hours=hours), ctx.universe)
            except Exception:  # noqa: BLE001
                df = None
            cache[key] = df
        if df is None or df.empty:
            return 0 if name == "news.count" else None
        sym_df = df[df["symbols"].apply(lambda arr: symbol in (arr or []))]
        if sym_df.empty:
            return 0 if name == "news.count" else None
        if name == "news.count":
            return int(len(sym_df))
        col = "sentiment" if name != "news.urgency_max" else "urgency"
        vals = sym_df[col].dropna()
        if vals.empty:
            return None
        if name == "news.sentiment_max" or name == "news.urgency_max":
            return float(vals.max())
        if name == "news.sentiment_min":
            return float(vals.min())
        return None

    if name.startswith("social."):
        if ctx.get_social is None:
            return 0 if name == "social.count" else None
        hours = max(1, int(params.get("lookback_h", 12)))
        key = ("social", hours)
        df = cache.get(key)
        if df is None:
            try:
                df = ctx.get_social(dt.timedelta(hours=hours), ctx.universe)
            except Exception:  # noqa: BLE001
                df = None
            cache[key] = df
        if df is None or df.empty:
            return 0 if name == "social.count" else None
        sym_df = df[df["symbols"].apply(lambda arr: symbol in (arr or []))]
        if sym_df.empty:
            return 0 if name == "social.count" else None
        if name == "social.count":
            return int(len(sym_df))
        vals = sym_df["sentiment"].dropna()
        if vals.empty:
            return None
        return float(vals.mean())

    if name.startswith("price."):
        if ctx.get_price_history is None:
            return None
        bars = max(2, int(params.get("bars", 20)))
        # 15-min stock bars → ~4/h; 5-min crypto bars → ~12/h. Asking
        # for `bars+1` hours guarantees enough rows for either cadence
        # without being absurdly wide.
        hours = max(2, bars + 1)
        key = ("price", hours)
        df = cache.get(key)
        if df is None:
            try:
                df = ctx.get_price_history(ctx.universe, dt.timedelta(hours=hours * 1))
            except Exception:  # noqa: BLE001
                df = None
            cache[key] = df
        if df is None or df.empty:
            return None
        sym_df = df[df["symbol"] == symbol].sort_values("ts").tail(bars + 1)
        if len(sym_df) < 2:
            return None
        prior = sym_df.iloc[:-1]
        latest = sym_df.iloc[-1]
        if name == "price.return_pct":
            base = float(prior.iloc[0]["close"])
            if base == 0:
                return None
            return (float(latest["close"]) - base) / base
        if name == "price.breakout_high":
            return float(latest["close"]) > float(prior["close"].max())
        if name == "price.volume_ratio":
            vm = float(prior["volume"].mean() or 0)
            if vm <= 0:
                return None
            return float(latest["volume"] or 0) / vm

    if name == "rag.relations_count":
        if ctx.get_relations_rag is None:
            return 0
        try:
            hits = ctx.get_relations_rag(
                str(params.get("query", f"drivers for {symbol}"))[:200],
                limit=int(params.get("limit", 10)),
                symbols=[symbol],
                min_confidence=float(params.get("min_confidence", 0.0)),
            )
        except Exception:  # noqa: BLE001
            hits = []
        return len(hits or [])

    return None


def _eval_when(node: dict, *, symbol: str, ctx: DecisionContext,
                cache: dict) -> bool:
    if "all" in node:
        return all(_eval_when(k, symbol=symbol, ctx=ctx, cache=cache)
                   for k in node["all"])
    if "any" in node:
        return any(_eval_when(k, symbol=symbol, ctx=ctx, cache=cache)
                   for k in node["any"])
    val = _eval_signal(node["signal"], node, symbol=symbol, ctx=ctx, cache=cache)
    if val is None:
        return False
    if isinstance(val, bool):
        val = 1.0 if val else 0.0
    rhs = node["value"]
    if isinstance(rhs, bool):
        rhs = 1.0 if rhs else 0.0
    try:
        return _apply_op(node["op"], float(val), float(rhs))
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------- #
# Compilation — DSL → callable StrategyDef
# --------------------------------------------------------------------------- #
def compile_spec(spec: dict, *, name: str, description: str = "") -> StrategyDef:
    """Validate + bind. Does NOT register in REGISTRY — see
    llm_generated.load_generated_strategies() for the registration
    path."""
    validate_spec(spec)
    asset_types = tuple(spec.get("asset_types") or ("stock", "crypto"))
    max_frac = spec.get("max_position_frac")
    rules: list[dict] = list(spec["rules"])
    uf = spec.get("universe_filter") or {}
    uf_symbols = {str(s).upper() for s in (uf.get("symbols") or [])} or None

    def decide(ctx: DecisionContext) -> list[Signal]:
        if not ctx.universe:
            return []
        cache: dict = {}
        signals: list[Signal] = []
        # Universe slice for the spec.
        universe = ctx.universe
        if uf_symbols:
            universe = [s for s in universe if s.upper() in uf_symbols]
        for sym in universe:
            atype = ctx.asset_types.get(sym, "stock")
            if asset_types and atype not in asset_types:
                continue
            # First matching rule per (symbol, action) wins so a tight
            # sell condition can take precedence over a generic "trim"
            # rule.
            actions_done: set[str] = set()
            for rule in rules:
                action = rule["action"]
                if action in actions_done:
                    continue
                rule_syms = rule.get("symbols")
                if rule_syms:
                    if sym.upper() not in {str(s).upper() for s in rule_syms}:
                        continue
                if action == "buy" and sym in ctx.positions:
                    # Don't double-buy — the orchestrator would reject
                    # it anyway, but skipping here saves a predicate
                    # evaluation.
                    continue
                if action == "sell" and sym not in ctx.positions:
                    continue
                try:
                    matched = _eval_when(rule["when"], symbol=sym, ctx=ctx, cache=cache)
                except Exception as exc:  # noqa: BLE001
                    log.debug("dsl[%s] rule %s eval error on %s: %s",
                              name, rule.get("id"), sym, exc)
                    matched = False
                if not matched:
                    continue
                extra: dict[str, Any] = {
                    "dsl_rule_id": rule.get("id"),
                    "dsl_rule_action": action,
                }
                if action == "buy":
                    sizing = rule.get("sizing") or {"mode": "max_position_frac"}
                    mode = sizing.get("mode", "max_position_frac")
                    qty = 1.0
                    if mode == "max_position_frac":
                        extra["eur_target"] = "max_position_frac"
                    elif mode == "fixed_eur":
                        price = ctx.latest_prices.get(sym, 0.0)
                        if price <= 0:
                            continue
                        qty = max(0.0, float(sizing.get("eur", 0)) / price)
                        if qty <= 0:
                            continue
                    extra["sizing_mode"] = mode
                else:  # sell — always full close
                    pos = ctx.positions.get(sym)
                    if not pos or float(pos.get("qty", 0)) <= 0:
                        continue
                    qty = float(pos["qty"])
                    extra["sizing_mode"] = "position_qty"
                reason = (rule.get("reason")
                          or f"{action} {sym} via {rule.get('id') or 'rule'}").replace("{symbol}", sym)
                signals.append(Signal(
                    symbol=sym, action=action, qty=qty,
                    confidence=float(rule.get("confidence", 0.6)),
                    risk=float(rule.get("risk", 0.4)),
                    reason=reason[:240],
                    extra=extra,
                ))
                actions_done.add(action)
        return signals

    desc = description or spec.get("description") or "LLM-generated DSL strategy"
    return StrategyDef(
        name=name,
        description=desc[:240],
        decide=decide,
        asset_types=asset_types,
        max_position_frac=float(max_frac) if max_frac is not None else None,
    )


def signal_catalog() -> dict[str, str]:
    """Surfaced to the LLM-genesis workflow so the model can be told
    exactly which signal names + semantics are legal."""
    return dict(ALLOWED_SIGNALS)

