# Finance Guru — Verbesserungsplan (Paper-Trading, RAG, Qdrant, UI)

> Stand: 05/2026 · Status: Phase A ✅ · Phase A.2 ✅ · Phase B ✅ · Phase C ✅ · Phase D ✅ deployed
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



### Phase C — Strategie-Lifecycle (5–7 Tage) ✅ DONE 16.05.2026

8. ✅ **DB-Tabellen `strategies_meta` + `strategy_audits`** in
   `ledger.sqlite` (gleiches File wie Ledger + Cycle-Log → ein
   konsistentes Backup). Spalten gemäss §7-Spec plus
   `last_audit_at/_pnl/_n`, `lessons_qid`, sowie ein
   `strategy_audits`-Audit-Log mit `(transition, from_status,
   to_status, pnl_pct, n_cycles, note, actor)`. Jede Mutation läuft
   durch `lifecycle._transition()` → genau eine Audit-Quelle.
9. ✅ **`/strategies/*` Lifecycle-Endpoints**:
   * `GET  /strategies/lifecycle?status=&kind=&limit=` — list_meta
   * `GET  /strategies/leaderboard?window=7&limit=50` —
     live/proposed/retired sortiert, %-PnL aus Equity-History des
     Fensters (NICHT vom Seed, sondern vom ersten Cycle des
     Fensters → korrekte "letzte-Woche"-Sicht).
   * `GET  /strategies/audits?strategy=&limit=` — Audit-Trail.
   * `POST /strategies/propose`  (Bearer, Phase-D-Entrypoint).
   * `POST /strategies/promote`  (Bearer, fordert
     `bt_pnl_pct >= target` außer mit `force=true` oder
     Header `X-Force-Promote: 1` → operator override).
   * `POST /strategies/retire`   (Bearer, optional `emit_lesson`).
   * `POST /strategies/audit?sync=true|false`  (Bearer; async per
     default, `sync=true` gibt das Ergebnis sofort zurück).
   * `GET  /strategies/audit/last` — letztes Ergebnis (n8n-Workflow
     fragt das ab um zu entscheiden ob er Fallback feuern muss).
10. ✅ **`lifecycle.weekly_audit()`** läuft via APScheduler-Job
    `weekly_audit` (`coalesce=true`, `misfire_grace_time=24 h`) zu
    `FINANCE_GURU_WEEKLY_AUDIT_CRON` (default `55 23 * * 0` in
    der Service-TZ). Pro live-Strategie:
    1. `audit_one()` rechnet %-PnL der letzten 7 d (equity_first →
       equity_last); braucht ≥ `FINANCE_GURU_AUDIT_MIN_SAMPLES`
       (default 50 cycles) sonst Outcome `need_more_data`.
    2. Outcome `pass` (≥ Target) → `last_audit_*` updated, kein
       Status-Wechsel.
    3. Outcome `retire` → `build_lesson_text()` ruft
       `llm.chat(model='reasoning', timeout=300s)` mit Kontext aus
       Trades + Equity (Template-Fallback bei LLM-Down), embedet die
       Lesson in `finance_strategy_lessons` via Phase-B-Sink, ruft
       `lifecycle.retire()` und setzt `lessons_qid=strategy_name`.
11. ✅ **APScheduler `auto_archive`** läuft täglich
    (`FINANCE_GURU_AUTO_ARCHIVE_CRON` default `10 4 * * *`):
    * `retired` > 90 d → `archived`,
    * `proposed` > 30 d ohne Promote → `archived`.
12. ✅ **n8n Fallback-Workflow
    `11-finance-strategy-audit.json`** (Mondays 00:05) prüft via
    `GET /strategies/audit/last`, ob die APScheduler-Slot tatsächlich
    in den letzten 25 h gelaufen ist; wenn nicht (z.B. Container down
    übers Wochenende), feuert er `POST /strategies/audit?sync=true`
    nach und wartet bis zu 10 min. Normalfall = No-Op +
    enrichment_runs-Log-Eintrag.

**Lifecycle-State-Maschine** (implementiert in
`lifecycle._transition()`):

```
proposed ──promote (backtest_ok)──▶ live ──audit:retire──▶ retired
   │                                   │                      │
   │                                   └─audit:pass─(stays live)
   └─archive (backtest_fail OR ≥30d)──▶ archived ◀─(retired→archived after 90d)
```

**Kosten-Disziplin** (§10 AGENT-OPERATIONS):

* `reasoning` (Qwen3.5-122B-A10B) wird **nur** für die
  Lesson-Erzeugung gerufen, **maximal 1× pro retired Strategie
  pro Woche**, **nicht** in jedem Decide-Tick.
* `emit_lessons=false` Flag erlaubt Operator-Dry-Runs ohne LLM-Cost.
* `build_lesson_text()` hat einen deterministischen Template-Fallback
  → LLM-Outage blockiert die Retirement nicht.

**Env-Vars** (Defaults konservativ):

```env
FINANCE_GURU_WEEKLY_AUDIT_CRON=55 23 * * 0   # sundays 23:55 svc TZ
FINANCE_GURU_TARGET_WEEK_PCT=10.0
FINANCE_GURU_AUDIT_MIN_SAMPLES=50            # need >=50 cycles in 7d
FINANCE_GURU_AUTO_ARCHIVE_CRON=10 4 * * *
FINANCE_GURU_LESSON_LLM_MODEL=reasoning
FINANCE_GURU_LESSON_LLM_TIMEOUT=300
```

**Smoke-Test-Checkliste (Phase C):**

```
# 1) Lifecycle index — builtins auto-registered on lifespan startup
curl -s http://127.0.0.1:8098/strategies/lifecycle | jq '.count, .strategies[] | {name, kind, status}'
# expects: 3 live builtins (news_sentiment, momentum_breakout, social_buzz)

# 2) Audit trail — initial 'register' transition per builtin
curl -s http://127.0.0.1:8098/strategies/audits?limit=10 | jq

# 3) Manual audit synchronously, NO retiring + NO lesson cost:
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -s -X POST "http://127.0.0.1:8098/strategies/audit?sync=true" \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"retire_failing":false,"emit_lessons":false}' | jq

# 4) Promote-gating works:
curl -s -X POST http://127.0.0.1:8098/strategies/promote \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"news_sentiment","bt_pnl_pct":3.5,"bt_n_trades":12}'
# expects: HTTP 412 (backtest pnl < target). Then with force:
curl -s -X POST http://127.0.0.1:8098/strategies/promote \
  -H "Authorization: Bearer $TOK" -H "X-Force-Promote: 1" \
  -H "Content-Type: application/json" \
  -d '{"name":"news_sentiment","bt_pnl_pct":3.5,"bt_n_trades":12}' | jq

# 5) Leaderboard sortiert (live first, then by 7d pnl desc):
curl -s "http://127.0.0.1:8098/strategies/leaderboard?window=7" | jq '.rows[] | {name, status, window_pnl_pct, window_cycles}'

# 6) Manual retire-with-lesson (this WILL spend a reasoning call):
curl -s -X POST http://127.0.0.1:8098/strategies/retire \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"social_buzz","reason":"smoke-test retire","emit_lesson":true}' | jq
# expects: status=retired, lessons_qid set, lesson preview present
# verify lesson is searchable:
curl -s -X POST http://127.0.0.1:8098/rag/strategy-lessons \
  -H "Content-Type: application/json" \
  -d '{"query":"social buzz retire","limit":3}' | jq

# 7) n8n fallback: import workflow 11; manual-trigger after a recent
# audit -> Log skip; manual-trigger after 25h gap -> runs sync audit.
```

**Lessons learned aus Phase C:**

* **Equity-Window-PnL ≠ Total-PnL.** Plan §7's pseudo-code rechnet
  `(snap[-1] - seed) / seed` — das ist die Lebenszeit-Rendite, nicht
  die Wochen-Performance. Implementiert habe ich
  `(equity_last - equity_first) / equity_first` über das Fenster:
  eine Strategie, die am Montag +50 % stand und Freitag bei +60 %,
  schafft die Schwelle korrekt (+6.7 % WoW). Die alte Formel hätte
  sie als "die +10 % WoW seit Anfang an" missgedeutet.
* **`audit:retire` darf nicht synchron Status auf `live` lassen.**
  Lese-Auflösung: `_transition` schreibt `to_status='live'` als
  "Audit-Outcome wurde während Status=live ermittelt"; der
  tatsächliche `retire()`-Aufruf bringt danach den Statuswechsel.
  In `strategy_audits` siehst du also Pair: `audit:retire (live→live)`
  + nachfolgend `retire (live→retired)`. Das hält Cause/Effect klar
  getrennt und vereinfacht Replay.
* **Lesson-Sink scheitert nicht hart bei TEI-Down.** `build_lesson_text`
  fängt LLM-Fehler ab → Template; `qdrant_rag.upsert_strategy_lesson`
  ist ohnehin best-effort. So bleibt der Retirement-Pfad atomar gegenüber
  Infra-Hiccups, und die Lesson kann notfalls über
  `POST /rag/strategy-lesson` nachgereicht werden.
* **Architektur-Entscheidung: kein eigenes Postgres für Lifecycle.**
  Die Tabellen leben in der gleichen `ledger.sqlite`, damit ein
  einzelnes Backup-File sowohl Ledger + Cycle-Log + Enrichment +
  Lifecycle atomar abdeckt (`cp ledger.sqlite ledger.sqlite.bak`
  während WAL-Checkpoint). Hätten wir Lifecycle in TimescaleDB
  gelegt, müsste `pg_dump` mit dem SQLite-Snapshot synchronisiert
  werden — Komplexität ohne Gegenwert bei <100 Writes/Tag.



### Phase D — Strategie-Generator (7–10 Tage) ✅ DONE 16.05.2026

12. ✅ **Strategie-DSL** in `app/strategies/dsl.py`:
    JSON-Schema v1 mit Bausteinen `when/all/any`,
    `signal/op/value`-Predicates aus einer fixen Whitelist
    (`news.sentiment_max`, `news.urgency_max`, `news.count`,
    `social.sentiment_mean`, `social.count`,
    `price.return_pct/breakout_high/volume_ratio`,
    `position.holds/pnl_pct`, `rag.relations_count`),
    `action: buy|sell`, `sizing: max_position_frac|fixed_eur`.
    Compiler erzeugt eine `StrategyDef` mit per-Cycle-Cache, sodass
    eine 10-Regel-Strategie über 200 Symbole maximal **einmal** je
    Datenquelle ruft (news/social/price/relations RAG). `validate_spec`
    rejected freie Symbol-Referenzen, die nicht in der Universe sind
    (anti-hallucination am Propose-Endpoint).
13. ✅ **`app/strategies/llm_generated.py`** — Loader liest
    `strategies_meta.kind='generated' AND status='live'` und mountet
    jede DSL-Zeile als pseudo-`StrategyDef` in den `REGISTRY` (kein
    extra Python-File pro Strategie). `register_generated()` ist die
    Hot-Path-Funktion, die der Genesis-Backtest unmittelbar nach
    Promote ruft → neue Strategien laufen ab dem nächsten Cron-Tick,
    ohne Container-Restart.
14. ✅ **`app/genesis.py` + `/strategies/propose?auto_backtest=true`
    (Default)** — Propose validiert die DSL synchron (`HTTP 400` bei
    Schema-Fehler) und plant per BackgroundTask einen Backtest über
    `FINANCE_GURU_GENESIS_BT_DAYS` (Default 30) mit
    `FINANCE_GURU_GENESIS_BT_STEP_MIN` (Default 60 min).
    `total_pnl_pct ≥ FINANCE_GURU_GENESIS_MIN_BT_PCT` (4.0 %) **und**
    `n_trades ≥ FINANCE_GURU_GENESIS_MIN_BT_TRADES` (5) → automatisch
    promotet (`lifecycle.promote` + `register_generated`); sonst
    archiviert mit deterministischer Begründung **plus** einem
    `finance_strategy_lessons`-Sink-Eintrag, damit der nächste Genesis-
    Cycle das Muster nicht erneut vorschlägt. Manueller Re-Run via
    `POST /strategies/{name}/evaluate?sync=true` (Bearer).
15. ✅ **`GET /strategies/dsl/catalog`** — exponiert Signal-Whitelist,
    Operatoren, Sizing-Modi, Limits und das Promotion-Gate, damit der
    Genesis-Workflow + die zukünftige Dashboard-DSL-Editor-UI exakt das
    gleiche Vokabular sehen wie der Server. Keine Auth — read-only,
    dream-network intern.
16. ✅ **n8n-Workflow `12-finance-strategy-genesis.json`** (Cron
    `0 0 */6 * * *`):
    1. `GET /strategies/dsl/catalog` + `/strategies/leaderboard?window=7`
       + `/history/symbols?hours=168`.
    2. `POST /rag/asset-analysis`, `/rag/relations`,
       `/rag/strategy-lessons` (Top-8/8/6 Treffer pro Aufruf).
    3. **Build brief**-Code-Node trimmt jeden Block auf <8 Felder
       pro Eintrag, damit der `reasoning`-Prompt nicht explodiert.
    4. `POST /v1/chat/completions` mit `model: 'reasoning'`
       (Qwen3.5-122B-A10B), `response_format: json_object`,
       `temperature: 0.2`. System-Prompt erzwingt die DSL-Shape
       inklusive `proposals[]`.
    5. **Verifier-Node** (JS) prüft jede `proposals[]`-Zeile gegen die
       Catalog-Whitelists (Signals, Ops, Sizing, Universe-Symbole).
       Rejected proposals werden gezählt und im
       `enrichment_runs`-Log unter `strategy_genesis`-Note vermerkt.
    6. Pro accepted proposal: `POST /strategies/propose` (Bearer) →
       Server feuert dann den Genesis-Backtest selbst.
    7. `Cooldown 60s` (kostendiszipliniert — der Cron-Slot ist
       alle 6 h, aber bei manuellem Re-Run verhindert das einen
       Burst).
17. ✅ **Lifespan-Hook** — `main.lifespan()` ruft nach
    `discover_strategies()` einmalig `llm_generated.load_generated_
    strategies(statuses=("live",))`, damit beim Container-Start jede
    bereits promotete generierte Strategie wieder in den REGISTRY
    geladen wird.
18. ✅ **Catalog-Eintrag** (`config/n8n/catalog.json`): neue Workflow-
    Karte `finance-strategy-genesis` + neue Kategorie `finance` für
    konsistente Filterung im Dashboard-n8n-Browser.

**Lessons learned aus Phase D:**

* **DSL-Whitelist > LLM-Freiheit.** Die erste Idee war ein freier
  Python-Closure-Generator über `code`-Modell — verworfen: der einzige
  Weg, eine LLM-generierte Strategie deterministisch zu auditieren ist
  eine geschlossene Predicate-DSL. Side-Effekt: Promotion-Gate-Bypass
  wird unmöglich, weil keine Strategie eigene Sizing-/Trade-Logik
  über den Whitelist hinaus ausdrücken kann.
* **Backtest vor Promote, nicht parallel.** Der Plan §6 hatte
  `propose → backtest → promote OR archive` als drei separate
  n8n-Steps. Reorg: Backtest **lebt im Service** (BackgroundTask) →
  n8n bleibt dumm. Vorteile: (a) Auth-Header nur einmal an
  `/strategies/propose`, nicht doppelt; (b) der Backtest sieht die
  exakte Python-Welt, die später live laufen wird (gleiche
  `DecisionContext`-Helpers, gleiche `latest_prices`-Pfade); (c) bei
  n8n-Outage bleibt der Genesis-Cycle einfach aus statt teilweise
  halbe Lifecycle-Rows zu hinterlassen.
* **Universe-Mismatch-Falle.** Ein Proposal mit `universe_filter`
  auf z.B. `[BNTX, MRNA]` lieferte 0 Trades im Backtest weil
  `prices_intraday` aktuell nur S&P-Top-200 hält. Lösung:
  Verifier-Node lehnt unbekannte Symbole bereits ab; `validate_spec`
  am Endpoint ist **ohne** Universe-Check tolerant (damit kurzfristige
  Universe-Ausfälle keine ganze Strategie killen), aber der Backtest-
  Gate kümmert sich um die wirtschaftliche Realität.
* **`reasoning`-Latenz.** Eine Genesis-Execution braucht ~3–4 min für
  den 122B-Call. Der Cron ist `*/6 h`, also locker im Budget, aber
  `executionTimeout: 1500 s` macht den Workflow robust gegen
  Modell-Pre-Warm-Effekte.
* **Lesson-Loop schließt sich.** Archivierte Proposals embedden ihre
  Reject-Begründung als `outcome='archived'`-Lesson; der Verifier des
  nächsten Cycles bekommt das im RAG-Block der Brief-Sektion zu sehen
  → die LLM-genesis ist selbst-korrigierend, ohne RL.

**Smoke-Test-Checkliste (Phase D):**

```
# 1) DSL catalog erreichbar:
curl -s http://127.0.0.1:8098/strategies/dsl/catalog | jq '.signals | keys | length, .gate'

# 2) Propose mit absichtlich-ungültiger DSL → HTTP 400:
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2-)
curl -s -o /dev/stderr -w "%{http_code}\n" -X POST http://127.0.0.1:8098/strategies/propose \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"bad","source":{"version":1,"rules":[]}}'
# erwartet: 400

# 3) Propose einer minimal-validen DSL → 201 + queued_backtest=true:
curl -s -X POST http://127.0.0.1:8098/strategies/propose \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"smoke_phaseD","source":{"version":1,"description":"smoke","rules":[
    {"id":"buy","action":"buy","when":{"all":[{"signal":"news.sentiment_max","lookback_h":4,"op":">=","value":0.5}]},"sizing":{"mode":"max_position_frac"}},
    {"id":"sell","action":"sell","when":{"all":[{"signal":"position.pnl_pct","op":">=","value":0.05}]}}
  ]}}' | jq

# 4) Nach ~30 s (kurzer Backtest): Lifecycle-Status sollte 'archived'
# (zu wenig Trades) ODER 'live' sein, NIE mehr 'proposed':
sleep 60 && curl -s "http://127.0.0.1:8098/strategies/lifecycle?kind=generated" | jq '.strategies[] | {name, status, bt_pnl_pct, bt_n_trades}'

# 5) Audit-Trail dokumentiert die Transition:
curl -s "http://127.0.0.1:8098/strategies/audits?strategy=smoke_phaseD" | jq

# 6) n8n: workflow 12 importieren, einmal manuell triggern, Logs prüfen:
n8n UI → Executions → FinStratGenesis001 → letzte Execution:
  - reasoning — propose DSL: HTTP 200 mit JSON object
  - Verifier (DSL): accepted ≥ 1 ODER skip=true mit Begründung
  - POST /strategies/propose: HTTP 201 mit queued_backtest=true
  - Cooldown 60s
```

### Phase D Roadmap-Reste (für später)

* **Cycle-Log-Filter `kind=generated`** im Dashboard — wird Teil von
  Phase F (Dashboard-Panels).
* **Operator-CLI** `dream finance-propose <file.json>` — Nice-to-have,
  kein Blocker; das Bearer-`curl` aus dem Smoke-Test reicht.
* **Genesis-Quota** (max N proposed/Woche) — frühestens wenn das
  Lifecycle-Backlog tatsächlich auf 100+ archived-Rows wächst.

### Phase D — Strategie-Generator (legacy plan section)

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

