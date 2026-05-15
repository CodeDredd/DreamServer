# AGENT OPERATIONS — Context for new AI/Copilot sessions

> Paste this into a new chat as the first message when you want the AI to
> pick up where the last session left off.  It contains everything the
> assistant needs to operate on your two boxes (Halo Strix + Open Claw on
> Pi 5) without re-discovering the layout or repeating mistakes already
> caught.

## 1. Servers

| Alias        | Host                                     | Role                                                                |
|--------------|------------------------------------------|---------------------------------------------------------------------|
| **Halo Strix** | `sky-net@192.168.178.110`              | Primary DreamServer host (AMD backend, this repo's `dream-server/`) |
| **Open Claw**  | `claw-pi5` (SSH alias in `~/.ssh/config`) | Open Claw on Pi 5 — secondary AI-agent runtime                      |

### SSH

Don't paste passwords into prompts or commit them.  Set up once on your
WSL workstation:

```bash
ssh-copy-id sky-net@192.168.178.110         # pubkey auth, no more sshpass
# or, if you must keep password auth, store the password in your shell's
# secret manager (1password CLI, pass, etc.) and export $SSHPASS at session
# start so sshpass -e picks it up.
```

The earlier sessions used `sshpass -e` with `SSHPASS` env-var set.
That keeps the password out of `ps`, history, and any committed file.
**Never** commit the password to this repo (it's effectively public).

## 2. Repo layout

```
DreamServer/                    ← meta-repo (this directory)
├── AGENT-OPERATIONS.md         ← THIS file — operator context
├── dream-server/               ← upstream Dream Server fork (most code lives here)
│   ├── dream-cli               ← all dream <subcommand> entry-points
│   ├── extensions/services/<sid>/
│   │   ├── compose.yaml         ← active = enabled
│   │   ├── compose.yaml.disabled← active = disabled (flip via dream enable/disable)
│   │   ├── Dockerfile           ← only if locally built
│   │   └── manifest.yaml
│   ├── installers/phases/08-images.sh   ← parallel image pin list
│   ├── scripts/
│   │   ├── sync-from-repo.sh           ← repo→install rsync + state preserve
│   │   ├── check-image-updates.py      ← dream check-image-updates
│   │   └── audit-extensions.py         ← dream audit
│   └── docs/
│       ├── IMAGE-UPDATES.md
│       ├── ADR-IMAGE-TAG-PINNING.md
│       └── …
├── installer/                  ← Tauri dashboard installer (separate project)
└── resources/                  ← reference material (cookbooks, blogs, frameworks)
```

The **Halo Strix** has two parallel paths:

* `~/DreamServer/`            → git working copy, `git pull` lives here
* `~/dream-server/`           → install dir; runtime state, `.env`, `data/`,
                                user-flipped `compose.yaml.disabled` markers

`dream sync --pull` reconciles them (see §5).

## 3. Active service inventory (Halo Strix)

Last verified state (re-run `dream status` to refresh):

| Service           | Image                                                          | Notes                                  |
|-------------------|----------------------------------------------------------------|----------------------------------------|
| qdrant            | `qdrant/qdrant:v1.18.0`                                        | Has live data: `finance_assets`        |
| n8n               | `n8nio/n8n:2.20.7`                                             | Workflow engine                        |
| searxng           | `searxng/searxng:2026.5.13-8e5aa9d39`                         |                                        |
| embeddings        | `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9.3`      | TEI on CPU                             |
| whisper           | `ghcr.io/speaches-ai/speaches:0.9.0-rc.3-cpu`                  | RC pin — no stable tag upstream        |
| tts               | `ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4`                     |                                        |
| **finance-vector** | locally built `dream-server/finance-vector:0.1.0`              | Daily seeder, port 8095, see service README |
| litellm, langfuse, hermes, perplexica, comfyui, dream-proxy, hermes-proxy, privacy-shield, token-spy, tailscale, dashboard, dashboard-api, webui, llama-server | various | core stack         |

Disabled-by-user (must stay disabled across syncs): `ape`, `dreamforge`,
`openclaw`, `vikunja`.

## 4. Daily commands

```bash
# Show every container + its health
ssh sky-net@192.168.178.110 'dream status'

# Tail logs for one service
ssh sky-net@192.168.178.110 'dream logs n8n'

# Restart one service after manual config tweak
ssh sky-net@192.168.178.110 'dream restart qdrant'

# Are any image pins stale?
ssh sky-net@192.168.178.110 'dream check-image-updates'

# Full doctor
ssh sky-net@192.168.178.110 'dream doctor'
```

## 5. Edit → ship → roll out

The repo is a public Git remote; the Halo always pulls from `main`.

```bash
# On workstation
$EDITOR <files>
git commit -m "scope(svc): what changed"
git push origin main

# On Halo Strix
ssh sky-net@192.168.178.110 'dream sync --pull --auto-restart'
```

What `dream sync --pull --auto-restart` does, in order:

1. `git pull --ff-only` in `~/DreamServer`
2. **Snapshot** every service's enabled/disabled state in `~/dream-server`
   (`extensions/services/<sid>/` and `data/user-extensions/<sid>/`)
3. rsync repo → install (additive by default, no deletes)
4. **Reconcile** state: any service the user had disabled stays
   disabled (and gets fresh content under `.disabled`); any service
   the user had enabled stays enabled (and gets the fresh repo content
   even if the repo ships it as `.disabled`)
5. Regenerate `.compose-flags`
6. Auto-detect changed services (now **also** triggers on
   "mtime-only" changes for contract files — `compose*.yaml`,
   `Dockerfile*`, `manifest.*`, `.env*` — to catch byte-identical pin
   bumps that rsync's quick-check otherwise misclassifies as noise)
7. `dream restart` each, **skipping** services that ended up disabled

For a one-off rollout where you only want the auto-restart:
`dream sync --pull --auto-restart --dry-run` first to preview.

## 6. Image-pin bump procedure

```bash
# 1. See what's stale
dream check-image-updates

# 2. For each bump, edit BOTH:
#    extensions/services/<svc>/compose.yaml         (image: line)
#    installers/phases/08-images.sh                 (PULL_LIST entry)
# Some compose files have a comment block at the image: line documenting
# the bump procedure; update the version in the comment too.

# 3. Verify
dream check-image-updates -s <svc>

# 4. Ship & roll out
git commit -am "chore(<svc>): bump to <tag>"
git push
ssh sky-net@192.168.178.110 'dream sync --pull --auto-restart'
```

For containers with **live data** (qdrant, langfuse-postgres,
n8n, finance-vector seeder) you can snapshot before bumping if
the upstream changelog mentions storage migrations:

```bash
ssh sky-net@192.168.178.110 'KEY=$(grep ^QDRANT_API_KEY= ~/dream-server/.env | cut -d= -f2-) && \
  curl -fsS -X POST -H "api-key: $KEY" \
    http://127.0.0.1:6333/collections/finance_assets/snapshots'
```

## 7. Things that bit us before — read these once

* **Sync silently flipped service intent.** Before `feat(sync): preserve
  per-service enabled/disabled intent across pulls`, every pull
  re-enabled disabled services and never updated content of
  user-enabled-from-`.disabled` services.  Now both directions are
  reconciled; opt-out via `--no-preserve-state`.

* **Auto-restart missed byte-identical pin bumps.** A bump from
  `qdrant:v1.16.3` → `v1.18.0` (both 7 chars after the colon) made
  rsync classify the freshly-copied compose.yaml as `>f..t......`
  (mtime-only) and skip auto-restart.  Fix: contract files
  (`compose*.yaml`, `Dockerfile*`, `manifest.*`, `.env*`) under
  `extensions/services/<sid>/` always trigger restart.

* **Yahoo Finance throttles after a few hundred unauthenticated
  calls.** finance-vector's seeder uses the NASDAQ screener API as
  primary source for stocks (one HTTP call returns all US-listed
  symbols with marketCap, sector, country); yfinance/Wikipedia is the
  documented fallback.  See `extensions/services/finance-vector/app/seeder.py`.

* **n8n workflows reference env-vars.** Anything a workflow's Code/HTTP
  node needs via `$env.NAME` must be exposed in
  `extensions/services/n8n/compose.yaml` under `environment:`.
  Currently exposed: `VIKUNJA_API_TOKEN`, `OPENCLAW_TOKEN`,
  `GITHUB_TOKEN`, `AGENT_*`, `FINANCE_VECTOR_TOKEN`,
  `FINANCE_PRICES_TOKEN`, `FINANCE_NEWS_TOKEN`,
  `FINANCE_GURU_TOKEN`, `FINANCE_SOCIAL_TOKEN`, `LOTTO_ORACLE_TOKEN`,
  `N8N_*`, `WEBHOOK_URL`, `GENERIC_TIMEZONE`.

* **searxng config dir has GID conflicts with rsync.** rsync emits a
  benign `chgrp … failed: Operation not permitted` for
  `~/dream-server/config/searxng/`; the container creates files with
  its own UID/GID.  One-off fix:
  `sudo chgrp -R sky-net ~/dream-server/config/searxng/`.  Not blocking.

## 8. Repo invariants — keep these true

* `extensions/services/<sid>/compose.yaml` and the matching
  `installers/phases/08-images.sh::PULL_LIST` entry pin the **same**
  image:tag.  `dream check-image-updates` will report drift between
  them as two separate rows (`<svc>` and `installer:<svc>`).

* Image bumps go to commit messages with `chore(<svc>): bump …`,
  feature work goes to `feat(<svc>): …`, bug fixes to `fix(<svc>): …`.

* Storage volumes for stateful services live under
  `~/dream-server/data/<sid>/` and are **never** synced.

* User-enabled services on Halo Strix that the repo ships disabled:
  `langfuse`.  Don't undo this in the repo without coordinating with
  the operator.

## 9. When in doubt

* `dream-server/CLAUDE.md` and `dream-server/CONTRIBUTING.md` — upstream
  conventions for the dream-server project itself.
* `dream-server/docs/IMAGE-UPDATES.md` — how the version checker
  classifies tags.
* `dream-server/docs/ADR-IMAGE-TAG-PINNING.md` — when to use
  `@sha256:` digests vs tag pins.
* `dream-server/extensions/services/<sid>/README.md` — per-service
  details (most have one; finance-vector definitely does).

## 10. LiteLLM-routed models (Lemonade `/api/v1` → `:4000`)

### What clients actually call

LiteLLM (port `:4000`) exposes a small set of **routing aliases** that
map onto the underlying Lemonade models. Application code should
**always** use the alias, never the raw Lemonade name — that way the
operator can swap the backing model without touching service code.

| LiteLLM alias  | Backing Lemonade model | Size    | Load mode    | Use for                                         |
|----------------|------------------------|---------|--------------|-------------------------------------------------|
| `fast`         | `qwen3-4b`             | ~3.5 GB | warm-loaded  | Tool-routing, classification, news headlines    |
| `default`      | `Qwen3.6-35B-A3B`      | ~22 GB  | on-demand    | All-rounder / agent (text only!)                |
| `vision`       | `qwen3-vl-30b`         | ~22 GB  | on-demand    | Vision (mmproj) — ONLY model that reads images  |
| `code`         | `qwen3-coder-next`     | ~48 GB  | on-demand    | Code generation / refactor                      |
| `reasoning`    | `Qwen3.5-122B-A10B`    | ~77 GB  | on-demand    | Heavy reasoning, weekly retrospectives          |

To check the live alias list against the gateway:

```bash
KEY=$(grep ^LITELLM_KEY= ~/dream-server/.env | cut -d= -f2-)
curl -fsS -H "Authorization: Bearer $KEY" http://127.0.0.1:4000/v1/models | jq
```

### Defined fallbacks (LiteLLM router config)

```
reasoning -> default -> vision -> fast
vision    -> default -> fast
code      -> default -> fast
default   -> fast
```

So if `code` is busy or out of memory, LiteLLM transparently retries
on `default`, then `fast`. Application code does not need to handle
fallback itself.

### Auth (the bit that bit us once)

The project-wide convention in `.env` is **`LITELLM_KEY`** (not
`LITELLM_API_KEY`). The OpenAI-compatible HTTP client expects
`LITELLM_API_KEY`. Service compose files should bridge the two:

```yaml
- LITELLM_API_KEY=${LITELLM_KEY:-${LITELLM_API_KEY:-}}
```

The internal master key is `LITELLM_MASTER_KEY` (set in the litellm
container env, surfaced as `LITELLM_KEY` to clients via `.env`).

### Facts that contradict common web claims

> `Qwen3.6-35B-A3B` Instruct is **text-only**. Web claims to the
> contrary are wrong. For images use `vision` (qwen3-vl-30b).

### Cost discipline

Pick the smallest model that fits the task. Never call `reasoning`
(122B) on every event-loop tick — use it for batched / scheduled
reasoning only (cost & latency). The pattern that finance-news
follows: deterministic Python computes the per-item work, the LLM is
only invoked **batched** (16 headlines per `chat/completions` call)
and **only when needed** (sentiment that's already filled is skipped).

## 11. Finance pipeline — strategy engine roadmap

The user wants: **dependencies between prices and news/social → AI-driven
strategies → paper trade with €1000 reference, target ~10 %/week.**

### Decision: dashboard-integrated, not standalone

Implement as a **headless backend service** (`finance-guru-api`) +
**dashboard tab** in the existing UI. Reasons:

- `dashboard` and `dashboard-api` already exist → reuse the pattern.
- Strategies must run 24/7 (even with the dashboard closed) → headless
  daemon is required either way; a standalone GUI app on top would
  duplicate state.
- One source of truth (Qdrant + TimescaleDB), dashboard is just a view.
- LiteLLM routing, dream-network auth, n8n triggers are already wired —
  no new auth surface.

### Service layer (extend the README roadmap of `finance-vector`)

```
                                                          ┌──> dashboard tab
finance-vector  (this service, daily)  ──┐                │     "Finance Guru"
finance-prices  (NEW, 5–15 min, OHLCV) ──┼──> TimescaleDB │
finance-news    (NEW, 10 min, RSS+SearX)─┼──> Qdrant      │
finance-social  (NEW, 15 min, Reddit)   ─┘     finance_news
                                          ↘                ↑
                                           finance-guru-api ┘
                                           (FastAPI, strategies,
                                            paper-trade ledger,
                                            LiteLLM client)
```

| New service        | Stack                  | Writes to                  | Notes                                                                 |
|--------------------|------------------------|----------------------------|-----------------------------------------------------------------------|
| `finance-prices`   | Python + APScheduler   | TimescaleDB hypertable     | OHLCV via yfinance batched + CoinGecko `/coins/markets`. NO embedding. |
| `finance-news`     | Python + feedparser    | Qdrant `finance_news`      | RSS (Yahoo, Reuters, Handelsblatt) + SearXNG fallback. TEI embeds.    |
| `finance-social`   | Python + PRAW          | Qdrant `finance_social`    | Reddit free tier first; Mastodon/Bluesky later. X/Twitter is paid → out. |
| `timescaledb`      | `timescale/timescaledb`| (own volume)               | Postgres-compatible → n8n + dashboard-api use existing Postgres node. |
| `finance-guru-api` | FastAPI + APScheduler  | own SQLite ledger          | Strategy plugins, paper trading, LiteLLM calls.                       |

Why TimescaleDB and not "just Qdrant": the finance-vector README already
warns that vectors are the wrong tool for *"price moved X % within Y min
of news Z"*. Time-series joins need a real time-series store.

### Refresh cadence (all free-tier compatible)

| Source                    | Cadence                          | Free-tier headroom                                     |
|---------------------------|----------------------------------|--------------------------------------------------------|
| Stammdaten (`finance-vector`) | **1×/day**, unchanged        | re-embedding 500 docs is the cost driver, daily is fine |
| Prices stocks             | **15 min** during market hours   | yfinance batched (50 syms/req); ~7 calls/quarter-hour  |
| Prices crypto             | **5 min**                        | CoinGecko Demo = 30 req/min, top-250 = 1 paginated call |
| News (RSS)                | **10 min**                       | RSS has no real limit                                  |
| Social (Reddit)           | **15 min**                       | Reddit free OAuth = 100 QPM authenticated              |

Hourly was the original question — for **strategy reaction** 15 min on
prices is the sweet spot (free, gives ~26 ticks/day per symbol, enough
for intraday signals without burning CPU/embeddings). Going below 5 min
needs paid market data; not worth it for a paper-trade prototype.

### Strategy engine (`finance-guru-api`)

- **Plugin layout**: `app/strategies/<name>.py`, each exports
  `signal(state, prices_df, news_df) -> {action, qty, confidence, risk}`.
- **Initial strategies**:
  - `momentum_breakout`  — 20-day high + volume spike
  - `mean_reversion`     — Bollinger ±2σ
  - `news_sentiment`     — Qwen-classified headline polarity → entry
  - `event_driven`       — earnings + post-earnings drift
  - `pairs_correlation`  — co-moved pairs from finance-vector clusters
- **Paper ledger**: SQLite, one ledger per strategy, seeded with
  €1 000.00 each; every trade records entry, exit, PnL, reason text from
  the LLM (for the dashboard "why did it buy?" panel).
- **Backtest first, then live paper**: REST endpoint `POST /backtest`
  runs the strategy against 2 years of history before it's promoted to
  the live paper loop.
- **Target tracking**: weekly KPI = realised + unrealised PnL / 1 000;
  the 10 %/week target is a *KPI*, not a constraint — the engine shows
  which strategies hit it and the operator picks survivors.

### LLM call routing (which model for what)

| Task                                                       | Model               |
|------------------------------------------------------------|---------------------|
| Task                                                       | LiteLLM alias       |
|------------------------------------------------------------|---------------------|
| News headline → (symbols, sentiment, urgency)              | `fast`              |
| Per-tick strategy decision over aggregated signals         | `default`           |
| Generate / refactor a new strategy plugin                  | `code`              |
| Weekly retrospective: "why did strategy X under-perform?"  | `reasoning`         |
| Read a TradingView screenshot (later, optional)            | `vision`            |

**Never** call `default`/`reasoning` inside a per-tick loop. The pattern is:
deterministic Python computes signals → batched LLM call summarises /
decides → result cached for the next N ticks.

### Build order (smallest shippable steps)

1. ✅ `timescaledb` service + retention policy (90 d raw intraday,
   5 y daily aggregate; 180 d news.events).
2. ✅ `finance-prices` writing to TimescaleDB; bearer-guarded
   `/refresh` for n8n triggers.
3. ✅ `finance-news` writing to TimescaleDB `news.events` AND Qdrant
   `finance_news` (768-dim, same TEI as finance-vector); LiteLLM
   `fast` alias for sentiment + urgency tagging.
4. ✅ `finance-guru-api` skeleton: `/health`, `/strategies`,
   `/ledger`, `/decide`, `/backtest`. Plugin layout
   `app/strategies/<name>.py` with auto-discovery; SQLite paper
   ledger seeded €1 000 per strategy; APScheduler `*/30 * * * *`
   decide loop; LiteLLM `fast` alias for the `news_sentiment`
   reason-string. Two starter strategies shipped: `news_sentiment`
   (LLM-assisted) and `momentum_breakout` (pure Python).
5. ✅ Dashboard tab "Finance Guru" consumes the API. Backend: new
   `dashboard-api/routers/finance_guru.py` proxy that forwards
   `/api/finance-guru/{status,strategies,ledger,decide,backtest}` to
   the upstream service over the dream-network — `FINANCE_GURU_TOKEN`
   never leaves the host (read from `.env` like `VIKUNJA_API_TOKEN`).
   Frontend: `pages/FinanceGuru.jsx` registered in `plugins/core.js`
   with sidebar visibility gated on the `finance-guru-api` service
   being present. Renders aggregate KPI strip (seeded, equity, PnL,
   delta vs 10 %/week target, open positions), per-strategy list, and
   a detail pane with positions table + trade log including the LLM
   "why" reason string.
6. ✅ `finance-social` — Reddit aggregator (PRAW free-tier OAuth)
   pulling new submissions from `wallstreetbets`, `stocks`, `investing`,
   `StockMarket`, `CryptoCurrency`, `SecurityAnalysis` every 15 min.
   Same dual-sink pattern as finance-news: TimescaleDB `social.events`
   hypertable (own retention: 60 d) + Qdrant `finance_social` collection.
   Sentiment via LiteLLM `fast` (qwen3-4b) — only posts that mention a
   known symbol get embedded/scored to keep cost proportional to signal.
   Bonus: shipped a third strategy `social_buzz` in finance-guru-api
   (buy on Reddit-buzz spike + positive mean sentiment, sell on
   negative buzz or +5 % take-profit). DecisionContext gained an
   optional `get_social` lookup; older strategies are unaffected.
   Operator setup (Reddit script app + .env credentials) documented in
   `extensions/services/finance-social/README.md`.

Everything follows the existing service contract (`compose.yaml`,
`manifest.yaml`, `installers/phases/08-images.sh` pin, `dream sync`
behaviour). No new ops surface for the operator.

## 12. Quick-paste prompt for new sessions

> I'm working on the DreamServer fork at
> `~/PhpstormProjects/codedredd/DreamServer`.  Read
> `AGENT-OPERATIONS.md` for the operator context (servers, repo
> layout, daily commands, sync semantics, things that bit us).
> SSH to the Halo Strix is `sky-net@192.168.178.110` and I have
> `SSHPASS` exported.  Pi 5 is the `claw-pi5` ssh alias.

## 13. Lotto Oracle — second tab inside Finance Guru

A separate FastAPI service `lotto-oracle` (port `:8099`, locally built
image `dream-server/lotto-oracle:0.1.0`) collects German lottery draws
and generates suggested tips. Surfaced in the dashboard as a **second
tab** inside the existing Finance Guru page (next to "Paper-Trade
Strategien"). The whole feature is opt-in — sidebar shows the page if
*either* `finance-guru-api` or `lotto-oracle` is registered.

### Supported games

| Service id      | Spiel                | Pool                        | Days   |
|-----------------|----------------------|-----------------------------|--------|
| `lotto-6aus49`  | Lotto 6 aus 49       | 6/49 + Superzahl 0–9        | Mi/Sa  |
| `eurojackpot`   | Eurojackpot          | 5/50 + 2/12 (since 03/2022) | Di/Fr  |
| `spiel77`       | Spiel 77             | 7-digit Losnummer           | Mi/Sa  |
| `super6`        | Super 6              | 6-digit Spielscheinnummer   | Mi/Sa  |

### Strategies

Combinatorial games (6aus49, Eurojackpot):
`recency_exclude`, `frequency_hot`, `frequency_cold`, `gap_due`,
`balanced`, `anti_pattern`, `random_uniform`.
Digit games (Spiel77, Super6): `recency_exclude`, `frequency_hot`,
`frequency_cold`, `random_uniform`.

`recency_exclude` is a **hard constraint**: every number / digit drawn
in the last K=1 draws is forbidden. This guarantees the user-stated
requirement *"die Tipps müssen sich nach jeder Ziehung ändern"*.

### Auto-update cron

Default: `30 3 * * 1,4` in `Europe/Berlin` (Mon + Thu at 03:30) —
covers the Sa & Fr draws, then the Mi & Di draws. After every fetch
the engine auto-generates a fresh tip set per game
(`LOTTO_ORACLE_AUTO_GENERATE=1`, default on).

Override per-deployment via `.env`:

```env
LOTTO_ORACLE_FETCH_CRON=30 3 * * 1,4
LOTTO_RETENTION_YEARS=30
LOTTO_ORACLE_TOKEN=$(openssl rand -hex 32)   # Pflicht für Write-Endpoints
```

### Real-money submission

> **There is no public/legal API to submit lottery tips in Germany.**
> lotto.de / lotto24.de / tipp24.de require a registered account +
> payment method and only expose web forms. Affiliate REST endpoints
> exist for licensed B2B partners only.
>
> The service therefore generates tips that the operator transfers
> manually (the dashboard provides per-tip Copy buttons).

If we ever want true automation, only realistic path is an official
Lotto24 / Tipp24 affiliate contract — out of scope for this repo.

### Pipeline

```
external mirror(s) ──▶ lotto-oracle ──▶ /api/lotto/* (dashboard-api proxy)
   (lottozahlenonline.de / lotto.de)        ▲
   /seed/<game>.csv (offline bootstrap)     │
                                            └── dashboard "Lotto Oracle" tab
                                                inside Finance Guru page
```

### n8n exposure

`LOTTO_ORACLE_TOKEN` is bridged into `extensions/services/n8n/compose.yaml`
(same pattern as `FINANCE_*_TOKEN`). Workflows can call the upstream
service directly (`http://lotto-oracle:8099/refresh`) with
`{{ $env.LOTTO_ORACLE_TOKEN }}` as the bearer.

### Build order completed

1. ✅ Backend: FastAPI + SQLite (`extensions/services/lotto-oracle/`)
   with `games.py`, `store.py`, `fetchers.py`, `strategies.py`,
   `main.py`. CSV seed bootstrap + multi-source HTML archive scraping
   (`lottozahlenonline.de` per-year pages, `lotto.de` / `eurojackpot.de`
   as fallback) + `/admin/import` for operator-supplied CSV.
2. ✅ Dashboard-api proxy (`routers/lotto.py`) with bearer injection.
3. ✅ Dashboard tab navigation in `pages/FinanceGuru.jsx` —
   `StrategiesTab` (existing UI) + `LottoTab` (new). Sidebar entry
   gated on either service being present (`plugins/core.js`).
4. ✅ Strategy unit-test (recency_exclude guarantees zero overlap with
   last draw for every game) — see `dream-server/extensions/services/lotto-oracle/`
   smoke test in commit history.

