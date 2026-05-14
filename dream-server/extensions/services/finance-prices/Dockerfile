# Dream Server — Finance Intraday Price Fetcher
#
# Pulls intraday OHLCV for the top-N stocks (yfinance, batched) and
# top-N cryptos (CoinGecko) and upserts them into TimescaleDB
# (hypertable finance.prices_intraday). The universe of symbols is
# read from the Qdrant collection populated by finance-vector — so
# this service inherits "what's worth tracking" from the daily seeder.
#
# Endpoints:
#   GET  /health      -> liveness
#   GET  /status      -> last/next runs per job, row counts
#   POST /refresh     -> trigger ad-hoc fetch (?kind=stocks|crypto|all)
#                        bearer-token guarded if FINANCE_PRICES_TOKEN set

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Light-Heart-Labs/DreamServer"
LABEL org.opencontainers.image.description="Dream Server Finance Intraday Price Fetcher"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 dreamer && mkdir -p /data && chown -R dreamer:dreamer /app /data
USER dreamer

ENV FINANCE_PRICES_PORT=8096 \
    TIMESCALEDB_HOST=timescaledb \
    TIMESCALEDB_PORT_INTERNAL=5432 \
    TIMESCALEDB_DB=finance \
    TIMESCALEDB_USER=finance \
    QDRANT_URL=http://qdrant:6333 \
    FINANCE_COLLECTION=finance_assets \
    FINANCE_PRICES_TOP_STOCKS=100 \
    FINANCE_PRICES_TOP_CRYPTO=100 \
    FINANCE_PRICES_STOCKS_CRON="*/15 * * * 1-5" \
    FINANCE_PRICES_CRYPTO_CRON="*/5 * * * *" \
    FINANCE_PRICES_RUN_ON_START=auto \
    FINANCE_PRICES_RESPECT_MARKET_HOURS=true \
    PYTHONUNBUFFERED=1

EXPOSE 8096

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:${FINANCE_PRICES_PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FINANCE_PRICES_PORT}"]

