# finance-social — Reddit social-signal aggregator

Step 6 of the AGENT-OPERATIONS.md §11 finance pipeline. Pulls Reddit
posts (PRAW, free-tier OAuth), tags them with finance symbols from the
shared `finance_assets` Stammdaten universe, classifies sentiment +
urgency via LiteLLM `fast` (qwen3-4b), and writes to:

* **TimescaleDB `social.events`** (hypertable, same shape as
  `news.events` so strategies can `UNION ALL`).
* **Qdrant `finance_social`** (own collection, separate retention).

## Operator setup (one-time)

You need a Reddit "script"-type app:

1. Visit <https://www.reddit.com/prefs/apps>, click *create another app…*
2. Choose **script**, fill name + an `about` URL (anything, not used).
3. Set redirect URI to `http://localhost:8000` (placeholder; we don't
   use the user-flow).
4. Copy the 14-char *client id* (under the app name) and the
   *secret*.
5. Add to `.env`:

   ```
   REDDIT_CLIENT_ID=…
   REDDIT_CLIENT_SECRET=…
   REDDIT_USER_AGENT=DreamServer-FinanceSocial/0.1 (by u/<your-handle>)
   FINANCE_SOCIAL_TOKEN=$(openssl rand -hex 32)
   ```

   The User-Agent string is a Reddit ToS hard requirement — be
   identifiable, version-stamp, include a way to contact (your
   reddit handle works).

If the credentials are missing the service stays alive but won't fetch
anything; `/status` will report `reddit.configured = false`.

## Endpoints

| Verb | Path        | Auth   | Purpose                                       |
|------|-------------|--------|-----------------------------------------------|
| GET  | `/health`   | none   | liveness probe                                |
| GET  | `/status`   | none   | last/next runs, row counts, per-sub counters  |
| POST | `/refresh`  | bearer | trigger ad-hoc fetch (n8n/cron friendly)      |
| POST | `/search`   | none   | semantic search over the Qdrant collection    |

## Default subreddits

```
wallstreetbets, stocks, investing, StockMarket,
CryptoCurrency, SecurityAnalysis
```

Override with `FINANCE_SOCIAL_SUBREDDITS=sub1,sub2,…` in `.env`. The
`r/` prefix is optional.

## Cadence

`*/15 * * * *` by default (per AGENT-OPERATIONS.md §11). Reddit free
OAuth = ~100 QPM; pulling `new(limit=50)` from 6 subreddits every 15
minutes is well within budget.

## What it does NOT do

* No comment scraping. Submissions only — comments would multiply the
  embedding bill 10× and the marginal signal is small.
* No X/Twitter, no Discord. Both require paid API tiers.
* No upvote-trajectory tracking yet (single-snapshot score). A
  follow-up could re-poll posts after 1h to derive a velocity signal.

