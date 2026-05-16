# Seed CSVs

This directory is bind-mounted read-only into the container at `/seed`.
On first start (when the SQLite DB is empty), the bundled CSV per game
is imported so the engine has *some* history even when external fetches
fail (corp proxy, DNS block, mirror down).

After bootstrap, the scheduled fetcher (see `LOTTO_ORACLE_FETCH_CRON`,
default `30 3 * * 1,4`) keeps the archive up to date.

## Bundled history (≥ 30 years)

| File                   | Spiel             | Draws | Range                        |
|------------------------|-------------------|-------|------------------------------|
| `lotto-6aus49.csv`     | Lotto 6 aus 49    | ~2 590| Mi/Sa 1957 → 2022            |
| `eurojackpot.csv`      | Eurojackpot       | ~510  | Di/Fr 2012 → 2022            |
| `spiel77.csv`          | Spiel 77          | ~2 845| 1975 → 2022                  |
| `super6.csv`           | Super 6           | ~1 975| 1991 → 2022                  |
| `LOTTO_ab_2018.csv`    | Lotto + S77 + Su6 | ~940  | lotto.de bulk export 2018-   |
| `EJ_ab_2018.csv`       | Eurojackpot       | ~720  | lotto.de bulk export 2018-   |

The per-game CSVs above are generated from the operator-supplied Excel
archives under `_sources/` (`LOTTO6aus49_2021.xlsx`, `Eurojackpot.xlsx`,
`Spiel77.xlsx`, `SUPER6.xlsx`) by the `scripts/import_xlsx.py`
converter. To regenerate after dropping a fresher xlsx archive::

    pip install openpyxl              # one-time
    python3 scripts/import_xlsx.py    # writes seed_data/<game>.csv

The bulk `LOTTO_ab_2018.csv` / `EJ_ab_2018.csv` files come straight from
lotto.de's CSV export and are read by a separate parser
(`OfficialArchiveParser`) on every cron tick, so any drift between the
two source sets is silently de-duplicated by the upsert layer.

## Per-game CSV format

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

The bundled per-game CSVs already give you the full 30+ year history on
**first** start. For an **existing** install (DB already seeded with a
smaller stub), the engine will *not* re-import on container restart
(bootstrap only runs against an empty DB). Two options to ingest the
new history:

```bash
# A) cleanest: wipe the DB on the host and let bootstrap re-run
docker compose stop lotto-oracle
rm ~/dream-server/data/lotto-oracle/lotto.db
docker compose start lotto-oracle
```

Or, if you want to keep auto-generated tips and other state intact:

Easiest path:

```bash
# On the host, after the service is up:
TOKEN=$(grep ^LOTTO_ORACLE_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -fsS -X POST -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8100/refresh/full
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

