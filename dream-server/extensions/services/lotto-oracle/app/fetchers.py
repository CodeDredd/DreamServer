"""External data fetchers for German lottery archives.

The DLTB (Deutscher Lotto- und Totoblock) does not publish a stable
machine-readable bulk archive. As of 05/2026 every German operator
(`lotto.de`, `eurojackpot.de`, `westlotto.de`, `lotto-bayern.de`,
`lottozahlen.de`, `dielottozahlen.de`, …) ships their lottozahlen
archive as a JS-rendered SPA — the HTML returned to a non-browser
client is a tiny shell with no draw data inline. The previously used
`lottozahlenonline.de` mirror has gone offline (every URL 404s).

We therefore use a **layered**, intentionally pessimistic strategy:

  1. ``CsvSeedParser`` — bundled CSVs in ``seed_data/`` (mounted at
     ``/seed`` in the container) bootstrap the DB on cold-start.
     The repo ships a small but accurate seed of recent draws so the
     UI has *something* to render even when every live source is dead.
  2. ``LottoReportLatestParser`` — scrapes the latest draw of
     ``lotto-6aus49`` and ``eurojackpot`` from
     ``https://www.lottoreport.de/dyn-vorw-lo.htm`` (the only public
     German lottery page we have verified to render server-side).
     This grows the DB by 1–2 draws per run, on top of the seed.
  3. Operator-supplied CSV via ``POST /admin/import`` — for the full
     30-year backfill of ``spiel77`` and ``super6`` (no public mirror
     exposes those server-side; an operator with their own scraper
     can drop a CSV into the seed dir and POST it).

If a parser raises, the others still run. ``fetch_into`` reports per
parser counts so the operator can tell which source contributed.

Parsers return ``list[(draw_date_iso, payload_dict, display_string)]``.
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
        headers={
            "User-Agent": CFG.user_agent,
            "Accept": "text/html, text/csv, */*",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        },
        follow_redirects=True,
        verify=False,  # lottoreport.de presents an outdated chain
    )


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
@dataclass
class BaseParser:
    game_id: str
    name: str
    offline: bool = False  # True ⇒ usable as cold-start bootstrap (no network)

    def fetch_recent(self) -> list[DrawTuple]:
        """Return the most recent ~N draws (since-last-update fetch)."""
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
        super().__init__(game_id=game_id, name="csv-seed", offline=True)
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
# Parser: official semicolon-separated archives shipped by lotto.de /
# eurojackpot.de operators (and re-distributed by community trackers).
#
# Two file shapes are recognised, both ISO-8859-1 with CRLF and a quote
# table appended after the draw rows:
#
#   LOTTO_*.csv  →  Lotto 6aus49 + Spiel 77 + Super 6 (one row per Mi/Sa)
#       columns: Datum;;Z1;Z2;Z3;Z4;Z5;Z6;Zusatz;Zusatz2;Superzahl;Spiel77;Super6;…quotes…
#       (Zusatz columns are always "--" since the Zusatzzahl was abolished
#        in mid-2013, but the column itself is still emitted by the archive.)
#
#   EJ_*.csv     →  Eurojackpot (one row per Di/Fr)
#       columns: Datum;H1;H2;H3;H4;H5;EZ1;EZ2;…quotes…
#
# The archive is matched by glob (LOTTO_*.csv / EJ_*.csv) so the operator
# can drop multiple files (e.g. one per year) into seed_data/ without
# touching the code. Anything that doesn't parse as a valid draw row is
# silently skipped (header rows, trailing "Spieleinsätze und Quoten in
# EUR" boilerplate, blank lines, …).
# --------------------------------------------------------------------------- #
_DATE_DDMMYYYY_LINE = re.compile(r"^\s*(\d{2})\.(\d{2})\.(\d{4})\s*;")


class OfficialArchiveParser(BaseParser):
    """Multi-game archive parser. One instance per ``game_id``; each
    instance scans the seed dir for the matching archive(s) and yields
    only the rows for its own game.

    Mapping ``game_id → glob``::

        lotto-6aus49 / spiel77 / super6  →  LOTTO_*.csv
        eurojackpot                       →  EJ_*.csv
    """

    _GLOBS = {
        "lotto-6aus49": "LOTTO_*.csv",
        "spiel77":      "LOTTO_*.csv",
        "super6":       "LOTTO_*.csv",
        "eurojackpot":  "EJ_*.csv",
    }

    def __init__(self, game_id: str):
        super().__init__(game_id=game_id, name="csv-archive", offline=True)
        self.game = GAMES[game_id]
        self.seed_dir = Path(CFG.seed_dir)

    def fetch_archive(self, since: str | None = None) -> list[DrawTuple]:
        glob = self._GLOBS.get(self.game_id)
        if not glob or not self.seed_dir.is_dir():
            return []
        out: list[DrawTuple] = []
        seen_dates: set[str] = set()
        # Sort for deterministic order when multiple archive shards exist.
        for fp in sorted(self.seed_dir.glob(glob)):
            try:
                # The DLTB / lottoreport archives are emitted as ISO-8859-1.
                # Fall back to utf-8 just in case an operator pre-converted
                # one of the files.
                try:
                    text = fp.read_text(encoding="cp1252")
                except UnicodeDecodeError:
                    text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                log.warning("[%s] failed to read archive %s: %s",
                            self.game_id, fp, exc)
                continue
            for draw in self._parse_text(text):
                if draw[0] in seen_dates:
                    continue
                seen_dates.add(draw[0])
                out.append(draw)
        if out:
            log.info("[%s] csv-archive: %d draws across %d file(s)",
                     self.game_id, len(out), len(list(self.seed_dir.glob(glob))))
        return out

    def fetch_recent(self) -> list[DrawTuple]:
        # The whole archive is cheap to re-parse (<1 MB total); a "recent"
        # call returns everything and the upsert layer dedupes.
        return self.fetch_archive()

    # ── per-line parsing ──────────────────────────────────────────────
    def _parse_text(self, text: str) -> Iterable[DrawTuple]:
        for line in text.splitlines():
            if not _DATE_DDMMYYYY_LINE.match(line):
                continue
            cols = [c.strip() for c in line.split(";")]
            try:
                draw = self._parse_row(cols)
            except (ValueError, IndexError):
                continue
            if draw is not None:
                yield draw

    def _parse_row(self, cols: list[str]) -> DrawTuple | None:
        date_iso = _parse_date(cols[0])
        if not date_iso:
            return None

        if self.game_id == "eurojackpot":
            # cols: 0=date, 1..5=Hauptzahlen, 6..7=Eurozahlen, 8+=quotes
            main = [int(cols[i]) for i in range(1, 6)]
            euro = [int(cols[i]) for i in range(6, 8)]
            if not (all(1 <= n <= 50 for n in main)
                    and all(1 <= n <= 12 for n in euro)
                    and len(set(main)) == 5
                    and len(set(euro)) == 2):
                return None
            payload, display = _payload_combinatorial(
                self.game,
                {"Hauptzahlen": sorted(main), "Eurozahlen": sorted(euro)},
            )
            return (date_iso, payload, display)

        # All three LOTTO_* games share the same row layout:
        # cols: 0=date, 1=" "(empty marker), 2..7=Z1..Z6, 8/9=Zusatz markers
        # ("--" since 2013), 10=Superzahl, 11=Spiel77, 12=Super6, 13+=quotes.
        # Some archive variants drop the empty 2nd column → detect by
        # checking whether cols[1] is empty (legacy) or already a number
        # (compact variant).
        first_num_idx = 2 if cols[1] == "" else 1
        try:
            main = [int(cols[first_num_idx + i]) for i in range(6)]
        except ValueError:
            return None
        if not (all(1 <= n <= 49 for n in main) and len(set(main)) == 6):
            return None
        # Skip the two "--" Zusatz columns; the next numeric column is
        # the Superzahl, then Spiel77, then Super6.
        tail = cols[first_num_idx + 6:]
        # Drop leading "--" placeholders (Zusatzzahl).
        while tail and tail[0] in {"--", ""}:
            tail.pop(0)
        if len(tail) < 3:
            return None
        try:
            superzahl = int(tail[0])
            spiel77   = re.sub(r"\D", "", tail[1])
            super6    = re.sub(r"\D", "", tail[2])
        except ValueError:
            return None

        if self.game_id == "lotto-6aus49":
            if not 0 <= superzahl <= 9:
                return None
            payload, display = _payload_combinatorial(
                self.game,
                {"Hauptzahlen": sorted(main), "Superzahl": [superzahl]},
            )
            return (date_iso, payload, display)

        if self.game_id == "spiel77":
            if len(spiel77) != self.game.digits:
                return None
            payload, display = _payload_digits(spiel77)
            return (date_iso, payload, display)

        if self.game_id == "super6":
            if len(super6) != self.game.digits:
                return None
            payload, display = _payload_digits(super6)
            return (date_iso, payload, display)

        return None


# --------------------------------------------------------------------------- #
# Parser: lottoreport.de — single-page latest-draw scraper
# --------------------------------------------------------------------------- #
# https://www.lottoreport.de/dyn-vorw-lo.htm renders server-side and
# contains four "carousel cards", one per game (lotto, eurojackpot,
# gluecksspirale, keno). Each card has a <h5>Ziehung vom <Tag>, den
# DD.MM.YYYY</h5> and then a sequence of <p class="lotto-bullet--number">
# elements (or eurojackpot-equivalents) carrying the drawn numbers.
#
# This parser yields **only the most recent draw** per supported game.
# It runs on every cron tick and progressively grows the archive.
# --------------------------------------------------------------------------- #
_LOTTOREPORT_URL = "https://www.lottoreport.de/dyn-vorw-lo.htm"

# Map game_id → (CSS class prefix on the result block,
#                expected pool sizes in order).
_LOTTOREPORT_CARDS: dict[str, tuple[str, ...]] = {
    "lotto-6aus49": ("lotto",),
    "eurojackpot": ("eurojackpot",),
}


class LottoReportLatestParser(BaseParser):
    """Latest-draw scraper for lotto-6aus49 / eurojackpot."""

    def __init__(self, game_id: str):
        super().__init__(game_id=game_id, name="lottoreport-latest")
        self.game = GAMES[game_id]

    def fetch_recent(self) -> list[DrawTuple]:
        if self.game_id not in _LOTTOREPORT_CARDS:
            return []
        try:
            with _client() as cx:
                r = cx.get(_LOTTOREPORT_URL)
        except httpx.HTTPError as exc:
            log.info("[%s] lottoreport.de unreachable: %s", self.game_id, exc)
            return []
        if r.status_code != 200 or len(r.text) < 1000:
            return []
        return self._parse_card(r.text)

    def fetch_archive(self, since: str | None = None) -> list[DrawTuple]:
        # The page only ever holds one draw — same as fetch_recent.
        return self.fetch_recent()

    def _parse_card(self, html: str) -> list[DrawTuple]:
        soup = BeautifulSoup(html, "lxml")
        prefix = _LOTTOREPORT_CARDS[self.game_id][0]
        block = soup.find("div", class_=f"{prefix}-result")
        if not block:
            return []

        # Extract the date.
        h5 = block.find("h5")
        if not h5:
            return []
        date_iso = _parse_date(h5.get_text(" ", strip=True))
        if not date_iso:
            return []

        # Extract numbers — every <p class="*--number"> in the block.
        nums: list[int] = []
        for p in block.find_all("p", class_=re.compile(r"--number$")):
            txt = p.get_text(strip=True)
            if txt.isdigit():
                nums.append(int(txt))

        if self.game_id == "lotto-6aus49":
            # 6 main numbers + Superzahl (1 digit). lottoreport places
            # the Superzahl as the 7th bullet styled as "superzahl";
            # the regex above already captures it.
            if len(nums) < 7:
                return []
            main = sorted(nums[:6])
            sz = nums[6] if 0 <= nums[6] <= 9 else None
            if sz is None:
                return []
            payload, display = _payload_combinatorial(
                self.game, {"Hauptzahlen": main, "Superzahl": [sz]},
            )
            return [(date_iso, payload, display)]

        if self.game_id == "eurojackpot":
            # 5 main + 2 Eurozahlen
            main = [n for n in nums if 1 <= n <= 50]
            euro = [n for n in nums if 1 <= n <= 12]
            # crude split: take first 5 for main, last 2 for euro
            if len(nums) < 7:
                return []
            main = sorted(nums[:5])
            euro = sorted(nums[5:7])
            payload, display = _payload_combinatorial(
                self.game, {"Hauptzahlen": main, "Eurozahlen": euro},
            )
            return [(date_iso, payload, display)]

        return []


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
PARSERS: dict[str, list[BaseParser]] = {
    "lotto-6aus49": [
        CsvSeedParser("lotto-6aus49"),
        OfficialArchiveParser("lotto-6aus49"),
        LottoReportLatestParser("lotto-6aus49"),
    ],
    "eurojackpot": [
        CsvSeedParser("eurojackpot"),
        OfficialArchiveParser("eurojackpot"),
        LottoReportLatestParser("eurojackpot"),
    ],
    # spiel77 / super6 inherit their history from the LOTTO_*.csv archive
    # (one row produces draws for all three games). lotto.de itself is a
    # SPA, so without an operator-supplied archive these stay empty.
    "spiel77": [
        CsvSeedParser("spiel77"),
        OfficialArchiveParser("spiel77"),
    ],
    "super6": [
        CsvSeedParser("super6"),
        OfficialArchiveParser("super6"),
    ],
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

