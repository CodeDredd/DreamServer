# Dream Server — Finance Social Aggregator
#
# Pulls Reddit submissions from a curated subreddit list (wallstreetbets,
# stocks, investing, CryptoCurrency, ...), tags them with finance symbols
# from the shared finance_assets universe, classifies sentiment + urgency
# via the local LiteLLM (`fast` alias = qwen3-4b), and writes to two sinks:
#
#   1. TimescaleDB social.events hypertable  → fast time-joins with prices
#                                              and news.events
#   2. Qdrant finance_social collection      → semantic search over posts
#
# Same shape as finance-news on purpose: a strategy can UNION ALL across
# news.events + social.events and treat both as "signal events".
#
# Endpoints:
#   GET  /health      -> liveness
#   GET  /status      -> last/next runs, row counts, per-subreddit counters
#   POST /refresh     -> trigger ad-hoc fetch (bearer-token guarded
#                        when FINANCE_SOCIAL_TOKEN is set)
#   POST /search      -> semantic search over the Qdrant collection

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Light-Heart-Labs/DreamServer"
LABEL org.opencontainers.image.description="Dream Server Finance Social Aggregator"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 dreamer && mkdir -p /data && chown -R dreamer:dreamer /app /data
USER dreamer

ENV FINANCE_SOCIAL_PORT=8099 \
    TIMESCALEDB_HOST=timescaledb \
    TIMESCALEDB_PORT_INTERNAL=5432 \
    TIMESCALEDB_DB=finance \
    TIMESCALEDB_USER=finance \
    QDRANT_URL=http://qdrant:6333 \
    EMBEDDINGS_URL=http://embeddings:80 \
    LITELLM_URL=http://litellm:4000/v1 \
    FINANCE_SOCIAL_COLLECTION=finance_social \
    FINANCE_COLLECTION=finance_assets \
    FINANCE_SOCIAL_LLM_MODEL=fast \
    FINANCE_SOCIAL_LLM_BATCH=16 \
    FINANCE_SOCIAL_USE_LLM=true \
    FINANCE_SOCIAL_CRON="*/15 * * * *" \
    FINANCE_SOCIAL_RUN_ON_START=auto \
    FINANCE_SOCIAL_MAX_PER_SUB=50 \
    FINANCE_SOCIAL_DEDUP=true \
    FINANCE_SOCIAL_MIN_SCORE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${FINANCE_SOCIAL_PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FINANCE_SOCIAL_PORT}"]

