# Finance News

Aggregates finance-relevant headlines from a curated RSS feed list,
tags each item with the symbols it mentions (against the universe in
Qdrant `finance_assets`), classifies sentiment + urgency via LiteLLM
(`qwen3-4b`), and writes the result into **two sinks**:

1. **TimescaleDB** `news.events` hypertable — time-series joins with
   `finance.prices_intraday` ("price moved X % within Y min of news Z").
2. **Qdrant** `finance_news` collection — semantic similarity search
   ("show me news similar to this one") for the strategy engine and the
   future dashboard tab.

Per [`AGENT-OPERATIONS.md` §11](../../../../AGENT-OPERATIONS.md) this
is **step 3** of the finance-pipeline build order.

## How it works

```
RSS feeds (parallel) ──► dedup vs news.events ──► tag symbols (Qdrant universe)
                                                       │
                                                       ▼
                                         classify sentiment + urgency
                                          (LiteLLM qwen3-4b, batched)
                                                       │
                                ┌──────────────────────┴──────────────────────┐
                                ▼                                             ▼
                  TimescaleDB news.events                        Qdrant finance_news
                  (id, ts, symbols, sentiment,                   (vector, payload incl.
                   urgency, payload JSONB)                        symbols + sentiment)
```

## Why two sinks?

The finance-vector service already explained why vectors are the wrong
tool for *"price moved X% within Y min of news Z"* — that's a time-join,
which belongs in TimescaleDB. But strategies will *also* want
*"find news similar to this one across the last 30 days"* — that's a
nearest-neighbour search, which belongs in Qdrant. Each headline
therefore lands in both stores; the `id` column in TimescaleDB and the
`doc_id` payload in Qdrant are the same SHA-1 hash so we can join them.

## Endpoints

| Method | Path        | Auth   | Purpose                                                 |
|--------|-------------|--------|---------------------------------------------------------|
| GET    | `/health`   | none   | liveness + running-cycle state                          |
| GET    | `/status`   | none   | feed counters, DB/Qdrant stats, scheduler info, LLM cfg |
| POST   | `/refresh`  | bearer*| trigger ad-hoc cycle (no body)                          |
| POST   | `/search`   | none   | semantic search (`{"q":"...", "limit":10, "symbols":["AAPL"]}`) |

*bearer auth only enabled when `FINANCE_NEWS_TOKEN` is set.

## Configuration (read from project `.env`)

| Variable                     | Default                  | Description                                       |
|------------------------------|--------------------------|---------------------------------------------------|
| `FINANCE_NEWS_PORT`          | `8097`                   | external port (bound to `BIND_ADDRESS`)           |
| `TIMESCALEDB_*`              | (see timescaledb README) | DB connection — must match the timescaledb svc    |
| `QDRANT_URL`                 | `http://qdrant:6333`     | Qdrant service                                    |
| `QDRANT_API_KEY`             | _empty_                  | Qdrant API key                                    |
| `FINANCE_NEWS_COLLECTION`    | `finance_news`           | Qdrant collection name                            |
| `FINANCE_COLLECTION`         | `finance_assets`         | symbol-universe collection (from finance-vector)  |
| `EMBEDDINGS_URL`             | `http://embeddings:80`   | TEI embedding service                             |
| `FINANCE_NEWS_FEEDS`         | _empty (= curated list)_ | comma-separated RSS URLs to override the defaults |
| `FINANCE_NEWS_USE_LLM`       | `true`                   | classify sentiment + urgency via LiteLLM          |
| `FINANCE_NEWS_LLM_MODEL`     | `qwen3-4b`               | LiteLLM model alias                               |
| `FINANCE_NEWS_LLM_BATCH`     | `16`                     | headlines per LLM call                            |
| `LITELLM_URL`                | `http://litellm:4000/v1` | LiteLLM gateway                                   |
| `FINANCE_NEWS_CRON`          | `*/10 * * * *`           | 5-field cron (per §11 cadence table)              |
| `FINANCE_NEWS_TZ`            | `${TIMEZONE:-UTC}`       | scheduler timezone                                |
| `FINANCE_NEWS_RUN_ON_START`  | `auto`                   | `auto` (run if hypertable empty), `always`, `never` |
| `FINANCE_NEWS_MAX_PER_FEED`  | `50`                     | newest-N items pulled per feed per cycle          |
| `FINANCE_NEWS_DEDUP`         | `true`                   | drop items already in news.events (last 14 days)  |
| `FINANCE_NEWS_TOKEN`         | _empty_                  | bearer token for `/refresh`                       |
| `FINANCE_NEWS_USE_SEARXNG`   | `false`                  | (reserved) SearXNG fallback for ad-hoc searches   |

## Default RSS feeds

If `FINANCE_NEWS_FEEDS` is empty, this curated list is used (per-feed
failures are logged and tolerated):

| Channel            | URL                                                                              |
|--------------------|----------------------------------------------------------------------------------|
| `yahoo-finance`    | `https://finance.yahoo.com/news/rssindex`                                        |
| `reuters-business` | `https://www.reutersagency.com/feed/?best-topics=business-finance&post_type=best`|
| `handelsblatt`     | `https://www.handelsblatt.com/contentexport/feed/finanzen`                       |
| `cnbc-top`         | `https://www.cnbc.com/id/100003114/device/rss/rss.html`                          |
| `marketwatch-top`  | `https://feeds.content.dowjones.io/public/rss/mw_topstories`                     |
| `seekingalpha`     | `https://seekingalpha.com/market_currents.xml`                                   |
| `coindesk`         | `https://www.coindesk.com/arc/outboundfeeds/rss/`                                |

To replace, set
`FINANCE_NEWS_FEEDS="https://example.com/a.xml,https://example.com/b.rss"`.

## Bring it up

```bash
# 0. dependencies (must be enabled and healthy first)
dream enable timescaledb finance-vector embeddings finance-news

# 1. set token (optional but recommended)
echo "FINANCE_NEWS_TOKEN=$(openssl rand -hex 32)" >> ~/dream-server/.env

# 2. start
make up SERVICES="timescaledb finance-vector embeddings finance-news"

# 3. observe
docker logs -f dream-finance-news
curl -s http://127.0.0.1:8097/status | jq
```

## Sample queries

```bash
# Latest news rows in TimescaleDB
docker exec dream-timescaledb psql -U finance -d finance -c "
SELECT ts, source, channel, symbols, sentiment, title
FROM news.events
ORDER BY ts DESC
LIMIT 20;"

# All news touching AAPL in the last 24h
docker exec dream-timescaledb psql -U finance -d finance -c "
SELECT ts, channel, sentiment, urgency, title
FROM news.events
WHERE 'AAPL' = ANY(symbols)
  AND ts >= now() - interval '24 hours'
ORDER BY ts DESC;"

# Semantic search (Qdrant)
curl -s -X POST http://127.0.0.1:8097/search \
  -H 'Content-Type: application/json' \
  -d '{"q":"Federal Reserve rate decision impact on tech stocks","limit":5}' | jq
```

## Cost / cadence math (free-tier)

| Workload                   | Per cycle (10 min)         | Daily        |
|----------------------------|----------------------------|--------------|
| RSS HTTP                   | 7 feeds × 1 req            | 1 008 req    |
| Symbol tagging             | 0 net (in-process regex)   | —            |
| LiteLLM classifications    | ~50 headlines / 16 batch ≈ 4 calls | ~576 calls (qwen3-4b warm-loaded → trivial) |
| TEI embeddings             | ~50 vectors                | ~7 200 vec   |
| TimescaleDB writes         | ~50 inserts                | trivial      |
| Qdrant upserts             | ~50 points                 | trivial      |

If you ever flip to a 5-min cadence, double the above — still well
under any practical limit. The LiteLLM call is the slowest step;
qwen3-4b on warm-loaded Lemonade typically returns in 1–3 s for a
batch of 16 headlines.

## Trigger from n8n

`FINANCE_NEWS_TOKEN` is exposed in the n8n container env (see
`extensions/services/n8n/compose.yaml`). HTTP node →

```
POST http://finance-news:8097/refresh
Authorization: Bearer {{$env.FINANCE_NEWS_TOKEN}}
```

## Troubleshooting

* **LLM classification is silently skipped.** Check
  `curl :8097/status | jq .llm` — `enabled: false` means
  `FINANCE_NEWS_USE_LLM=false`. Otherwise the per-cycle log line will
  show the LiteLLM HTTP error.
* **Universe is empty / no symbols are extracted.** finance-vector
  hasn't seeded `finance_assets` yet, or the Qdrant API key changed.
  `curl :8097/status | jq .universe` shows the size.
* **Feeds keep returning 0 items.** Many publishers rotate RSS URLs.
  Override the list with `FINANCE_NEWS_FEEDS=…` and restart. The
  per-feed counters under `/status` show which URL is failing.

## Roadmap fit

```
finance-vector  (1/day)   ──► Qdrant.finance_assets   (universe)
finance-prices  (5–15min) ──► TimescaleDB.finance.prices_intraday
finance-news    (10 min)  ─┬─► TimescaleDB.news.events
                           └─► Qdrant.finance_news
finance-social  (15 min, NEXT) ─► same shape, social channels
                                       │
                                       ▼
                               finance-guru-api
                               (strategies, paper trades, LiteLLM)
                                       │
                                       ▼
                               dashboard tab "Finance Guru"
```

