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


# ---------------------------------------------------------------------------
# Recency sweet-spot search
# ---------------------------------------------------------------------------
def recency_sweet_spot(
    game: Game,
    history: list[dict],
    make_strategy_for_k: Callable[[int], object],
    *,
    ks: Iterable[int] = (1, 2, 3, 4, 5),
    window: int = _BACKTEST_WINDOW,
    rows: int = 3,
) -> dict:
    """Backtest the recency_exclude strategy for several values of K and
    return per-K metrics plus the recommended sweet spot.

    "Sweet spot" = K with the highest backtested ``avg_match`` (ties
    broken in favour of *smaller* K, because every additional excluded
    draw needlessly forbids more candidate numbers).  For an i.i.d.
    lottery the differences are tiny, but the operator gets to see the
    actual empirical curve and pick consciously.

    ``make_strategy_for_k(k)`` should return a Strategy-like object with
    a ``.fn`` callable matching the ``backtest_strategy`` contract.
    """
    per_k: list[dict] = []
    best_k: int | None = None
    best_avg: float | None = None
    for k in ks:
        try:
            strat = make_strategy_for_k(int(k))
            res = backtest_strategy(game, history, strat.fn,
                                    window=window, rows=rows, seed=4321 + int(k))
        except Exception as exc:  # noqa: BLE001
            log.exception("recency_sweet_spot: K=%s crashed: %s", k, exc)
            res = _empty_backtest()
        avg = res.get("avg_match")
        per_k.append({
            "k":               int(k),
            "avg_match":       avg,
            "expected_random": res.get("expected_random"),
            "edge":            res.get("edge"),
            "n_trials":        res.get("n_trials"),
            "window":          res.get("window"),
        })
        if avg is not None and (best_avg is None or avg > best_avg + 1e-9):
            best_avg = avg
            best_k = int(k)
    return {
        "per_k":             per_k,
        "recommended_k":     best_k,
        "recommended_avg":   best_avg,
        "history_size":      len(history),
        "window":            min(window, max(0, len(history) - 1)),
    }


# ---------------------------------------------------------------------------
# Long-horizon jackpot backtest
# ---------------------------------------------------------------------------
# Approximate German lottery prize classes (only the classes that need a
# numerical match are listed; classes that depend on Superzahl etc. are
# handled separately below).  We use the per-pool main-match count as the
# canonical "class proxy":
#
#   Lotto 6 aus 49   — class 1 (jackpot) = 6 main + Superzahl
#                                   2     = 6 main without Superzahl
#                                   3     = 5 main + Superzahl
#                                   4     = 5 main
#                                   ...
#   Eurojackpot      — class 1 = 5 main + 2 Eurozahlen
#                                   2 = 5 main + 1 Eurozahl
#                                   3 = 5 main + 0 Eurozahlen
#                                   4 = 4 main + 2 Eurozahlen
#                                   ...
#   Spiel 77 / Super 6 — Endziffer-Kaskade von rechts;
#                        class 1 = volle Übereinstimmung
#                        class 2 = letzte n-1 Stellen
#                        usw.
#
# We surface n_class_1 and n_class_2 (plus a small "near-miss" tier) per
# strategy.  The dashboard turns this into "wäre in 10 Jahren X Mal ein
# Voll-/Hauptgewinn gewesen".
JACKPOT_BACKTEST_DEFAULT_YEARS = 10
# How far back we cap a single backtest run — 10 years × 2 draws/wk ≈ 1040
# trials per strategy. With 8 strategies and 1 tip per strategy that's
# ~8000 comparisons, < 1 second on the Halo Strix.
JACKPOT_BACKTEST_MAX_TRIALS = 1100


def _spiel_endziffer_class(tip_digits: str, actual_digits: str) -> int:
    """Spiel 77 / Super 6: zähle die rechts-bündige Anzahl gleicher
    Endziffern (full match → klasse 1, n-1 → klasse 2, …, 0 → keine
    Klasse). Wir liefern die *Anzahl gleicher Endziffern* zurück; die
    UI mappt das auf die Klasse (Anzahl == n → Klasse 1, == n-1 →
    Klasse 2, etc.).
    """
    if not tip_digits or not actual_digits or len(tip_digits) != len(actual_digits):
        return 0
    cnt = 0
    for a, b in zip(reversed(tip_digits), reversed(actual_digits)):
        if a == b:
            cnt += 1
        else:
            break
    return cnt


def _classify_combinatorial(game: Game, tip: dict, actual: dict) -> tuple[int, int]:
    """Returns ``(main_hits, bonus_hits)`` for a combinatorial game."""
    main = game.pools[0]
    bonus = game.pools[1] if len(game.pools) > 1 else None
    tip_main = tip.get(main.name) or (tip.get("payload") or {}).get(main.name) or []
    actual_main = actual.get(main.name) or []
    main_hits = len(set(tip_main) & set(actual_main))
    bonus_hits = 0
    if bonus:
        tip_bonus = tip.get(bonus.name) or (tip.get("payload") or {}).get(bonus.name) or []
        actual_bonus = actual.get(bonus.name) or []
        bonus_hits = len(set(tip_bonus) & set(actual_bonus))
    return main_hits, bonus_hits


def jackpot_backtest_strategy(
    game: Game,
    history: list[dict],
    strategy_fn: Callable,
    *,
    years: int = JACKPOT_BACKTEST_DEFAULT_YEARS,
    rows: int = 1,
    seed: int = 9001,
) -> dict:
    """For one strategy, replay the last ``years`` years of draws and
    count, for every draw, whether the generated tip would have hit
    each prize tier.

    Returns::

        {
          "n_trials":     1040,
          "years":        10,
          "window":       1040,
          "tier_counts":  [
            {"key": "class_1", "label": "Hauptgewinn (Klasse 1)", "count": 0},
            {"key": "class_2", "label": "Klasse 2", "count": 0},
            {"key": "class_3", "label": "Klasse 3", "count": 3},
            ...
          ],
          "best_match":   {"main": 4, "bonus": 1, "draw_date": "2021-...", "value": "06 12 ..."},
        }

    Tiers depend on game.kind:
      * combinatorial — (main_hits, bonus_hits) cascaded to prize classes
        (table inside ``_combo_class``).  Per draw we count whichever tier
        the tip reached (or "miss" if it didn't meet any pay-out class).
      * digit — Endziffer-Übereinstimmung (rechts-bündig) → cnt == digits
        => class 1, cnt == digits-1 => class 2, …, cnt == 0 => miss.
    """
    rng = random.Random(seed)
    if not history:
        return {"n_trials": 0, "years": years, "window": 0,
                "tier_counts": [], "best_match": None}

    upper = min(JACKPOT_BACKTEST_MAX_TRIALS, len(history) - 1,
                years * 110)  # ~110 draws/year is the upper bound (lotto + eurojackpot 2x/wk)
    if upper <= 0:
        return {"n_trials": 0, "years": years, "window": 0,
                "tier_counts": [], "best_match": None}

    tier_counts: Counter = Counter()
    best: dict | None = None

    for i in range(upper):
        actual = history[i]
        past = history[i + 1:]
        try:
            tips = strategy_fn(game, past, rng, rows)
        except Exception as exc:  # noqa: BLE001
            log.warning("jackpot backtest strategy crashed at i=%d: %s", i, exc)
            continue
        for t in tips:
            if game.kind == "combinatorial":
                main_hits, bonus_hits = _classify_combinatorial(game, t, actual)
                cls = _combo_class(game, main_hits, bonus_hits)
                if cls:
                    tier_counts[cls] += 1
                # Track best
                score = main_hits * 10 + bonus_hits
                if not best or score > best.get("_score", -1):
                    best = {
                        "_score":     score,
                        "main":       main_hits,
                        "bonus":      bonus_hits,
                        "draw_date":  actual.get("draw_date"),
                        "class":      cls or "—",
                    }
            else:
                tip_d = t.get("digits") or (t.get("payload") or {}).get("digits") or ""
                cnt = _spiel_endziffer_class(tip_d, actual.get("digits") or "")
                if cnt > 0:
                    cls = f"class_{game.digits - cnt + 1}"
                    tier_counts[cls] += 1
                if not best or cnt > best.get("_score", -1):
                    best = {
                        "_score":     cnt,
                        "matches":    cnt,
                        "draw_date":  actual.get("draw_date"),
                        "class":      f"class_{game.digits - cnt + 1}" if cnt > 0 else "—",
                    }

    if best:
        best.pop("_score", None)
    return {
        "n_trials":    upper * rows,
        "years":       years,
        "window":      upper,
        "tier_counts": _format_tier_counts(game, tier_counts),
        "best_match":  best,
    }


# Combinatorial prize-class mapping (proxy table — real prizes also depend
# on # of winners, but this is good enough for "would I have won?").
def _combo_class(game: Game, main: int, bonus: int) -> str | None:
    if game.id == "lotto-6aus49":
        # main is over 6/49, bonus is Superzahl (1 of 10)
        if main == 6 and bonus == 1: return "class_1"
        if main == 6:                return "class_2"
        if main == 5 and bonus == 1: return "class_3"
        if main == 5:                return "class_4"
        if main == 4 and bonus == 1: return "class_5"
        if main == 4:                return "class_6"
        if main == 3 and bonus == 1: return "class_7"
        if main == 3:                return "class_8"
        if main == 2 and bonus == 1: return "class_9"
        return None
    if game.id == "eurojackpot":
        # main over 5/50, bonus over 2/12
        if main == 5 and bonus == 2: return "class_1"
        if main == 5 and bonus == 1: return "class_2"
        if main == 5:                return "class_3"
        if main == 4 and bonus == 2: return "class_4"
        if main == 4 and bonus == 1: return "class_5"
        if main == 3 and bonus == 2: return "class_6"
        if main == 4:                return "class_7"
        if main == 2 and bonus == 2: return "class_8"
        if main == 3 and bonus == 1: return "class_9"
        if main == 3:                return "class_10"
        if main == 1 and bonus == 2: return "class_11"
        if main == 2 and bonus == 1: return "class_12"
        return None
    return None


_TIER_LABELS = {
    "lotto-6aus49": {
        "class_1": "Klasse 1 (Jackpot 6 + Superzahl)",
        "class_2": "Klasse 2 (6 Richtige)",
        "class_3": "Klasse 3 (5 + Superzahl)",
        "class_4": "Klasse 4 (5 Richtige)",
        "class_5": "Klasse 5 (4 + Superzahl)",
        "class_6": "Klasse 6 (4 Richtige)",
        "class_7": "Klasse 7 (3 + Superzahl)",
        "class_8": "Klasse 8 (3 Richtige)",
        "class_9": "Klasse 9 (2 + Superzahl)",
    },
    "eurojackpot": {
        "class_1":  "Klasse 1 (Jackpot 5 + 2)",
        "class_2":  "Klasse 2 (5 + 1)",
        "class_3":  "Klasse 3 (5 + 0)",
        "class_4":  "Klasse 4 (4 + 2)",
        "class_5":  "Klasse 5 (4 + 1)",
        "class_6":  "Klasse 6 (3 + 2)",
        "class_7":  "Klasse 7 (4 + 0)",
        "class_8":  "Klasse 8 (2 + 2)",
        "class_9":  "Klasse 9 (3 + 1)",
        "class_10": "Klasse 10 (3 + 0)",
        "class_11": "Klasse 11 (1 + 2)",
        "class_12": "Klasse 12 (2 + 1)",
    },
}


def _format_tier_counts(game: Game, counts: Counter) -> list[dict]:
    if game.kind == "digit":
        # class_1 = volle Übereinstimmung, class_n = letzte (digits-n+1) Endziffern
        out = []
        for n in range(1, game.digits + 1):
            key = f"class_{n}"
            matched = game.digits - n + 1
            label = (f"Klasse {n} – letzte {matched} Endziffer{'' if matched == 1 else 'n'}"
                     if n > 1 else f"Klasse {n} (Voll-Treffer · alle {game.digits} Stellen)")
            out.append({"key": key, "label": label, "count": counts.get(key, 0)})
        return out
    labels = _TIER_LABELS.get(game.id, {})
    return [
        {"key": k, "label": labels.get(k, k), "count": c}
        for k, c in sorted(counts.items(), key=lambda kv: kv[0])
    ]


def jackpot_backtest_all(
    game: Game,
    history: list[dict],
    strategies: list,
    *,
    years: int = JACKPOT_BACKTEST_DEFAULT_YEARS,
    rows: int = 1,
) -> dict:
    """Run ``jackpot_backtest_strategy`` for every strategy and return
    ``{strategy_name: result}`` plus a summary block.
    """
    per_strategy: dict[str, dict] = {}
    for s in strategies:
        try:
            per_strategy[s.name] = jackpot_backtest_strategy(
                game, history, s.fn, years=years, rows=rows)
        except Exception as exc:  # noqa: BLE001
            log.exception("jackpot_backtest_all: %s crashed: %s", s.name, exc)
            per_strategy[s.name] = {"n_trials": 0, "tier_counts": [], "best_match": None}
    return {
        "years":         years,
        "rows":          rows,
        "history_size":  len(history),
        "per_strategy":  per_strategy,
    }


