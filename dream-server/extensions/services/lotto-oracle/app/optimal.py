"""Optimal-Spielschein + Custom-Spielschein generation.

These endpoints are *stateless* (no DB writes) — every call computes
fresh tips, optionally using the recommended K from the sweet-spot
analytics. They sit alongside the existing /tips/generate API which
persists strategy-runs for the dashboard's main "Vorschläge"-panel.

Conventions
-----------
* "Spielschein" = a tip-slip with multiple fields. Lotto 6 aus 49 has
  12 fields per Schein (max); Eurojackpot 8 (max). We default to 4
  (the *Normalschein*).
* "Field" = one combination (one row of numbers / one Losnummer).
* Each field carries its strategy name + rationale so the dashboard can
  explain why each field was generated this way.

The "optimal" Schein follows a simple rule: pick the top-N strategies
by backtest **edge** (avg_match − expected_random) and run each once.
For digit games (Spiel 77 / Super 6) only one field is generated since
the Schein only has one Losnummer.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Iterable

from . import store
from .analytics import score_all_strategies
from .games import GAMES, Game, get_game
from .strategies import (
    RECENCY_K_DEFAULT,
    Strategy,
    get_strategy,
    run_strategy,
    strategies_for,
)

log = logging.getLogger("lotto-oracle.optimal")


# How many fields per Schein for each combinatorial game (Normalschein,
# 1 € pro Tipp). Digit games always have exactly one field.
DEFAULT_FIELDS: dict[str, int] = {
    "lotto-6aus49": 4,
    "eurojackpot":  4,
    "spiel77":      1,
    "super6":       1,
}


@dataclass(frozen=True)
class FieldSpec:
    """One requested field in a custom Spielschein."""
    game: str
    strategy: str | None       # None / 'auto' → top strategy
    recency_k: int = RECENCY_K_DEFAULT


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _rank_strategies_by_edge(meta: dict, fallback: list[Strategy]) -> list[str]:
    """Return strategy names sorted by backtest edge desc (best first).
    Falls back to declaration order for strategies without backtest meta.
    """
    declared = [s.name for s in fallback]
    if not meta:
        return declared

    def _edge(name: str) -> float:
        m = meta.get(name) or {}
        e = m.get("edge")
        return float(e) if isinstance(e, (int, float)) else -1e9

    ranked = sorted(declared, key=lambda n: -_edge(n))
    return ranked


def _generate_field(game_id: str, strategy_name: str | None, history: list[dict],
                    *, recency_k: int, rng: random.Random) -> dict:
    """Generate one field for the given game/strategy."""
    g = get_game(game_id)
    if not g:
        raise ValueError(f"unknown game {game_id!r}")

    if strategy_name in (None, "", "auto"):
        # default to the first declared strategy (recency_exclude)
        strategy_name = strategies_for(game_id, recency_k=recency_k)[0].name

    tips = run_strategy(game_id, strategy_name, history,
                        rows=1, recency_k=recency_k, rng=rng)
    if not tips:
        raise RuntimeError(f"strategy {strategy_name!r} produced no tip")
    tip = tips[0]
    # Flatten payload to top-level so the UI can read tip['Hauptzahlen']
    # or tip['digits'] directly (mirrors store.latest_tip_run shape).
    payload = tip.pop("payload", None) or {}
    for k, v in payload.items():
        tip.setdefault(k, v)
    tip["game"] = game_id
    return tip


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def build_optimal_schein(*, recency_k: int = RECENCY_K_DEFAULT,
                         rng: random.Random | None = None) -> dict:
    """Generate the auto-optimal Schein for every supported game.

    Strategy selection per game:
      * combinatorial (lotto-6aus49, eurojackpot) — 4 fields, top-4
        strategies by backtest edge (ties broken by declaration order).
      * digit (spiel77, super6) — 1 field, top-1 strategy by edge.

    Returns a dict with one block per game::

        {
          "generated_at": "...",
          "recency_k":    1,
          "schein": {
            "lotto-6aus49": { "fields": [...], "n_fields": 4 },
            "eurojackpot":  { "fields": [...], "n_fields": 4 },
            "spiel77":      { "fields": [...], "n_fields": 1 },
            "super6":       { "fields": [...], "n_fields": 1 },
            # plus the convenience combo "Sa/Mi-Schein" (lotto + spiel77 + super6)
            "combo_mittwoch_samstag": { ... }
          },
          "next_draw": "..."  # for the UI's countdown
        }
    """
    rng = rng or random.Random()
    out_blocks: dict[str, dict] = {}
    for gid in GAMES:
        g = get_game(gid)
        n_fields = DEFAULT_FIELDS.get(gid, 1)
        history = list(store.all_draws(gid))

        # Use the persisted strategy_meta from the latest tip-run if
        # available — saves a full backtest pass.
        latest = store.latest_tip_run(gid)
        meta = (latest or {}).get("strategy_meta") or {}
        if not meta:
            try:
                meta = score_all_strategies(g, history,
                                            strategies_for(gid, recency_k=recency_k),
                                            rows=1)
            except Exception:  # noqa: BLE001
                meta = {}

        ranked = _rank_strategies_by_edge(meta, strategies_for(gid, recency_k=recency_k))

        # Combinatorial: top-N strategies, each one field. Cycle the list
        # if there are fewer strategies than fields requested.
        if g.kind == "combinatorial":
            chosen_names = ranked[:n_fields]
            while len(chosen_names) < n_fields:
                chosen_names.append(ranked[0])
        else:
            chosen_names = ranked[:1]

        fields = []
        for name in chosen_names:
            try:
                tip = _generate_field(gid, name, history,
                                      recency_k=recency_k, rng=rng)
                m = meta.get(name) or {}
                tip["strategy_edge"]   = m.get("edge")
                tip["strategy_label"]  = next(
                    (s.label for s in strategies_for(gid, recency_k=recency_k)
                     if s.name == name), name,
                )
                fields.append(tip)
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] optimal field for %s failed: %s", gid, name, exc)

        out_blocks[gid] = {
            "game_id":  gid,
            "n_fields": len(fields),
            "fields":   fields,
        }

    # Convenience: the typical Mittwoch/Samstag-Schein bundles
    # 6aus49 + Spiel77 + Super6. Eurojackpot is Di/Fr and stands alone.
    sat_fields = (out_blocks.get("lotto-6aus49", {}).get("fields") or []) + \
                 (out_blocks.get("spiel77", {}).get("fields") or []) + \
                 (out_blocks.get("super6",  {}).get("fields") or [])
    out_blocks["combo_mittwoch_samstag"] = {
        "game_id":  "combo_mittwoch_samstag",
        "label":    "Schein Mi/Sa (6 aus 49 + Spiel 77 + Super 6)",
        "n_fields": len(sat_fields),
        "fields":   sat_fields,
    }
    eur_fields = out_blocks.get("eurojackpot", {}).get("fields") or []
    out_blocks["combo_dienstag_freitag"] = {
        "game_id":  "combo_dienstag_freitag",
        "label":    "Schein Di/Fr (Eurojackpot)",
        "n_fields": len(eur_fields),
        "fields":   eur_fields,
    }

    return {
        "recency_k":     recency_k,
        "schein":        out_blocks,
        "next_draws":    _next_draws(),
    }


def build_custom_schein(specs: Iterable[FieldSpec],
                        *, rng: random.Random | None = None) -> dict:
    """Generate a Spielschein from explicit per-field specs.

    Each FieldSpec describes one field (game + strategy). Several
    fields per game are allowed and ordered as given. Returns the
    same per-game block structure as ``build_optimal_schein`` so the
    UI can re-use the renderer.
    """
    rng = rng or random.Random()
    blocks: dict[str, dict] = {}
    for spec in specs:
        if spec.game not in GAMES:
            raise ValueError(f"unknown game {spec.game!r}")
        history = list(store.all_draws(spec.game))
        tip = _generate_field(spec.game, spec.strategy, history,
                              recency_k=spec.recency_k, rng=rng)
        tip["strategy_label"] = next(
            (s.label for s in strategies_for(spec.game, recency_k=spec.recency_k)
             if s.name == (spec.strategy or 'auto') or
             (spec.strategy in (None, '', 'auto') and s.name == 'recency_exclude')),
            spec.strategy or "auto",
        )
        blk = blocks.setdefault(spec.game, {
            "game_id":  spec.game,
            "n_fields": 0,
            "fields":   [],
        })
        blk["fields"].append(tip)
        blk["n_fields"] += 1
    return {"schein": blocks}


# --------------------------------------------------------------------------- #
# Next-draw helper (Europe/Berlin)
# --------------------------------------------------------------------------- #
def _next_draws() -> dict[str, str | None]:
    """Best-effort next draw date for each game in Europe/Berlin.

    We hard-code the official cut-off times:
      * Lotto / Spiel 77 / Super 6 — Wed 18:25 + Sat 18:25
      * Eurojackpot                — Tue 19:00 + Fri 19:00

    Output: ``{game_id: "YYYY-MM-DD HH:MM"}`` (UTC ISO).
    """
    import datetime as dt
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/Berlin")
    now = dt.datetime.now(tz)
    out: dict[str, str | None] = {}

    weekday_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
                   "fri": 4, "sat": 5, "sun": 6}
    cutoff_times = {
        "lotto-6aus49": dt.time(18, 25),
        "spiel77":      dt.time(18, 25),
        "super6":       dt.time(18, 25),
        "eurojackpot":  dt.time(19, 0),
    }
    for gid, g in GAMES.items():
        target_dows = {weekday_map[d] for d in g.draw_days}
        cutoff = cutoff_times.get(gid, dt.time(18, 25))
        best: dt.datetime | None = None
        for delta in range(0, 8):
            day = (now + dt.timedelta(days=delta)).date()
            if day.weekday() not in target_dows:
                continue
            cand = dt.datetime.combine(day, cutoff, tzinfo=tz)
            if cand > now:
                best = cand
                break
        out[gid] = best.astimezone(dt.timezone.utc).isoformat() if best else None
    return out

