"""Persistent log of every decide-cycle the scheduler (or /decide) runs.

The point: the dashboard needs to show *that* and *how* the strategy
engine has been running, including idle ticks where no signals fired
and cycles that crashed. Up to now the only state we kept was the
in-memory `_state['last_cycle']` snapshot — that's lost on restart and
only ever has the **last** cycle per strategy.

Stored in the same SQLite file as the ledger so backups stay coherent.
Lightweight schema: one row per (strategy, ts) cycle.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from . import ledger

log = logging.getLogger("finance-guru.cycle_log")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS cycle_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,                  -- cycle start (ISO UTC)
    strategy      TEXT NOT NULL,
    trigger       TEXT NOT NULL DEFAULT 'scheduler', -- scheduler|manual|backtest
    duration_ms   INTEGER NOT NULL DEFAULT 0,
    universe      INTEGER NOT NULL DEFAULT 0,
    signals       INTEGER NOT NULL DEFAULT 0,
    executed      INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    equity_eur    REAL,
    cash_eur      REAL,
    pnl_pct       REAL,
    status        TEXT NOT NULL DEFAULT 'ok',     -- ok|error|empty
    error         TEXT,
    payload_json  TEXT,                           -- compressed run-result for drill-down
    -- Phase G: lifecycle snapshot at write-time so the dashboard's
    -- "nur generierte" filter doesn't need a JOIN per row, and so the
    -- record survives later renames/retires of the strategy.
    kind          TEXT,                           -- builtin|generated (nullable for legacy rows)
    bt_pnl_pct    REAL                            -- promotion-backtest pnl%, copied from strategies_meta
);

CREATE INDEX IF NOT EXISTS idx_cycle_runs_strategy_ts ON cycle_runs (strategy, ts DESC);
CREATE INDEX IF NOT EXISTS idx_cycle_runs_ts          ON cycle_runs (ts DESC);
CREATE INDEX IF NOT EXISTS idx_cycle_runs_kind_ts     ON cycle_runs (kind, ts DESC);
"""


# Columns added after the initial Phase B ship. SQLite has no
# "ADD COLUMN IF NOT EXISTS", so we inspect pragma_table_info and
# patch on the fly. Keeps in-place upgrades automatic — operators
# don't have to run a migration script.
_EXTRA_COLS = (
    ("kind",       "TEXT"),
    ("bt_pnl_pct", "REAL"),
)


def _ensure_extra_columns() -> None:
    with ledger.conn() as c:
        have = {row["name"] for row in c.execute("PRAGMA table_info(cycle_runs)").fetchall()}
        for col, ddl in _EXTRA_COLS:
            if col not in have:
                c.execute(f"ALTER TABLE cycle_runs ADD COLUMN {col} {ddl}")
                log.info("cycle_log: added column %s %s", col, ddl)
        c.execute("CREATE INDEX IF NOT EXISTS idx_cycle_runs_kind_ts ON cycle_runs (kind, ts DESC)")


def init_db() -> None:
    """Idempotent — safe to call after ledger.init_db()."""
    with ledger.conn() as c:
        c.executescript(SCHEMA_SQL)
    _ensure_extra_columns()
    log.info("Cycle log table ready")


def _lookup_meta_snapshot(strategy: str) -> tuple[str | None, float | None]:
    """Best-effort (kind, bt_pnl_pct) lookup from strategies_meta. Returns
    (None, None) when the lifecycle table doesn't exist yet (cold boot)
    or the strategy was never registered (legacy backtest harness).
    Never raises — cycle_log writes must not block on lifecycle hiccups."""
    try:
        with ledger.conn() as c:
            row = c.execute(
                "SELECT kind, bt_pnl_pct FROM strategies_meta WHERE name = ?",
                (strategy,),
            ).fetchone()
        if row is None:
            return None, None
        return row["kind"], row["bt_pnl_pct"]
    except Exception:  # noqa: BLE001
        return None, None


def record(
    *,
    strategy: str,
    started: dt.datetime,
    finished: dt.datetime,
    trigger: str = "scheduler",
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> int:
    """Insert one cycle row. `result` is the dict returned by
    orchestrator.run_strategy_once() (may be None on hard crash)."""
    result = result or {}
    kpi = result.get("kpi") or {}
    executed = result.get("executed") or []
    skipped = result.get("skipped") or []
    signals = int(result.get("signals") or 0)
    status = "error" if error else ("empty" if signals == 0 and not executed else "ok")
    duration_ms = max(0, int((finished - started).total_seconds() * 1000))
    # Trim the payload — we don't want every single tick to dump KB of
    # JSON. The detail view re-pulls /ledger if it wants more.
    trimmed = {
        "executed": executed[:25],
        "skipped":  skipped[:25],
        "signals":  signals,
        "kpi":      kpi,
    }
    with ledger.conn() as c:
        kind, bt_pnl_pct = _lookup_meta_snapshot(strategy)
        cur = c.execute(
            "INSERT INTO cycle_runs (ts, strategy, trigger, duration_ms, universe, "
            "signals, executed, skipped, equity_eur, cash_eur, pnl_pct, status, error, "
            "payload_json, kind, bt_pnl_pct) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                started.isoformat(),
                strategy,
                trigger,
                duration_ms,
                int(result.get("universe") or 0),
                signals,
                len(executed),
                len(skipped),
                kpi.get("equity_eur"),
                kpi.get("cash_eur"),
                kpi.get("total_pnl_pct"),
                status,
                (error or "")[:500] or None,
                json.dumps(trimmed, default=str),
                kind,
                bt_pnl_pct,
            ),
        )
        return int(cur.lastrowid or 0)


def list_cycles(strategy: str | None = None, limit: int = 50,
                status_filter: str | None = None,
                kind: str | None = None) -> list[dict]:
    sql = ["SELECT id, ts, strategy, trigger, duration_ms, universe, signals, "
           "executed, skipped, equity_eur, cash_eur, pnl_pct, status, error, "
           "kind, bt_pnl_pct "
           "FROM cycle_runs WHERE 1=1"]
    args: list = []
    if strategy:
        sql.append("AND strategy = ?")
        args.append(strategy)
    if status_filter:
        sql.append("AND status = ?")
        args.append(status_filter)
    if kind:
        sql.append("AND kind = ?")
        args.append(kind)
    sql.append("ORDER BY ts DESC LIMIT ?")
    args.append(max(1, min(limit, 500)))
    with ledger.conn() as c:
        rows = c.execute(" ".join(sql), tuple(args)).fetchall()
        return [dict(r) for r in rows]


def equity_history(strategy: str, since: dt.datetime | None = None,
                   limit: int = 500) -> list[dict]:
    """Time-series of (ts, equity_eur, pnl_pct) from successful cycles —
    drives the per-strategy equity chart."""
    sql = ["SELECT ts, equity_eur, cash_eur, pnl_pct FROM cycle_runs "
           "WHERE strategy = ? AND equity_eur IS NOT NULL"]
    args: list = [strategy]
    if since:
        sql.append("AND ts >= ?")
        args.append(since.isoformat())
    sql.append("ORDER BY ts ASC LIMIT ?")
    args.append(max(1, min(limit, 5000)))
    with ledger.conn() as c:
        rows = c.execute(" ".join(sql), tuple(args)).fetchall()
        return [dict(r) for r in rows]


def summary(strategy: str | None = None) -> dict:
    """Aggregate counts for the dashboard banner: total cycles, errors,
    last-24h activity."""
    base = "FROM cycle_runs"
    where = ""
    args: tuple = ()
    if strategy:
        where = " WHERE strategy = ?"
        args = (strategy,)
    with ledger.conn() as c:
        total = c.execute(f"SELECT COUNT(*) c {base}{where}", args).fetchone()["c"]
        errors = c.execute(
            f"SELECT COUNT(*) c {base}{where + (' AND' if where else ' WHERE')} status='error'",
            args,
        ).fetchone()["c"]
        last_24h = c.execute(
            f"SELECT COUNT(*) c {base}{where + (' AND' if where else ' WHERE')} ts >= ?",
            args + ((dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)).isoformat(),),
        ).fetchone()["c"]
        last_row = c.execute(
            f"SELECT ts, status, signals, executed, error {base}{where} ORDER BY ts DESC LIMIT 1",
            args,
        ).fetchone()
    return {
        "total":    int(total or 0),
        "errors":   int(errors or 0),
        "last_24h": int(last_24h or 0),
        "last":     dict(last_row) if last_row else None,
    }


def prune(keep_days: int = 90) -> int:
    """Housekeeping: drop rows older than `keep_days`. Called from the
    scheduler lifespan."""
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=keep_days)).isoformat()
    with ledger.conn() as c:
        cur = c.execute("DELETE FROM cycle_runs WHERE ts < ?", (cutoff,))
        return int(cur.rowcount or 0)

