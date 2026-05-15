"""Tip-generation strategies.

Each strategy reads the historical draws for a game and emits one or
more suggested tips. A tip is shaped exactly like a draw payload (so the
storage layer can persist them with the same schema).

Per the user's spec:
  * Tips MUST change after every new draw — strategies that take the
    most recent draws into account satisfy this naturally. The
    ``recency_exclude`` strategy is the strongest such guarantor: it
    refuses to recommend any number that appeared in the last K draws.
  * Whether to exclude very low numbers (1 / 2 / 3) is left to the
    engine — the ``balanced`` strategy enforces a minimum sum so it
    auto-avoids "all small" combinations; ``anti_pattern`` rejects
    consecutive runs and date-only tips (≤ 31). The plain ``frequency``
    and ``random_uniform`` strategies do *not* censor low numbers
    because that would bias against statistically valid combinations.

For digit games (Spiel 77 / Super 6) the same strategies are applied
*per digit position*: the previous draw's digits are excluded for the
recency strategy, frequency is computed per position, etc.
"""
from __future__ import annotations

import logging
import math
import random
import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

from .games import GAMES, Game, Pool

log = logging.getLogger("lotto-oracle.strategies")


# --------------------------------------------------------------------------- #
# Strategy descriptor
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Strategy:
    name: str
    label: str
    description: str
    # Function: (game, history) -> list[Tip]
    fn: Callable
    # How many tip rows this strategy emits per call (after default
    # tips_per_strategy multiplier).
    rows: int = 2


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _format_combinatorial(g: Game, pool_values: dict[str, list[int]]) -> tuple[dict, str]:
    payload = {p.name: sorted(pool_values[p.name]) for p in g.pools}
    parts = []
    for p in g.pools:
        nums = " ".join(f"{n:02d}" if p.high >= 10 else str(n) for n in payload[p.name])
        parts.append(f"{p.name}: {nums}")
    return payload, " | ".join(parts)


def _format_digits(digits: str) -> tuple[dict, str]:
    return {"digits": digits}, digits


def _pool_history(history: list[dict], pool_name: str) -> list[list[int]]:
    """List of past draws restricted to one pool, newest first."""
    out = []
    for h in history:
        v = h.get(pool_name)
        if isinstance(v, list):
            out.append(v)
    return out


def _digit_history(history: list[dict]) -> list[str]:
    out = []
    for h in history:
        d = h.get("digits")
        if isinstance(d, str):
            out.append(d)
    return out


def _weighted_sample(rng: random.Random, weights: dict[int, float], k: int,
                     forbidden: set[int] | None = None) -> list[int]:
    """Sample k *unique* integers from `weights` proportional to their weight."""
    forbidden = forbidden or set()
    candidates = {n: max(w, 1e-9) for n, w in weights.items() if n not in forbidden}
    chosen: list[int] = []
    while len(chosen) < k and candidates:
        total = sum(candidates.values())
        r = rng.random() * total
        acc = 0.0
        pick = None
        for n, w in candidates.items():
            acc += w
            if r <= acc:
                pick = n
                break
        if pick is None:
            pick = next(iter(candidates))
        chosen.append(pick)
        del candidates[pick]
    return sorted(chosen)


# --------------------------------------------------------------------------- #
# Combinatorial strategies (Lotto 6aus49, Eurojackpot)
# --------------------------------------------------------------------------- #
def _strat_recency_exclude(g: Game, history: list[dict], *, rng: random.Random,
                           rows: int, exclude_last_k: int = 1) -> list[dict]:
    """Forbid every number drawn in the last K draws → tip *must* differ
    from the most recent draw(s). This is the user's primary requirement
    ("die Zahlen von der letzten Ziehung sehr unwahrscheinlich in der
    nächsten") implemented as a hard constraint.
    """
    out = []
    for _ in range(rows):
        pool_values: dict[str, list[int]] = {}
        rationale_parts = []
        for p in g.pools:
            past = _pool_history(history, p.name)[:exclude_last_k]
            forbidden = {n for draw in past for n in draw}
            available = [n for n in range(p.low, p.high + 1) if n not in forbidden]
            need = p.pick
            if len(available) < need:
                # Pool too small to honour the constraint — relax.
                available = list(range(p.low, p.high + 1))
                rationale_parts.append(f"{p.name}: Constraint relaxiert (Pool zu klein)")
            else:
                rationale_parts.append(
                    f"{p.name}: {len(forbidden)} Zahlen aus letzten {exclude_last_k} Ziehung(en) ausgeschlossen"
                )
            pool_values[p.name] = sorted(rng.sample(available, need))
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  "recency_exclude",
            "payload":   payload,
            "display":   display,
            "rationale": " · ".join(rationale_parts),
        })
    return out


def _strat_frequency_weighted(g: Game, history: list[dict], *, rng: random.Random,
                              rows: int, hot: bool) -> list[dict]:
    """Sample weighted by historical frequency.

    hot=True  → favour numbers that came up often ("hot")
    hot=False → favour numbers that came up rarely ("cold / due")

    Ignores the very-recent constraint deliberately (so it complements
    recency_exclude — it's a different statistical narrative).
    """
    out = []
    name = "frequency_hot" if hot else "frequency_cold"
    for _ in range(rows):
        pool_values: dict[str, list[int]] = {}
        rationale_parts = []
        for p in g.pools:
            counts = Counter()
            for draw in _pool_history(history, p.name):
                counts.update(draw)
            total_draws = max(len(_pool_history(history, p.name)), 1)
            base_weight = total_draws * (p.pick / (p.high - p.low + 1))
            weights: dict[int, float] = {}
            for n in range(p.low, p.high + 1):
                c = counts.get(n, 0)
                if hot:
                    weights[n] = max(c, 0.1)
                else:
                    # Cold: how much under the expected count.
                    weights[n] = max(base_weight - c + 0.1, 0.1)
            pool_values[p.name] = _weighted_sample(rng, weights, p.pick)
            rationale_parts.append(
                f"{p.name}: gewichtet {'hot' if hot else 'cold'} über {total_draws} Ziehung(en)"
            )
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  name,
            "payload":   payload,
            "display":   display,
            "rationale": " · ".join(rationale_parts),
        })
    return out


def _strat_gap_due(g: Game, history: list[dict], *, rng: random.Random,
                   rows: int) -> list[dict]:
    """Pick numbers with the longest current "absence streak".

    Conceptually similar to frequency_cold but uses *current gap* rather
    than aggregate frequency. Defensible reasoning: independent draws
    give every number the same probability per round, but the empirical
    distribution of "how long has it been absent?" is well-defined and a
    common Lotto-magazine heuristic. We surface it so the user can pick
    consciously.
    """
    out = []
    for _ in range(rows):
        pool_values: dict[str, list[int]] = {}
        rationale_parts = []
        for p in g.pools:
            past = _pool_history(history, p.name)
            gaps: dict[int, int] = {n: len(past) for n in range(p.low, p.high + 1)}
            for i, draw in enumerate(past):
                for n in draw:
                    if gaps[n] == len(past):
                        gaps[n] = i
            # Take the top (3 × pick) longest gaps and sample randomly
            # within them so consecutive runs still vary per row.
            ranked = sorted(gaps.items(), key=lambda kv: -kv[1])
            shortlist = [n for n, _ in ranked[:max(p.pick * 3, p.pick + 5)]]
            pool_values[p.name] = sorted(rng.sample(shortlist, p.pick))
            avg_gap = statistics.mean(g_ for n, g_ in ranked[:p.pick])
            rationale_parts.append(f"{p.name}: ⌀ Gap der Auswahl ≈ {avg_gap:.0f} Ziehungen")
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  "gap_due",
            "payload":   payload,
            "display":   display,
            "rationale": " · ".join(rationale_parts),
        })
    return out


def _strat_balanced(g: Game, history: list[dict], *, rng: random.Random,
                    rows: int) -> list[dict]:
    """Constraint-satisfying random tip:

      - even/odd ratio close to 50 / 50
      - sum of main pool inside the empirical IQR of historical sums
      - no three-in-a-row
      - never all numbers ≤ 31 (so it's not "just dates")
      - excludes the most recent draw's numbers (varies after each draw)
    """
    out = []
    for _ in range(rows):
        pool_values: dict[str, list[int]] = {}
        rationale_parts = []
        for i, p in enumerate(g.pools):
            past = _pool_history(history, p.name)
            sums = [sum(d) for d in past] or [p.pick * (p.low + p.high) // 2]
            target_lo = statistics.quantiles(sums, n=4)[0] if len(sums) >= 4 else min(sums)
            target_hi = statistics.quantiles(sums, n=4)[2] if len(sums) >= 4 else max(sums)
            forbidden = set(past[0]) if past else set()
            attempts = 0
            chosen: list[int] = []
            while attempts < 800:
                attempts += 1
                pool = [n for n in range(p.low, p.high + 1) if n not in forbidden]
                pick = sorted(rng.sample(pool, p.pick))
                if i == 0 and g.id in {"lotto-6aus49", "eurojackpot"} and p.pick >= 5:
                    s = sum(pick)
                    if not (target_lo <= s <= target_hi):
                        continue
                    odd = sum(1 for n in pick if n % 2)
                    if not (p.pick // 3 <= odd <= p.pick - p.pick // 3):
                        continue
                    if any(b - a == 1 and c - b == 1 for a, b, c in zip(pick, pick[1:], pick[2:])):
                        continue
                    if all(n <= 31 for n in pick):
                        continue
                chosen = pick
                break
            if not chosen:
                chosen = sorted(rng.sample(
                    [n for n in range(p.low, p.high + 1) if n not in forbidden] or list(range(p.low, p.high + 1)),
                    p.pick,
                ))
            pool_values[p.name] = chosen
            if i == 0:
                rationale_parts.append(
                    f"{p.name}: Summe∈[{int(target_lo)},{int(target_hi)}], "
                    "even/odd-balanciert, ≥1 Zahl >31, keine 3er-Sequenz"
                )
            else:
                rationale_parts.append(f"{p.name}: zufällig (excl. letzte Ziehung)")
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  "balanced",
            "payload":   payload,
            "display":   display,
            "rationale": " · ".join(rationale_parts),
        })
    return out


def _strat_anti_pattern(g: Game, history: list[dict], *, rng: random.Random,
                        rows: int) -> list[dict]:
    """Avoid combinations that *humans* love → reduces share of jackpot
    if you *do* hit. Excludes:

      - any tip where every number ≤ 31 (date-only)
      - arithmetic progressions (1,2,3,4,5,6 / 7,14,21,28,35,42 / etc.)
      - fully on a single grid row of the German Spielschein
        (rows of 7 numbers)
    Constraint applies only to the main pool; bonus pools are random.
    """
    rows_grid = [set(range(start, start + 7)) for start in range(1, 50, 7)]
    out = []
    for _ in range(rows):
        pool_values: dict[str, list[int]] = {}
        rationale_parts = []
        for i, p in enumerate(g.pools):
            past = _pool_history(history, p.name)
            forbidden = set(past[0]) if past else set()
            attempts = 0
            chosen: list[int] = []
            while attempts < 500:
                attempts += 1
                pool = [n for n in range(p.low, p.high + 1) if n not in forbidden]
                pick = sorted(rng.sample(pool, p.pick))
                if i == 0 and p.pick >= 5:
                    if all(n <= 31 for n in pick):
                        continue
                    diffs = {b - a for a, b in zip(pick, pick[1:])}
                    if len(diffs) == 1:           # arithmetic progression
                        continue
                    if any(set(pick).issubset(rg) for rg in rows_grid):
                        continue
                chosen = pick
                break
            if not chosen:
                chosen = sorted(rng.sample(list(range(p.low, p.high + 1)), p.pick))
            pool_values[p.name] = chosen
            if i == 0:
                rationale_parts.append(
                    f"{p.name}: Anti-Beliebtheits-Filter (keine Datums-only, "
                    "keine arithm. Folge, keine Schein-Reihe)"
                )
            else:
                rationale_parts.append(f"{p.name}: zufällig (excl. letzte Ziehung)")
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  "anti_pattern",
            "payload":   payload,
            "display":   display,
            "rationale": " · ".join(rationale_parts),
        })
    return out


def _strat_random_uniform(g: Game, history: list[dict], *, rng: random.Random,
                          rows: int) -> list[dict]:
    """Truly uniform sample — provided as a baseline for the user to
    compare against the heuristic strategies.
    """
    out = []
    for _ in range(rows):
        pool_values = {p.name: sorted(rng.sample(list(range(p.low, p.high + 1)), p.pick))
                       for p in g.pools}
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  "random_uniform",
            "payload":   payload,
            "display":   display,
            "rationale": "Baseline: gleichverteilte Zufallsziehung ohne Constraints",
        })
    return out


# --------------------------------------------------------------------------- #
# Digit-game strategies (Spiel 77 / Super 6)
# --------------------------------------------------------------------------- #
def _digit_strat_recency_exclude(g: Game, history: list[dict], *, rng: random.Random,
                                 rows: int) -> list[dict]:
    """For each digit position, pick a digit different from the previous
    draw's digit at that position (10 → 9 candidates per position).
    """
    out = []
    last_digits = (_digit_history(history) or [None])[0]
    for _ in range(rows):
        digits = []
        for pos in range(g.digits):
            forbidden = {int(last_digits[pos])} if last_digits else set()
            choices = [d for d in range(10) if d not in forbidden]
            digits.append(str(rng.choice(choices)))
        payload, display = _format_digits("".join(digits))
        out.append({
            "strategy":  "recency_exclude",
            "payload":   payload,
            "display":   display,
            "rationale": ("Pro Position andere Ziffer als die letzte Ziehung"
                          if last_digits else "Keine vorherige Ziehung — uniform"),
        })
    return out


def _digit_strat_frequency(g: Game, history: list[dict], *, rng: random.Random,
                           rows: int, hot: bool) -> list[dict]:
    out = []
    history_strs = _digit_history(history)
    name = "frequency_hot" if hot else "frequency_cold"
    for _ in range(rows):
        digits = []
        for pos in range(g.digits):
            counts = Counter(s[pos] for s in history_strs if len(s) > pos)
            n_total = sum(counts.values()) or 1
            weights: dict[int, float] = {}
            for d in range(10):
                c = counts.get(str(d), 0)
                if hot:
                    weights[d] = max(c, 0.1)
                else:
                    weights[d] = max(n_total / 10 - c + 0.1, 0.1)
            digits.append(str(_weighted_sample(rng, weights, 1)[0]))
        payload, display = _format_digits("".join(digits))
        out.append({
            "strategy":  name,
            "payload":   payload,
            "display":   display,
            "rationale": f"Pro Position {'häufigste' if hot else 'seltenste'} Ziffer (gewichtet)",
        })
    return out


def _digit_strat_random_uniform(g: Game, history: list[dict], *, rng: random.Random,
                                rows: int) -> list[dict]:
    out = []
    for _ in range(rows):
        digits = "".join(str(rng.randint(0, 9)) for _ in range(g.digits))
        payload, display = _format_digits(digits)
        out.append({
            "strategy":  "random_uniform",
            "payload":   payload,
            "display":   display,
            "rationale": "Baseline: 7 unabhängige uniform-zufällige Ziffern",
        })
    return out


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
COMBINATORIAL_STRATEGIES: list[Strategy] = [
    Strategy("recency_exclude", "Letzte Ziehung ausgeschlossen",
             "Garantiert keine Zahl aus den jüngsten Ziehungen — Tipps ändern sich nach jeder Ziehung.",
             lambda g, h, rng, rows: _strat_recency_exclude(g, h, rng=rng, rows=rows, exclude_last_k=1)),
    Strategy("frequency_hot", "Hot Numbers",
             "Häufiger gezogene Zahlen werden bevorzugt (ohne Recency-Filter).",
             lambda g, h, rng, rows: _strat_frequency_weighted(g, h, rng=rng, rows=rows, hot=True)),
    Strategy("frequency_cold", "Cold / Due",
             "Selten gezogene Zahlen werden bevorzugt (Gegenstrategie zu Hot).",
             lambda g, h, rng, rows: _strat_frequency_weighted(g, h, rng=rng, rows=rows, hot=False)),
    Strategy("gap_due", "Lange Pause",
             "Zahlen mit dem aktuell längsten Abstand seit der letzten Ziehung.",
             lambda g, h, rng, rows: _strat_gap_due(g, h, rng=rng, rows=rows)),
    Strategy("balanced", "Balanced",
             "Even/Odd-Mix, plausible Summe, ≥1 Zahl >31, keine 3er-Folge — und ohne letzte Ziehung.",
             lambda g, h, rng, rows: _strat_balanced(g, h, rng=rng, rows=rows)),
    Strategy("anti_pattern", "Anti-Massenmuster",
             "Vermeidet Tipps, die viele Spieler abgeben (Datums-only, arithm. Folgen, Scheinreihen).",
             lambda g, h, rng, rows: _strat_anti_pattern(g, h, rng=rng, rows=rows)),
    Strategy("random_uniform", "Zufall (Baseline)",
             "Reine Gleichverteilung — als Vergleichswert.",
             lambda g, h, rng, rows: _strat_random_uniform(g, h, rng=rng, rows=rows)),
]

DIGIT_STRATEGIES: list[Strategy] = [
    Strategy("recency_exclude", "Letzte Ziehung ausgeschlossen",
             "Jede Position erhält eine andere Ziffer als die letzte Ziehung.",
             lambda g, h, rng, rows: _digit_strat_recency_exclude(g, h, rng=rng, rows=rows)),
    Strategy("frequency_hot", "Hot per Position",
             "Häufigste Ziffer pro Position (gewichtet).",
             lambda g, h, rng, rows: _digit_strat_frequency(g, h, rng=rng, rows=rows, hot=True)),
    Strategy("frequency_cold", "Cold per Position",
             "Seltenste Ziffer pro Position (gewichtet).",
             lambda g, h, rng, rows: _digit_strat_frequency(g, h, rng=rng, rows=rows, hot=False)),
    Strategy("random_uniform", "Zufall (Baseline)",
             "10⁷ bzw. 10⁶ gleichverteilt.",
             lambda g, h, rng, rows: _digit_strat_random_uniform(g, h, rng=rng, rows=rows)),
]


def strategies_for(game_id: str) -> list[Strategy]:
    g = GAMES[game_id]
    return DIGIT_STRATEGIES if g.kind == "digit" else COMBINATORIAL_STRATEGIES


def generate_tips(game_id: str, history: list[dict],
                  *, rows_per_strategy: int = 2,
                  rng: random.Random | None = None) -> list[dict]:
    """Run every strategy and return a flat list of tip dicts."""
    g = GAMES[game_id]
    rng = rng or random.Random()
    tips: list[dict] = []
    for s in strategies_for(game_id):
        try:
            tips.extend(s.fn(g, history, rng, rows_per_strategy))
        except Exception as exc:  # noqa: BLE001
            log.exception("strategy %s for %s crashed: %s", s.name, game_id, exc)
    return tips


def list_strategies(game_id: str) -> list[dict]:
    return [
        {"name": s.name, "label": s.label, "description": s.description}
        for s in strategies_for(game_id)
    ]

