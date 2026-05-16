# Finance Guru API

FastAPI service that runs paper-trade strategies against the
TimescaleDB time-series and Qdrant news pipeline built in steps 1–3
of [`AGENT-OPERATIONS.md` §11](../../../../AGENT-OPERATIONS.md). This
is **step 4** of the roadmap: the strategy-engine skeleton.

## What it does

```
                      ┌── prices_intraday ──┐
TimescaleDB           │                     │
                      └── news.events ──────┤        ┌─ paper trade ─► SQLite ledger
                                            │        │
                                       (decide loop) │
LiteLLM (alias `fast`) ───────────────────► strategy ┤
                                            │        │
                                       APScheduler   └─ KPI snapshot
```

Two strategies ship in the skeleton:

| Plugin                | Inputs                              | LLM | Logic                                                      |
|-----------------------|-------------------------------------|-----|------------------------------------------------------------|
| `news_sentiment`      | `news.events` (last 4 h, scored)    | yes | Buy on strong-and-urgent positive headline; sell on negative news or +5% take-profit. |
| `momentum_breakout`   | `prices_intraday` (last 20 bars)    | no  | Buy on 20-bar high + 1.5× volume spike; stop at 20-bar low or +8% trail. |

Both write to a per-strategy paper ledger seeded with
`FINANCE_GURU_SEED_EUR` (default **€1 000**).

## Endpoints

| Method | Path                | Auth   | Purpose                                                       |
|--------|---------------------|--------|---------------------------------------------------------------|
| GET    | `/health`           | none   | liveness; lists registered + enabled strategies                |
| GET    | `/strategies`       | none   | per-strategy KPIs + last-cycle counters + scheduler info       |
| GET    | `/ledger?strategy=` | none   | cash, positions, trades, KPI for a strategy                    |
| POST   | `/decide`           | bearer*| trigger a live cycle (`{"strategy": "...", "all", null}`)      |
| POST   | `/backtest`         | bearer*| historical replay (no live ledger writes)                      |

*bearer auth only enabled when `FINANCE_GURU_TOKEN` is set.

## Configuration (read from project `.env`)

| Variable                       | Default                  | Description                                                |
|--------------------------------|--------------------------|------------------------------------------------------------|
| `FINANCE_GURU_PORT`            | `8098`                   | external port (bound to `BIND_ADDRESS`)                    |
| `TIMESCALEDB_*`                | (see timescaledb README) | DB connection — must match the timescaledb service          |
| `LITELLM_URL`                  | `http://litellm:4000/v1` | LiteLLM gateway                                             |
| `LITELLM_KEY` / `LITELLM_API_KEY` | _required_            | bridged in compose (`LITELLM_API_KEY=${LITELLM_KEY:-}`)     |
| `FINANCE_GURU_LLM_MODEL`       | `fast`                   | LiteLLM routing alias (see AGENT-OPERATIONS.md §10)        |
| `FINANCE_GURU_SEED_EUR`        | `1000`                   | starting cash per strategy (€)                              |
| `FINANCE_GURU_CRON`            | `*/30 * * * *`           | 5-field cron for the decide loop                            |
| `FINANCE_GURU_TZ`              | `${TIMEZONE:-UTC}`       | scheduler timezone                                          |
| `FINANCE_GURU_STRATEGIES`      | `all`                    | comma-list of strategy names, or `all`                      |
| `FINANCE_GURU_MAX_POSITION_FRAC` | `0.10`                 | max % of free cash any single buy may use                   |
| `FINANCE_GURU_FEE_BPS`         | `10`                     | simulated round-trip fee in basis points (0.10%)            |
| `FINANCE_GURU_TOKEN`           | _empty_                  | bearer token for `/decide` and `/backtest`                  |
| `FINANCE_GURU_LEDGER_PATH`     | `/data/ledger.sqlite`    | SQLite path inside the container (mounted at `data/finance-guru-api/`) |

## Plugin layout

Drop a new file in `app/strategies/`:

```python
# app/strategies/my_idea.py
from . import DecisionContext, Signal, strategy

@strategy(name="my_idea",
          description="Buy when X happens, sell when Y.",
          asset_types=("stock",))   # or ("crypto",) or both
def decide(ctx: DecisionContext) -> list[Signal]:
    if ctx.cash_eur < 10:
        return []
    return [Signal(symbol="AAPL", action="buy", qty=1.0,
                   confidence=0.7, risk=0.3,
                   reason="my_idea triggered",
                   extra={"eur_target": "max_position_frac"})]
```

That's it — restart the container, the orchestrator picks it up,
seeds it with €1 000, and starts running it on the next cron tick.

### Sizing convention

For **buy** signals, the typical pattern is `qty=1.0` plus
`extra.eur_target = "max_position_frac"`. The orchestrator will then
compute `qty = (cash * max_frac) / price`. If you want explicit
sizing, just pass the right `qty` and omit `eur_target`.

For **sell** signals, pass the actual `qty` you want to close
(usually `pos.qty` from the context).

## Bring it up

```bash
# 0. dependencies (must already be enabled & healthy)
dream enable timescaledb finance-prices finance-news finance-guru-api

# 1. set token (recommended for /decide and /backtest)
echo "FINANCE_GURU_TOKEN=$(openssl rand -hex 32)" >> ~/dream-server/.env

# 2. start
make up SERVICES="timescaledb finance-prices finance-news finance-guru-api"

# 3. observe
docker logs -f dream-finance-guru-api
curl -s http://127.0.0.1:8098/strategies | jq
```

## Manual decide / backtest

```bash
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2-)

# Run one live cycle of every enabled strategy.
curl -fsS -X POST -H "Authorization: Bearer $TOK" \
     -H "Content-Type: application/json" \
     -d '{"strategy":"all"}' \
     http://127.0.0.1:8098/decide | jq

# Inspect the news_sentiment ledger.
curl -fsS "http://127.0.0.1:8098/ledger?strategy=news_sentiment" | jq

# Backtest momentum_breakout over the last 7 days at 1-hour steps.
curl -fsS -X POST -H "Authorization: Bearer $TOK" \
     -H "Content-Type: application/json" \
     -d '{"strategy":"momentum_breakout","step_minutes":60}' \
     http://127.0.0.1:8098/backtest | jq '.total_pnl_pct, .n_trades'
```

## Trigger from n8n

`FINANCE_GURU_TOKEN` is exposed in the n8n container env (see
`extensions/services/n8n/compose.yaml`). HTTP node →

```
POST http://finance-guru-api:8098/decide
Authorization: Bearer {{$env.FINANCE_GURU_TOKEN}}
Content-Type: application/json
Body: {"strategy": "all"}
```

## KPI semantics

```
realised_pnl_eur   sum of realised P&L from closed sells (incl. fees)
unrealised_pnl_eur (current_price - avg_entry) * qty across open positions
equity_eur         cash + Σ(qty * current_price)   ← the one number that matters
total_pnl_pct      (equity − seed) / seed × 100   ← the one to compare to 10%/week
```

The 10 %/week target from AGENT-OPERATIONS.md §11 is a **KPI**, not a
constraint — the engine doesn't refuse to trade when it falls below.
The dashboard (step 5) will be the place to compare strategies side
by side and pick survivors.

## Cost discipline

- News classification is **already done** by the finance-news service
  at ingest time; this service never re-classifies. Strategies just
  read the precomputed `sentiment` / `urgency` columns.
- `news_sentiment` only calls the LLM **after** it has decided to act,
  to polish the human-readable `reason` string. Latency-critical
  branches don't touch the LLM.
- `momentum_breakout` is pure-Python, zero LLM calls.
- Backtests pre-pull all data once and replay in-memory — they don't
  re-query TimescaleDB per step.

## Roadmap fit

```
finance-vector  (1/day)    ──► Qdrant.finance_assets
finance-prices  (5–15 min) ──► TimescaleDB.finance.prices_intraday
finance-news    (10 min)  ─┬─► TimescaleDB.news.events
                           └─► Qdrant.finance_news
                                       │
                                       ▼
                  ✅ finance-guru-api  ←── you are here
                  (FastAPI strategies, paper ledger, LiteLLM)
                                       │
                                       ▼
                  ⏭ dashboard tab "Finance Guru" (step 5)
                  ⏭ finance-social    (step 6)
```

## Phase D — LLM strategy genesis (DSL)

Generated strategies are stored as a small JSON DSL in
`strategies_meta.source_json` and materialised into callable
`StrategyDef` instances by `app/strategies/llm_generated.py`.

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET  /strategies/dsl/catalog` | none | signal whitelist, op/sizing/action lists, promotion-gate config — consumed by the n8n genesis workflow so the LLM always sees the authoritative vocabulary. |
| `POST /strategies/propose` | bearer | validates DSL, inserts a `proposed` row, dispatches the genesis backtest in the background (override with `?auto_backtest=false`). |
| `POST /strategies/{name}/evaluate` | bearer | re-runs the genesis evaluation (e.g. after a Timescale outage). `?sync=true` returns the outcome inline. |

`n8n/12-finance-strategy-genesis.json` runs every 6 hours: queries the
DSL catalog, the 7-day leaderboard, and three RAG collections
(asset-analysis, relations, strategy-lessons), asks the reasoning
model (`Qwen3.5-122B-A10B`) for 1–3 DSL candidates, validates them
locally, and POSTs each to `/strategies/propose`. The server then
backtests over the last
`FINANCE_GURU_GENESIS_BT_DAYS` days and auto-promotes any candidate
whose `total_pnl_pct ≥ FINANCE_GURU_GENESIS_MIN_BT_PCT` and
`n_trades ≥ FINANCE_GURU_GENESIS_MIN_BT_TRADES`. Everything else is
archived with a deterministic reason + a tiny lesson embedded so the
next cycle doesn't re-propose the same pattern.

### DSL example

```json
{
  "version": 1,
  "description": "Buy oil majors on strong positive headlines, take +5% / stop -4%.",
  "asset_types": ["stock"],
  "max_position_frac": 0.08,
  "universe_filter": { "symbols": ["XOM", "CVX", "BP"] },
  "rules": [
    { "id": "entry",
      "action": "buy",
      "when": { "all": [
        { "signal": "news.sentiment_max", "lookback_h": 4, "op": ">=", "value": 0.5 },
        { "signal": "news.urgency_max",   "lookback_h": 4, "op": ">=", "value": 0.4 }
      ]},
      "sizing": { "mode": "max_position_frac" },
      "reason": "Strong positive news for {symbol}"
    },
    { "id": "tp", "action": "sell",
      "when": { "all": [ { "signal": "position.pnl_pct", "op": ">=", "value": 0.05 } ]},
      "reason": "Take profit +5%"
    },
    { "id": "sl", "action": "sell",
      "when": { "all": [ { "signal": "position.pnl_pct", "op": "<=", "value": -0.04 } ]},
      "reason": "Stop loss -4%"
    }
  ]
}
```

### Genesis env-vars

| Variable | Default | Description |
|---|---|---|
| `FINANCE_GURU_GENESIS_BT_DAYS`         | `30`  | backtest window before promotion |
| `FINANCE_GURU_GENESIS_BT_STEP_MIN`     | `60`  | minutes per backtest step |
| `FINANCE_GURU_GENESIS_BT_UNIVERSE`     | `40`  | top-N symbols by row count |
| `FINANCE_GURU_GENESIS_MIN_BT_PCT`      | `4.0` | min realised %-PnL to promote |
| `FINANCE_GURU_GENESIS_MIN_BT_TRADES`   | `5`   | min n_trades to promote |


