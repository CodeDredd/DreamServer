"""External data fetchers for German lottery archives.

The DLTB (Deutscher Lotto- und Totoblock) does not publish a stable
machine-readable bulk archive. Several third-party mirrors and statistics
sites do — none of them are guaranteed to be stable forever, so this
module:

  1. Tries multiple parsers per game in declared order.
  2. Treats a "fetch" as "give me everything I don't already have, going
     back to ``Game.history_from`` if necessary".
  3. Gracefully no-ops if every source fails — the operator can drop a
     CSV into the bind-mounted ``/seed`` directory (see README) and call
     ``POST /admin/import`` to bootstrap manually.

Parsers return:  list[(draw_date_iso, payload_dict, display_string)]

The payload schema follows ``store.upsert_draw``:
    combinatorial → {"<pool_name>": [int, ...], ...}
    digit         → {"digits": "0123456"}

Adding a new parser
-------------------
Subclass ``BaseParser``, set ``game_id``, implement ``fetch_recent`` and
optionally ``fetch_archive``, then register the instance in ``PARSERS``.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from .config import CFG
from .games import GAMES, Game

log = logging.getLogger("lotto-oracle.fetchers")


DrawTuple = tuple[str, dict, str]


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def _client() -> httpx.Client:
    return httpx.Client(
        timeout=CFG.fetch_timeout_sec,
        headers={"User-Agent": CFG.user_agent, "Accept": "text/html, text/csv, */*"},
        follow_redirects=True,
    )


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
@dataclass
class BaseParser:
    game_id: str
    name: str

    def fetch_recent(self) -> list[DrawTuple]:
        """Return the most recent ~30 draws (since-last-update fetch)."""
        return []

    def fetch_archive(self, since: str | None = None) -> list[DrawTuple]:
        """Return as much history as the source exposes."""
        return self.fetch_recent()


# ─── helpers ───────────────────────────────────────────────────────────────
_DATE_DDMMYYYY = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
_DATE_YYYYMMDD = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def _parse_date(text: str) -> str | None:
    m = _DATE_DDMMYYYY.search(text)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo}-{d}"
    m = _DATE_YYYYMMDD.search(text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _payload_combinatorial(g: Game, pool_values: dict[str, list[int]]) -> tuple[dict, str]:
    payload = {p.name: sorted(pool_values[p.name]) for p in g.pools}
    parts = []
    for p in g.pools:
        nums = " ".join(f"{n:02d}" if p.high >= 10 else str(n) for n in payload[p.name])
        parts.append(f"{p.name}: {nums}")
    return payload, " | ".join(parts)


def _payload_digits(digits: str) -> tuple[dict, str]:
    return {"digits": digits}, digits


# --------------------------------------------------------------------------- #
# Parser: lottozahlenonline.de — covers 6aus49, eurojackpot, super6, spiel77
# --------------------------------------------------------------------------- #
# This site exposes per-year HTML archive pages with a stable layout
# (one row per draw). We probe a few URL templates per game; whichever
# returns 200 is parsed.
#
# This parser is intentionally tolerant: it accepts any HTML containing
# `<td>NN.NN.NNNN</td>` followed by digit-only cells, and assigns them
# to the game's pools in declaration order.
# --------------------------------------------------------------------------- #
_URL_TEMPLATES: dict[str, list[str]] = {
    "lotto-6aus49": [
        "https://www.lottozahlenonline.de/statistik/6aus49/jahr/{year}/",
        "https://www.lotto.de/lotto-6aus49/lottozahlen-archiv?year={year}",
    ],
    "eurojackpot": [
        "https://www.lottozahlenonline.de/statistik/eurojackpot/jahr/{year}/",
        "https://www.eurojackpot.de/ej/eurojackpot/zahlen-und-quoten/archiv?year={year}",
    ],
    "spiel77": [
        "https://www.lottozahlenonline.de/statistik/spiel77/jahr/{year}/",
    ],
    "super6": [
        "https://www.lottozahlenonline.de/statistik/super6/jahr/{year}/",
    ],
}


class HtmlYearArchiveParser(BaseParser):
    """Iterates per-year archive pages of a known mirror."""

    def __init__(self, game_id: str):
        super().__init__(game_id=game_id, name="html-year-archive")
        self.game = GAMES[game_id]

    def _years_to_scan(self, since: str | None) -> list[int]:
        start_year = int((since or self.game.history_from)[:4])
        end_year = dt.date.today().year
        # Clamp to retention window so we don't re-fetch 1955–1980 every
        # run if the operator capped retention to 30 years.
        retention_start = end_year - max(CFG.retention_years - 1, 0)
        start_year = max(start_year, retention_start)
        return list(range(start_year, end_year + 1))

    def fetch_archive(self, since: str | None = None) -> list[DrawTuple]:
        years = self._years_to_scan(since)
        log.info("[%s] scanning %d year archive page(s) (%s..%s)",
                 self.game_id, len(years), years[0], years[-1])
        results: list[DrawTuple] = []
        with _client() as cx:
            for year in years:
                for tmpl in _URL_TEMPLATES.get(self.game_id, []):
                    url = tmpl.format(year=year)
                    try:
                        r = cx.get(url)
                    except httpx.HTTPError as exc:
                        log.debug("[%s] %s: %s", self.game_id, url, exc)
                        continue
                    if r.status_code != 200 or len(r.text) < 200:
                        continue
                    parsed = self._parse_html(r.text)
                    if parsed:
                        log.info("[%s] %d → %d draws from %s",
                                 self.game_id, year, len(parsed), url)
                        results.extend(parsed)
                        break  # next year
        return results

    def fetch_recent(self) -> list[DrawTuple]:
        # Just scan the current year.
        return [
            d for d in self.fetch_archive(
                since=f"{dt.date.today().year}-01-01"
            )
        ]

    # ---- parsing ---------------------------------------------------------
    def _parse_html(self, html: str) -> list[DrawTuple]:
        soup = BeautifulSoup(html, "lxml")
        out: list[DrawTuple] = []
        # Approach: find every table row that looks like a draw row.
        for row in soup.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
            if not cells:
                continue
            date_iso = None
            for c in cells:
                d = _parse_date(c)
                if d:
                    date_iso = d
                    break
            if not date_iso:
                continue
            tup = self._row_to_payload(date_iso, cells)
            if tup is not None:
                out.append(tup)
        return out

    def _row_to_payload(self, date_iso: str, cells: list[str]) -> DrawTuple | None:
        if self.game.kind == "digit":
            # Find the first cell that is exactly N digits long.
            for c in cells:
                stripped = re.sub(r"\D", "", c)
                if len(stripped) == self.game.digits:
                    payload, display = _payload_digits(stripped)
                    return (date_iso, payload, display)
            return None

        # Combinatorial: extract every standalone integer in remaining
        # cells, ignoring the date itself.
        nums: list[int] = []
        for c in cells:
            if _parse_date(c):
                continue
            for tok in re.findall(r"-?\d+", c):
                try:
                    nums.append(int(tok))
                except ValueError:
                    pass

        # Filter to plausible numbers (within union of pool ranges).
        plausible = []
        max_high = max(p.high for p in self.game.pools)
        min_low = min(p.low for p in self.game.pools)
        for n in nums:
            if min_low <= n <= max_high:
                plausible.append(n)

        # Need at least sum(pool.pick).
        need = sum(p.pick for p in self.game.pools)
        if len(plausible) < need:
            return None
        plausible = plausible[:need]

        # Greedy assign: first pool's `pick` numbers (sorted), then next
        # pool's `pick` numbers from what remains. Many archive pages
        # already deliver them in this order; if not, rely on validity
        # checks below.
        pool_values: dict[str, list[int]] = {}
        idx = 0
        for p in self.game.pools:
            slice_ = plausible[idx:idx + p.pick]
            # Restrict to the pool's range.
            slice_ok = [n for n in slice_ if p.low <= n <= p.high]
            if len(slice_ok) != p.pick:
                # Try filtering all plausible numbers to this pool's range.
                pool_pool = [n for n in plausible if p.low <= n <= p.high]
                if len(set(pool_pool)) < p.pick:
                    return None
                slice_ok = sorted(set(pool_pool))[:p.pick] if p.pick > 1 else pool_pool[:1]
            pool_values[p.name] = slice_ok
            idx += p.pick

        payload, display = _payload_combinatorial(self.game, pool_values)
        return (date_iso, payload, display)


# --------------------------------------------------------------------------- #
# Parser: bundled CSV seed files (always tried first — offline-capable)
# --------------------------------------------------------------------------- #
class CsvSeedParser(BaseParser):
    """Reads /seed/<game_id>.csv shipped with the image / repo.

    CSV format (header required):

        # combinatorial games
        date,Hauptzahlen,Superzahl
        2024-12-28,3 11 24 31 38 47,5

        # digit games
        date,digits
        2024-12-28,1234567
    """

    def __init__(self, game_id: str):
        super().__init__(game_id=game_id, name="csv-seed")
        self.game = GAMES[game_id]
        self.path = Path(CFG.seed_dir) / f"{game_id}.csv"

    def fetch_archive(self, since: str | None = None) -> list[DrawTuple]:
        if not self.path.is_file():
            return []
        try:
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("[%s] failed to read seed %s: %s", self.game_id, self.path, exc)
            return []
        return list(self._parse_csv(text))

    def fetch_recent(self) -> list[DrawTuple]:
        return self.fetch_archive()

    def _parse_csv(self, text: str) -> Iterable[DrawTuple]:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            date_iso = (row.get("date") or "").strip()
            if not _DATE_YYYYMMDD.match(date_iso):
                continue
            if self.game.kind == "digit":
                digits = re.sub(r"\D", "", row.get("digits") or "")
                if len(digits) != self.game.digits:
                    continue
                payload, display = _payload_digits(digits)
                yield (date_iso, payload, display)
            else:
                pool_values: dict[str, list[int]] = {}
                ok = True
                for p in self.game.pools:
                    raw = row.get(p.name) or ""
                    nums = [int(x) for x in re.findall(r"\d+", raw)]
                    nums = [n for n in nums if p.low <= n <= p.high]
                    if len(set(nums)) < p.pick:
                        ok = False
                        break
                    pool_values[p.name] = sorted(set(nums))[:p.pick] if p.pick > 1 else nums[:1]
                if not ok:
                    continue
                payload, display = _payload_combinatorial(self.game, pool_values)
                yield (date_iso, payload, display)


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
PARSERS: dict[str, list[BaseParser]] = {
    gid: [CsvSeedParser(gid), HtmlYearArchiveParser(gid)] for gid in GAMES
}


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def fetch_into(store_module, *, full_archive: bool = False) -> dict:
    """Run every parser for every game; return per-game result counts."""
    summary: dict = {}
    for gid in GAMES:
        added = 0
        per_parser: dict[str, dict] = {}
        for parser in PARSERS.get(gid, []):
            try:
                draws = (
                    parser.fetch_archive(since=None)
                    if full_archive
                    else parser.fetch_recent()
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] parser %s crashed: %s", gid, parser.name, exc)
                per_parser[parser.name] = {"error": str(exc)}
                continue
            n_changed = store_module.bulk_upsert(gid, draws)
            added += n_changed
            per_parser[parser.name] = {"fetched": len(draws), "new_or_changed": n_changed}
        summary[gid] = {"new_or_changed": added, "parsers": per_parser}
    return summary

