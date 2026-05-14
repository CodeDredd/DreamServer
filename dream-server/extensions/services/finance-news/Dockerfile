# Dream Server — Finance News Aggregator
#
# Pulls headlines from a curated RSS feed list (Yahoo Finance, Reuters,
# Handelsblatt, CNBC, MarketWatch, CoinDesk, ...), enriches each item
# with (symbols, sentiment, urgency) via the local LiteLLM (qwen3-4b),
# and writes the result into TWO sinks:
#
#   1. TimescaleDB news.events hypertable  → fast time-joins with prices
#   2. Qdrant finance_news collection      → semantic similarity search
#                                            ("find news similar to X")
#
# Both sinks are required for the strategy engine planned in
# AGENT-OPERATIONS.md §11 (news_sentiment, event_driven, ...).
#
# Endpoints:
#   GET  /health      -> liveness
#   GET  /status      -> last/next runs, row counts, feed health
#   POST /refresh     -> trigger ad-hoc fetch (bearer-token guarded
#                        when FINANCE_NEWS_TOKEN is set)
#   POST /search      -> semantic search over news (proxy to Qdrant)

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Light-Heart-Labs/DreamServer"
LABEL org.opencontainers.image.description="Dream Server Finance News Aggregator"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 dreamer && mkdir -p /data && chown -R dreamer:dreamer /app /data
USER dreamer

ENV FINANCE_NEWS_PORT=8097 \
    TIMESCALEDB_HOST=timescaledb \
    TIMESCALEDB_PORT_INTERNAL=5432 \
    TIMESCALEDB_DB=finance \
    TIMESCALEDB_USER=finance \
    QDRANT_URL=http://qdrant:6333 \
    EMBEDDINGS_URL=http://embeddings:80 \
    SEARXNG_URL=http://searxng:8080 \
    LITELLM_URL=http://litellm:4000/v1 \
    FINANCE_NEWS_COLLECTION=finance_news \
    FINANCE_COLLECTION=finance_assets \
    FINANCE_NEWS_LLM_MODEL=fast \
    FINANCE_NEWS_LLM_BATCH=16 \
    FINANCE_NEWS_USE_LLM=true \
    FINANCE_NEWS_USE_SEARXNG=false \
    FINANCE_NEWS_CRON="*/10 * * * *" \
    FINANCE_NEWS_RUN_ON_START=auto \
    FINANCE_NEWS_MAX_PER_FEED=50 \
    FINANCE_NEWS_DEDUP=true \
    PYTHONUNBUFFERED=1

EXPOSE 8097

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${FINANCE_NEWS_PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FINANCE_NEWS_PORT}"]

