"""SQLite store for draws and generated tips.

Schema is intentionally tiny — three tables, one row per draw, one row
per generated tip. JSON columns hold the variable-width number arrays so
we don't need a side table per pool.

A "draw" is one historical lottery result; numbers are stored as a
sorted JSON array (pool name → list[int]) plus, for digit games, the
raw digit string.

A "tip" is one generated suggestion. Multiple tips per (game, strategy)
are normal — the engine produces N rows per strategy per generation.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Iterable, Iterator

from .games import GAMES, Game


_LOCK = threading.RLock()


# --------------------------------------------------------------------------- #
# connection
# --------------------------------------------------------------------------- #
def _open(db_path: str) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_CONN: sqlite3.Connection | None = None
_DB_PATH: str | None = None


def init_db(db_path: str) -> None:
    """Open the connection (idempotent) and create tables if missing."""
    global _CONN, _DB_PATH
    with _LOCK:
        if _CONN is not None and _DB_PATH == db_path:
            return
        if _CONN is not None:
            with contextlib.suppress(Exception):
                _CONN.close()
        _CONN = _open(db_path)
        _DB_PATH = db_path
        _create_schema(_CONN)


def conn() -> sqlite3.Connection:
    if _CONN is None:
        raise RuntimeError("store.init_db() must be called first")
    return _CONN


def _create_schema(c: sqlite3.Connection) -> None:
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS draws (
            game_id   TEXT NOT NULL,
            draw_date TEXT NOT NULL,            -- ISO yyyy-mm-dd
            -- Combinatorial games: JSON object pool_name -> sorted list[int]
            -- Digit games:        JSON object {"digits": "0123456"}
            payload   TEXT NOT NULL,
            -- Convenience: flat space-separated representation for grep/log.
            display   TEXT NOT NULL,
            inserted_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (game_id, draw_date)
        );

        CREATE INDEX IF NOT EXISTS idx_draws_game_date
            ON draws(game_id, draw_date DESC);

        CREATE TABLE IF NOT EXISTS tip_runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id    TEXT NOT NULL,
            generated_at TEXT NOT NULL DEFAULT (datetime('now')),
            -- Snapshot of the latest draw_date that the run was based on.
            based_on_draw TEXT,
            n_strategies  INTEGER NOT NULL,
            n_tips        INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tips (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id     INTEGER NOT NULL REFERENCES tip_runs(id) ON DELETE CASCADE,
            game_id    TEXT NOT NULL,
            strategy   TEXT NOT NULL,
            payload    TEXT NOT NULL,           -- JSON, same shape as draws.payload
            display    TEXT NOT NULL,
            rationale  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_tips_run ON tips(run_id);
        CREATE INDEX IF NOT EXISTS idx_tips_game_strategy
            ON tips(game_id, strategy);
        """
    )


# --------------------------------------------------------------------------- #
# draws
# --------------------------------------------------------------------------- #
def upsert_draw(game_id: str, draw_date: str, payload: dict, display: str) -> bool:
    """Insert or replace one draw. Returns True if row was new/changed."""
    if game_id not in GAMES:
        raise ValueError(f"unknown game {game_id!r}")
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    with _LOCK:
        cur = conn().execute(
            "SELECT payload FROM draws WHERE game_id=? AND draw_date=?",
            (game_id, draw_date),
        )
        row = cur.fetchone()
        if row and row["payload"] == payload_json:
            return False
        conn().execute(
            "INSERT INTO draws(game_id, draw_date, payload, display) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(game_id, draw_date) DO UPDATE SET "
            "payload=excluded.payload, display=excluded.display",
            (game_id, draw_date, payload_json, display),
        )
        return True


def list_draws(game_id: str, *, limit: int = 100, offset: int = 0) -> list[dict]:
    rows = conn().execute(
        "SELECT draw_date, payload, display FROM draws "
        "WHERE game_id=? ORDER BY draw_date DESC LIMIT ? OFFSET ?",
        (game_id, limit, offset),
    ).fetchall()
    return [
        {"draw_date": r["draw_date"], "display": r["display"], **json.loads(r["payload"])}
        for r in rows
    ]


def all_draws(game_id: str, *, since_date: str | None = None) -> Iterator[dict]:
    """Yield every stored draw for a game, newest first.

    Used by the strategy engine. Pulls the whole result set into memory
    deliberately — even 30 years × 2 draws/week is < 3 200 rows.
    """
    if since_date:
        cur = conn().execute(
            "SELECT draw_date, payload FROM draws "
            "WHERE game_id=? AND draw_date>=? ORDER BY draw_date DESC",
            (game_id, since_date),
        )
    else:
        cur = conn().execute(
            "SELECT draw_date, payload FROM draws "
            "WHERE game_id=? ORDER BY draw_date DESC",
            (game_id,),
        )
    for r in cur:
        yield {"draw_date": r["draw_date"], **json.loads(r["payload"])}


def latest_draw(game_id: str) -> dict | None:
    row = conn().execute(
        "SELECT draw_date, payload, display FROM draws "
        "WHERE game_id=? ORDER BY draw_date DESC LIMIT 1",
        (game_id,),
    ).fetchone()
    if not row:
        return None
    return {"draw_date": row["draw_date"], "display": row["display"], **json.loads(row["payload"])}


def draw_count(game_id: str) -> int:
    return conn().execute(
        "SELECT COUNT(*) AS n FROM draws WHERE game_id=?", (game_id,)
    ).fetchone()["n"]


def history_extent(game_id: str) -> dict:
    row = conn().execute(
        "SELECT MIN(draw_date) AS first, MAX(draw_date) AS last, COUNT(*) AS n "
        "FROM draws WHERE game_id=?",
        (game_id,),
    ).fetchone()
    return {"first": row["first"], "last": row["last"], "n": row["n"]}


def prune_history(retention_years: int) -> int:
    """Drop draws older than retention_years; returns rows deleted."""
    if retention_years <= 0:
        return 0
    cutoff = (dt.date.today() - dt.timedelta(days=retention_years * 366)).isoformat()
    cur = conn().execute("DELETE FROM draws WHERE draw_date<?", (cutoff,))
    return cur.rowcount or 0


# --------------------------------------------------------------------------- #
# tips
# --------------------------------------------------------------------------- #
def save_tip_run(
    game_id: str,
    based_on_draw: str | None,
    tips: list[dict],
) -> int:
    """Persist one tip-generation run. Returns the run_id."""
    with _LOCK:
        cur = conn().execute(
            "INSERT INTO tip_runs(game_id, based_on_draw, n_strategies, n_tips) "
            "VALUES (?, ?, ?, ?)",
            (
                game_id,
                based_on_draw,
                len({t['strategy'] for t in tips}),
                len(tips),
            ),
        )
        run_id = cur.lastrowid
        for t in tips:
            conn().execute(
                "INSERT INTO tips(run_id, game_id, strategy, payload, display, rationale) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    game_id,
                    t["strategy"],
                    json.dumps(t["payload"], separators=(",", ":"), sort_keys=True),
                    t["display"],
                    t.get("rationale"),
                ),
            )
        return int(run_id)


def latest_tip_run(game_id: str) -> dict | None:
    row = conn().execute(
        "SELECT id, generated_at, based_on_draw, n_strategies, n_tips "
        "FROM tip_runs WHERE game_id=? ORDER BY id DESC LIMIT 1",
        (game_id,),
    ).fetchone()
    if not row:
        return None
    tips = conn().execute(
        "SELECT strategy, payload, display, rationale FROM tips "
        "WHERE run_id=? ORDER BY id ASC",
        (row["id"],),
    ).fetchall()
    return {
        "run_id":         row["id"],
        "generated_at":   row["generated_at"],
        "based_on_draw":  row["based_on_draw"],
        "n_strategies":   row["n_strategies"],
        "n_tips":         row["n_tips"],
        "tips": [
            {
                "strategy":  t["strategy"],
                "rationale": t["rationale"],
                "display":   t["display"],
                **json.loads(t["payload"]),
            }
            for t in tips
        ],
    }


def cleanup_old_tip_runs(keep_per_game: int = 20) -> int:
    """Keep only the most recent N tip_runs per game."""
    deleted = 0
    for gid in GAMES:
        rows = conn().execute(
            "SELECT id FROM tip_runs WHERE game_id=? ORDER BY id DESC LIMIT -1 OFFSET ?",
            (gid, keep_per_game),
        ).fetchall()
        for r in rows:
            conn().execute("DELETE FROM tip_runs WHERE id=?", (r["id"],))
            deleted += 1
    return deleted


# --------------------------------------------------------------------------- #
# helpers used by API
# --------------------------------------------------------------------------- #
def games_overview() -> list[dict]:
    out: list[dict] = []
    for g in GAMES.values():
        ext = history_extent(g.id)
        last = latest_draw(g.id)
        out.append({
            "id":            g.id,
            "label":         g.label,
            "kind":          g.kind,
            "draw_days":     list(g.draw_days),
            "history_from":  g.history_from,
            "first_in_db":   ext["first"],
            "last_in_db":    ext["last"],
            "n_draws":       ext["n"],
            "last_draw":     last,
            "pools":         [p.__dict__ for p in g.pools],
            "digits":        g.digits,
            "digit_label":   g.digit_field_label,
            "notes":         g.notes,
        })
    return out


def bulk_upsert(game_id: str, draws: Iterable[tuple[str, dict, str]]) -> int:
    """Returns the number of changed rows."""
    n = 0
    for date, payload, display in draws:
        if upsert_draw(game_id, date, payload, display):
            n += 1
    return n

