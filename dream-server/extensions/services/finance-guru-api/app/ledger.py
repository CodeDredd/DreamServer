"""SQLite paper-trade ledger.

One ledger per strategy, seeded with FINANCE_GURU_SEED_EUR (default
€1000). All trades are paper — no broker integration. Every action
records a human-readable `reason` string so the dashboard can show
"why did the bot trade?" without re-running the LLM.

Schema is created idempotently at import time (single SQLite file
under FINANCE_GURU_LEDGER_PATH).
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from .config import CFG

log = logging.getLogger("finance-guru.ledger")

_lock = threading.RLock()


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS strategies (
    name        TEXT PRIMARY KEY,
    description TEXT,
    seeded_eur  REAL NOT NULL,
    created_at  TEXT NOT NULL,
    is_paper    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cash (
    strategy    TEXT PRIMARY KEY REFERENCES strategies(name),
    eur         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    strategy    TEXT NOT NULL REFERENCES strategies(name),
    symbol      TEXT NOT NULL,
    asset_type  TEXT NOT NULL,
    qty         REAL NOT NULL,
    avg_entry   REAL NOT NULL,
    opened_at   TEXT NOT NULL,
    PRIMARY KEY (strategy, symbol)
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy    TEXT NOT NULL REFERENCES strategies(name),
    ts          TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    asset_type  TEXT NOT NULL,
    action      TEXT NOT NULL CHECK (action IN ('buy','sell')),
    qty         REAL NOT NULL,
    price       REAL NOT NULL,
    fee         REAL NOT NULL,
    realised_pnl REAL,
    reason      TEXT,
    signal_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_trades_strategy_ts ON trades (strategy, ts DESC);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_ts   ON trades (symbol,   ts DESC);
"""


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(CFG.ledger_path) or ".", exist_ok=True)
    c = sqlite3.connect(CFG.ledger_path, timeout=10, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.row_factory = sqlite3.Row
    return c


@contextmanager
def conn():
    with _lock:
        c = _connect()
        try:
            yield c
        finally:
            c.close()


def init_db() -> None:
    with conn() as c:
        c.executescript(SCHEMA_SQL)
    log.info("Ledger ready at %s", CFG.ledger_path)


# --------------------------------------------------------------------------- #
# Strategy registration
# --------------------------------------------------------------------------- #
def ensure_strategy(name: str, description: str = "") -> None:
    """Idempotently register a strategy + seed its cash bucket."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with conn() as c:
        existing = c.execute("SELECT 1 FROM strategies WHERE name = ?", (name,)).fetchone()
        if existing:
            if description:
                c.execute("UPDATE strategies SET description = ? WHERE name = ?",
                          (description, name))
            return
        c.execute(
            "INSERT INTO strategies (name, description, seeded_eur, created_at) VALUES (?,?,?,?)",
            (name, description, CFG.seed_eur, now),
        )
        c.execute("INSERT INTO cash (strategy, eur) VALUES (?, ?)", (name, CFG.seed_eur))
        log.info("Seeded strategy %r with %.2f EUR", name, CFG.seed_eur)


# --------------------------------------------------------------------------- #
# Trade execution (paper)
# --------------------------------------------------------------------------- #
@dataclass
class TradeResult:
    accepted: bool
    reason_code: str       # 'ok' | 'no_cash' | 'no_position' | 'invalid'
    trade_id: int | None
    realised_pnl: float
    note: str = ""


def _round_qty(qty: float) -> float:
    # Paper trades: keep 6 decimals — fine for fractional crypto + stocks.
    return round(float(qty), 6)


def execute_trade(strategy: str, *, symbol: str, asset_type: str,
                  action: str, qty: float, price: float,
                  reason: str = "", signal: dict | None = None,
                  ts: dt.datetime | None = None) -> TradeResult:
    """All-or-nothing paper trade. Updates cash + positions atomically."""
    if action not in ("buy", "sell"):
        return TradeResult(False, "invalid", None, 0.0, "bad action")
    qty = _round_qty(qty)
    if qty <= 0:
        return TradeResult(False, "invalid", None, 0.0, "non-positive qty")
    when = (ts or dt.datetime.now(dt.timezone.utc)).isoformat()
    fee = abs(qty * price) * (CFG.fee_bps / 10_000.0)

    with conn() as c:
        cash_row = c.execute("SELECT eur FROM cash WHERE strategy = ?", (strategy,)).fetchone()
        if not cash_row:
            return TradeResult(False, "invalid", None, 0.0, "unknown strategy")
        cash = float(cash_row["eur"])
        pos_row = c.execute(
            "SELECT qty, avg_entry FROM positions WHERE strategy = ? AND symbol = ?",
            (strategy, symbol)).fetchone()
        cur_qty   = float(pos_row["qty"]) if pos_row else 0.0
        avg_entry = float(pos_row["avg_entry"]) if pos_row else 0.0

        realised = 0.0
        c.execute("BEGIN")
        try:
            if action == "buy":
                cost = qty * price + fee
                if cost > cash + 1e-6:
                    c.execute("ROLLBACK")
                    return TradeResult(False, "no_cash", None, 0.0,
                                       f"need {cost:.2f}, have {cash:.2f}")
                new_qty = cur_qty + qty
                new_avg = ((cur_qty * avg_entry) + (qty * price)) / new_qty
                c.execute("UPDATE cash SET eur = eur - ? WHERE strategy = ?",
                          (cost, strategy))
                if pos_row:
                    c.execute(
                        "UPDATE positions SET qty = ?, avg_entry = ? WHERE strategy = ? AND symbol = ?",
                        (new_qty, new_avg, strategy, symbol),
                    )
                else:
                    c.execute(
                        "INSERT INTO positions (strategy, symbol, asset_type, qty, avg_entry, opened_at) VALUES (?,?,?,?,?,?)",
                        (strategy, symbol, asset_type, new_qty, new_avg, when),
                    )
            else:  # sell
                if qty > cur_qty + 1e-9:
                    c.execute("ROLLBACK")
                    return TradeResult(False, "no_position", None, 0.0,
                                       f"want sell {qty}, hold {cur_qty}")
                proceeds = qty * price - fee
                realised = (price - avg_entry) * qty - fee
                c.execute("UPDATE cash SET eur = eur + ? WHERE strategy = ?",
                          (proceeds, strategy))
                remaining = cur_qty - qty
                if remaining < 1e-9:
                    c.execute("DELETE FROM positions WHERE strategy = ? AND symbol = ?",
                              (strategy, symbol))
                else:
                    c.execute(
                        "UPDATE positions SET qty = ? WHERE strategy = ? AND symbol = ?",
                        (remaining, strategy, symbol),
                    )

            cur = c.execute(
                "INSERT INTO trades (strategy, ts, symbol, asset_type, action, qty, price, fee, realised_pnl, reason, signal_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (strategy, when, symbol, asset_type, action, qty, price, fee,
                 realised if action == "sell" else None,
                 reason, json.dumps(signal or {}, default=str)),
            )
            tid = cur.lastrowid
            c.execute("COMMIT")
            return TradeResult(True, "ok", tid, realised)
        except Exception:
            c.execute("ROLLBACK")
            raise


# --------------------------------------------------------------------------- #
# Inspection helpers
# --------------------------------------------------------------------------- #
def list_strategies() -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT name, description, seeded_eur, created_at, is_paper FROM strategies ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]


def get_cash(strategy: str) -> float:
    with conn() as c:
        r = c.execute("SELECT eur FROM cash WHERE strategy = ?", (strategy,)).fetchone()
        return float(r["eur"]) if r else 0.0


def get_positions(strategy: str) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT symbol, asset_type, qty, avg_entry, opened_at FROM positions WHERE strategy = ? ORDER BY symbol",
            (strategy,)).fetchall()
        return [dict(r) for r in rows]


def get_trades(strategy: str, limit: int = 50) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT id, ts, symbol, asset_type, action, qty, price, fee, realised_pnl, reason "
            "FROM trades WHERE strategy = ? ORDER BY ts DESC LIMIT ?",
            (strategy, limit)).fetchall()
        return [dict(r) for r in rows]


def kpi(strategy: str, mark_prices: dict[str, float]) -> dict:
    """Returns realised PnL (sum of sell-side realised), unrealised
    (mark-to-market vs avg_entry), total equity (cash + holdings),
    and the target-comparison %."""
    cash = get_cash(strategy)
    positions = get_positions(strategy)
    seeded = next((s["seeded_eur"] for s in list_strategies() if s["name"] == strategy), CFG.seed_eur)
    holdings_value = 0.0
    unrealised = 0.0
    for p in positions:
        mark = mark_prices.get(p["symbol"], p["avg_entry"])
        holdings_value += mark * p["qty"]
        unrealised += (mark - p["avg_entry"]) * p["qty"]
    with conn() as c:
        r = c.execute(
            "SELECT COALESCE(SUM(realised_pnl), 0) AS realised, COUNT(*) AS trades "
            "FROM trades WHERE strategy = ?",
            (strategy,)).fetchone()
        realised = float(r["realised"] or 0.0)
        n_trades = int(r["trades"] or 0)
    equity = cash + holdings_value
    return {
        "strategy":         strategy,
        "seeded_eur":       seeded,
        "cash_eur":         round(cash, 2),
        "holdings_eur":     round(holdings_value, 2),
        "equity_eur":       round(equity, 2),
        "realised_pnl_eur": round(realised, 2),
        "unrealised_pnl_eur": round(unrealised, 2),
        "total_pnl_pct":    round((equity - seeded) / seeded * 100.0, 2) if seeded else None,
        "n_trades":         n_trades,
        "n_positions":      len(positions),
    }

