"""Game definitions for the supported German lotteries.

Each game describes:
  * its draw structure (k of n, plus optional bonus pools / digit fields)
  * the weekdays it is drawn on
  * the canonical id used by the rest of the codebase

All four supported games are state-licensed (Deutscher Lotto- und
Totoblock / DLTB).  ``super6`` and ``spiel77`` are *digit games* — they
don't pick numbers from a pool but draw a single 6- or 7-digit string
where each digit is uniform 0–9 and (officially) independent.  Strategies
that only make sense for combinatorial games (frequency-of-number,
recency-exclude on the previous winning set, etc.) are skipped for the
digit games and replaced with per-digit-position frequency / hot-cold.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


GameKind = Literal["combinatorial", "digit"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass(frozen=True)
class Pool:
    """One field of numbers to pick from (e.g. main 6 of 49)."""
    name: str               # human label, e.g. "Hauptzahlen"
    pick: int               # how many numbers are drawn
    low: int                # inclusive
    high: int               # inclusive


@dataclass(frozen=True)
class Game:
    id: str
    label: str              # German-facing display name
    kind: GameKind
    pools: tuple[Pool, ...]      # for combinatorial games
    digits: int                  # for digit games (0 if combinatorial)
    digit_field_label: str       # e.g. "Losnummer"
    draw_days: tuple[Weekday, ...]
    history_from: str            # earliest date with reliable archive
    notes: str


GAMES: dict[str, Game] = {
    # ─── Lotto 6 aus 49 ────────────────────────────────────────────────
    # First draw: 1955-10-09. Superzahl is a single digit 0–9 drawn
    # separately (since 1991-12-04 the Superzahl replaced the older
    # Spielscheinnummer-letter system; before that the pre-1992 archive
    # has only the 6 main + Zusatzzahl). We model the modern format —
    # the historical Zusatzzahl is ignored (it no longer exists).
    "lotto-6aus49": Game(
        id="lotto-6aus49",
        label="Lotto 6 aus 49",
        kind="combinatorial",
        pools=(
            Pool(name="Hauptzahlen", pick=6, low=1, high=49),
            Pool(name="Superzahl", pick=1, low=0, high=9),
        ),
        digits=0,
        digit_field_label="",
        draw_days=("wed", "sat"),
        history_from="1955-10-09",
        notes="Modernes Format mit Superzahl seit 04.12.1991.",
    ),

    # ─── Eurojackpot ───────────────────────────────────────────────────
    # First draw: 2012-03-23. Pool changed 2022-03-25 from 5/50 + 2/10
    # to 5/50 + 2/12 — we use the modern (current) parameters and the
    # archive will contain both pre- and post-2022 draws (Eurozahlen
    # 11–12 simply never appear before 2022).
    "eurojackpot": Game(
        id="eurojackpot",
        label="Eurojackpot",
        kind="combinatorial",
        pools=(
            Pool(name="Hauptzahlen", pick=5, low=1, high=50),
            Pool(name="Eurozahlen", pick=2, low=1, high=12),
        ),
        digits=0,
        digit_field_label="",
        draw_days=("tue", "fri"),
        history_from="2012-03-23",
        notes="Pool-Erweiterung Eurozahlen 1–10 → 1–12 seit 25.03.2022.",
    ),

    # ─── Spiel 77 ──────────────────────────────────────────────────────
    # 7-digit "Losnummer" 0000000–9999999. Each digit is uniform 0–9.
    # Drawn together with 6aus49 on Wed + Sat. First draw of modern
    # format: ca. 1975 (we accept whatever the archive returns).
    "spiel77": Game(
        id="spiel77",
        label="Spiel 77",
        kind="digit",
        pools=(),
        digits=7,
        digit_field_label="Losnummer",
        draw_days=("wed", "sat"),
        history_from="1975-01-04",
        notes="7-stellige Zusatzlotterie zu Lotto 6 aus 49.",
    ),

    # ─── Super 6 ───────────────────────────────────────────────────────
    # 6-digit number 000000–999999. Drawn together with 6aus49.
    "super6": Game(
        id="super6",
        label="Super 6",
        kind="digit",
        pools=(),
        digits=6,
        digit_field_label="Spielscheinnummer",
        draw_days=("wed", "sat"),
        history_from="1991-05-04",
        notes="6-stellige Zusatzlotterie zu Lotto 6 aus 49.",
    ),
}


def list_games() -> list[Game]:
    return list(GAMES.values())


def get_game(game_id: str) -> Game | None:
    return GAMES.get(game_id)

