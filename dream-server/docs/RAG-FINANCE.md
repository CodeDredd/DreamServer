# RAG Finance — Collection-Schemas und Beispiel-Queries

> Stand: 05/2026 · Phase G der `FINANCE-GURU-IMPROVEMENT-PLAN.md`
> Audience: AI-Agenten, n8n-Workflow-Autoren, Dashboard-Entwickler,
> Operator, die die Vector-Pipeline manuell prüfen wollen

Der Finance-Stack schreibt sechs Qdrant-Collections und liest sie über
einen einheitlichen Layer (`finance-guru-api/app/qdrant_rag.py`)
zurück. Dieses Dokument ist die *einzige* Stelle, an der die
Collection-Verträge zusammen mit Beispiel-Queries dokumentiert sind —
wer ein neues n8n-Asset oder eine neue Strategie schreibt, sollte hier
starten.

Alle Collections nutzen:

* **Distance:** `Cosine`
* **Vektor-Dimension:** **768** (TEI `mxbai-embed-large-v1` o.ä.,
  geliefert vom `embeddings`-Service)
* **Embedding-Quelle:** `EMBEDDINGS_URL=http://embeddings:80/embed`
* **Best-Effort-Writes:** Jeder Producer fängt Qdrant-/TEI-Fehler ab.
  Eine ausgefallene Vektor-DB blockiert nie den Haupt-Pfad — die
  Strategie sieht im Zweifel eine leere RAG-Trefferliste.

---

## 1. Übersicht

| Collection                 | Producer                                                                                     | Cadence    | Konsumenten                                                                                  |
|----------------------------|----------------------------------------------------------------------------------------------|------------|----------------------------------------------------------------------------------------------|
| `finance_assets`           | `finance-vector/app/seeder.py` (`ensure_collection`)                                          | 1 ×/Tag     | `qdrant_rag.search_assets` → DSL-Strategien (`rag.*`-Whitelist)                              |
| `finance_news`             | `finance-news/app/qdrant_sink.py` (`ensure_collection`) + `finance-guru-api/app/qdrant_sink.propagate_source_weight` | 10 min     | `qdrant_rag.search_news`, n8n `09-finance-asset-behaviour`, `13-finance-causal-extraction`    |
| `finance_social`           | `finance-social/app/qdrant_sink.py` (`ensure_collection`)                                     | 15 min     | `qdrant_rag.search_social`, Strategie `social_buzz` (`get_social_rag`)                       |
| `finance_asset_analysis`   | `finance-guru-api/app/qdrant_sink.upsert_asset_analysis` (n8n `09-finance-asset-behaviour`)   | bedarf     | `qdrant_rag.search_asset_analyses`, n8n `12-finance-strategy-genesis`                        |
| `finance_relations`        | `finance-guru-api/app/qdrant_rag.upsert_relation` (n8n `13-finance-causal-extraction`)        | 15 min     | `qdrant_rag.search_relations`, DSL-Signal `rag.relations_count`                              |
| `finance_strategy_lessons` | `finance-guru-api/app/qdrant_rag.upsert_strategy_lesson` (`lifecycle.weekly_audit` + Operator) | bei Retire | `qdrant_rag.search_strategy_lessons`, n8n `12-finance-strategy-genesis` (Brief-Aufbau)        |

Status-Check live:

```bash
curl -s http://192.168.178.110:8098/rag/status | jq
# erwartet: 6 Einträge mit {collection, exists, points, dim}
```

---

## 2. Collection-Schemas

### 2.1 `finance_assets` — Stammdaten der handelbaren Universe

Was es ist: Per-Symbol-Stammdaten (Sektor, Land, Market-Cap,
Beschreibung) — täglich vom `finance-vector`-Seeder von NASDAQ-Screener
+ CoinGecko + Wikipedia-Fallback ausgespielt.

| Payload-Feld    | Typ       | Index    | Notizen                                            |
|-----------------|-----------|----------|----------------------------------------------------|
| `type`          | KEYWORD   | ✓ KEYWORD | `stock` \| `crypto` \| `etf` \| `index`            |
| `symbol`        | KEYWORD   | ✓ KEYWORD | Ticker (US-Format, Uppercase)                      |
| `sector`        | KEYWORD   | ✓ KEYWORD | GICS Sector (Stocks); für Crypto: Kategorie         |
| `country`       | KEYWORD   | ✓ KEYWORD | ISO-Code                                           |
| `market_cap`    | FLOAT     | ✓ FLOAT   | USD, FLOAT-Index erlaubt Range-Filter + `order_by` |
| `name`          | TEXT      |          | volle Beschreibung — Embedding-Quelle              |
| `last_updated`  | TEXT(ISO) |          | Seeder-Zeitstempel                                 |

Point-ID: `uuid5(NAMESPACE_URL, "finance:{type}:{symbol}")`

```bash
# alle Energie-Stocks > $100B, semantisch nach "renewable transition"
TOKEN=$(grep ^QDRANT_API_KEY= ~/dream-server/.env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:6333/collections/finance_assets/points/search \
  -H "api-key: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"vector": [...768 floats...], "limit": 20,
       "filter": {"must": [
         {"key": "type",       "match": {"value": "stock"}},
         {"key": "sector",     "match": {"value": "Energy"}},
         {"key": "market_cap", "range": {"gte": 100000000000}}]}}'

# Mit den vorgebauten Helpers (lieber so — kein Embedding-Boilerplate):
curl -s -X POST http://192.168.178.110:8098/rag/assets \
  -H 'Content-Type: application/json' \
  -d '{"query":"renewable energy transition","limit":10,
       "filters":{"type":"stock","sector":"Energy"}}' | jq '.hits[] | {symbol, sector, market_cap, score}'
```

### 2.2 `finance_news` — Headline-Korpus mit Sentiment

Was es ist: Jede 10 min wird der RSS-Pool (Yahoo, Reuters, Handelsblatt
+ SearXNG-Fallback) gepullt; pro Headline gibt es einen Punkt mit
Sentiment + Urgency aus dem `fast`-Modell. Die `propagate_source_weight`
des `finance-guru-api` patcht zusätzlich `source_reliability` /
`source_weight` per `set_payload` (kein Re-Embedding).

| Payload-Feld           | Typ       | Index | Notizen                                            |
|------------------------|-----------|-------|----------------------------------------------------|
| `symbols`              | KEYWORD[] | ✓     | extrahierte Ticker pro Headline                     |
| `source`               | KEYWORD   | ✓     | Domain / RSS-Feed                                  |
| `ts_unix`              | INTEGER   | ✓     | Epoch (für `range` Filter)                         |
| `sentiment`            | FLOAT     | ✓     | -1.0 … +1.0                                        |
| `urgency`              | FLOAT     |       | 0 … 1 (LLM)                                        |
| `title` / `summary`    | TEXT      |       | Embedding-Quelle (title + summary)                 |
| `news_id`              | KEYWORD   |       | identisch zu TimescaleDB PK (`news.events.id`)     |
| `source_reliability`*  | FLOAT     |       | von `finance-guru-api/qdrant_sink` patched         |
| `source_weight`*       | FLOAT     |       | `reliability * min(1, sample_size/50) * 2`         |
| `contradiction`*       | BOOL      |       | gesetzt von Verifier in `news_sentiment`           |

*: nachträglich via `set_payload` ergänzt, kann auf älteren Punkten fehlen.

```bash
# Letzte 24h, Reuters, mindestens stark-positiv:
curl -s -X POST http://192.168.178.110:8098/rag/news \
  -H 'Content-Type: application/json' \
  -d '{"query":"federal reserve rate cut","limit":5,
       "min_sentiment":0.4,"max_age_hours":24,
       "sources":["reuters.com"]}' | jq '.hits[] | {title, sentiment, source, ts}'

# Nur Headlines, die mindestens ein Symbol getroffen haben:
curl -s -X POST http://192.168.178.110:8098/rag/news \
  -H 'Content-Type: application/json' \
  -d '{"query":"oil supply disruption","limit":10,"symbols":["XOM","CVX","BP"]}'
```

### 2.3 `finance_social` — Reddit + (später) Mastodon/Bluesky

Was es ist: Alle 15 min werden `wallstreetbets`, `stocks`, `investing`,
`StockMarket`, `CryptoCurrency`, `SecurityAnalysis` per PRAW gepullt;
pro Submission ein Punkt mit `sentiment` + `score` (Upvotes).

| Payload-Feld          | Typ       | Index | Notizen                                          |
|-----------------------|-----------|-------|--------------------------------------------------|
| `symbols`             | KEYWORD[] | ✓     | extrahierte Ticker pro Post                      |
| `source`              | KEYWORD   | ✓     | `reddit` (später `mastodon`, `bluesky`)          |
| `channel`             | KEYWORD   | ✓     | Subreddit-Slug (`wallstreetbets`, ...)           |
| `ts_unix`             | INTEGER   | ✓     | Epoch                                            |
| `sentiment`           | FLOAT     | ✓     | -1.0 … +1.0 (`fast`-Modell)                       |
| `score`               | INTEGER   | ✓     | Reddit-Upvotes ⇒ Buzz-Indikator                 |
| `title` / `selftext`  | TEXT      |       | Embedding-Quelle                                 |

```bash
# WSB-Hype-Score: alle Posts der letzten 6 h mit > 500 Upvotes:
curl -s -X POST http://192.168.178.110:8098/rag/social \
  -H 'Content-Type: application/json' \
  -d '{"query":"meme stock momentum","limit":20,
       "min_score":500,"max_age_hours":6,
       "channels":["wallstreetbets"]}' | jq '.hits[] | {title, score, sentiment, ts}'
```

### 2.4 `finance_asset_analysis` — LLM-Analysen pro (Symbol, Periode)

Was es ist: Die n8n-Workflow-Kette `09-finance-asset-behaviour.json`
zieht für ein Symbol 6 Monate OHLCV + Headlines, lässt das
`default`-Modell die größten Moves erklären und schreibt
`{summary, keywords, drivers[], confidence, contradictions}` zurück.
Der Phase-A.2 Per-Item-Batching-Refactor erzeugt bis zu 5
Analysen/Cron-Tick.

| Payload-Feld          | Typ       | Index | Notizen                                              |
|-----------------------|-----------|-------|------------------------------------------------------|
| `symbol`              | KEYWORD   | ✓     | Ticker                                               |
| `asset_type`          | KEYWORD   | ✓     | stock \| crypto \| etf                              |
| `keywords`            | KEYWORD[] | ✓     | ≤ 12, lowercase                                      |
| `confidence`          | FLOAT     | ✓     | 0 … 1, vom Verifier um -0.15/Widerspruch reduziert    |
| `ts_unix`             | INTEGER   | ✓     | `period_end` als Epoch                               |
| `period_start/end`    | TEXT(ISO) |       | analysierter Zeitraum                                |
| `summary`             | TEXT      |       | Embedding-Quelle (summary + keywords)               |
| `drivers`             | JSON      |       | `[{date, move_pct, narrative, news_ids, source}]`    |
| `contradictions`      | KEYWORD[] |       | nachvollziehbarer Audit-Trail                        |

```bash
# Welche AAPL-Treiber wurden zuletzt vom LLM identifiziert?
curl -s -X POST http://192.168.178.110:8098/rag/asset-analysis \
  -H 'Content-Type: application/json' \
  -d '{"query":"earnings surprise revenue","limit":3,
       "symbols":["AAPL"],"min_confidence":0.5}' \
  | jq '.hits[] | {symbol, summary, keywords, confidence, ts}'

# Alle Tech-Analysen mit hohem ETF-Inflow-Treiber:
curl -s -X POST http://192.168.178.110:8098/rag/asset-analysis \
  -H 'Content-Type: application/json' \
  -d '{"query":"ETF inflow institutional buying","limit":10}'
```

### 2.5 `finance_relations` — Kausalketten (Phase E)

Was es ist: Alle 15 min ruft `13-finance-causal-extraction.json` die
letzten 6h News (`min_urgency >= 2`) ab und bittet `default` darum, sie
zu **Themen** zu verdichten: *"Iran-Krieg → Hormus gesperrt →
Tanker-Disruption → Brent +X % → Auswirkungen auf …"*. Verifier sortiert
halluzinierte Symbole und Themen mit `confidence < 0.3` aus.

| Payload-Feld    | Typ       | Index | Notizen                                              |
|-----------------|-----------|-------|------------------------------------------------------|
| `theme`         | KEYWORD   | ✓     | menschenlesbarer Themen-Slug                          |
| `mechanism`     | KEYWORD   | ✓     | knappe Begründung (≤ 240 Zeichen)                    |
| `entities`      | KEYWORD[] | ✓     | Geo / Event / Org / Person                           |
| `sectors`       | KEYWORD[] | ✓     | GICS-Sektoren                                        |
| `symbols`       | KEYWORD[] | ✓     | nur **verifizierte** Ticker aus der Live-Universe    |
| `evidence_ids`  | KEYWORD[] |       | `news_id`s, die das Thema gestützt haben             |
| `confidence`    | FLOAT     | ✓     | 0 … 1 (nach Verifier-Strafen)                         |
| `ts_unix`       | INTEGER   | ✓     | Epoch                                                |
| `model`         | KEYWORD   |       | z.B. `default` (Qwen3.6-35B-A3B)                     |
| `summary`       | TEXT      |       | Embedding-Quelle (Theme + Mechanism + Symbols)       |

```bash
# "Welche Macro-Themen treffen Energie gerade?"
curl -s -X POST http://192.168.178.110:8098/rag/relations \
  -H 'Content-Type: application/json' \
  -d '{"query":"oil supply disruption middle east","limit":5,
       "min_confidence":0.5,"sectors":["Energy"]}' \
  | jq '.hits[] | {theme, mechanism, symbols, confidence, ts}'

# "Welche Relations treffen mein offenes XOM-Investment?"
curl -s -X POST http://192.168.178.110:8098/rag/relations \
  -H 'Content-Type: application/json' \
  -d '{"query":"impact on XOM","limit":3,"symbols":["XOM"]}'
```

DSL-Signal: `rag.relations_count` (mit `lookback_h`, `min_confidence`)
liest direkt aus dieser Collection.

### 2.6 `finance_strategy_lessons` — Lessons-Learned der Strategie-Lifecycle

Was es ist: Sobald `lifecycle.weekly_audit()` eine Strategie unter dem
WoW-Target retiret, schreibt `build_lesson_text` einen `reasoning`-Brief
(max. 120 Wörter), embedet ihn und legt einen Punkt hier ab.
`12-finance-strategy-genesis` zieht beim Bauen des Reasoning-Briefs
Top-N Lessons als RAG-Kontext mit — damit halluzinierte Strategien
nicht zweimal vorgeschlagen werden.

| Payload-Feld   | Typ       | Index | Notizen                                              |
|----------------|-----------|-------|------------------------------------------------------|
| `strategy`     | KEYWORD   | ✓     | Strategie-Name                                       |
| `outcome`      | KEYWORD   | ✓     | `retired` \| `promoted` \| `archived` \| `note`      |
| `pnl_pct`      | FLOAT     | ✓     | %-PnL des Audit-Fensters                              |
| `ts_unix`      | INTEGER   | ✓     | Epoch                                                |
| `lesson`       | TEXT      |       | Brief-Text, Embedding-Quelle                         |
| `keywords`     | KEYWORD[] |       | ≤ 24, lowercase                                      |
| `extra`        | JSON      |       | optional, z.B. `target_pct`, `n_cycles`              |

```bash
# Welche Lessons hat der letzte Audit-Zyklus produziert?
curl -s -X POST http://192.168.178.110:8098/rag/strategy-lessons \
  -H 'Content-Type: application/json' \
  -d '{"query":"social buzz failed mean reversion","limit":5,
       "outcome":"retired"}' | jq '.hits[] | {strategy, outcome, pnl_pct, lesson}'

# Lesson manuell schreiben (Operator):
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -s -X POST http://192.168.178.110:8098/rag/strategy-lesson \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"strategy":"manual_note","outcome":"note",
       "lesson":"Universe drift detected — re-pull stammdaten before next genesis cycle.",
       "keywords":["operator","note","stammdaten"]}'
```

---

## 3. API-Surface (`finance-guru-api`)

Alle Read-Endpoints sind **offen** (dream-network intern, kein Bearer);
Writes sind **bearer-guarded** mit `FINANCE_GURU_TOKEN`.

| Methode | Route                                  | Bearer | Zweck                                              |
|---------|----------------------------------------|--------|----------------------------------------------------|
| GET     | `/rag/status`                           | nein   | Exists/Points/Dim für alle 6 Collections           |
| POST    | `/rag/assets`                           | nein   | `query` + Filter → Top-K                            |
| POST    | `/rag/news`                             | nein   | `query` + `min_sentiment` + `symbols` + `sources`   |
| POST    | `/rag/social`                           | nein   | `query` + `min_score` + `channels`                 |
| POST    | `/rag/asset-analysis`                   | nein   | `query` + `symbols` + `min_confidence`              |
| POST    | `/rag/asset-analysis/search` (legacy)   | nein   | Alias auf `/rag/asset-analysis`                    |
| POST    | `/rag/relations`                        | nein   | `query` + `sectors` + `symbols` + `min_confidence`  |
| POST    | `/rag/strategy-lessons`                 | nein   | `query` + `outcome` + `strategy`                    |
| POST    | `/rag/relation`                         | **ja** | Phase-E n8n-Sink (`upsert_relation`)                |
| POST    | `/rag/strategy-lesson`                  | **ja** | Phase-C/D Sink (`upsert_strategy_lesson`)           |

Alle Read-Endpoints liefern `{count, hits: [{id, score, payload}]}`.

---

## 4. Anti-Halluzination — Verifier-Pattern

Jeder LLM-Producer (`09`, `10`, `12`, `13`) endet mit einem
Verifier-Node, der strukturierten Output gegen die Eingabe abgleicht:

* **`09-finance-asset-behaviour`** — jedes `news_ids` muss im Brief
  vorkommen; jedes `date` muss in `biggest_moves`; pro Verstoß wird
  `confidence` × 0.85 multipliziert.
* **`10-finance-source-reliability`** — die Liste der Quellen, die das
  LLM bewertet, wird gegen die übergebene Quellen-Aggregation gefiltert;
  invented sources werden gedroppt.
* **`12-finance-strategy-genesis`** — jedes `signal` muss in der
  DSL-Whitelist (`/strategies/dsl/catalog`) liegen; jedes `symbol` muss
  in der Live-Universe sein.
* **`13-finance-causal-extraction`** — Symbole werden gegen die Universe
  gefiltert (partielle Akzeptanz: das Thema bleibt, solange ≥ 1 Ticker
  ODER ≥ 1 `evidence_id` verifizierbar ist); `confidence < 0.3` wird
  verworfen; max. 6 Themen pro Run.

Das **Promotion-Gate** (`POST /strategies/promote`) verlangt zudem
**beide** Backtest-Bedingungen vor dem Mounten als `live`:

* `bt_pnl_pct >= FINANCE_GURU_TARGET_WEEK_PCT` (default 10 %)
* `bt_n_trades >= FINANCE_GURU_GENESIS_MIN_BT_TRADES` (default 5)

Override **nur** über `X-Force-Promote: 1` (Operator-Header; der
ehemalige `force`-Body-Feld-Pfad wurde in Phase G entfernt — Pydantic
`extra=forbid` → HTTP 400).

---

## 5. Beispiel: DSL-Strategie zieht RAG

```python
# finance-guru-api/app/strategies/news_sentiment.py (gekürzt)
def decide(ctx: DecisionContext) -> list[Signal]:
    sigs: list[Signal] = []
    for symbol in ctx.universe[:30]:
        if not ctx.get_news_rag or not ctx.get_analysis_rag:
            continue                                # Qdrant down → still trade on SQL
        rag = {
            "symbol":    symbol,
            "analyses":  ctx.get_analysis_rag(query=symbol, symbols=[symbol], limit=3),
            "news":      ctx.get_news_rag(query=symbol, symbols=[symbol], limit=3,
                                          min_sentiment=0.4, max_age_hours=6),
            "relations": ctx.get_relations_rag(query=symbol, symbols=[symbol], limit=2,
                                                min_confidence=0.4),
        }
        if not rag["news"]:
            continue
        sigs.append(Signal(symbol=symbol, action="buy", qty=1.0,
                           reason=f"+{rag['news'][0]['payload']['sentiment']:.2f} sentiment",
                           extra={"rag": rag, "eur_target": "max_position_frac"}))
    return sigs
```

Das `extra.rag` wandert durch `orchestrator.run_strategy_once()` ins
Cycle-Log (`payload_json.executed[].extra.rag`) — das Dashboard zeigt
es im Cycle-Drill-down, und der wöchentliche Auditor hat die Belege
für die Lesson-Generierung.

---

## 6. Operator-Checks

```bash
# Schneller "alles ok?"-Check:
curl -s http://192.168.178.110:8098/rag/status | jq '
  .collections[] | {collection, exists, points, dim}'
# erwartet: 6 Zeilen, alle exists:true, points > 0 (sobald
# Producer mind. 1× gelaufen sind).

# Smoke-Test pro Endpoint (Read):
for path in assets news social asset-analysis relations strategy-lessons; do
  echo "=== /rag/$path ==="
  curl -s -X POST "http://192.168.178.110:8098/rag/$path" \
    -H 'Content-Type: application/json' \
    -d '{"query":"smoke test","limit":1}' | jq '{count, sample: .hits[0] | {id, score}}'
done

# Sink-Roundtrip (Lesson):
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -s -X POST http://192.168.178.110:8098/rag/strategy-lesson \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"strategy":"docs_smoke","outcome":"note","lesson":"docs smoke","keywords":["docs"]}'
curl -s -X POST http://192.168.178.110:8098/rag/strategy-lessons \
  -H 'Content-Type: application/json' \
  -d '{"query":"docs smoke","limit":1}' | jq '.hits[0].payload.lesson'
```

---

## 7. Wartung & Migration

* **Schema-Erweiterungen** — Payload-Felder können ohne Re-Embedding
  ergänzt werden (`client.set_payload`). Dimensionsänderungen
  erfordern Re-Embedding + neue Collection — siehe `seeder.py`'s
  `recreate=True`-Pfad als Vorlage.
* **Index-Drift** — Neue Payload-Indexe werden in den `ensure_*`-
  Funktionen idempotent angelegt; Producer einmal hochfahren reicht.
* **Größenbudget** — `finance_news` wächst am schnellsten
  (~144 Punkte/h). Bei Volumen-Problemen via Qdrant `delete_points` mit
  `range`-Filter auf `ts_unix` zurückschneiden (Retention liegt
  serverseitig nicht hart, weil n8n-Workflows Time-Series-Lookups
  via TimescaleDB erledigen und Qdrant nur als ANN-Index dient).
* **Backups** — Qdrant-Snapshot-API (`POST /collections/{name}/snapshots`)
  pro Collection; AGENT-OPERATIONS §6 zeigt den Pattern für
  `finance_assets`. Lessons/Relations/Analyses sind reproduzierbar
  (Producer können bei Bedarf re-laufen), `finance_news` und
  `finance_social` sind die einzigen Sinks mit unwiederbringlichem
  Inhalt (RSS/Reddit retentiert nicht ewig).

---

## 8. Verwandte Dokumente

* `dream-server/docs/FINANCE-GURU-IMPROVEMENT-PLAN.md` — der
  Master-Plan (Phasen A–G).
* `dream-server/extensions/services/finance-guru-api/README.md` —
  Service-spezifische Endpoints, ENV-Vars, Strategie-Plugin-API.
* `dream-server/extensions/services/finance-vector/README.md` —
  Stammdaten-Seeder-Internals.
* `AGENT-OPERATIONS.md` §11 — Cycle-Log, Enrichment, n8n-Workflow-Liste.

