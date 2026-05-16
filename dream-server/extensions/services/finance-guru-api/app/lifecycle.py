"""Strategy lifecycle — proposals, promotions, retirements, weekly audit.

Phase C of FINANCE-GURU-IMPROVEMENT-PLAN.md.

Why a *separate* module and not just more columns on `strategies`?
  * `strategies` (ledger.py) is the **execution** table: cash + seed +
    creation timestamp. Renaming or dropping rows there would break the
    ledger's foreign keys. The lifecycle is metadata *about* execution
    rows that may come and go.
  * Lifecycle state changes are driven by external actors (weekly
    auditor, n8n strategy-genesis workflow in Phase D, operator). They
    need their own write path with audit logging.
  * The `lessons_id` column points at a `finance_strategy_lessons`
    Qdrant point; we never want to mix vector IDs into the ledger PK
    space.

State machine — implemented strictly via `_transition()`:

    proposed ──promote (backtest_ok)──▶ live ──audit:fail──▶ retired
       │                                   │                    │
       │                                   ├─audit:pass──┐      │
       │                                                 ▼      │
       │                                              (stays live)
       └─archive (backtest_fail OR ≥30d stale)──▶ archived ◀────┘
                                                  (retired→archived after 90d)

Every transition is recorded in `strategy_audits` so we can answer
"why was strategy X retired on 2026-05-25?" without grepping logs.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from typing import Iterable, Literal

from . import cycle_log, ledger, llm, qdrant_rag
from .config import CFG

log = logging.getLogger("finance-guru.lifecycle")

Status  = Literal["proposed", "live", "retired", "archived"]
Kind    = Literal["builtin", "generated"]
Outcome = Literal["pass", "retire", "need_more_data"]


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS strategies_meta (
    name             TEXT PRIMARY KEY,
    kind             TEXT NOT NULL DEFAULT 'builtin',     -- builtin | generated
    status           TEXT NOT NULL DEFAULT 'live',        -- proposed | live | retired | archived
    parent_id        TEXT,                                -- predecessor strategy (for generated)
    source_json      TEXT,                                -- DSL / generator metadata
    created_at       TEXT NOT NULL,
    live_started_at  TEXT,
    retired_at       TEXT,
    bt_pnl_pct       REAL,                                -- promotion backtest result
    bt_n_trades      INTEGER,
    last_audit_at    TEXT,
    last_audit_pnl   REAL,
    last_audit_n     INTEGER,
    retire_reason    TEXT,
    lessons_qid      TEXT                                 -- Qdrant point id when a lesson is embedded
);

CREATE INDEX IF NOT EXISTS idx_strat_meta_status ON strategies_meta (status);
CREATE INDEX IF NOT EXISTS idx_strat_meta_kind   ON strategies_meta (kind);

CREATE TABLE IF NOT EXISTS strategy_audits (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    strategy     TEXT NOT NULL,
    transition   TEXT NOT NULL,                           -- propose|promote|retire|archive|audit:pass|audit:need_more_data
    from_status  TEXT,
    to_status    TEXT,
    pnl_pct      REAL,
    n_cycles     INTEGER,
    note         TEXT,
    actor        TEXT NOT NULL DEFAULT 'system'           -- system | operator | n8n:<wf>
);

CREATE INDEX IF NOT EXISTS idx_strat_audit_ts ON strategy_audits (ts DESC);
CREATE INDEX IF NOT EXISTS idx_strat_audit_strategy ON strategy_audits (strategy, ts DESC);
"""


def init_db() -> None:
    with ledger.conn() as c:
        c.executescript(SCHEMA_SQL)
    log.info("Lifecycle tables ready")


# --------------------------------------------------------------------------- #
# Read helpers
# --------------------------------------------------------------------------- #
def get_meta(name: str) -> dict | None:
    with ledger.conn() as c:
        r = c.execute("SELECT * FROM strategies_meta WHERE name = ?", (name,)).fetchone()
        return dict(r) if r else None


def list_meta(status: Status | None = None,
              kind: Kind | None = None,
              limit: int = 500) -> list[dict]:
    sql = ["SELECT * FROM strategies_meta WHERE 1=1"]
    args: list = []
    if status:
        sql.append("AND status = ?")
        args.append(status)
    if kind:
        sql.append("AND kind = ?")
        args.append(kind)
    sql.append("ORDER BY (status='live') DESC, created_at DESC LIMIT ?")
    args.append(max(1, min(limit, 1000)))
    with ledger.conn() as c:
        return [dict(r) for r in c.execute(" ".join(sql), tuple(args)).fetchall()]


def count_recent_proposed(*, days: int, kind: Kind = "generated") -> int:
    """Count strategies_meta rows of the given kind created within the
    rolling window. Used by the genesis quota guard so a misbehaving
    LLM workflow can't flood the lifecycle table.

    Counts ALL transitions (proposed → live AND proposed → archived)
    since the relevant quantity for the quota is "how many proposals
    did we accept and run", not "how many are still in 'proposed'
    status right now"."""
    if days <= 0:
        return 0
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(days=days)).isoformat()
    with ledger.conn() as c:
        row = c.execute(
            "SELECT COUNT(*) AS n FROM strategies_meta "
            "WHERE kind = ? AND created_at >= ?",
            (kind, cutoff),
        ).fetchone()
    return int(row["n"] if row else 0)


def list_audits(strategy: str | None = None, limit: int = 100) -> list[dict]:
    sql = ["SELECT id, ts, strategy, transition, from_status, to_status, "
           "pnl_pct, n_cycles, note, actor FROM strategy_audits WHERE 1=1"]
    args: list = []
    if strategy:
        sql.append("AND strategy = ?")
        args.append(strategy)
    sql.append("ORDER BY ts DESC LIMIT ?")
    args.append(max(1, min(limit, 500)))
    with ledger.conn() as c:
        return [dict(r) for r in c.execute(" ".join(sql), tuple(args)).fetchall()]


# --------------------------------------------------------------------------- #
# Writes — every public mutation routes through _transition() so we have
# one place that emits an audit row.
# --------------------------------------------------------------------------- #
def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _transition(*, strategy: str, transition: str, from_status: str | None,
                to_status: str | None, pnl_pct: float | None = None,
                n_cycles: int | None = None, note: str | None = None,
                actor: str = "system") -> int:
    with ledger.conn() as c:
        cur = c.execute(
            "INSERT INTO strategy_audits "
            "(ts, strategy, transition, from_status, to_status, pnl_pct, n_cycles, note, actor) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (_now(), strategy, transition, from_status, to_status,
             pnl_pct, n_cycles, (note or "")[:500] or None, actor),
        )
        return int(cur.lastrowid or 0)


def ensure_meta(name: str, *, kind: Kind = "builtin",
                status: Status = "live", parent_id: str | None = None,
                source: dict | None = None) -> dict:
    """Idempotent — used by main.lifespan() right after the strategy
    registry is built so every discovered plugin gets a meta row even
    if the lifecycle table is empty.

    For freshly-discovered builtins we register them as `live`
    immediately (no backtest gating); generated strategies must go
    through `propose() → promote()`.
    """
    existing = get_meta(name)
    if existing:
        return existing
    now = _now()
    live_started = now if status == "live" else None
    with ledger.conn() as c:
        c.execute(
            "INSERT INTO strategies_meta "
            "(name, kind, status, parent_id, source_json, created_at, live_started_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (name, kind, status, parent_id,
             json.dumps(source or {}, default=str),
             now, live_started),
        )
    _transition(strategy=name, transition="register",
                from_status=None, to_status=status,
                note=f"kind={kind}", actor="system")
    return get_meta(name) or {}


def propose(*, name: str, source: dict, parent_id: str | None = None,
            actor: str = "n8n:strategy_genesis") -> dict:
    """Phase D entry point — n8n strategy-genesis workflow proposes a
    new DSL strategy. It does NOT touch the ledger yet (no seed); the
    backtest decides whether we ever `promote()` it."""
    if get_meta(name):
        raise ValueError(f"strategy {name!r} already exists in lifecycle")
    with ledger.conn() as c:
        c.execute(
            "INSERT INTO strategies_meta "
            "(name, kind, status, parent_id, source_json, created_at) "
            "VALUES (?, 'generated', 'proposed', ?, ?, ?)",
            (name, parent_id, json.dumps(source, default=str), _now()),
        )
    _transition(strategy=name, transition="propose",
                from_status=None, to_status="proposed",
                note=(source.get("note") if isinstance(source, dict) else None) or None,
                actor=actor)
    return get_meta(name) or {}


def promote(*, name: str, bt_pnl_pct: float, bt_n_trades: int,
            actor: str = "system") -> dict:
    meta = get_meta(name)
    if not meta:
        raise ValueError(f"unknown strategy {name!r}")
    now = _now()
    was_live = meta["status"] == "live"
    if was_live:
        # Already live: just refresh the backtest snapshot (operator
        # ran another backtest and wants the leaderboard to reflect
        # it) but DON'T reset live_started_at — the strategy's live
        # clock keeps ticking.
        with ledger.conn() as c:
            c.execute(
                "UPDATE strategies_meta SET bt_pnl_pct=?, bt_n_trades=? WHERE name=?",
                (bt_pnl_pct, bt_n_trades, name),
            )
        _transition(strategy=name, transition="promote:refresh",
                    from_status="live", to_status="live",
                    pnl_pct=bt_pnl_pct, n_cycles=bt_n_trades,
                    note=f"refresh backtest_pnl={bt_pnl_pct:.2f}% n={bt_n_trades}",
                    actor=actor)
        return get_meta(name) or {}
    with ledger.conn() as c:
        c.execute(
            "UPDATE strategies_meta SET status='live', live_started_at=?, "
            "bt_pnl_pct=?, bt_n_trades=?, retired_at=NULL, retire_reason=NULL "
            "WHERE name = ?",
            (now, bt_pnl_pct, bt_n_trades, name),
        )
    _transition(strategy=name, transition="promote",
                from_status=meta["status"], to_status="live",
                pnl_pct=bt_pnl_pct, n_cycles=bt_n_trades,
                note=f"backtest_pnl={bt_pnl_pct:.2f}% n={bt_n_trades}",
                actor=actor)
    return get_meta(name) or {}


def retire(*, name: str, reason: str, pnl_pct: float | None = None,
           n_cycles: int | None = None, lessons_qid: str | None = None,
           actor: str = "system") -> dict:
    meta = get_meta(name)
    if not meta:
        # Auto-register before retiring — happens when an operator hits
        # /strategies/retire on a builtin that never got a meta row
        # (e.g. legacy install).
        ensure_meta(name)
        meta = get_meta(name) or {}
    if meta.get("status") == "retired":
        return meta
    now = _now()
    with ledger.conn() as c:
        c.execute(
            "UPDATE strategies_meta SET status='retired', retired_at=?, "
            "retire_reason=?, last_audit_at=?, last_audit_pnl=?, last_audit_n=?, "
            "lessons_qid=COALESCE(?, lessons_qid) "
            "WHERE name = ?",
            (now, reason[:500], now, pnl_pct, n_cycles, lessons_qid, name),
        )
    _transition(strategy=name, transition="retire",
                from_status=meta.get("status"), to_status="retired",
                pnl_pct=pnl_pct, n_cycles=n_cycles, note=reason[:500],
                actor=actor)
    return get_meta(name) or {}


def archive(*, name: str, reason: str, actor: str = "system") -> dict:
    meta = get_meta(name)
    if not meta:
        ensure_meta(name)
        meta = get_meta(name) or {}
    if meta.get("status") == "archived":
        return meta
    now = _now()
    with ledger.conn() as c:
        c.execute(
            "UPDATE strategies_meta SET status='archived', retired_at=COALESCE(retired_at, ?), "
            "retire_reason=COALESCE(retire_reason, ?) WHERE name = ?",
            (now, reason[:500], name),
        )
    _transition(strategy=name, transition="archive",
                from_status=meta.get("status"), to_status="archived",
                note=reason[:500], actor=actor)
    return get_meta(name) or {}


# --------------------------------------------------------------------------- #
# Audit — the 7-day "is this strategy still earning?" gate
# --------------------------------------------------------------------------- #
@dataclass
class AuditResult:
    strategy: str
    outcome: Outcome
    pnl_pct: float | None
    n_cycles: int
    target_pct: float
    note: str = ""


def _equity_window_pnl(strategy: str, days: int) -> tuple[float | None, int]:
    """Compute %-PnL across the equity_history window relative to the
    *first* equity reading of the window (NOT to the seed). That's the
    semantically right number for "last week", because the strategy's
    starting equity for the week is whatever cash + holdings it had on
    Monday morning — not whatever it had on creation day."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    points = cycle_log.equity_history(strategy=strategy, since=since, limit=5000)
    if not points:
        return None, 0
    starts = [p for p in points if p.get("equity_eur") is not None]
    if not starts:
        return None, 0
    first = float(starts[0]["equity_eur"])
    last  = float(starts[-1]["equity_eur"])
    if first <= 0:
        return None, len(starts)
    return ((last - first) / first) * 100.0, len(starts)


def audit_one(name: str, *, target_pct: float | None = None,
              min_samples: int | None = None,
              window_days: int = 7) -> AuditResult:
    target = target_pct if target_pct is not None else CFG.weekly_audit_target_pct
    minimum = min_samples if min_samples is not None else CFG.weekly_audit_min_samples
    pnl, n = _equity_window_pnl(name, window_days)
    if pnl is None or n < minimum:
        return AuditResult(strategy=name, outcome="need_more_data",
                           pnl_pct=pnl, n_cycles=n, target_pct=target,
                           note=f"only {n} cycles in last {window_days}d (need {minimum})")
    if pnl >= target:
        return AuditResult(strategy=name, outcome="pass",
                           pnl_pct=pnl, n_cycles=n, target_pct=target,
                           note=f"pnl_{window_days}d={pnl:.2f}% >= target {target:.2f}%")
    return AuditResult(strategy=name, outcome="retire",
                       pnl_pct=pnl, n_cycles=n, target_pct=target,
                       note=f"pnl_{window_days}d={pnl:.2f}% < target {target:.2f}%")


# --------------------------------------------------------------------------- #
# Lesson generation — runs after a retire decision so the next
# strategy-genesis cycle (Phase D) can RAG-query "what failed and why".
# --------------------------------------------------------------------------- #
_LESSON_SYSTEM = (
    "You write a single short lesson (<=120 words) summarising why a "
    "paper-trade strategy lost money this week. Be specific and "
    "actionable: cite the rule that mis-fired, the market regime, and "
    "what a future strategy generator should *avoid*. No filler, no "
    "praise, no markdown headings."
)


def _build_lesson_context(strategy: str, *, days: int = 7) -> dict:
    """Pull the data the lesson model gets to write from. We keep it
    tight — model + ledger queries only, no extra Qdrant calls — so a
    failing TEI doesn't block the audit."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    points = cycle_log.equity_history(strategy=strategy, since=since, limit=2000)
    trades = ledger.get_trades(strategy, limit=200)
    recent_trades = [t for t in trades if (t.get("ts") or "") >= since.isoformat()]
    losers = sorted([t for t in recent_trades if (t.get("realised_pnl") or 0) < 0],
                    key=lambda t: t.get("realised_pnl") or 0)[:5]
    winners = sorted([t for t in recent_trades if (t.get("realised_pnl") or 0) > 0],
                     key=lambda t: -(t.get("realised_pnl") or 0))[:5]
    return {
        "equity_first": points[0]["equity_eur"] if points else None,
        "equity_last":  points[-1]["equity_eur"] if points else None,
        "n_cycles":     len(points),
        "n_trades_total":  len(recent_trades),
        "n_trades_loser":  len(losers),
        "n_trades_winner": len(winners),
        "biggest_losers": [{
            "ts":     t["ts"],
            "symbol": t["symbol"],
            "action": t["action"],
            "pnl":    t.get("realised_pnl"),
            "reason": (t.get("reason") or "")[:140],
        } for t in losers],
        "biggest_winners": [{
            "ts":     t["ts"],
            "symbol": t["symbol"],
            "action": t["action"],
            "pnl":    t.get("realised_pnl"),
            "reason": (t.get("reason") or "")[:140],
        } for t in winners],
    }


def build_lesson_text(strategy: str, *, pnl_pct: float, target_pct: float,
                      n_cycles: int, days: int = 7) -> str:
    """LLM-polished lesson string. Falls back to a deterministic template
    on any LLM failure so weekly_audit() is never blocked by inference
    outages."""
    ctx = _build_lesson_context(strategy, days=days)
    template = (
        f"{strategy} retired after {days}d at {pnl_pct:+.2f}% "
        f"(target {target_pct:+.2f}%) across {n_cycles} cycles. "
        f"Trades: {ctx['n_trades_total']} total, "
        f"{ctx['n_trades_loser']} losers, {ctx['n_trades_winner']} winners. "
    )
    if ctx["biggest_losers"]:
        worst = ctx["biggest_losers"][0]
        template += (
            f"Worst trade: {worst['action']} {worst['symbol']} "
            f"({worst['pnl']:.2f} EUR) — \"{worst['reason']}\"."
        )
    try:
        messages = [
            {"role": "system", "content": _LESSON_SYSTEM},
            {"role": "user",
             "content": (
                 f"Strategy: {strategy}\n"
                 f"Window: last {days} days\n"
                 f"PnL: {pnl_pct:+.2f}% (target {target_pct:+.2f}%)\n"
                 f"Cycles: {n_cycles}\n"
                 f"Trades summary: {json.dumps(ctx, default=str)}\n"
                 "Write the lesson now."
             )},
        ]
        text = llm.chat(messages, max_tokens=240,
                        model=CFG.lesson_llm_model,
                        timeout=CFG.lesson_llm_timeout).strip()
        if text:
            return text[:2000]
    except Exception as exc:  # noqa: BLE001
        log.warning("Lesson LLM call failed for %s (%s) — using template", strategy, exc)
    return template[:2000]


def weekly_audit(*, only: Iterable[str] | None = None,
                 actor: str = "system",
                 emit_lessons: bool = True,
                 retire_failing: bool = True) -> dict:
    """Iterate every `live` strategy, run audit_one, retire all under
    target. Returns a summary dict that the API exposes verbatim so
    the dashboard can show "retired today" notifications.

    Knobs:
        * `only`           — restrict audit to a subset (operator
                              dry-run; default = every live row).
        * `retire_failing` — when False, only computes pass/fail and
                              records the audit row but doesn't change
                              status. Useful for previewing.
        * `emit_lessons`   — when False, skip the LLM call entirely
                              (saves cost during dry-runs).
    """
    target_set = set(only) if only else None
    live_rows = [m for m in list_meta(status="live")
                 if not target_set or m["name"] in target_set]
    results: list[dict] = []
    for meta in live_rows:
        name = meta["name"]
        ar = audit_one(name)
        # Always record the audit, regardless of outcome.
        _transition(strategy=name,
                    transition=f"audit:{ar.outcome}",
                    from_status="live",
                    to_status="live" if ar.outcome != "retire" else "live",
                    pnl_pct=ar.pnl_pct, n_cycles=ar.n_cycles,
                    note=ar.note, actor=actor)
        # Update last_audit_* fields in-place even on pass.
        with ledger.conn() as c:
            c.execute(
                "UPDATE strategies_meta SET last_audit_at=?, last_audit_pnl=?, "
                "last_audit_n=? WHERE name=?",
                (_now(), ar.pnl_pct, ar.n_cycles, name),
            )
        out = {
            "strategy":   name,
            "outcome":    ar.outcome,
            "pnl_pct":    ar.pnl_pct,
            "n_cycles":   ar.n_cycles,
            "target_pct": ar.target_pct,
            "note":       ar.note,
            "retired":    False,
            "lesson_stored": False,
        }
        if ar.outcome == "retire" and retire_failing:
            lesson_qid = None
            lesson_text = ""
            if emit_lessons:
                lesson_text = build_lesson_text(
                    name, pnl_pct=ar.pnl_pct or 0.0,
                    target_pct=ar.target_pct, n_cycles=ar.n_cycles,
                )
                ok = qdrant_rag.upsert_strategy_lesson(
                    strategy=name, outcome="retired",
                    pnl_pct=ar.pnl_pct, lesson_text=lesson_text,
                    keywords=[name, "weekly_audit", "retired"],
                    extra={"target_pct": ar.target_pct,
                           "n_cycles": ar.n_cycles},
                )
                lesson_qid = name if ok else None
                out["lesson_stored"] = bool(ok)
            retire(name=name, reason=ar.note,
                   pnl_pct=ar.pnl_pct, n_cycles=ar.n_cycles,
                   lessons_qid=lesson_qid, actor=actor)
            out["retired"] = True
            if lesson_text:
                out["lesson"] = lesson_text[:240]
        results.append(out)
    return {
        "ts":           _now(),
        "actor":        actor,
        "evaluated":    len(results),
        "retired":      sum(1 for r in results if r["retired"]),
        "passed":       sum(1 for r in results if r["outcome"] == "pass"),
        "need_more":    sum(1 for r in results if r["outcome"] == "need_more_data"),
        "retire_failing": retire_failing,
        "emit_lessons": emit_lessons,
        "results":      results,
    }


# --------------------------------------------------------------------------- #
# Leaderboard — for the dashboard panel
# --------------------------------------------------------------------------- #
def leaderboard(*, window_days: int = 7, limit: int = 50) -> list[dict]:
    """Joins strategies_meta with the equity_history-derived %-PnL.
    `status` is preserved so the dashboard can group live / retired /
    archived. Sorted: live first, then by pnl_pct descending."""
    meta_rows = list_meta(limit=limit * 2)
    out: list[dict] = []
    for m in meta_rows:
        pnl, n = _equity_window_pnl(m["name"], window_days)
        out.append({
            "name":           m["name"],
            "kind":           m["kind"],
            "status":         m["status"],
            "parent_id":      m["parent_id"],
            "created_at":     m["created_at"],
            "live_started_at": m["live_started_at"],
            "retired_at":     m["retired_at"],
            "retire_reason":  m["retire_reason"],
            "bt_pnl_pct":     m["bt_pnl_pct"],
            "bt_n_trades":    m["bt_n_trades"],
            "last_audit_at":  m["last_audit_at"],
            "last_audit_pnl": m["last_audit_pnl"],
            "lessons_qid":    m["lessons_qid"],
            "window_days":    window_days,
            "window_pnl_pct": pnl,
            "window_cycles":  n,
        })
    out.sort(key=lambda r: (
        0 if r["status"] == "live" else (1 if r["status"] == "proposed" else 2),
        -(r["window_pnl_pct"] if r["window_pnl_pct"] is not None else -9999),
    ))
    return out[:limit]


# --------------------------------------------------------------------------- #
# Housekeeping — auto-archive stale retired rows
# --------------------------------------------------------------------------- #
def auto_archive(*, retired_grace_days: int = 90,
                 proposed_grace_days: int = 30,
                 actor: str = "system") -> int:
    """Drop retired rows older than `retired_grace_days` and proposed
    rows older than `proposed_grace_days` into 'archived'. Returns the
    count of rows transitioned."""
    now = dt.datetime.now(dt.timezone.utc)
    retired_cut  = (now - dt.timedelta(days=retired_grace_days)).isoformat()
    proposed_cut = (now - dt.timedelta(days=proposed_grace_days)).isoformat()
    with ledger.conn() as c:
        retired_targets  = [r["name"] for r in c.execute(
            "SELECT name FROM strategies_meta WHERE status='retired' AND retired_at < ?",
            (retired_cut,)).fetchall()]
        proposed_targets = [r["name"] for r in c.execute(
            "SELECT name FROM strategies_meta WHERE status='proposed' AND created_at < ?",
            (proposed_cut,)).fetchall()]
    n = 0
    for name in retired_targets:
        archive(name=name, reason=f"auto-archive: retired > {retired_grace_days}d", actor=actor)
        n += 1
    for name in proposed_targets:
        archive(name=name, reason=f"auto-archive: proposed > {proposed_grace_days}d", actor=actor)
        n += 1
    if n:
        log.info("auto_archive: moved %d strategies to archived", n)
    return n

