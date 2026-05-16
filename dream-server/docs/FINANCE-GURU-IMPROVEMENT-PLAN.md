# Finance Guru — Verbesserungsplan (Paper-Trading, RAG, Qdrant, UI)

> Stand: 05/2026 · Status: Phase A ✅ · Phase A.2 ✅ · Phase B ✅ deployed
> Verantwortlich: AI-Agent + Operator
> Bezugspunkte: `AGENT-OPERATIONS.md §11–§14`, `extensions/services/finance-guru-api/`,
> `extensions/services/finance-{vector,news,social,prices}/`, `extensions/services/dashboard-nuxt/`

## 0. Nordstern (Was wir am Ende haben wollen)

* **Selbstlernender Paper-Trader**: die App legt **laufend neue
  fiktive Strategien** an, die auf dem **aktuellen Wissensstand der
  RAG** beruhen (Qdrant-Treffer + TimescaleDB-Fakten), nicht auf
  hartcodierten Indikatoren.
* **Knallhartes 1-Wochen-Gate**: Strategie < +10 % nach 7 d ⇒
  *gescheitert*, wird automatisch retired und ihre Lessons-Learned
  in den RAG-Korpus zurückgeführt ("mehr Daten sammeln").
* **Kausalketten** statt Symbolfilter: "Iran-Krieg → Hormus gesperrt
  → Tanker-Disruption → Brent +X % → Auswirkungen auf
  {Airlines, Petrochemie, EUR/USD, Bitcoin}". Diese Ketten werden
  als Graph-ähnliche Beziehungen in Qdrant + Timescale gespeichert.
* **Keine Halluzinationen**: jede LLM-Aussage wird gegen
  TimescaleDB-Fakten und das Quellen-Reliability-Modell verifiziert
  (Verifier-Pattern wie in `09-finance-asset-behaviour.json`, nur
  flächendeckend).
* **Sidebar mit `UTree`**: Finance Guru ist ein Knoten mit
  Unterpunkten *Trading* + *Lotto Orakel* — kein Tabs-Wechsel
  innerhalb derselben Page mehr.

---

## 1. Bestandsanalyse Qdrant

Aktuell drei Collections — alle werden geschrieben, **kaum gelesen**.

| Collection                 | Geschrieben von                                                  | Gelesen von                                                                                | Nutzungsgrad                                  | Bewertung                          |
|---------------------------|-----------------------------------------------------------------|--------------------------------------------------------------------------------------------|-----------------------------------------------|------------------------------------|
| `finance_assets`          | `finance-vector/seeder.py` (täglich)                            | **Niemandem in der Trading-Pipeline**; nur per `dream` CLI / manuellem `curl` durchsuchbar | ☆☆☆☆☆ totes Kapital                          | als Stammdaten-RAG **anbinden**    |
| `finance_news`            | `finance-news/qdrant_sink.py` (10 min) + Payload-Patch via `finance-guru-api/qdrant_sink.propagate_source_weight` | `finance-news` `/search` Endpoint (nur extern via n8n nutzbar); **keine Strategie** liest semantisch | ☆☆★★★ wird angereichert, aber nicht abgefragt | in `DecisionContext.get_news_rag()` verfügbar machen |
| `finance_asset_analysis`  | `finance-guru-api/enrichment.upsert_asset_analysis()` (über n8n `09-…`) | nur `POST /enrichment/asset-analysis/search` (ungenutzt vom Dashboard und von Strategien)   | ☆☆★★★ existiert, wird nicht in Loops gezogen  | RAG-Kontext für Strategie-Generator |

**Fehlt komplett:**

* `finance_social` (geschrieben von `finance-social/qdrant_sink.py`,
  aber im guru-api gibt es keinen Read-Helper → DecisionContext
  hat nur SQL-basierten `get_social`, keinen vektorbasierten).
* `finance_relations` — Kausalketten ("Hormuz-Schließung" →
  betroffene Symbole/Sektoren). Existiert noch nicht.
* `finance_strategy_lessons` — was hat eine Strategie gelernt
  (Reasoning-Text der gescheiterten Strategien, RAG-fähig für den
  Strategie-Generator).

### Sofortmaßnahmen Qdrant (gehen in §3)

1. Read-Helper `qdrant_rag.py` in `finance-guru-api/app/` mit:
   `search_assets()`, `search_news_semantic()`,
   `search_social_semantic()`, `search_asset_analyses()`,
   `search_relations()`, `search_strategy_lessons()`.
2. `DecisionContext` um `get_rag_*`-Callables erweitern; alle
   Strategien dürfen sich Kontext ziehen, der **Verifier** (s. §4)
   hält LLM-Halluzinationen raus.
3. Zwei neue Collections (`finance_relations`,
   `finance_strategy_lessons`) plus Payload-Index in
   `qdrant_sink.ensure_*_collection()`.

---

## 2. Bestandsanalyse Strategien

| Strategie            | Logik                          | RAG?     | LLM?                          | 1-Wochen-Gate? | Auto-Generated? |
|----------------------|--------------------------------|----------|-------------------------------|----------------|------------------|
| `news_sentiment`     | letzte 60 min Sentiment≥+0.5   | nein     | nur Reason-Polish (fast)      | nein           | nein             |
| `momentum_breakout`  | 20-bar high + Volume-Spike     | nein     | nein                          | nein           | nein             |
| `social_buzz`        | Reddit-Buzz + Sentiment        | nein     | nur Reason-Polish (fast)      | nein           | nein             |

Beobachtungen:

* Alle Strategien sind **Hand-Code**. Kein Pfad, um RAG-getriebene
  Strategien dynamisch zu erzeugen.
* `seed_eur` ist 1 000 €, gezahlt **einmal** bei
  `ensure_strategy`. Es gibt keinen Reset / kein "Strategie gescheitert
  → entferne sie aus dem aktiven Cron-Slot".
* Backtest existiert (`/backtest`), wird aber nicht **automatisch** vor
  Promotion einer neuen Strategie gefahren.

---

## 3. n8n-Workflows: Leerlauf-Audit

| Workflow                                | Cron           | Pro Run       | Issue                                                                                          |
|-----------------------------------------|----------------|---------------|------------------------------------------------------------------------------------------------|
| `09-finance-asset-behaviour.json`       | `*/5 min`      | **1 Symbol**  | bei ~500 Symbolen = ~41 h pro Volldurchlauf. Parallelisierung nutzlos, weil cooldown `Wait 5min` |
| `10-finance-source-reliability.json`    | `0 */6 h`      | **1 Source**  | bei ~30 Quellen = ~7 Tagen pro Volldurchlauf, identisches Cooldown-Pattern                     |
| `finance-vector-refresh.json`           | `0 4 * * *`    | full          | ok                                                                                             |
| Fehlt                                   | —              | —             | **Strategie-Generator** (RAG → neue Strategie-Idee → Backtest → Promotion)                      |
| Fehlt                                   | —              | —             | **Strategie-Auditor** (7-Tage-Performance prüfen, < +10 % ⇒ retire + Lessons-Embedding)         |
| Fehlt                                   | —              | —             | **Kausalketten-Extractor** (Headlines → Geo/Event → Sektoren → Symbole, in `finance_relations`)  |
| Fehlt                                   | —              | —             | **Opportunity-Scanner** (RAG-Query nach Themen, die mehrere Symbole gleichzeitig betreffen)     |

Optimierungsmöglichkeiten an bestehenden Workflows:

* **Asset Behaviour**: Cron auf `*/2 min` mit `n=3` Symbole pro Run
  (3× SplitInBatches → Loop). Erspart Leerlauf. Cooldown bleibt
  global `5 min` über `Set Lock`-Node in Redis/SQLite.
* **Source Reliability**: 1×/h, Batch von 5 Quellen pro Run; LLM-Call
  bleibt 1× (Prompt liefert JSON-Array statt eines einzelnen Objekts).
* Beide Workflows: neuer Endpoint
  `POST /enrichment/next-candidate-batch` (Server entscheidet
  Batch-Größe, Workflows werden dumm).

---

## 4. Anti-Halluzination — Verifier-Pattern flächendeckend

Wiederverwenden was `09-finance-asset-behaviour.json` schon macht:

* LLM-Output ist immer **strukturiert** (JSON-Schema, kein Freitext).
* Jedes "Faktum" (Datum, Move-Prozent, news_id, Symbol, Sektor) wird
  **gegen die Eingabe** verifiziert (Python-Node prüft Set-Membership).
* Bei Verstoß: drop the field, log it, confidence ⨯ 0.5 multiplizieren.

Anwendungen:

* **Strategie-Generator**: LLM darf nur `signals_logic` aus einer
  vordefinierten DSL (s. §6) liefern; jede `symbol`-Erwähnung muss in
  der gerade gesehenen `universe`-Liste vorkommen.
* **Kausalketten-Extractor**: jeder Knoten muss entweder eine
  bekannte Geo-/Event-Entity sein (NER-Whitelist) oder eine
  TimescaleDB-Symbol-Row haben.
* **News-Sentiment-Reprise**: zusätzlich zur bestehenden
  `finance-news/sentiment.py` (LLM `fast`) ein
  *Konsistenz-Check* gegen `finance_asset_analysis`-Treffer der
  letzten 30 d des gleichen Symbols — widersprüchliches Sentiment
  setzt `payload.contradiction=true`.

---

## 5. Sidebar — `UTree` statt flache `UNavigationMenu`

Aktuell: `SidebarMenu.vue` rendert `UNavigationMenu` flach.
Ziel: rekursiv-baumartig mit `UTree` (Nuxt UI v4) für Items mit
`children`.

### Datenmodell-Erweiterung (`useDashboardRoutes.ts`)

```ts
export interface DashboardRoute {
  id: string
  to?: string                 // optional, wenn Knoten nur Container
  label: string
  icon: string
  order: number
  predicate?: (ctx: PredicateContext) => boolean
  children?: DashboardRoute[] // NEU
}
```

### Finance-Guru-Knoten neu

```ts
{
  id: 'finance-guru',
  label: 'Finance Guru',
  icon: 'i-lucide-trending-up',
  order: 4.5,
  predicate: ({ hasService }) =>
    hasService('finance-guru') || hasService('lotto-oracle'),
  children: [
    {
      id: 'finance-guru.trading',
      to: '/finance-guru/trading',
      label: 'Trading',
      icon: 'i-lucide-line-chart',
      order: 0,
      predicate: ({ hasService }) => hasService('finance-guru'),
    },
    {
      id: 'finance-guru.lotto',
      to: '/finance-guru/lotto',
      label: 'Lotto Orakel',
      icon: 'i-lucide-ticket',
      order: 1,
      predicate: ({ hasService }) => hasService('lotto-oracle'),
    },
  ],
}
```

### Page-Refactor

* `pages/finance-guru.vue` wird zu einer Redirect-Page
  (`navigateTo('/finance-guru/trading')` wenn beide Services
  vorhanden, sonst auf den verfügbaren) — die Hash-basierte
  Tab-Persistenz fällt weg.
* `pages/finance-guru/trading.vue` → mountet `StrategiesTab.vue`.
* `pages/finance-guru/lotto.vue` → mountet `LottoTab.vue`.
* Innerhalb dieser Seiten bleibt `UDashboardPanel` + `UDashboardNavbar`,
  Titel wechseln je nach Sub-Route.

### `SidebarMenu.vue`-Refactor

`UTree` mit `:items`, `:default-expanded` (alle, deren `children`
selektierten Pfad enthalten) und einem `#item`-Slot, der weiterhin
`UNavigationMenu`-Style rendert (Icon + Label + optional Badge).

---

## 6. Roadmap — phasenweise

### Phase A — Quick-Wins (1–2 Tage, kein Schema-Bruch) ✅ DONE 16.05.2026 (Commit fc2d3d5b)

1. ✅ **Sidebar `UTree`** (§5) inkl. Routen-Aufteilung
   `finance-guru/trading.vue` + `finance-guru/lotto.vue`.
   * `DashboardRoute` um optionales `to` + `children` erweitert,
     `visibleSidebar` filtert Children rekursiv und droppt leere
     Container.
   * `SidebarMenu.vue` rendert `UTree` (expanded → Tree, collapsed →
     flach via `UNavigationMenu` als Fallback, da UTree keine
     Icons-only-Variante hat).
   * `pages/finance-guru.vue` ist jetzt ein Service-aware Redirect,
     der alte `#lotto`-Hash bleibt funktional.
2. ✅ **n8n Asset-Behaviour-Batching**:
   * Server-Endpoint `POST /enrichment/next-candidate-batch`
     (Helper `enrichment.next_candidate_batch()`).
   * Workflow 09: Cron `0 */5` → `0 */2`, Cooldown `5 min` → `60 s`,
     Candidate-Picker holt jetzt eine Batch (`limit=3` Stocks +
     `limit=2` Crypto), nimmt aber **noch** nur das erste Symbol.
     Begründung: die Downstream-Nodes (`Build LLM payload`,
     `Verifier`) lesen via `$node['Pick candidate'].json` — das ist
     `first-item-only`. True per-item Parallel-Batching erfordert
     Umbau auf `$input.item.json` → schiebe ich nach Phase A.2.
3. ✅ **n8n Source-Reliability-Batching**:
   * Workflow 10: Cron `0 0 */6` → `0 0 *` (stündlich). Workflow
     batched intern bereits alle Quellen pro Run.
4. ⏭️  **`useFinanceGuru.ts` ETag-aware Polling**: deferred nach
   Phase B — kein Blocker, Nice-to-have.

**Lessons learned aus Phase A:**

* Erwartete Throughput-Steigerung Workflow 09 war **2.5×**
  (`*/5 → */2`), gemessen aber nur **~1.2–1.5×** weil der reale
  Bottleneck die LLM-`default`-Antwortzeit ist (~3–4 min/Call auf
  Halo Strix). Bei laufender Verarbeitung dropt der nächste
  Cron-Tick wegen `coalesce` ohnehin. Der Gewinn kommt v.a. aus dem
  **kürzeren Cooldown** (5 min → 60 s).
* Echte Throughput-Skalierung erfordert entweder:
  - **Phase A.2**: per-item Parallel-Batching (Nodes refactor auf
    `$input.item.json`) — dann verarbeitet ein Cycle 3 Symbole
    sequenziell aber innerhalb eines LLM-Calls (Batched-Prompt).
  - **Phase B**: Wechsel auf LLM-`fast` für die erste Vorqualifikation
    + `default` nur für komplexe Cases.
* UTree-Komponente in Nuxt UI v4 hat **keine collapsed/icons-only
  Variante** → wir mussten den Fallback auf `UNavigationMenu` mit
  flatten-Logik bauen. Akzeptabler Trade-off; alternativ später
  einen eigenen Custom-Tree-Renderer für Collapsed.
* Routing-Split funktioniert sauber (alle 3 Pfade liefern HTTP 200,
  Nuxt-Routes-Map in `client.precomputed.mjs` zeigt
  `/finance-guru`, `/finance-guru/lotto`, `/finance-guru/trading`).

**Smoke-Test-Ergebnisse (16.05.2026, post-deploy):**

```
finance-guru-api/health           → {"status":"ok", strategies=3}
POST /enrichment/next-candidate-batch (limit=3)
                                  → ["AAPL","GOOGL","MSFT"], count=3
GET /finance-guru                 → 200 (SPA-Redirect ins richtige
                                       Sub-Pages je Service-Inventar)
GET /finance-guru/trading         → 200
GET /finance-guru/lotto           → 200
n8n FinAssetBehav001              → aktiv, neuer Cron-Wert geladen
n8n FinSourceRel0001              → aktiv, stündlich
```

### Phase A.2 — Echte Per-Item Batching (Follow-up, 0.5–1 d) ✅ DONE 16.05.2026

* ✅ Refactor Workflow 09: `Build LLM payload` und `Verifier`
  laufen jetzt mit `mode: 'runOnceForEachItem'`, ziehen den
  passenden Pick / Preise / News-Eintrag via
  `$('NodeName').item.json` aus der paired-item-Kette statt aus
  `.first()`. `GET 6mo news` referenziert ebenfalls
  `$('Pick candidate').item.json`. `Report OK` / `Report error`
  nehmen `.item.json` statt `.first().json`.
* ✅ `Pick candidate` emittiert pro Cron-Tick bis zu **5 Items**
  (3 Stocks + 2 Crypto) statt einem einzigen Symbol. Skip-Fallback
  bleibt 1-Item, damit `Report skipped` nichts kaputtmacht.
* ✅ **Connection-Bug behoben** (war beim Phase-A-Rename liegen
  geblieben): `connections` referenzierten weiterhin
  `"Every 5 min"` / `"Cooldown 5 min"` während die Nodes
  `"Every 2 min"` / `"Cooldown 60s"` hießen — Workflow lief
  vorher nur über den Manual Trigger. Jetzt synchron.
* ✅ `executionTimeout` von 600 s auf **1200 s** hochgesetzt
  (kumulativ können 5 × LLM-`default`-Calls à ~3–4 min knapp
  werden; Cooldown 60 s bleibt einmalig pro Execution, weil
  `Wait` ein einmaliger Wait pro Execution ist und nicht pro
  Item feuert).
* ✅ `orchestrator.run_strategy_once()` schreibt `signal.extra`
  (inkl. neuem `rag`-Block, s. Phase B) mit ins `executed`-Log,
  so dass Phase-D-Auditing die Belege je Trade einsehen kann.

**Erwartete Throughput-Steigerung:** **5×** (1 Symbol/Run → 5
Symbole/Run); 30 Symbole/h → **bis zu 150 Symbole/h**. Realer
Wert hängt von der `default`-LLM-Latenz ab — bei ~3 min/Call und
1200 s Timeout passen ~6 Items locker in eine Execution, im
Worst-Case wartet n8n `coalesce` den nächsten Tick ab.

**Smoke-Test-Checkliste (Phase A.2):**

```
# Per-item-Batching: Logs zeigen ≥ 3 unterschiedliche
# `target`-Symbole in einer Workflow-Execution:
n8n UI → Executions → FinAssetBehav001 → letzte Execution →
  Verifier (anti-hallucination): 5 Output-Items, je eigenes
  `symbol`
  Store analysis: 5 separate POSTs an
  /enrichment/asset-analysis (HTTP 201)
  Report OK: 5 separate POSTs an /enrichment/run

# Connection-Sanity:
curl -s http://127.0.0.1:5678/api/v1/workflows/FinAssetBehav001 \
  -H "X-N8N-API-KEY: ${N8N_API_KEY}" \
  | jq '.connections | keys'
# enthält "Every 2 min" und "Cooldown 60s", keine 5-min-Namen.

# Cron lebt:
n8n UI → Executions: ein neuer Run alle 2 min.
```

### Phase B — RAG-Aktivierung (3–5 Tage) ✅ DONE 16.05.2026

5. ✅ **`app/qdrant_rag.py`** — neuer, unifizierter Read/Write-Layer
   für *alle* sechs finance-Collections:
   * Read: `search_assets`, `search_news`, `search_social`,
     `search_asset_analyses`, `search_relations`,
     `search_strategy_lessons`.
   * Write: `upsert_relation` (Phase E entrypoint),
     `upsert_strategy_lesson` (Phase C entrypoint).
   * Bootstrap: `ensure_relations_collection`,
     `ensure_lessons_collection` mit Payload-Indizes
     (`theme/entities/symbols/sectors/mechanism/confidence/ts_unix`
     für relations; `strategy/outcome/pnl_pct/ts_unix` für
     lessons).
   * Status: `collection_status()` listet exists/points/dim für
     alle sechs — wird von `GET /rag/status` exponiert.
6. ✅ **`DecisionContext`** um sechs Callables erweitert
   (`get_assets_rag`, `get_news_rag`, `get_social_rag`,
   `get_analysis_rag`, `get_relations_rag`,
   `get_strategy_lessons_rag`). Default = `None`, Strategien
   prüfen explizit, damit alte Plugins beim Import nicht crashen.
7. ✅ **`orchestrator._build_context`** verdrahtet alle sechs in
   die `DecisionContext`-Instanz.
8. ✅ **`news_sentiment`-Strategie** demonstriert RAG-Nutzung:
   pro Signal wird `_rag_evidence(ctx, symbol, …)` aufgerufen
   und steckt Top-3 `finance_asset_analysis`-Treffer + Top-3
   `finance_news`-Treffer + Top-2 `finance_relations`-Treffer
   in `signal.extra["rag"]`. Fehlerresistent — leere Listen wenn
   Qdrant nicht erreichbar.
9. ✅ **`orchestrator.run_strategy_once()`** propagiert
   `sig.extra` ins `executed`-Cycle-Log → DoD §10/B erfüllt:
   jedes ausgeführte Signal trägt im Cycle-Log mindestens einen
   RAG-Eintrag (mindestens leere Listen, sobald Collections
   gefüllt sind echte Treffer).
10. ✅ **Bearer-guarded Write-Endpoints** für die Phase-D/E-Workflows:
    * `POST /rag/relation` (n8n Phase-E `13-finance-causal-extraction`)
    * `POST /rag/strategy-lesson` (Phase-C `weekly_audit` ruft das
      gleichermaßen + die n8n-Phase-D-Workflows können archivieren).
11. ✅ **Read-Endpoints** offen (dream-network internal, kein
    Bearer): `/rag/{news,social,asset-analysis,relations,strategy-lessons}`
    (POST mit `query`+Filtern) und `/rag/status` (GET).
12. ✅ **Env-Vars** (Defaults konservativ):
    * `FINANCE_ASSETS_COLLECTION=finance_assets`
    * `FINANCE_SOCIAL_COLLECTION=finance_social`
    * `FINANCE_RELATIONS_COLLECTION=finance_relations`
    * `FINANCE_STRATEGY_LESSONS_COLLECTION=finance_strategy_lessons`
    * `FINANCE_GURU_RAG_TOPK=10`
    * Compose-Defaults gesetzt; `.env`-Override optional.

**Smoke-Test-Checkliste (Phase B):**

```
# Status der RAG-Collections:
curl -s http://127.0.0.1:8098/rag/status | jq
# erwartet: 6 Einträge; assets/news/social/asset_analysis sollten
# exists:true sein, relations/lessons noch exists:false bis Phase E
# / Phase C sie schreiben.

# Semantische Suche über Asset-Analysen (sofortiger Hit, da n8n
# Workflow 09 die Collection füllt):
curl -s -X POST http://127.0.0.1:8098/rag/asset-analysis \
  -H "Content-Type: application/json" \
  -d '{"query":"ETF inflow positive sentiment","limit":3}' | jq '.count, .hits[0]'

# Semantische Suche über News:
curl -s -X POST http://127.0.0.1:8098/rag/news \
  -H "Content-Type: application/json" \
  -d '{"query":"interest rate cut Federal Reserve","limit":3}' | jq '.count'

# Strategy-Lesson schreiben + suchen (Bearer required):
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -s -X POST http://127.0.0.1:8098/rag/strategy-lesson \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"strategy":"smoke_test","outcome":"note","lesson":"smoke-test lesson body","keywords":["smoke","test"]}'
curl -s -X POST http://127.0.0.1:8098/rag/strategy-lessons \
  -H "Content-Type: application/json" \
  -d '{"query":"smoke test","limit":3}' | jq

# Cycle-Log mit RAG-Evidence (DoD §10/B):
curl -s -X POST http://127.0.0.1:8098/decide \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"strategy":"news_sentiment"}'
# nach einer Minute:
curl -s "http://127.0.0.1:8098/cycles?strategy=news_sentiment&limit=1" \
  | jq '.cycles[0].payload.executed[0].extra.rag'
# erwartet: {symbol, seed, analyses:[…], news:[…], relations:[…]}
```

**Lessons learned aus Phase B:**

* Wir mussten doppelt einbinden: `qdrant_sink.py` ist das
  bestehende Write-Modul (asset_analysis + source-weight-Patch),
  `qdrant_rag.py` das neue Read+Write-Modul für die zusätzlichen
  Collections. Beide teilen die `tei_embed`-Logik trivial und
  bleiben getrennt, damit der Hot-Write-Pfad keine RAG-Imports
  zieht und die Bootstrap-Reihenfolge (Sink → Collection → Embed
  → Upsert) klar dokumentiert bleibt.
* `DecisionContext`-Callables sind alle optional (`= None`).
  Strategien müssen `if ctx.get_news_rag is None: skip` prüfen.
  Vorteil: alte Plugins (`momentum_breakout`, `social_buzz`)
  laufen ungebremst weiter, neue können selektiv RAG ziehen.
* Cycle-Log `payload_json` enthält jetzt `executed[].extra.rag`.
  Bei vielen Trades pro Cycle wächst die Spalte — falls das in
  Produktion zum Problem wird, bei `cycle_log.record()` ein
  zusätzliches Trimming auf z.B. die 3 stärksten Hits pro Block
  einziehen. Aktuell unproblematisch (≤ 3 buys + ≤ N sells pro
  Cycle, je ≤ 8 kleine Treffer).
* `qdrant_rag.collection_status()` ist defensiv: wenn ein einzelner
  Collection-Check exceptet, wird ein Fehler-Row mit `exists:false`
  zurückgegeben statt die ganze Antwort zu killen.



### Phase C — Strategie-Lifecycle (5–7 Tage)

8. **DB-Tabelle `strategies_meta`** in `ledger.sqlite`:
   `(name, kind, created_at, retired_at, parent_id, source_json,
   bt_pnl_pct, bt_n_trades, live_started_at)`.
9. **`/strategies/lifecycle` Endpoint**:
   * `POST /strategies/promote` (LLM-generierte Strategie aus
     `pending` → aktiv, nachdem Backtest grün).
   * `POST /strategies/retire` (mit Grund + `lessons_text`).
   * `GET /strategies/leaderboard?window=7d`.
10. **`orchestrator.weekly_audit()`**: läuft sonntags 23:55,
    iteriert über live-Strategien, berechnet 7-Tage-PnL, retired
    alles < +10 %, embedded Lessons.
11. **APScheduler-Job** dafür + n8n-Workflow
    `11-finance-strategy-audit.json` als Fallback-Trigger
    (`POST /strategies/audit`).

### Phase D — Strategie-Generator (7–10 Tage)

12. **Strategie-DSL** in `app/strategies/dsl.py`:
    JSON-Schema mit erlaubten Bausteinen
    (`when: {signal: 'sentiment', op: '>=', value: 0.5}`,
    `and / or`, `action: buy/sell`, `sizing: max_frac/fixed_eur`).
13. **`app/strategies/llm_generated.py`**: Loader, der eine Zeile
    aus `strategies_meta.kind='generated'` in eine Pseudo-`StrategyDef`
    übersetzt (interpretiert die DSL → `decide(ctx)`-Closure). Damit
    bleibt Discovery automatisch, ohne neue Python-Files.
14. **n8n-Workflow `12-finance-strategy-genesis.json`** (Cron `0 */6 h`):
    * Query an Qdrant `finance_relations` + `finance_asset_analysis`:
      "welche Themen haben in den letzten 7 d die meiste
      Sentiment-Bewegung?".
    * LLM `reasoning` (`Qwen3.5-122B-A10B`) erzeugt **1–3 DSL-Patches**
      (mit Verifier).
    * `POST /strategies/propose` → guru-api macht **automatischen
      Backtest** über die letzten 30 d Daten.
    * Wenn `bt_pnl_pct >= 4 %` und `n_trades >= 5` → automatisch
      promotet, sonst archiviert in `finance_strategy_lessons`.

### Phase E — Kausalketten (7–10 Tage, parallel zu D möglich)

15. **`finance_relations`-Collection** anlegen
    (Payload: `{theme, entities[], symbols[], sectors[], evidence_ids[],
    confidence, ts}`).
16. **n8n `13-finance-causal-extraction.json`** (Cron `*/15 min`,
    batched):
    * Holt die letzten 6 h news.events mit `urgency >= 2`.
    * LLM `default` extrahiert pro Headline ein
      `{event, geo, mechanism}`-Triple + Vorschlag betroffener
      Sektoren/Symbole.
    * Verifier: jedes Symbol muss in TimescaleDB existieren.
    * Aggregiert pro Thema → Upsert in `finance_relations`.
17. **`relations_rag` Strategie** (Phase F): RAG-Treffer aus
    `finance_relations` + Price-Korrelation gegen Sektor-Proxy =
    BUY-Signal.

### Phase F — Dashboard-Erweiterungen

18. **`pages/finance-guru/trading.vue`** bekommt zusätzlich:
    * **`StrategiesLifecyclePanel.vue`** (live + retired Tabs,
      Leaderboard 7d).
    * **`RagInsightsPanel.vue`** (zeigt Top-5 Treffer aus
      `finance_asset_analysis` + `finance_relations` für jede
      aktuelle Position).
    * **`CausalGraphView.vue`** (D3-/Cytoscape-ähnlich, oder
      simples ECharts-Sankey: Event → Sektor → Symbol).
19. **`useFinanceGuru.ts`** um RAG-Endpoints erweitern; alle
    neuen Panels über `usePolling` mit angepassten Intervallen.

### Phase G — Härtung & Aufräumen

20. **Backtest-Pflicht im Promotion-Pfad**: ohne grünen Backtest
    keine Promotion (auch nicht manuell — Header-Override mit
    `X-Force-Promote: 1` nur für Operator).
21. **Cycle-Log-Index** um `bt_pnl_pct` + `kind` erweitern,
    Dashboard-Filter "nur generierte".
22. **Docs**: `dream-server/docs/RAG-FINANCE.md` mit
    Collection-Schemas + Beispiel-Queries.

---

## 7. Strategie-Lifecycle-Detailspezifikation (für Phase C)

### State-Machine

```
proposed ──backtest_ok──▶ live ──weekly_audit failed──▶ retired
   │                                                       │
   └──backtest_failed──▶ archived ◀──auto-archive(>30d)────┘
```

### 7-Tage-Gate-Algorithmus

```python
def weekly_audit(strategy_name: str) -> Outcome:
    snap = cycle_log.equity_history(strategy_name, days=7)
    if len(snap) < 50:        # zu wenig Daten → kein Urteil
        return Outcome.NEED_MORE_DATA
    seed = CFG.seed_eur
    pnl_pct = (snap[-1].equity - seed) / seed * 100
    if pnl_pct >= 10.0:
        return Outcome.PASS
    return Outcome.RETIRE_AND_LEARN
```

Bei `RETIRE_AND_LEARN`:

```python
lessons = build_lesson_text(strategy_name, last_30d_trades,
                            last_30d_signals, market_context)
qdrant_sink.upsert_strategy_lesson(
    strategy=strategy_name,
    pnl_pct=pnl_pct,
    lesson=lessons,
    ts=now,
)
ledger.retire_strategy(strategy_name, reason=f"pnl_7d={pnl_pct:.2f}%")
```

`build_lesson_text` ruft `reasoning`-Modell auf, max **1×/Woche pro
retired Strategie** (Kostendisziplin §10 in AGENT-OPERATIONS.md).

---

## 8. Migrationen / Breaking Changes

* **Pages**: `/finance-guru` wird Redirect; alte Bookmarks mit
  `#lotto` → Server-Side `redirect-rules` in `nuxt.config.ts`
  übersetzt zu `/finance-guru/lotto`.
* **`DecisionContext`-Felder neu (alle `field(default=None)`)** —
  alte Strategien laufen weiter.
* **Neue `.env`-Variablen** (mit Defaults):
  * `FINANCE_GURU_WEEKLY_AUDIT_CRON=55 23 * * 0`
  * `FINANCE_GURU_TARGET_WEEK_PCT=10.0`
  * `FINANCE_GURU_RAG_TOPK=10`
  * `FINANCE_RELATIONS_COLLECTION=finance_relations`
  * `FINANCE_STRATEGY_LESSONS_COLLECTION=finance_strategy_lessons`

---

## 9. Reihenfolge & Aufwandsschätzung

| Phase | Inhalt                           | Aufwand | Abhängig von |
|-------|----------------------------------|---------|--------------|
| A     | Sidebar-UTree + n8n-Batching     | 1–2 d   | —            |
| B     | RAG-Reads in DecisionContext     | 3–5 d   | A            |
| C     | Strategie-Lifecycle + Audit      | 5–7 d   | B            |
| D     | Strategie-Generator (DSL+LLM)    | 7–10 d  | B+C          |
| E     | Kausalketten-Extraktor           | 7–10 d  | B            |
| F     | Dashboard-Panels (RAG, Graph)    | 4–6 d   | B+C(+D+E)    |
| G     | Härtung & Doku                   | 2–3 d   | alle         |

Gesamt: ~30 d AI-Agent-Arbeit, parallelisierbar in 3 Tracks
(Backend-RAG, Lifecycle, Frontend).

---

## 10. Definition of Done je Phase

* **A**: Sidebar zeigt Finance Guru als Tree mit zwei Kindern; alte
  Tabs entfernt; n8n-Workflows verarbeiten je Run ≥ 3 (Asset) bzw.
  ≥ 5 (Source) Targets; `dream check-image-updates` grün.
* **B**: `curl POST /strategies/decide` einer Test-Strategie liefert
  in den Cycle-Log-Notes mindestens einen RAG-Treffer-Eintrag pro
  Signal.
* **C**: Sonntag 23:55 erfolgt automatisches Retirement aller
  Strategien < +10 % WoW; UI-Panel "Retired Strategies"
  rendert die Lessons.
* **D**: Innerhalb 7 d nach Phase-D-Release tauchen ≥ 5
  LLM-generierte Strategien in `strategies_meta` auf, davon ≥ 1
  promoted.
* **E**: `finance_relations` enthält ≥ 50 Themen-Knoten;
  `CausalGraphView` rendert für jedes Symbol einer offenen Position
  mindestens 1 Pfad.
* **F**: Alle neuen Panels passen ins Polling-Budget
  (≤ 1 zusätzlicher Roundtrip / 30 s).
* **G**: `dream-server/docs/RAG-FINANCE.md` lebt, Cycle-Log filtert
  nach `kind=generated`.

---

## 11. Was wir bewusst **nicht** tun

* **Echtgeld-Anbindung**: bleibt out-of-scope wie bei Lotto (§13
  AGENT-OPERATIONS) — alles Paper-Trade.
* **Reinforcement Learning**: kein RL-Agent. Genesis durch LLM +
  DSL ist deterministisch genug und nachvollziehbar.
* **Externes Feature-Engineering-SaaS** (FeatureLabs etc.):
  alles bleibt im AMD-/CPU-only Stack der Halo Strix.
* **Tabs zurück**: nach Phase A wird `UTree` nicht wieder gegen
  Tabs eingetauscht; falls nötig kommt eine `UBreadcrumb` als
  Sekundärnavigation.

