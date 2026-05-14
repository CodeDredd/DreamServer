# Dream Server — Finance Guru API (Strategy Engine)
#
# FastAPI service that runs paper-trade strategies against the
# TimescaleDB time-series and Qdrant news pipeline built in
# steps 1-3 of the AGENT-OPERATIONS.md §11 roadmap.
#
# Endpoints:
#   GET  /health           — liveness
#   GET  /strategies       — registered plugins + last decision
#   GET  /ledger?strategy= — positions, trades, PnL per strategy
#   POST /decide           — run one decision cycle for one or all
#                            strategies (bearer-guarded)
#   POST /backtest         — replay history for one strategy
#                            (bearer-guarded; no live ledger writes)

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Light-Heart-Labs/DreamServer"
LABEL org.opencontainers.image.description="Dream Server Finance Guru API (Strategy Engine)"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN useradd -m -u 1000 dreamer && mkdir -p /data && chown -R dreamer:dreamer /app /data
USER dreamer

ENV FINANCE_GURU_PORT=8098 \
    TIMESCALEDB_HOST=timescaledb \
    TIMESCALEDB_PORT_INTERNAL=5432 \
    TIMESCALEDB_DB=finance \
    TIMESCALEDB_USER=finance \
    LITELLM_URL=http://litellm:4000/v1 \
    FINANCE_GURU_LLM_MODEL=fast \
    FINANCE_GURU_LEDGER_PATH=/data/ledger.sqlite \
    FINANCE_GURU_SEED_EUR=1000 \
    FINANCE_GURU_CRON="*/30 * * * *" \
    FINANCE_GURU_STRATEGIES=all \
    FINANCE_GURU_MAX_POSITION_FRAC=0.10 \
    FINANCE_GURU_FEE_BPS=10 \
    PYTHONUNBUFFERED=1

EXPOSE 8098

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${FINANCE_GURU_PORT}/health || exit 1

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${FINANCE_GURU_PORT}"]

