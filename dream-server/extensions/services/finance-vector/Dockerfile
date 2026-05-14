# Dream Server — Finance Vector Seeder
#
# Pulls top-N stocks (Wikipedia + yfinance) and top-N cryptos (CoinGecko)
# and upserts them into Qdrant via local TEI embeddings.
#
# Exposes a tiny FastAPI:
#   GET  /health      -> liveness
#   GET  /status      -> last/next run, point counts
#   POST /refresh     -> trigger ad-hoc seed (background) [bearer token]
#
# An in-process APScheduler runs the daily cron defined by
# FINANCE_REFRESH_CRON (default: "17 3 * * *", i.e. 03:17 UTC daily).

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Light-Heart-Labs/DreamServer"
LABEL org.opencontainers.image.description="Dream Server Finance Vector Seeder"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 dreamer && mkdir -p /data && chown -R dreamer:dreamer /app /data
USER dreamer

ENV FINANCE_VECTOR_PORT=8095 \
    QDRANT_URL=http://qdrant:6333 \
    EMBEDDINGS_URL=http://embeddings:80 \
    FINANCE_COLLECTION=finance_assets \
    FINANCE_TOP_STOCKS=250 \
    FINANCE_TOP_CRYPTO=250 \
    FINANCE_REFRESH_CRON="17 3 * * *" \
    FINANCE_RUN_ON_START=auto \
    PYTHONUNBUFFERED=1

EXPOSE 8095

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:${FINANCE_VECTOR_PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FINANCE_VECTOR_PORT}"]

