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


def _strat_meta_combo(g: Game, history: list[dict], *, rng: random.Random,
                      rows: int, exclude_last_k: int = 1) -> list[dict]:
    """Top-Strategie: kaskadiert die stärksten Constraints in einem Pass.

    Für den Hauptpool werden gleichzeitig erzwungen:
      * recency_exclude  — keine Zahl aus den letzten K Ziehungen
      * balanced         — Summe ∈ IQR der historischen Summen,
                            Even/Odd-Mix, keine 3-er-Sequenz, ≥1 Zahl >31
      * anti_pattern     — keine arithm. Folge, keine Schein-Reihe (1–7, 8–14, …)
      * (history-guard wird automatisch via Post-Filter angewendet)

    Bonuspools (Superzahl / Eurozahlen) erhalten ``recency_exclude``
    ohne Soft-Constraints — der Pool ist zu klein für sinnvolle Regeln.

    Statistisch ist jedes Lotto iid, also keine Verschiebung des
    Erwartungswerts; was sich verschiebt ist die *Anteilsquote*
    (geringere Überlappung mit beliebten Tipps → höherer Jackpot-Anteil,
    falls man trifft) und das Risiko-Profil (keine Random-Ausreißer).
    """
    rows_grid = [set(range(start, start + 7)) for start in range(1, 50, 7)]
    out = []
    for _ in range(rows):
        pool_values: dict[str, list[int]] = {}
        rationale_parts = []
        for i, p in enumerate(g.pools):
            past = _pool_history(history, p.name)
            past_k = past[:exclude_last_k]
            forbidden = {n for draw in past_k for n in draw}
            sums = [sum(d) for d in past] or [p.pick * (p.low + p.high) // 2]
            target_lo = statistics.quantiles(sums, n=4)[0] if len(sums) >= 4 else min(sums)
            target_hi = statistics.quantiles(sums, n=4)[2] if len(sums) >= 4 else max(sums)
            attempts = 0
            chosen: list[int] = []
            relaxed = False
            while attempts < 1500:
                attempts += 1
                pool = [n for n in range(p.low, p.high + 1) if n not in forbidden]
                if len(pool) < p.pick:
                    pool = list(range(p.low, p.high + 1))
                    relaxed = True
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
                    diffs = {b - a for a, b in zip(pick, pick[1:])}
                    if len(diffs) == 1:
                        continue
                    if any(set(pick).issubset(rg) for rg in rows_grid):
                        continue
                chosen = pick
                break
            if not chosen:
                pool = [n for n in range(p.low, p.high + 1) if n not in forbidden] \
                       or list(range(p.low, p.high + 1))
                chosen = sorted(rng.sample(pool, p.pick))
                relaxed = True
            pool_values[p.name] = chosen
            if i == 0 and p.pick >= 5:
                rationale_parts.append(
                    f"{p.name}: recency+balanced+anti-pattern kaskadiert "
                    f"(Summe∈[{int(target_lo)},{int(target_hi)}], even/odd, "
                    f"≥1 Zahl >31, keine 3er-Folge, keine Scheinreihe)"
                    + (" — relaxed" if relaxed else ""),
                )
            else:
                rationale_parts.append(
                    f"{p.name}: recency_exclude (letzte {exclude_last_k} Ziehung(en) verboten)"
                    + (" — relaxed" if relaxed else ""),
                )
        payload, display = _format_combinatorial(g, pool_values)
        out.append({
            "strategy":  "meta_combo",
            "payload":   payload,
            "display":   display,
            "rationale": " · ".join(rationale_parts),
        })
    return out


# --------------------------------------------------------------------------- #
# Digit-game strategies (Spiel 77 / Super 6)
# --------------------------------------------------------------------------- #
def _digit_strat_recency_exclude(g: Game, history: list[dict], *, rng: random.Random,
                                 rows: int, exclude_last_k: int = 1) -> list[dict]:
    """For each digit position, pick a digit different from the previous
    K draws' digits at that position (10 → up to ``10 - K`` candidates).
    With K=1 this behaves like the classic "letzte Ziehung ausschließen"
    rule; higher K rotates digits more aggressively.
    """
    out = []
    history_strs = _digit_history(history)[:exclude_last_k]
    for _ in range(rows):
        digits = []
        relax_count = 0
        for pos in range(g.digits):
            forbidden = {int(s[pos]) for s in history_strs if len(s) > pos}
            choices = [d for d in range(10) if d not in forbidden]
            if not choices:
                # All 10 digits already used in last K draws → relax.
                choices = list(range(10))
                relax_count += 1
            digits.append(str(rng.choice(choices)))
        payload, display = _format_digits("".join(digits))
        out.append({
            "strategy":  "recency_exclude",
            "payload":   payload,
            "display":   display,
            "rationale": (
                (f"Pro Position andere Ziffer als die letzten {exclude_last_k} "
                 f"Ziehung(en)"
                 f"{' (' + str(relax_count) + ' Position(en) relaxed)' if relax_count else ''}")
                if history_strs else "Keine vorherige Ziehung — uniform"),
        })
    return out


def _digit_strat_last_digit_recency(g: Game, history: list[dict], *, rng: random.Random,
                                    rows: int) -> list[dict]:
    """User-requested: the **last (rightmost) digit** of the Losnummer /
    Spielscheinnummer is the actual Gewinnklasse-7-Marker bei Spiel 77
    (Endziffer-Übereinstimmung) — und auch bei Super 6 wird von rechts
    nach links gezählt. Wir variieren also die rechte Endziffer als die
    "wertvollste" Position: sie wird aus dem Komplement der letzten K=5
    Ziehungen gezogen, die restlichen Positionen bleiben uniform.
    """
    out = []
    last_digit_history = [int(s[-1]) for s in _digit_history(history)[:5] if s]
    for _ in range(rows):
        forbidden_last = set(last_digit_history)
        last_choices = [d for d in range(10) if d not in forbidden_last]
        if not last_choices:
            last_choices = list(range(10))
        digits = [str(rng.randint(0, 9)) for _ in range(g.digits - 1)]
        digits.append(str(rng.choice(last_choices)))
        payload, display = _format_digits("".join(digits))
        out.append({
            "strategy":  "last_digit_recency",
            "payload":   payload,
            "display":   display,
            "rationale": (f"Endziffer ≠ Endziffer(n) der letzten {len(last_digit_history)} "
                          "Ziehung(en) — bei Spiel 77 entscheidet die rechte Endziffer "
                          "über Gewinnklasse 7; restliche Positionen zufällig."
                          if last_digit_history else
                          "Keine vorherige Ziehung — alle Positionen uniform"),
        })
    return out


def _digit_strat_unique_history(g: Game, history: list[dict], *, rng: random.Random,
                                rows: int) -> list[dict]:
    """User-requested: bei Spiel 77 (10⁷ Kombinationen) und Super 6 (10⁶)
    wurde noch nie eine Ziehung exakt wiederholt — der Erwartungswert
    eines Doppels nach ~3000 Ziehungen liegt bei < 0.5 %. Diese
    Strategie schließt jede jemals gezogene Losnummer komplett aus.
    Statistisch nur ein winziger Edge (jede Ziehung ist iid), aber sie
    setzt die User-Intuition direkt um und garantiert, dass kein Tipp
    eine historische Wiederholung ist.
    """
    out = []
    seen: set[str] = {s for s in _digit_history(history) if len(s) == g.digits}
    for _ in range(rows):
        attempts = 0
        cand = ""
        while attempts < 2000:
            attempts += 1
            cand = "".join(str(rng.randint(0, 9)) for _ in range(g.digits))
            if cand not in seen:
                break
        if not cand:
            cand = "".join(str(rng.randint(0, 9)) for _ in range(g.digits))
        seen.add(cand)
        payload, display = _format_digits(cand)
        out.append({
            "strategy":  "unique_history",
            "payload":   payload,
            "display":   display,
            "rationale": (f"Schließt alle {len(seen) - 1} bislang gezogene Losnummern aus "
                          f"(Pool {10 ** g.digits:,} — Überlapp nur {(len(seen) - 1) / 10 ** g.digits:.4%})."),
        })
    return out


def _digit_strat_anti_pattern(g: Game, history: list[dict], *, rng: random.Random,
                              rows: int) -> list[dict]:
    """Avoid digit patterns that humans love → reduces share of jackpot
    if we *do* hit. Excludes:

      - all identical digits (1111111)
      - strictly monotone sequences (1234567 / 9876543)
      - 7-digit dates (DDMMYYY-style: starts with 0/1/2/3 + month-like)
      - palindromes (1234321) — over-represented in popular tips
    """
    out = []
    last_digits = (_digit_history(history) or [None])[0]
    for _ in range(rows):
        attempts = 0
        digits = ""
        while attempts < 200:
            attempts += 1
            cand = "".join(str(rng.randint(0, 9)) for _ in range(g.digits))
            # all-same?
            if len(set(cand)) == 1:
                continue
            # monotone?
            asc = all(int(b) - int(a) == 1 for a, b in zip(cand, cand[1:]))
            desc = all(int(a) - int(b) == 1 for a, b in zip(cand, cand[1:]))
            if asc or desc:
                continue
            # palindrome?
            if cand == cand[::-1]:
                continue
            # date-shape: first 2 digits 01–31, next 2 digits 01–12 (typical
            # Geburtstags-Lotto-Tipp). Only reject when it could plausibly be
            # a date — being strict would discard too much.
            if g.digits >= 4:
                d1 = int(cand[:2]); d2 = int(cand[2:4])
                if 1 <= d1 <= 31 and 1 <= d2 <= 12:
                    continue
            # avoid exact match with last draw
            if last_digits and cand == last_digits:
                continue
            digits = cand
            break
        if not digits:
            digits = "".join(str(rng.randint(0, 9)) for _ in range(g.digits))
        payload, display = _format_digits(digits)
        out.append({
            "strategy":  "anti_pattern",
            "payload":   payload,
            "display":   display,
            "rationale": "Vermeidet beliebte Muster (gleiche Ziffer, Folge, Datum, Palindrom)",
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
            "rationale": "Baseline: unabhängige uniform-zufällige Ziffern",
        })
    return out


def _digit_strat_meta_combo(g: Game, history: list[dict], *, rng: random.Random,
                            rows: int, exclude_last_k: int = 1) -> list[dict]:
    """Top-Digit-Strategie: kaskadiert die User-Wünsche in einem Pass.

      * recency_exclude (pro Position andere Ziffer als letzte K Ziehungen)
      * last_digit_recency (Endziffer ≠ Endziffern der letzten 5 Ziehungen
        → Spiel-77-Klasse-7-Marker, Super-6 Endziffer-Logik)
      * anti_pattern (keine all-equal, keine 1234567, keine Datums-Tipps,
        keine Palindrome)
      * unique_history (post-filter via history-guard) — schließt jede
        je gezogene Losnummer aus.
    """
    out = []
    history_strs = _digit_history(history)
    history_k = history_strs[:exclude_last_k]
    last_digit_history = {int(s[-1]) for s in history_strs[:5] if s}
    last_full = history_strs[0] if history_strs else None
    for _ in range(rows):
        attempts = 0
        digits = ""
        while attempts < 1500:
            attempts += 1
            # Position-wise build under recency+last-digit constraint
            buf: list[str] = []
            ok = True
            for pos in range(g.digits):
                forbidden = {int(s[pos]) for s in history_k if len(s) > pos}
                if pos == g.digits - 1:
                    forbidden |= last_digit_history
                choices = [d for d in range(10) if d not in forbidden] or list(range(10))
                buf.append(str(rng.choice(choices)))
            cand = "".join(buf)
            # anti_pattern checks
            if len(set(cand)) == 1:
                continue
            if all(int(b) - int(a) == 1 for a, b in zip(cand, cand[1:])):
                continue
            if all(int(a) - int(b) == 1 for a, b in zip(cand, cand[1:])):
                continue
            if cand == cand[::-1]:
                continue
            if g.digits >= 4:
                d1 = int(cand[:2]); d2 = int(cand[2:4])
                if 1 <= d1 <= 31 and 1 <= d2 <= 12:
                    continue
            if last_full and cand == last_full:
                continue
            digits = cand
            break
        if not digits:
            digits = "".join(str(rng.randint(0, 9)) for _ in range(g.digits))
        payload, display = _format_digits(digits)
        out.append({
            "strategy":  "meta_combo",
            "payload":   payload,
            "display":   display,
            "rationale": ("recency+endziffer+anti-pattern kaskadiert "
                          f"(Endziffer ≠ {sorted(last_digit_history) or '–'}, "
                          "keine all-equal/Folge/Datum/Palindrom)"),
        })
    return out


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
RECENCY_K_MIN = 1
RECENCY_K_MAX = 5
RECENCY_K_DEFAULT = 1


def _recency_label(k: int) -> str:
    return ("Letzte Ziehung ausgeschlossen"
            if k == 1 else f"Letzte {k} Ziehungen ausgeschlossen")


def _recency_desc_combo(k: int) -> str:
    if k == 1:
        return ("Garantiert keine Zahl aus der letzten Ziehung — Tipps "
                "ändern sich nach jeder neuen Ziehung.")
    return (f"Garantiert keine Zahl aus den letzten {k} Ziehungen — "
            "Tipps unterscheiden sich aggressiver, geben aber bewusst "
            "etwas Trefferwahrscheinlichkeit auf (Lotto ist iid).")


def _recency_desc_digit(k: int) -> str:
    if k == 1:
        return "Jede Position erhält eine andere Ziffer als die letzte Ziehung."
    return (f"Jede Position vermeidet alle Ziffern der letzten {k} "
            "Ziehungen — Tipps ändern sich aggressiver.")


def _combinatorial_strategies(recency_k: int) -> list[Strategy]:
    k = max(RECENCY_K_MIN, min(RECENCY_K_MAX, int(recency_k)))
    return [
        Strategy("meta_combo", "Top-Mix (Recency + Balanced + Anti-Pattern)",
                 "Kombiniert die stärksten Constraints in einer Auswahl: schließt die "
                 "letzten K Ziehungen aus, erzwingt plausible Summe/Even-Odd und vermeidet "
                 "beliebte Spielermuster — plus History-Guard (kein 1:1-Match je Ziehung).",
                 lambda g, h, rng, rows, _k=k:
                     _strat_meta_combo(g, h, rng=rng, rows=rows, exclude_last_k=_k)),
        Strategy("recency_exclude", _recency_label(k), _recency_desc_combo(k),
                 lambda g, h, rng, rows, _k=k:
                     _strat_recency_exclude(g, h, rng=rng, rows=rows, exclude_last_k=_k)),
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


def _digit_strategies(recency_k: int) -> list[Strategy]:
    k = max(RECENCY_K_MIN, min(RECENCY_K_MAX, int(recency_k)))
    return [
        Strategy("meta_combo", "Top-Mix (Recency + Endziffer + Anti-Pattern)",
                 "Kaskadiert recency_exclude, last_digit_recency und anti_pattern — "
                 "und der History-Guard schließt automatisch alle je gezogenen Losnummern aus.",
                 lambda g, h, rng, rows, _k=k:
                     _digit_strat_meta_combo(g, h, rng=rng, rows=rows, exclude_last_k=_k)),
        Strategy("recency_exclude", _recency_label(k), _recency_desc_digit(k),
                 lambda g, h, rng, rows, _k=k:
                     _digit_strat_recency_exclude(g, h, rng=rng, rows=rows, exclude_last_k=_k)),
        Strategy("last_digit_recency", "Endziffer rotieren",
                 "Endziffer ungleich der Endziffer der letzten 5 Ziehungen (Spiel 77 Klasse-7-Marker / Super 6 Endziffer-Logik).",
                 lambda g, h, rng, rows: _digit_strat_last_digit_recency(g, h, rng=rng, rows=rows)),
        Strategy("unique_history", "Noch nie gezogen",
                 "Schließt jede jemals gezogene Losnummer aus — bei Spiel 77 / Super 6 hat sich noch nie eine wiederholt.",
                 lambda g, h, rng, rows: _digit_strat_unique_history(g, h, rng=rng, rows=rows)),
        Strategy("frequency_hot", "Hot per Position",
                 "Häufigste Ziffer pro Position (gewichtet).",
                 lambda g, h, rng, rows: _digit_strat_frequency(g, h, rng=rng, rows=rows, hot=True)),
        Strategy("frequency_cold", "Cold per Position",
                 "Seltenste Ziffer pro Position (gewichtet).",
                 lambda g, h, rng, rows: _digit_strat_frequency(g, h, rng=rng, rows=rows, hot=False)),
        Strategy("anti_pattern", "Anti-Massenmuster",
                 "Vermeidet beliebte Muster (gleiche Ziffer, 1234567, Datums-Tipps, Palindrome).",
                 lambda g, h, rng, rows: _digit_strat_anti_pattern(g, h, rng=rng, rows=rows)),
        Strategy("random_uniform", "Zufall (Baseline)",
                 "10⁷ bzw. 10⁶ gleichverteilt.",
                 lambda g, h, rng, rows: _digit_strat_random_uniform(g, h, rng=rng, rows=rows)),
    ]


def strategies_for(game_id: str, *, recency_k: int = RECENCY_K_DEFAULT) -> list[Strategy]:
    g = GAMES[game_id]
    return (_digit_strategies(recency_k) if g.kind == "digit"
            else _combinatorial_strategies(recency_k))


def make_recency_strategy(game_id: str, k: int) -> Strategy:
    """Return a single recency_exclude Strategy bound to the given K.
    Used by the sweet-spot analytics so we don't need to rebuild the
    whole strategy list for each candidate K.
    """
    g = GAMES[game_id]
    if g.kind == "digit":
        return Strategy(
            "recency_exclude", _recency_label(k), _recency_desc_digit(k),
            lambda g_, h, rng, rows, _k=k:
                _digit_strat_recency_exclude(g_, h, rng=rng, rows=rows, exclude_last_k=_k))
    return Strategy(
        "recency_exclude", _recency_label(k), _recency_desc_combo(k),
        lambda g_, h, rng, rows, _k=k:
            _strat_recency_exclude(g_, h, rng=rng, rows=rows, exclude_last_k=_k))


# --------------------------------------------------------------------------- #
# History guard (combinatorial)
# --------------------------------------------------------------------------- #
# Lotto 6 aus 49 hat C(49,6) ≈ 1.4e7 mögliche Hauptzahl-Kombinationen,
# Eurojackpot C(50,5)·C(12,2) ≈ 1.4e8 — bei nur ~5 000 bzw. ~1 500
# historischen Ziehungen ist die Wahrscheinlichkeit, *exakt* eine alte
# Voll-Kombination zu raten, mikroskopisch (0.036 % bzw. 0.001 %).
# Der statistische Edge ist also vernachlässigbar; trotzdem ist es ein
# kostenloses Komfort-Feature — analog zum ``unique_history`` für die
# Digit-Spiele schließen wir nach jeder Strategie aus, dass der Tipp
# 1:1 einer historischen Ziehung entspricht. Wird via Rationale-Suffix
# transparent gemacht.
HISTORY_GUARD_MAX_RETRIES = 12


def _combo_signature(payload: dict, g: Game) -> tuple:
    parts = []
    for p in g.pools:
        v = payload.get(p.name) if isinstance(payload, dict) else None
        if not isinstance(v, (list, tuple)) or len(v) != p.pick:
            return ()
        parts.append((p.name, tuple(sorted(int(x) for x in v))))
    return tuple(parts)


def _historical_combo_set(g: Game, history: list[dict]) -> set[tuple]:
    sigs: set[tuple] = set()
    for h in history:
        sig = _combo_signature(h, g)
        if sig:
            sigs.add(sig)
    return sigs


def _historical_digit_set(g: Game, history: list[dict]) -> set[str]:
    """Set jeder je gezogenen Losnummer (für Spiel77 / Super6)."""
    if g.kind != "digit":
        return set()
    return {s for s in _digit_history(history) if len(s) == g.digits}


def _apply_history_guard_digit(g: Game, tips: list[dict], history_set: set[str],
                               *, regen: Callable[[], list[dict]]) -> list[dict]:
    if not history_set:
        return tips
    n_hist = len(history_set)
    out: list[dict] = []
    for tip in tips:
        cur = tip
        payload = cur.get("payload") or {}
        digits = payload.get("digits") if isinstance(payload, dict) else None
        retries = 0
        while isinstance(digits, str) and digits in history_set and retries < HISTORY_GUARD_MAX_RETRIES:
            retries += 1
            try:
                replacement = regen() or []
            except Exception:  # noqa: BLE001
                break
            if not replacement:
                break
            cur = replacement[0]
            payload = cur.get("payload") or {}
            digits = payload.get("digits") if isinstance(payload, dict) else None
        if isinstance(digits, str) and digits in history_set:
            note = f"⚠ historische Losnummer nicht vermeidbar ({n_hist} hist. Ziehungen)"
        else:
            note = f"schließt {n_hist} historische Losnummern aus"
            if retries:
                note += f" ({retries}× neu gezogen)"
        r = (cur.get("rationale") or "").strip()
        cur["rationale"] = f"{r} · {note}" if r else note
        out.append(cur)
    return out


def _apply_history_guard_combo(g: Game, tips: list[dict], history_set: set[tuple],
                               *, regen: Callable[[], list[dict]]) -> list[dict]:
    if not history_set:
        return tips
    n_hist = len(history_set)
    out: list[dict] = []
    for tip in tips:
        cur = tip
        sig = _combo_signature(cur.get("payload") or {}, g)
        retries = 0
        while sig and sig in history_set and retries < HISTORY_GUARD_MAX_RETRIES:
            retries += 1
            try:
                replacement = regen() or []
            except Exception:  # noqa: BLE001
                break
            if not replacement:
                break
            cur = replacement[0]
            sig = _combo_signature(cur.get("payload") or {}, g)
        note: str | None = None
        if sig and sig in history_set:
            note = f"⚠ historische Wiederholung nicht vermeidbar (Pool zu klein, {n_hist} hist. Ziehungen)"
        else:
            note = f"schließt {n_hist} historische Voll-Kombinationen aus"
            if retries:
                note += f" ({retries}× neu gezogen)"
        r = (cur.get("rationale") or "").strip()
        cur["rationale"] = f"{r} · {note}" if r else note
        out.append(cur)
    return out


def generate_tips(game_id: str, history: list[dict],
                  *, rows_per_strategy: int = 2,
                  recency_k: int = RECENCY_K_DEFAULT,
                  rng: random.Random | None = None) -> list[dict]:
    """Run every strategy and return a flat list of tip dicts.

    For combinatorial games every emitted tip is post-filtered through
    the history guard: if the tip's full payload matches any historical
    draw, the strategy is re-rolled (up to ``HISTORY_GUARD_MAX_RETRIES``)
    so we never recommend a 1:1 repeat.
    For digit games the analogous guard rejects any Losnummer that has
    ever been drawn (10⁷ pool for Spiel 77, 10⁶ for Super 6 — repeats
    are theoretically possible but historically didn't happen).
    """
    g = GAMES[game_id]
    rng = rng or random.Random()
    history_set_combo = _historical_combo_set(g, history) if g.kind == "combinatorial" else set()
    history_set_digit = _historical_digit_set(g, history)  if g.kind == "digit"          else set()
    tips: list[dict] = []
    for s in strategies_for(game_id, recency_k=recency_k):
        try:
            emitted = s.fn(g, history, rng, rows_per_strategy)
        except Exception as exc:  # noqa: BLE001
            log.exception("strategy %s for %s crashed: %s", s.name, game_id, exc)
            continue
        if history_set_combo:
            emitted = _apply_history_guard_combo(
                g, emitted, history_set_combo,
                regen=lambda _s=s: _s.fn(g, history, rng, 1),
            )
        elif history_set_digit and s.name != "unique_history":
            # unique_history schließt das schon per Definition aus —
            # die Note wäre redundant.
            emitted = _apply_history_guard_digit(
                g, emitted, history_set_digit,
                regen=lambda _s=s: _s.fn(g, history, rng, 1),
            )
        tips.extend(emitted)
    return tips


def list_strategies(game_id: str, *, recency_k: int = RECENCY_K_DEFAULT) -> list[dict]:
    return [
        {"name": s.name, "label": s.label, "description": s.description}
        for s in strategies_for(game_id, recency_k=recency_k)
    ]


def get_strategy(game_id: str, name: str, *,
                 recency_k: int = RECENCY_K_DEFAULT) -> Strategy | None:
    """Lookup one Strategy by name for the given game."""
    for s in strategies_for(game_id, recency_k=recency_k):
        if s.name == name:
            return s
    return None


def run_strategy(game_id: str, name: str, history: list[dict], *,
                 rows: int = 1, recency_k: int = RECENCY_K_DEFAULT,
                 rng: random.Random | None = None) -> list[dict]:
    """Run a single named strategy. Used by the custom Spielschein
    generator (one strategy per field). Returns the same dict shape as
    ``generate_tips``.
    """
    g = GAMES.get(game_id)
    if not g:
        raise ValueError(f"unknown game {game_id!r}")
    s = get_strategy(game_id, name, recency_k=recency_k)
    if not s:
        raise ValueError(f"unknown strategy {name!r} for {game_id!r}")
    rng = rng or random.Random()
    emitted = s.fn(g, history, rng, rows)
    if g.kind == "combinatorial":
        history_set = _historical_combo_set(g, history)
        emitted = _apply_history_guard_combo(
            g, emitted, history_set,
            regen=lambda: s.fn(g, history, rng, 1),
        )
    elif g.kind == "digit" and name != "unique_history":
        history_set_d = _historical_digit_set(g, history)
        emitted = _apply_history_guard_digit(
            g, emitted, history_set_d,
            regen=lambda: s.fn(g, history, rng, 1),
        )
    return emitted


