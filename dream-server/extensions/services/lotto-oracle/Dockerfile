# Dream Server — Lotto Oracle (Tip Engine)
#
# FastAPI service that ingests German lottery draw history (Lotto 6aus49,
# Eurojackpot, Super6, Spiel77), keeps ~30 years of draws in SQLite, and
# generates suggested tips via several strategies (frequency, cold/due,
# recency-exclude, gap-analysis, balanced, anti-pattern, random-baseline).
#
# Endpoints (see app/main.py):
#   GET  /health            — liveness
#   GET  /games             — game definitions + last draw + counts
#   GET  /draws?game=…      — paginated draw history
#   GET  /stats?game=…      — frequency / co-occurrence / gap analytics
#   GET  /tips?game=…       — last generated tips
#   POST /tips/generate     — run all strategies, persist suggestions
#   POST /refresh           — incremental fetch from external sources
#
# IMPORTANT: There is no public/legal API to *submit* lottery tips in
# Germany. LOTTO24 / Tipp24 / Lotto.de require a registered customer
# account + payment method and do not expose REST endpoints. This
# service generates tips and exports them in human-friendly form
# (JSON, plain text, optional QR code); the operator submits manually.

FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/Light-Heart-Labs/DreamServer"
LABEL org.opencontainers.image.description="Dream Server Lotto Oracle (Tip Engine)"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        gosu \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Container starts as root so the entrypoint can chown the bind-mounted
# /data volume to UID 1000 (dreamer) — same pattern as finance-guru-api.
RUN useradd -m -u 1000 dreamer && mkdir -p /data && chown -R dreamer:dreamer /app /data

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENV LOTTO_ORACLE_PORT=8099 \
    LOTTO_ORACLE_DB_PATH=/data/lotto.sqlite \
    LOTTO_ORACLE_FETCH_CRON="30 3 * * 1,4" \
    LOTTO_ORACLE_TZ=Europe/Berlin \
    LOTTO_ORACLE_AUTO_GENERATE=1 \
    LOTTO_RETENTION_YEARS=30 \
    LOTTO_FETCH_TIMEOUT_SEC=20 \
    PYTHONUNBUFFERED=1

EXPOSE 8099

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:${LOTTO_ORACLE_PORT}/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${LOTTO_ORACLE_PORT}"]

