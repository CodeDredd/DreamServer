# TimescaleDB

Time-series store for the Dream Server **finance pipeline** (see
`AGENT-OPERATIONS.md` §11). Postgres + TimescaleDB extension, pinned to
`timescale/timescaledb:2.17.2-pg16`.

## What lives here

| Schema    | Tables / hypertables                                        | Producer                  |
|-----------|-------------------------------------------------------------|---------------------------|
| `finance` | `prices_intraday` (hypertable), `prices_daily` (cont. agg.) | `finance-prices`          |
| `news`    | `events` (hypertable, GIN on `symbols`)                     | `finance-news` (planned)  |
| `guru`    | reserved for trade ledgers / strategy state                 | `finance-guru-api` (planned) |

Stammdaten (top-N stocks/crypto, Marketcap, Sektor) bleiben in
**Qdrant** (`finance_assets`, populated by `finance-vector`) — that is
the *semantic* index. Time-series belong in TimescaleDB.

## Retention & compression (sized for the Halo Strix)

| Table                     | Compression after | Retention      |
|---------------------------|-------------------|----------------|
| `finance.prices_intraday` | 7 days            | 90 days        |
| `finance.prices_daily`    | —                 | 5 years        |
| `news.events`             | 14 days           | 180 days       |

The compression segments by `symbol` (intraday) / `source` (news), so
strategy backtests that scan one symbol over months stay fast even on
compressed chunks.

## Configuration (read from project `.env`)

| Variable                | Default     | Description                                  |
|-------------------------|-------------|----------------------------------------------|
| `TIMESCALEDB_PORT`      | `5434`      | external port (bound to `BIND_ADDRESS`)      |
| `TIMESCALEDB_USER`      | `finance`   | superuser for the finance DB                 |
| `TIMESCALEDB_PASSWORD`  | _required_  | **must be set** in `.env` (no default)       |
| `TIMESCALEDB_DB`        | `finance`   | database name                                |
| `TIMESCALEDB_TUNE_MEMORY` | `1GB`     | `timescaledb-tune` memory hint               |
| `TIMESCALEDB_TUNE_CPUS` | `2`         | `timescaledb-tune` cpu hint                  |

Internal services connect via docker DNS — no port mapping needed:

```
postgresql://finance:${TIMESCALEDB_PASSWORD}@timescaledb:5432/finance
```

## Bring it up

```bash
# 1. set the password (once)
echo "TIMESCALEDB_PASSWORD=$(openssl rand -hex 24)" >> ~/dream-server/.env

# 2. enable + start
dream enable timescaledb
make up SERVICES="timescaledb"

# 3. verify
docker logs --tail=80 dream-timescaledb
docker exec -it dream-timescaledb psql -U finance -d finance \
    -c "SELECT extname, extversion FROM pg_extension WHERE extname='timescaledb';"

# 4. inspect schema
docker exec -it dream-timescaledb psql -U finance -d finance -c "\dt finance.*"
docker exec -it dream-timescaledb psql -U finance -d finance -c "\dt news.*"
```

## Data directory & permissions

The Postgres image runs as **uid 70** (`postgres`). On first boot the
entrypoint chowns `/var/lib/postgresql/data` itself, so the host
directory `~/dream-server/data/timescaledb/` just needs to exist and be
writable by Docker. The `langfuse` post-install hook is the reference
pattern if you ever hit "permission denied" after a host restore.

## Backup / restore

```bash
# Hot logical backup (safe while service is up)
docker exec dream-timescaledb pg_dump -U finance -Fc -d finance \
    > ~/timescaledb-$(date +%F).dump

# Restore into an empty container
cat ~/timescaledb-2026-05-14.dump | \
    docker exec -i dream-timescaledb pg_restore -U finance -d finance --clean
```

For minor-version pin bumps (e.g. `2.17.2 → 2.17.3`) snapshot the data
directory; for **major Postgres** moves (pg16 → pg17) plan a `pg_upgrade`
window — don't just swap the tag.

## Schema evolution after first boot

`init/01-schema.sql` runs **only** when the data directory is empty.
After that, every producing service must run its own idempotent
`CREATE … IF NOT EXISTS` / `add_compression_policy(…, if_not_exists =>
true)` at startup. See `extensions/services/finance-prices/app/db.py`
for the canonical example.

