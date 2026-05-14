# Finance Vector

Containerized seeder that keeps a Qdrant collection (`finance_assets`) up to date with:

- **Top 250 stocks** by market capitalization, drawn from S&P 500 + NASDAQ-100 + DAX (Wikipedia → `yfinance` enrichment).
- **Top 250 cryptocurrencies** by market capitalization, from CoinGecko `/coins/markets` (free tier; optional Demo API key supported).

Embeddings are produced **locally** via the `embeddings` service (TEI, default `BAAI/bge-base-en-v1.5`, 768 dim). No data leaves your network except the upstream HTTP reads from Wikipedia / Yahoo / CoinGecko.

## Architecture

```
        n8n (cron / manual)         APScheduler (in-process)
                │                            │
                └──── HTTP POST /refresh ────┘
                              │
                  ┌─── dream-finance-vector ───┐
                  │ 1. Wikipedia + yfinance    │
                  │ 2. CoinGecko markets       │
                  │ 3. TEI /embed (batched)    │
                  │ 4. Qdrant upsert (UUID5)   │
                  └──────────┬─────────────────┘
                             │ internal docker DNS
                ┌────────────┴───────────┐
                ▼                        ▼
          dream-qdrant            dream-embeddings
          :6333  :6334            :80
```

Everything talks over the shared `dream-network`, so service-to-service calls are encrypted-by-network-isolation and never leave the host.

## Why this design?

| Option | Verdict |
|---|---|
| Cron on Pi5 (Open Claw) calling the Halo over SSH | ❌ extra network hops, fragile auth, splits ops across two boxes |
| n8n cron node running Python inline | ❌ painful retry/lib management; n8n UI nodes can't sustain a 3–5 min job well |
| **Dedicated container on the Halo + n8n trigger** | ✅ data-locality with Qdrant/TEI, n8n becomes the future news/orchestration layer, room to grow |

The same pattern will fit **news / social-media ingestion later** (one container per source, n8n wires them together, all upserts hit Qdrant on the same network).

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET    | `/health`  | none | liveness |
| GET    | `/status`  | none | last/next run, current point count, schedule |
| POST   | `/refresh` | bearer (if `FINANCE_VECTOR_TOKEN` set) | trigger ad-hoc seed; `?recreate=true` rebuilds the collection |

## Configuration

All env vars read from the project `.env`:

| Variable | Default | Description |
|---|---|---|
| `FINANCE_VECTOR_PORT` | `8095` | external port (bound to `BIND_ADDRESS`) |
| `FINANCE_COLLECTION` | `finance_assets` | Qdrant collection name |
| `FINANCE_TOP_STOCKS` | `250` | how many stocks to keep |
| `FINANCE_TOP_CRYPTO` | `250` | how many cryptos to keep |
| `FINANCE_REFRESH_CRON` | `17 3 * * *` | crontab in 5-field form |
| `FINANCE_REFRESH_TZ` | `${TIMEZONE:-UTC}` | scheduler timezone |
| `FINANCE_RUN_ON_START` | `auto` | `auto` (only if collection empty), `always`, `never` |
| `FINANCE_VECTOR_TOKEN` | _empty_ | bearer token for `/refresh`; empty disables auth |
| `COINGECKO_API_KEY` | _empty_ | optional CoinGecko Demo key (`x-cg-demo-api-key`) |
| `QDRANT_URL` | `http://qdrant:6333` | internal address |
| `QDRANT_API_KEY` | _empty_ | passed through if your Qdrant is auth-protected |
| `EMBEDDINGS_URL` | `http://embeddings:80` | internal address |

## Bring it up

From the project root on the Halo Strix:

```bash
# 1. enable the deps
make up SERVICES="qdrant embeddings n8n"

# 2. add the new vars (example) to .env
cat >> .env <<'EOF'
FINANCE_VECTOR_TOKEN=$(openssl rand -hex 32)
COINGECKO_API_KEY=
FINANCE_REFRESH_CRON=17 3 * * *
EOF

# 3. start the seeder (will auto-seed if the collection is empty)
make up SERVICES="finance-vector"

# 4. observe
docker logs -f dream-finance-vector
curl -s http://127.0.0.1:8095/status | jq
```

## Trigger from n8n

The workflow `config/n8n/finance-vector-refresh.json` is auto-loaded by the n8n container (it mounts `./config/n8n`). It contains:

- a Schedule trigger (03:17 UTC daily — duplicate of the in-process cron, **disable one** to avoid double runs)
- a Manual trigger
- HTTP node → `POST http://finance-vector:8095/refresh` (with `Authorization: Bearer {{$env.FINANCE_VECTOR_TOKEN}}`)
- Wait 30s → `GET /status` so the run summary shows up in the workflow log

For the bearer header to resolve, expose the token to n8n by adding this line to `extensions/services/n8n/compose.yaml` `environment:` block:

```yaml
- FINANCE_VECTOR_TOKEN=${FINANCE_VECTOR_TOKEN:-}
```

Recommendation: **disable the in-process scheduler** (`FINANCE_REFRESH_CRON=` empty is not supported, so set `FINANCE_RUN_ON_START=never` and use n8n only) once you start using n8n as the central scheduler — that way the same dashboard tracks every job.

## Using the collection from your AI stack

```python
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

q = QdrantClient(url="http://qdrant:6333")
hits = q.search(
    collection_name="finance_assets",
    query_vector=embed("Wie ist Apple aufgestellt?"),
    query_filter=qm.Filter(must=[qm.FieldCondition(
        key="type", match=qm.MatchValue(value="stock"))]),
    limit=5,
)
for h in hits:
    print(h.payload["symbol"], h.payload["name"], h.payload["last_updated"], h.score)
```

In the system prompt for Qwen 3.6, **always** pass `last_updated` + `price` + `market_cap` from the payload and instruct the model not to invent numbers. That is the actual anti-hallucination lever — embeddings only get you the right document, the prompt does the rest.

## Roadmap fit (news / social / strategy layer)

This service is intentionally narrow. The next layers slot in like this:

```
            ┌──── finance-vector (this service)  ─── stocks + crypto stamm­daten
            │
            │     finance-news        ─── RSS / Yahoo headlines  ─┐
n8n  ───────┼─    finance-social      ─── X/Reddit firehose      ─┤── upsert into
            │     finance-events      ─── earnings calendar      ─┤   `finance_news`
            │                                                    ─┘   (separate collection,
            │                                                          same dim)
            └──── finance-guru-api    ─── strategy engine that joins
                                          finance_assets + finance_news
                                          and queries Qwen via LiteLLM
```

A separate Qdrant collection per source keeps schema clean; cross-collection joins happen in the strategy service via metadata (symbol, timestamp window). For correlation you'll want a small time-series store too (Prometheus, TimescaleDB, or even ClickHouse) — vectors alone aren't great for "price moved X% within Y minutes of news Z".

## Troubleshooting

```bash
docker logs --tail=200 dream-finance-vector
curl -s http://127.0.0.1:8095/status | jq

# manually rebuild from scratch
curl -X POST -H "Authorization: Bearer $FINANCE_VECTOR_TOKEN" \
  "http://127.0.0.1:8095/refresh?recreate=true"

# verify in Qdrant
curl -s http://127.0.0.1:6333/collections/finance_assets | jq
```

Common gotchas:

- **Embedding dim mismatch** after switching `EMBEDDING_MODEL`: call `/refresh?recreate=true` once.
- **CoinGecko 429**: set `COINGECKO_API_KEY` (free Demo plan) — gives you 30 req/min reliably.
- **yfinance timeouts**: usually transient; the next scheduled run will repair.

