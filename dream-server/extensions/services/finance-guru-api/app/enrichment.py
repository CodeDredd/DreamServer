"""Storage for enrichment artefacts produced by external n8n workflows.

Two domains:

1. **Asset behaviour analysis** — per (symbol, window) the LLM-derived
   summary of price moves, correlated news, extracted keywords,
   confidence + the supporting news_ids so a human can audit.

2. **News source reliability** — per source/domain a rolling reliability
   score (0..1), weight, sample size, methodology. Strategies consume
   this to down-weight unreliable feeds; the dashboard shows it.

Both tables live in the finance-guru SQLite (same file as ledger +
cycle log) so we keep one persistent volume. n8n workflows POST here
via the bearer-guarded `/enrichment/*` endpoints in main.py.

The schema is deliberately conservative — we trade flexibility for
auditability. Each row carries the model alias, prompt hash and raw
LLM response so the operator can re-evaluate runs later (e.g. if a
qwen update changes scoring behaviour we still have the inputs).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from typing import Any, Iterable

from . import ledger
from . import qdrant_sink

log = logging.getLogger("finance-guru.enrichment")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS enrichment_asset_analysis (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,                      -- when stored (ISO UTC)
    symbol          TEXT NOT NULL,
    asset_type      TEXT NOT NULL DEFAULT 'stock',
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    summary         TEXT NOT NULL,                      -- 1–3 sentence LLM verdict
    keywords_json   TEXT NOT NULL,                      -- ["tariffs","rate cut",…]
    drivers_json    TEXT NOT NULL,                      -- [{"date":…,"move_pct":…,"reason":…,"news_ids":[…]}]
    news_ids_json   TEXT NOT NULL DEFAULT '[]',         -- all supporting news IDs
    confidence      REAL NOT NULL DEFAULT 0,            -- 0..1, set by the verifier step
    contradictions  TEXT,                               -- non-null iff verifier rejected the draft
    model           TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,
    raw_response    TEXT
);

CREATE INDEX IF NOT EXISTS idx_enrich_asset_symbol_ts
    ON enrichment_asset_analysis (symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_enrich_asset_period
    ON enrichment_asset_analysis (symbol, period_start, period_end);

CREATE TABLE IF NOT EXISTS enrichment_source_reliability (
    source             TEXT PRIMARY KEY,                -- e.g. "reuters.com"
    reliability        REAL NOT NULL DEFAULT 0.5,       -- 0..1
    weight             REAL NOT NULL DEFAULT 1.0,       -- 0..2, multiplier for sentiment aggregation
    sample_size        INTEGER NOT NULL DEFAULT 0,
    methodology        TEXT NOT NULL DEFAULT '',
    last_evaluated_at  TEXT NOT NULL,
    model              TEXT NOT NULL,
    raw_response       TEXT
);

CREATE TABLE IF NOT EXISTS enrichment_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    workflow     TEXT NOT NULL,                         -- 'asset_behaviour'|'source_reliability'
    target       TEXT,                                  -- symbol or source
    status       TEXT NOT NULL DEFAULT 'ok',            -- ok|error|skipped
    duration_ms  INTEGER NOT NULL DEFAULT 0,
    note         TEXT
);

CREATE INDEX IF NOT EXISTS idx_enrich_runs_ts ON enrichment_runs (ts DESC);
"""


def init_db() -> None:
    with ledger.conn() as c:
        c.executescript(SCHEMA_SQL)
    log.info("Enrichment tables ready")


# --------------------------------------------------------------------------- #
# Asset behaviour analysis
# --------------------------------------------------------------------------- #
def _hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def upsert_asset_analysis(
    *,
    symbol: str,
    asset_type: str,
    period_start: dt.datetime,
    period_end: dt.datetime,
    summary: str,
    keywords: Iterable[str],
    drivers: list[dict],
    news_ids: Iterable[Any] = (),
    confidence: float = 0.0,
    contradictions: str | None = None,
    model: str = "default",
    prompt: Any | None = None,
    raw_response: str | None = None,
) -> int:
    """Insert one analysis row. We deliberately append rather than
    upsert so the history is preserved (the operator can compare last
    week's reading to this week's).

    If the same (symbol, period_start, period_end, prompt_hash) was
    already stored, we no-op and return the existing id — keeps n8n
    idempotent on retries.
    """
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    p_hash = _hash(prompt or [symbol, period_start.isoformat(), period_end.isoformat(), summary])
    with ledger.conn() as c:
        existing = c.execute(
            "SELECT id FROM enrichment_asset_analysis "
            "WHERE symbol=? AND period_start=? AND period_end=? AND prompt_hash=?",
            (symbol, period_start.isoformat(), period_end.isoformat(), p_hash),
        ).fetchone()
        if existing:
            return int(existing["id"])
        cur = c.execute(
            "INSERT INTO enrichment_asset_analysis (ts, symbol, asset_type, "
            "period_start, period_end, summary, keywords_json, drivers_json, "
            "news_ids_json, confidence, contradictions, model, prompt_hash, raw_response) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                now, symbol, asset_type,
                period_start.isoformat(), period_end.isoformat(),
                (summary or "").strip()[:4000],
                json.dumps(sorted({str(k).strip().lower() for k in keywords if str(k).strip()})[:64]),
                json.dumps(drivers[:50], default=str),
                json.dumps(list(news_ids)[:200], default=str),
                max(0.0, min(1.0, float(confidence))),
                (contradictions or None),
                model,
                p_hash,
                (raw_response or "")[:8000] or None,
            ),
        )
        new_id = int(cur.lastrowid or 0)

    # Fire-and-forget Qdrant write so the new analysis becomes
    # semantically searchable. Failures here MUST NOT roll back the
    # SQLite insert — the n8n workflow's idempotency relies on that.
    try:
        kw_list = sorted({str(k).strip().lower() for k in keywords if str(k).strip()})[:32]
        qdrant_sink.upsert_asset_analysis(
            analysis_id=new_id,
            symbol=symbol.upper(),
            asset_type=asset_type,
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            summary=(summary or "").strip()[:2000],
            keywords=kw_list,
            drivers=drivers or [],
            news_ids=list(news_ids or []),
            confidence=max(0.0, min(1.0, float(confidence))),
            model=model,
            ts=now,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Qdrant sink for asset_analysis %s failed (non-fatal): %s",
                    symbol, exc)
    return new_id


def latest_asset_analysis(symbol: str, limit: int = 10) -> list[dict]:
    with ledger.conn() as c:
        rows = c.execute(
            "SELECT id, ts, symbol, asset_type, period_start, period_end, "
            "summary, keywords_json, drivers_json, news_ids_json, confidence, "
            "contradictions, model FROM enrichment_asset_analysis "
            "WHERE symbol = ? ORDER BY ts DESC LIMIT ?",
            (symbol, max(1, min(limit, 100))),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        d["keywords"] = json.loads(d.pop("keywords_json") or "[]")
        d["drivers"] = json.loads(d.pop("drivers_json") or "[]")
        d["news_ids"] = json.loads(d.pop("news_ids_json") or "[]")
        out.append(d)
    return out


def list_analysed_symbols(limit: int = 200) -> list[dict]:
    """Symbols that have at least one analysis, with the latest summary
    timestamp — drives the "next candidate" picker used by the n8n
    workflow to pick the stalest item."""
    with ledger.conn() as c:
        rows = c.execute(
            "SELECT symbol, asset_type, MAX(ts) AS last_ts, COUNT(*) AS n, "
            "       AVG(confidence) AS avg_confidence "
            "FROM enrichment_asset_analysis GROUP BY symbol ORDER BY last_ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# News source reliability
# --------------------------------------------------------------------------- #
def upsert_source_reliability(
    *,
    source: str,
    reliability: float,
    weight: float = 1.0,
    sample_size: int = 0,
    methodology: str = "",
    model: str = "default",
    raw_response: str | None = None,
) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    rel = max(0.0, min(1.0, float(reliability)))
    w = max(0.0, min(2.0, float(weight)))
    with ledger.conn() as c:
        c.execute(
            "INSERT INTO enrichment_source_reliability "
            "(source, reliability, weight, sample_size, methodology, "
            " last_evaluated_at, model, raw_response) "
            "VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source) DO UPDATE SET "
            "  reliability=excluded.reliability, weight=excluded.weight, "
            "  sample_size=excluded.sample_size, methodology=excluded.methodology, "
            "  last_evaluated_at=excluded.last_evaluated_at, model=excluded.model, "
            "  raw_response=excluded.raw_response",
            (source.strip().lower(), rel, w, int(sample_size),
             (methodology or "")[:2000], now, model,
             (raw_response or "")[:4000] or None),
        )
    # Propagate the reliability/weight into the finance_news Qdrant
    # payloads so existing semantic searches benefit from it. Fire-and-
    # forget — Qdrant outages don't break the SQLite upsert.
    try:
        qdrant_sink.propagate_source_weight(
            source=source.strip().lower(),
            reliability=rel, weight=w, model=model,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Qdrant source_weight propagation for %s failed (non-fatal): %s",
                    source, exc)
    return {"source": source.strip().lower(), "reliability": rel,
            "weight": w, "last_evaluated_at": now}


def list_source_reliability(limit: int = 200) -> list[dict]:
    with ledger.conn() as c:
        rows = c.execute(
            "SELECT source, reliability, weight, sample_size, methodology, "
            "last_evaluated_at, model FROM enrichment_source_reliability "
            "ORDER BY last_evaluated_at DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# Workflow run audit log
# --------------------------------------------------------------------------- #
def record_run(*, workflow: str, target: str | None,
               status: str = "ok", duration_ms: int = 0,
               note: str | None = None) -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    with ledger.conn() as c:
        cur = c.execute(
            "INSERT INTO enrichment_runs (ts, workflow, target, status, duration_ms, note) "
            "VALUES (?,?,?,?,?,?)",
            (now, workflow, target, status, int(duration_ms), (note or "")[:500] or None),
        )
        return int(cur.lastrowid or 0)


def list_runs(workflow: str | None = None, limit: int = 100) -> list[dict]:
    sql = ["SELECT id, ts, workflow, target, status, duration_ms, note "
           "FROM enrichment_runs WHERE 1=1"]
    args: list = []
    if workflow:
        sql.append("AND workflow = ?")
        args.append(workflow)
    sql.append("ORDER BY ts DESC LIMIT ?")
    args.append(max(1, min(limit, 500)))
    with ledger.conn() as c:
        rows = c.execute(" ".join(sql), tuple(args)).fetchall()
    return [dict(r) for r in rows]


def run_health(window_hours: int = 24) -> list[dict]:
    """Phase P-2.1: per-workflow run summary over the last `window_hours`.

    Returns rows shaped for the dashboard health-tile and operator
    `dream doctor` checks. Distinguishes successful runs (`ok`),
    silent-skip runs (`status in ('skip','noop')` or a note that
    matches *no.*candidate|empty.universe|skip*), and errors. Makes
    P-1 regressions visible: a workflow that silently skips for >1h
    on a weekday is a red flag operators were previously blind to.
    """
    cutoff = (dt.datetime.now(dt.timezone.utc)
              - dt.timedelta(hours=max(1, int(window_hours)))).isoformat()
    out: dict[str, dict] = {}
    with ledger.conn() as c:
        rows = c.execute(
            "SELECT workflow, status, note, ts, duration_ms "
            "FROM enrichment_runs WHERE ts >= ? ORDER BY ts DESC",
            (cutoff,),
        ).fetchall()
    for r in rows:
        wf = r["workflow"] or "unknown"
        bucket = out.setdefault(wf, {
            "workflow":   wf,
            "runs":       0,
            "ok":         0,
            "skip":       0,
            "error":      0,
            "last_ts":    None,
            "last_ok_ts": None,
            "last_skip_note": None,
            "avg_ms":     0.0,
            "_dur_sum":   0,
            "_dur_n":     0,
        })
        bucket["runs"] += 1
        if not bucket["last_ts"]:
            bucket["last_ts"] = r["ts"]
        status = (r["status"] or "").lower()
        note = (r["note"] or "").lower()
        skip_hit = (status in ("skip", "skipped", "noop", "empty")
                    or "no stale candidate" in note
                    or "empty universe" in note
                    or "no candidate" in note
                    or note.startswith("skip"))
        if status == "ok" and not skip_hit:
            bucket["ok"] += 1
            if not bucket["last_ok_ts"]:
                bucket["last_ok_ts"] = r["ts"]
        elif skip_hit:
            bucket["skip"] += 1
            if not bucket["last_skip_note"]:
                bucket["last_skip_note"] = (r["note"] or status)[:160]
        else:
            bucket["error"] += 1
        if r["duration_ms"]:
            bucket["_dur_sum"] += int(r["duration_ms"])
            bucket["_dur_n"]   += 1
    for b in out.values():
        if b["_dur_n"]:
            b["avg_ms"] = round(b["_dur_sum"] / b["_dur_n"], 1)
        b.pop("_dur_sum", None)
        b.pop("_dur_n", None)
        b["skip_ratio"] = round(b["skip"] / b["runs"], 3) if b["runs"] else 0.0
        # Heuristic verdict — surfaces silent-skip anti-pattern in one
        # field the dashboard can colour.
        if b["error"] and b["error"] / max(b["runs"], 1) > 0.25:
            b["verdict"] = "errors"
        elif b["skip_ratio"] >= 0.9 and b["runs"] >= 3:
            b["verdict"] = "silent-skip"
        elif b["ok"] == 0:
            b["verdict"] = "no-progress"
        else:
            b["verdict"] = "healthy"
    return sorted(out.values(), key=lambda x: x["workflow"])


def next_candidate(asset_type: str | None = None, stale_after_hours: int = 48,
                   universe: list[str] | None = None) -> str | None:
    """Picks the symbol whose analysis is stalest (or has none at all).
    The n8n workflow calls this to find what to enrich next.

    `universe`, when provided, is the candidate list to consider —
    typically the latest finance-prices universe. Symbols not in
    `universe` are ignored.
    """
    if not universe:
        return None
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=stale_after_hours)).isoformat()
    placeholders = ",".join("?" * len(universe))
    with ledger.conn() as c:
        rows = c.execute(
            f"SELECT symbol, MAX(ts) AS last_ts FROM enrichment_asset_analysis "
            f"WHERE symbol IN ({placeholders}) GROUP BY symbol",
            tuple(universe),
        ).fetchall()
        ts_by_sym = {r["symbol"]: r["last_ts"] for r in rows}
    # Prefer symbols never analysed; fall back to oldest beyond cutoff.
    never = [s for s in universe if s not in ts_by_sym]
    if never:
        return sorted(never)[0]
    stale = [(s, t) for s, t in ts_by_sym.items() if (t or "") < cutoff]
    if not stale:
        return None
    stale.sort(key=lambda x: x[1] or "")
    return stale[0][0]


def next_candidate_batch(asset_type: str | None = None,
                         stale_after_hours: int = 48,
                         universe: list[str] | None = None,
                         limit: int = 3) -> list[str]:
    """Batched variant of next_candidate() — returns up to `limit`
    stalest symbols. Plan §3 / Phase A: lets n8n's asset-behaviour
    workflow process multiple symbols per run instead of looping a
    5-min cron + 5-min cooldown for every single ticker.

    Order:
      1. Symbols never analysed (alphabetical for determinism)
      2. Symbols whose last analysis is older than `stale_after_hours`
         (oldest first)
      3. Stop once `limit` reached
    """
    if not universe:
        return []
    limit = max(1, min(int(limit), 50))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=stale_after_hours)).isoformat()
    placeholders = ",".join("?" * len(universe))
    with ledger.conn() as c:
        rows = c.execute(
            f"SELECT symbol, MAX(ts) AS last_ts FROM enrichment_asset_analysis "
            f"WHERE symbol IN ({placeholders}) GROUP BY symbol",
            tuple(universe),
        ).fetchall()
        ts_by_sym = {r["symbol"]: r["last_ts"] for r in rows}
    out: list[str] = []
    # 1) Never analysed (alphabetical so two parallel n8n runs don't
    #    fight over the same symbol).
    never = sorted([s for s in universe if s not in ts_by_sym])
    out.extend(never[:limit])
    if len(out) >= limit:
        return out
    # 2) Stale beyond cutoff, oldest first.
    stale = sorted(
        [(s, t) for s, t in ts_by_sym.items() if (t or "") < cutoff],
        key=lambda x: x[1] or "",
    )
    for s, _ in stale:
        if s in out:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out

