# Seed CSVs

This directory is bind-mounted read-only into the container at `/seed`.
On first start (when the SQLite DB is empty), the bundled CSV per game
is imported so the engine has *some* history even when external fetches
fail (corp proxy, DNS block, mirror down).

After bootstrap, the scheduled fetcher (see `LOTTO_ORACLE_FETCH_CRON`,
default `30 3 * * 1,4`) keeps the archive up to date.

## Format

Each file is a header-row CSV. Field names are exactly the pool names
declared in `app/games.py`.

```
# extensions/services/lotto-oracle/seed_data/lotto-6aus49.csv
date,Hauptzahlen,Superzahl
2024-12-28,3 11 24 31 38 47,5

# extensions/services/lotto-oracle/seed_data/eurojackpot.csv
date,Hauptzahlen,Eurozahlen
2024-12-27,4 11 32 41 49,3 9

# extensions/services/lotto-oracle/seed_data/spiel77.csv
date,digits
2024-12-28,1234567

# extensions/services/lotto-oracle/seed_data/super6.csv
date,digits
2024-12-28,987654
```

The parser is tolerant: numbers within a pool can be space-, comma-, or
semicolon-separated; the date must be ISO `YYYY-MM-DD`.

## Manual bootstrap (full 30 years)

Easiest path:

```bash
# On the host, after the service is up:
TOKEN=$(grep ^LOTTO_ORACLE_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8099/refresh/full
```

This walks every year archive page (`history_from` → today, capped by
`LOTTO_RETENTION_YEARS`) for each game. Expect 1–3 minutes for the
combined run on a fresh install.

If your network blocks the upstream archive sites, drop hand-prepared
CSVs into this directory and run:

```bash
docker compose restart lotto-oracle
```

— or POST the CSV body to `/admin/import` with the same bearer token.

