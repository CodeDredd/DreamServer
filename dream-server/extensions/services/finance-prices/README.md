# Finance Prices

Containerized intraday OHLCV fetcher that keeps the TimescaleDB
hypertable `finance.prices_intraday` up to date with:

- **Top 100 stocks** by market cap (universe sourced from Qdrant
  `finance_assets`, populated daily by `finance-vector`), via
  `yfinance.download(period='1d', interval='15m')` in batches of ~50.
- **Top 100 cryptos** by market cap, via CoinGecko `/coins/markets`
  (one bar per cycle = current price snapshot — true OHLC would cost
  1 req/coin and bust the free tier).

Two APScheduler cron jobs run inside the container; n8n can also
trigger ad-hoc refreshes via the bearer-guarded `POST /refresh`.

## Why this is separate from `finance-vector`

| Concern             | finance-vector                | finance-prices              |
|---------------------|-------------------------------|-----------------------------|
| Cadence             | 1×/day                        | 5–15 min                    |
| What it stores      | Stammdaten + last snapshot    | Tick-level OHLCV history    |
| Where it stores     | Qdrant (semantic index)       | TimescaleDB (time-series)   |
| Dominant cost       | TEI embeddings (~500 docs)    | DB writes + HTTP            |

Mixing both into one daemon would mean re-embedding 500 docs every 15
min just to update prices — pure waste. Time-series belong in
TimescaleDB; vectors stay in Qdrant.

## Endpoints

| Method | Path        | Auth    | Purpose                                                        |
|--------|-------------|---------|----------------------------------------------------------------|
| GET    | `/health`   | none    | liveness (also reports per-job running state)                  |
| GET    | `/status`   | none    | last/next runs, row-count estimate, latest timestamp           |
| POST   | `/refresh`  | bearer* | trigger ad-hoc fetch (`?kind=stocks` / `crypto` / `all`)       |

*bearer auth only enabled when `FINANCE_PRICES_TOKEN` is set.

## Configuration (read from project `.env`)

| Variable                              | Default               | Description                                          |
|---------------------------------------|-----------------------|------------------------------------------------------|
| `FINANCE_PRICES_PORT`                 | `8096`                | external port (bound to `BIND_ADDRESS`)              |
| `TIMESCALEDB_HOST`                    | `timescaledb`         | docker DNS name of the DB                            |
| `TIMESCALEDB_USER` / `_DB`            | `finance` / `finance` | role + database (created by the timescaledb service) |
| `TIMESCALEDB_PASSWORD`                | _required_            | **must** match the timescaledb service               |
| `FINANCE_COLLECTION`                  | `finance_assets`      | Qdrant collection that defines the universe          |
| `FINANCE_PRICES_TOP_STOCKS`           | `100`                 | how many stocks to fetch per cycle                   |
| `FINANCE_PRICES_TOP_CRYPTO`           | `100`                 | how many cryptos to fetch per cycle                  |
| `FINANCE_PRICES_STOCKS_CRON`          | `*/15 * * * 1-5`      | 5-field cron for stocks                              |
| `FINANCE_PRICES_CRYPTO_CRON`          | `*/5 * * * *`         | 5-field cron for crypto                              |
| `FINANCE_PRICES_TZ`                   | `${TIMEZONE:-UTC}`    | scheduler timezone                                   |
| `FINANCE_PRICES_RUN_ON_START`         | `auto`                | `auto` (run if hypertable empty), `always`, `never`  |
| `FINANCE_PRICES_RESPECT_MARKET_HOURS` | `true`                | skip stocks ticks outside 14:30–21:00 UTC Mon–Fri    |
| `FINANCE_PRICES_TOKEN`                | _empty_               | bearer token for `/refresh`; empty disables auth     |
| `COINGECKO_API_KEY`                   | _empty_               | optional CoinGecko Demo key                          |

## Bring it up

```bash
# 0. timescaledb + finance-vector must be enabled first
dream enable timescaledb finance-vector finance-prices

# 1. set passwords/tokens (once)
cat >> ~/dream-server/.env <<EOF
TIMESCALEDB_PASSWORD=$(openssl rand -hex 24)
FINANCE_PRICES_TOKEN=$(openssl rand -hex 32)
EOF

# 2. start
make up SERVICES="timescaledb finance-vector finance-prices"

# 3. observe
docker logs -f dream-finance-prices
curl -s http://127.0.0.1:8096/status | jq
```

## Free-tier cadence math

| Source     | Per-cycle calls (top-100)  | Free quota                           | Headroom                    |
|------------|----------------------------|--------------------------------------|-----------------------------|
| yfinance   | ~2 (batched 50/req)        | unwritten — but throttles >~few hundred/h unauth'd | every 15 min, MoFr → ~52/day fine |
| CoinGecko  | 1–2 (paginated /markets)   | 30 req/min (Demo key)                | every 5 min → 12/h, well under |

Going below 5 min on prices needs a paid market-data feed (Polygon,
Alpaca, Finnhub paid tier). Not worth it for the paper-trade
prototype — the 35B/122B reasoning latency is the bottleneck for
strategy reactions, not tick frequency.

## Inspecting the data

```bash
# row count + latest tick
curl -s http://127.0.0.1:8096/status | jq '.db'

# sample query in-DB
docker exec -it dream-timescaledb psql -U finance -d finance -c "
SELECT symbol, asset_type, ts, close, volume
FROM finance.prices_intraday
WHERE symbol IN ('AAPL', 'BTC')
ORDER BY ts DESC
LIMIT 10;"
```

## Trigger from n8n

Same pattern as `finance-vector`: HTTP node →
`POST http://finance-prices:8096/refresh?kind=all` with
`Authorization: Bearer {{$env.FINANCE_PRICES_TOKEN}}`. Add this to
`extensions/services/n8n/compose.yaml` `environment:` block:

```yaml
- FINANCE_PRICES_TOKEN=${FINANCE_PRICES_TOKEN:-}
```

## Roadmap fit

```
finance-vector     (1×/day) ──► Qdrant.finance_assets    (universe)
        │                              │
        └─ symbol list ◄──────────────►┘
                       │
finance-prices  (5–15 min) ──► TimescaleDB.finance.prices_intraday
finance-news    (10 min, NEXT) ─► TimescaleDB.news.events
                                       │
                                       ▼
                               finance-guru-api
                               (strategies, paper trades, LiteLLM)
                                       │
                                       ▼
                               dashboard tab "Finance Guru"
```

