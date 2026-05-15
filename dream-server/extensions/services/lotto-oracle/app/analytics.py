"""Empirical analytics on draw history.

Two purposes:

1.  ``recency_overlap_distribution()`` — for each lookback N (1, 2, 3, …)
    answer the user's question "wie oft kamen aus den letzten N Ziehungen
    1, 2, … Zahlen wieder?".  Pure observation on the historical archive,
    no Bayesian magic — just count how many draws at index i shared
    exactly k numbers / digit-positions with the union of draws
    [i+1 … i+N].  We surface this in the dashboard so the operator sees
    that the recency-exclude constraint is justified by data (or not).

2.  ``backtest_strategy()`` — replay every strategy across the most
    recent W=200 draws *as if it had been run before each draw* and
    measure the average overlap with the actually-drawn numbers /
    digits.  The result is a per-strategy ``score`` we use to sort the
    cards in the UI.  Sorting is best-effort — lotteries are random,
    so the differences are tiny, but a strategy whose backtest
    *consistently* beats the random baseline gets bumped to the top.

The whole module is deliberately allocation-light: 30 years × 2 draws/wk
≈ 3 200 rows, and most strategies are O(pool_size) per call, so the
backtest of 200 draws × 7 strategies × 3 rows runs in well under a
second on the Halo Strix.
"""
from __future__ import annotations

import logging
import math
import random
import statistics
from collections import Counter
from typing import Callable, Iterable

from .games import Game

log = logging.getLogger("lotto-oracle.analytics")


# Default window for per-strategy backtest.  Big enough to swamp single-
# draw noise, small enough that recomputing on every /tips/generate is
# free.  Operator can override via ``rows_per_strategy`` indirectly: more
# rows = more variance smoothed.
_BACKTEST_WINDOW = 200
_DEFAULT_LOOKBACKS = (1, 2, 3)


# ---------------------------------------------------------------------------
# Recency-overlap distribution
# ---------------------------------------------------------------------------
def recency_overlap_distribution(
    game: Game,
    history: list[dict],
    lookbacks: Iterable[int] = _DEFAULT_LOOKBACKS,
) -> dict:
    """Empirical distribution of "how many numbers/positions of draw[i]
    were also in the union of draws[i+1 … i+N]".

    Returns a dict shaped like::

        {
          "kind": "combinatorial",          # or "digit"
          "main_pool":     "Hauptzahlen",   # name of the pool the histogram describes
          "main_pool_pick": 6,
          "main_pool_size": 49,
          "n_history":     1234,
          "lookbacks": {
            "1": {
              "samples":   1233,
              "histogram": [{"k": 0, "count": 600, "prob": 0.487}, …],
              "mean":      0.61,
              "expected_random": 0.612,
              "p_at_least": [{"k": 1, "prob": 0.42}, {"k": 2, "prob": 0.10}, …],
            },
            "2": …, "3": …,
          },
        }

    For digit games ``main_pool*`` is replaced with ``digits`` and the
    histogram counts position-wise matches (how many of the 7 / 6 digits
    matched the same position in the recent draw set).
    """
    out: dict = {
        "kind":      game.kind,
        "n_history": len(history),
        "lookbacks": {},
    }

    if game.kind == "combinatorial":
        # Use the main pool only — bonus pools (Eurozahlen, Superzahl) have
        # different size and would muddy the histogram.
        p = game.pools[0]
        out["main_pool"]      = p.name
        out["main_pool_pick"] = p.pick
        out["main_pool_size"] = p.high - p.low + 1

        sequences = [h.get(p.name) or [] for h in history]
        hist_len = len(sequences)

        for N in lookbacks:
            counts: Counter = Counter()
            samples = 0
            for i in range(hist_len - N):  # need N draws AFTER i to look back from i's POV
                cur = set(sequences[i])
                if not cur:
                    continue
                prev_union: set = set()
                for j in range(i + 1, i + 1 + N):
                    prev_union |= set(sequences[j])
                if not prev_union:
                    continue
                overlap = len(cur & prev_union)
                counts[overlap] += 1
                samples += 1
            out["lookbacks"][str(N)] = _build_histogram(
                counts, samples, max_k=p.pick,
                expected_random=_expected_random_combinatorial(p, N),
            )

    else:
        # Digit game: per-position match count.
        digit_strs = [h.get("digits") or "" for h in history]
        out["digits"] = game.digits

        for N in lookbacks:
            counts: Counter = Counter()
            samples = 0
            for i in range(len(digit_strs) - N):
                cur = digit_strs[i]
                if len(cur) != game.digits:
                    continue
                prev = digit_strs[i + 1 : i + 1 + N]
                # Per position: did THIS digit appear in any of the prev N
                # draws at the *same* position?
                hits = 0
                for pos in range(game.digits):
                    cur_d = cur[pos]
                    if any(len(p) > pos and p[pos] == cur_d for p in prev):
                        hits += 1
                counts[hits] += 1
                samples += 1
            # Random baseline: per position 1 - (1 - 1/10)^N → expected hits =
            # game.digits * (1 - 0.9^N).
            expected = game.digits * (1.0 - (0.9 ** N))
            out["lookbacks"][str(N)] = _build_histogram(
                counts, samples, max_k=game.digits, expected_random=expected,
            )

    return out


def _expected_random_combinatorial(pool, N: int) -> float:
    """Expected overlap |A ∩ B| where A = current draw (size pick) and
    B = union of N independent past draws (size at most N*pick) inside a
    pool of K numbers.  Per-number P(in B) = 1 - C(K-pick, N*pick) / C(K, N*pick)
    — but since pick draws are without replacement *within* one draw,
    we simplify with the standard hypergeometric expectation:
    expected = pick * P(number in B).
    """
    K = pool.high - pool.low + 1
    pick = pool.pick
    # P(specific number NOT drawn in one draw) = C(K-1, pick) / C(K, pick) = (K-pick)/K
    p_not_in_one_draw = (K - pick) / K
    p_in_union = 1.0 - p_not_in_one_draw ** N
    return pick * p_in_union


def _build_histogram(counts: Counter, samples: int, *,
                     max_k: int, expected_random: float) -> dict:
    if samples == 0:
        return {
            "samples": 0, "histogram": [], "mean": None,
            "expected_random": round(expected_random, 4),
            "p_at_least": [],
        }
    hist = []
    for k in range(0, max_k + 1):
        c = counts.get(k, 0)
        hist.append({"k": k, "count": c, "prob": round(c / samples, 4)})
    mean = sum(k * c for k, c in counts.items()) / samples
    # P(overlap >= k) for k = 1 … max_k
    p_at_least = []
    cumulative = 0
    for k in range(max_k, 0, -1):
        cumulative += counts.get(k, 0)
        p_at_least.append({"k": k, "prob": round(cumulative / samples, 4)})
    p_at_least.reverse()
    return {
        "samples":         samples,
        "histogram":       hist,
        "mean":            round(mean, 3),
        "expected_random": round(expected_random, 3),
        "p_at_least":      p_at_least,
    }


# ---------------------------------------------------------------------------
# Per-strategy backtest
# ---------------------------------------------------------------------------
def backtest_strategy(
    game: Game,
    history: list[dict],
    strategy_fn: Callable,
    *,
    window: int = _BACKTEST_WINDOW,
    rows: int = 3,
    seed: int = 1234,
) -> dict:
    """Replay one strategy across the most recent ``window`` draws.

    For each historical draw at index i (newest at index 0), build a
    "past" history that contains only draws strictly after i (i.e. older
    than i in time), call the strategy with that past, then compare the
    generated tip(s) to the actual draw at i.

    Returns metrics:
      * ``n_trials`` — number of (draw, tip) comparisons
      * ``avg_match`` — mean number of matching items (main pool or digits)
      * ``expected_random`` — same metric for a uniform-random tip,
        computed analytically (so the comparison is an apples-to-apples
        edge measurement — no second backtest needed)
      * ``edge`` — avg_match - expected_random
      * ``hit_rates`` — list of {k, prob} for "tip matched ≥ k items"

    For combinatorial games the metric counts main-pool overlap; for digit
    games it counts position-equal digits.
    """
    rng = random.Random(seed)
    if not history:
        return _empty_backtest()

    if game.kind == "combinatorial":
        p = game.pools[0]
        max_k = p.pick
        expected_random = _expected_random_combinatorial(p, 1)  # vs ONE draw
    else:
        max_k = game.digits
        # Per-position prob of match = 1/10 → expected = digits * 0.1
        expected_random = game.digits * 0.1

    matches: list[int] = []
    upper = min(window, len(history) - 1)
    if upper <= 0:
        return _empty_backtest()

    for i in range(upper):
        actual = history[i]
        past = history[i + 1 :]
        try:
            tips = strategy_fn(game, past, rng, rows)
        except Exception as exc:  # noqa: BLE001
            log.warning("backtest strategy crashed at i=%d: %s", i, exc)
            continue
        for t in tips:
            matches.append(_match_count(game, t, actual))

    if not matches:
        return _empty_backtest()

    n = len(matches)
    avg = sum(matches) / n
    bins = [0] * (max_k + 2)
    for m in matches:
        bins[min(m, max_k)] += 1
    hit_rates = []
    cumulative = 0
    for k in range(max_k, 0, -1):
        cumulative += bins[k]
        hit_rates.append({"k": k, "prob": round(cumulative / n, 4)})
    hit_rates.reverse()

    return {
        "n_trials":         n,
        "window":           upper,
        "avg_match":        round(avg, 3),
        "expected_random":  round(expected_random, 3),
        "edge":             round(avg - expected_random, 3),
        "hit_rates":        hit_rates,
        "max_match_seen":   max(matches),
    }


def _empty_backtest() -> dict:
    return {
        "n_trials":        0, "window": 0, "avg_match": None,
        "expected_random": None, "edge": None,
        "hit_rates":       [], "max_match_seen": 0,
    }


def _match_count(game: Game, tip: dict, actual: dict) -> int:
    if game.kind == "combinatorial":
        p = game.pools[0]
        # tip / actual store sorted lists under pool name (or via "payload")
        tip_main    = tip.get(p.name) or (tip.get("payload") or {}).get(p.name) or []
        actual_main = actual.get(p.name) or []
        return len(set(tip_main) & set(actual_main))
    # digit game
    tip_digits = tip.get("digits") or (tip.get("payload") or {}).get("digits") or ""
    actual_digits = actual.get("digits") or ""
    if not tip_digits or not actual_digits:
        return 0
    return sum(1 for a, b in zip(tip_digits, actual_digits) if a == b)


# ---------------------------------------------------------------------------
# Convenience: score every strategy for one game
# ---------------------------------------------------------------------------
def score_all_strategies(
    game: Game,
    history: list[dict],
    strategies: list,
    *,
    window: int = _BACKTEST_WINDOW,
    rows: int = 3,
) -> dict:
    """Returns ``{strategy_name: backtest_result}``.  ``strategies`` is
    a list of objects with ``.name`` and ``.fn`` (i.e. the dataclass
    from ``strategies.Strategy``).
    """
    out: dict[str, dict] = {}
    for s in strategies:
        try:
            out[s.name] = backtest_strategy(game, history, s.fn,
                                            window=window, rows=rows)
        except Exception as exc:  # noqa: BLE001
            log.exception("score_all_strategies: %s crashed: %s", s.name, exc)
            out[s.name] = _empty_backtest()
    return out

