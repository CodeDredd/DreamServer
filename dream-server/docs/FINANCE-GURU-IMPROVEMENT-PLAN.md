# Finance Guru — Verbesserungsplan (Paper-Trading, RAG, Qdrant, UI)

> Stand: 05/2026 · Status: Phase A ✅ · Phase A.2 ✅ · Phase B ✅ · Phase C ✅ · Phase D ✅ deployed · Phase E ✅ deployed · Phase G ✅ deployed
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
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2)
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
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2)
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

### Phase E — Kausalketten (7–10 Tage, parallel zu D möglich) ✅ DONE 16.05.2026

15. **`finance_relations`-Collection** ✅ vorhanden seit Phase B
    (Bootstrap-Helper `qdrant_rag.ensure_relations_collection`,
    Schreibhelfer `qdrant_rag.upsert_relation(...)`, HTTP-Endpoint
    `POST /rag/relation` und RAG-Such-Endpoint `POST /rag/relations`).
16. **n8n `13-finance-causal-extraction.json`** ✅ neu, Cron `*/15 min`:
    * `GET /history/news?hours=6&min_urgency=2&limit=120` ← neu hinzu-
      gefügte Query-Params (`hours` überschreibt `days`, `min_urgency`
      filtert serverseitig — schrumpft Payload an den LLM erheblich).
    * `GET /history/symbols?hours=168` liefert die Live-Universe.
    * **Build brief**: dedupliziert Headlines per
      `lower(source) + first 80 chars of title`, cappt auf 24 Items.
    * **LLM `default`** (kein Reasoning, Cost-Sparer) extrahiert
      `themes[]` mit `{theme, mechanism, summary, entities, sectors,
      symbols, evidence_ids, confidence}` als striktes JSON
      (`response_format: { type: 'json_object' }`).
    * **Verifier (relations)**:
      * filtert Symbole gegen die Live-Universe (Symbole, die nicht
        existieren, werden aus der Liste *entfernt* — aber das Thema
        bleibt erhalten, solange noch verifizierte Symbole/Evidence-IDs übrig sind),
      * filtert `evidence_ids` auf die tatsächlich übergebenen News-IDs
        des Briefs,
      * verwirft Themen mit `confidence < 0.3` oder ohne jedes
        verifizierte Symbol/Evidence,
      * begrenzt auf max. 6 Themen pro Run.
    * **POST `/rag/relation`** pro Thema (Bearer auth), danach
      `Report OK / reject / Log skip` ins `enrichment_runs`-Audit.
17. **`relations_rag` Strategie** — wird Phase F (Dashboard) zugeordnet,
    nicht Teil dieses Ships.

**Lessons learned aus Phase E:**

* **Server-side filter > LLM-side filter.** Die `min_urgency`-/`hours`-
  Query-Params auf `/history/news` sind ein 30-Zeilen-Patch, der den
  Token-Verbrauch des Extraction-Calls glatt halbiert. Solche Filter
  gehören vor das LLM, nicht in den System-Prompt.
* **Partielle Akzeptanz statt Reject.** Erstentwurf hat ein Thema
  komplett abgelehnt, sobald ein einziges nicht-Universe-Symbol darin
  war. Das hat funktionierende Macro-Themes verschenkt (z. B. "OPEC
  cuts" mit gültigen Energy-Tickern + einem halluzinierten EU-Ticker).
  Jetzt: Symbole werden gefiltert, das Thema bleibt, solange genug
  verifizierter Anker übrig ist.
* **`default` reicht für Themenextraktion.** `reasoning` (Qwen3.5-122B)
  ist hier nicht nötig — Headlines sind kurz, das Schema ist starr,
  der Job ist eher Klassifikation als Strategie-Design. Spart ~70 %
  Kosten pro Run gegenüber Workflow 12.
* **Cron alle 15 min ist ein Token-Verbraucher.** Wenn man das real
  laufen lässt, sind das 96 LLM-Calls/Tag — vergleichbar mit Workflow
  09 (asset-behaviour). Bei knappem Budget: Cron auf `*/30` oder
  `*/45` umstellen, der Trade-off ist nur Latenz beim Erkennen frischer
  Macro-Themen.

**Smoke-Test-Checkliste (Phase E):**

```bash
# 1) Neue Query-Params auf /history/news funktionieren:
curl -s "http://192.168.178.110:8098/history/news?hours=6&min_urgency=2&limit=5" \
  | jq '{n: (.rows | length), urgencies: ([.rows[].urgency] | unique)}'
# erwartet: alle urgencies >= 2; n <= 5

# 2) Workflow 13 manuell triggern:
#    n8n UI → "Finance Causal Extraction" → Execute Workflow
#    Erwartete Knotenkette: news → universe → brief → if → LLM →
#    verifier → if → POST /rag/relation (mehrfach) → Report OK

# 3) finance_relations enthält neue Einträge:
TOKEN=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2)
curl -s -X POST http://192.168.178.110:8098/rag/relations \
  -H "Content-Type: application/json" \
  -d '{"query":"macro themes affecting multiple symbols","limit":5,"min_confidence":0.3}' \
  | jq '.hits[] | {theme, mechanism, symbols, confidence, ts}'
# erwartet: ≥ 1 Treffer aus dem letzten 13-Workflow-Lauf

# 4) Audit-Trail sieht die Workflow-Runs:
curl -s "http://192.168.178.110:8098/enrichment/runs?workflow=causal_extraction&limit=5" \
  | jq '.runs[] | {ts, status, note}'
# erwartet: ok / skipped / error Einträge

# 5) DSL-Signal `rag.relations_count` kann jetzt sinnvoll feuern
#    (Phase D-Strategien haben Datengrundlage):
curl -s http://192.168.178.110:8098/strategies/dsl/catalog \
  | jq '.signals["rag.relations_count"]'
# erwartet: die Doku-Zeile aus dsl.py
```

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

### Phase G — Härtung & Aufräumen ✅ DONE 16.05.2026

20. ✅ **Backtest-Pflicht im Promotion-Pfad** —
    `POST /strategies/promote` prüft jetzt **beide** Gates synchron:
    `bt_pnl_pct >= FINANCE_GURU_TARGET_WEEK_PCT` und `bt_n_trades >=
    FINANCE_GURU_GENESIS_MIN_BT_TRADES`. Override **nur** über den
    Header `X-Force-Promote: 1` (Operator-only); das frühere
    `force: true`-Body-Feld wurde entfernt (Pydantic
    `model_config = {"extra": "forbid"}` → HTTP 422 bei Altcalls).
    Audit-Log differenziert `actor='operator:force-promote'`
    gegenüber `actor='operator'` (manuelle Promotion bei sauberem
    Gate) und `actor='system'` (Genesis-Pipeline).
    Response enthält `force_promoted: bool` + `gate_violations: []`,
    damit das Dashboard die Override-Markierung sichtbar machen
    kann.
21. ✅ **Cycle-Log um `kind` + `bt_pnl_pct`** —
    `cycle_runs` bekommt zwei neue Spalten (idempotente
    `ALTER TABLE`-Migration in `_ensure_extra_columns()`), die beim
    Insert per Lookup auf `strategies_meta` befüllt werden. Neuer
    Index `idx_cycle_runs_kind_ts (kind, ts DESC)`. Der API-Endpoint
    `GET /cycles` akzeptiert `?kind=builtin|generated` und reicht
    den Filter an den Server-side-Helper durch. Dashboard-API
    `/api/finance-guru/cycles` proxied den Param mit. Frontend:
    `CycleLogTable.vue` bekommt einen `USelect`-Filter "Alle Kinds
    / Builtin / Nur generierte" plus ein zweizeiliges Strategie-
    Cell (Name + UBadge `builtin`/`generated`), der UModal-Drill-
    down zeigt Kind + Backtest-%. Filter ist client-seitig — das
    Backend-Filter wird verfügbar gemacht, aber das Composable
    pollt weiterhin alle Cycles auf einmal, damit das Tab-Switching
    keinen zusätzlichen Roundtrip verursacht.
22. ✅ **`dream-server/docs/RAG-FINANCE.md`** — neues Dokument mit
    den vollständigen Payload-Schemas für alle sechs finance-
    Collections (`finance_assets`, `finance_news`, `finance_social`,
    `finance_asset_analysis`, `finance_relations`,
    `finance_strategy_lessons`), Beispiel-Queries (sowohl gegen
    `qdrant`-Raw als auch gegen die `/rag/*`-API), Operator-Smoke-
    Tests pro Collection, und Verifier-Pattern-Übersicht für die
    vier n8n-Workflows. Cross-Linked aus
    `FINANCE-GURU-IMPROVEMENT-PLAN.md` und der Service-README.

**Lessons learned aus Phase G:**

* **Pydantic `extra=forbid` statt nur "ignore die Old-Field"** — die
  saubere Lösung gegen accidental-bypass durch n8n-Workflow-
  Replay. n8n hängt manchmal alte Workflow-Versionen mit veralteten
  Bodies wieder los, und ein stillschweigend ignoriertes
  `force: true` wäre der genau falsche Trade-off zwischen Backwards-
  Compat und Sicherheit. Lieber laute HTTP 400.
* **SQLite `ALTER TABLE` ohne `IF NOT EXISTS`-Klausel.** Die
  Migration-Helper-Funktion `_ensure_extra_columns()` inspiziert
  `PRAGMA table_info`, fügt fehlende Spalten einzeln nach und ist
  damit idempotent — der gleiche Trick wie in `lifecycle.init_db()`.
  Kein eigenes Migrationssystem, weil der gesamte State in einer
  einzigen SQLite-Datei liegt und atomar gebackupt wird.
* **Cycle-Log-`kind` per Lookup statt per Parameter.** Erst dachten
  wir, `orchestrator.run_strategy_once()` sollte `kind` aus dem
  `StrategyDef` weiterreichen. Verworfen: damit hätten wir den
  Phase-D-Generated-Pfad und den Builtin-Pfad an zwei Stellen
  synchron halten müssen, und der Backtest-Harness (`backtest.py`)
  hätte denselben Lookup nochmal selbst machen müssen. Lookup im
  `cycle_log.record()` zentral, defensive Try/Except, fertig.
* **Dashboard-Filter client-seitig.** Der `kind`-Filter steht zwar
  als Query-Param am Server zur Verfügung, das Composable zieht aber
  weiterhin alle Cycles in einem Roundtrip — ein Tab-Wechsel im
  UI ist instantan, kein Loader-Flash. Bei stärkerem Volumen
  (>500 Cycles im Polling-Fenster) kann das Composable den
  Server-Filter aktivieren — der Code-Pfad ist bereit.

**Smoke-Test-Checkliste (Phase G):**

```bash
# 1) Cycle-Log-Migration ohne Datenverlust:
ssh sky-net@192.168.178.110 'docker compose exec finance-guru-api \
  sqlite3 /data/ledger.sqlite ".schema cycle_runs"' \
  | grep -E "kind|bt_pnl_pct"
# erwartet: beide Spalten + idx_cycle_runs_kind_ts

# 2) Neuer Filter funktioniert (nach mind. 1 Cycle pro Kind):
curl -s "http://192.168.178.110:8098/cycles?kind=generated&limit=5" \
  | jq '.cycles[] | {strategy, kind, bt_pnl_pct, status}'
curl -s "http://192.168.178.110:8098/cycles?kind=builtin&limit=5" \
  | jq '.cycles[] | {strategy, kind, bt_pnl_pct, status}'

# 3) Promote-Gate (beide Bedingungen):
TOK=$(grep ^FINANCE_GURU_TOKEN= ~/dream-server/.env | cut -d= -f2)
# a) zu wenig pct → 412
curl -s -o /dev/stderr -w "%{http_code}\n" -X POST http://192.168.178.110:8098/strategies/promote \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"news_sentiment","bt_pnl_pct":3.5,"bt_n_trades":20}'
# b) zu wenig trades → 412
curl -s -o /dev/stderr -w "%{http_code}\n" -X POST http://192.168.178.110:8098/strategies/promote \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"news_sentiment","bt_pnl_pct":15.0,"bt_n_trades":2}'
# c) Altes force-Feld → 422 (Pydantic extra_forbidden, kein 400)
curl -s -o /dev/stderr -w "%{http_code}\n" -X POST http://192.168.178.110:8098/strategies/promote \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"name":"news_sentiment","bt_pnl_pct":3.5,"bt_n_trades":2,"force":true}'
# d) Override per Header → 200 + force_promoted=true + gate_violations[]
curl -s -X POST http://192.168.178.110:8098/strategies/promote \
  -H "Authorization: Bearer $TOK" -H "X-Force-Promote: 1" \
  -H "Content-Type: application/json" \
  -d '{"name":"news_sentiment","bt_pnl_pct":3.5,"bt_n_trades":2}' | jq

# 4) Audit-Trail dokumentiert override:
curl -s "http://192.168.178.110:8098/strategies/audits?strategy=news_sentiment&limit=3" \
  | jq '.audits[] | {transition, from_status, to_status, actor, note}'
# erwartet: aktuellster Eintrag actor=operator:force-promote

# 5) Docs erreichbar im Editor:
ls -l ~/PhpstormProjects/codedredd/DreamServer/dream-server/docs/RAG-FINANCE.md

# 6) Dashboard-Filter sichtbar:
# /finance-guru/trading → Tab "Cycles & Runs" → neuer USelect
# "Alle Kinds / Builtin / Nur generierte"; UBadge unterhalb des
# Strategie-Namens; Modal zeigt "Kind" + "Backtest %".
```

### Phase G — Härtung & Aufräumen (legacy plan items, ✅ superseded)

> Die drei Items waren die ursprüngliche Phase-G-Skizze und sind oben
> umgesetzt. Mapping zur tatsächlichen Implementierung:

20. **Backtest-Pflicht im Promotion-Pfad** → `app/main.py::lifecycle_promote`
    + `PromoteStrategyIn (extra=forbid)` ✅
21. **Cycle-Log-Index `bt_pnl_pct` + `kind`** → `app/cycle_log.py`
    (`SCHEMA_SQL`, `_ensure_extra_columns`, `list_cycles(kind=)`) +
    `app/main.py::list_cycles` + Dashboard
    `CycleLogTable.vue` ✅
22. **`docs/RAG-FINANCE.md`** → neu, 8 Sektionen, alle 6 Collections
    + Beispiel-Queries + Operator-Smoke-Tests ✅

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

---

# Iteration 2 — Operator-Feedback 05/2026 (Phasen H–M)

> Quelle: Operator-Review nach Phase G-Deploy. Adressiert fünf
> konkrete Beobachtungen aus dem Live-Betrieb:
>
> 1. Strategien deployen nur ~30 % des Cash-Buckets pro Cycle, der
>    Rest liegt brach (Symptom: `equity_eur ≈ seed_eur + ε` selbst
>    bei steigenden Märkten).
> 2. Sell-Logik realisiert Verluste auf eine einzelne negative
>    Headline hin, ohne Re-Verifikation gegen News-/RAG-Stand und
>    ohne Mindesthaltedauer.
> 3. `_rag_evidence()` macht pro Trade-Signal **drei** sequentielle
>    Qdrant-Calls. Latenz im Decide-Loop unnötig hoch.
> 4. Sechs Qdrant-Collections — sind es zu viele? (Antwort vorweg:
>    nein, die Trennung ist korrekt, aber die *Nutzung* muss
>    konsolidiert werden, s. Phase J.)
> 5. Vorbereitung Live-Trading (Trade Republic via `pytr`,
>    Binance via `ccxt`) ohne sofortige Ausführung.
> 6. Neuer RAG-Knoten: Geo-/Rohstoff-Exposure pro Asset und pro
>    Land (Produktion vs. Import).

## H. Sizing & Cash-Utilization (3–4 d)

**Problem.** `max_position_frac=0.10` × `MAX_FRESH_BUYS=3` pro
Cycle ⇒ höchstens 30 % Cash je Strategie + Cycle in den Markt; bei
ruhigen News-Tagen 0 %. Verkäufe füllen Cash auf, der dann erst im
nächsten Cycle (Cron `*/5 min` für `news_sentiment`) re-investiert
wird — und auch dann wieder nur zu 30 %. Effektive Investitions­quote
typischerweise **15–40 %**, das +10 %-WoW-Gate ist mathematisch
kaum erreichbar.

**Plan.**

H-1. **Cash-Utilization-Target im Orchestrator.** Neuer Config-Wert
   `FINANCE_GURU_TARGET_INVESTED_FRAC=0.85` (Default; 0 = aus). Nach
   `decide()` rechnet `orchestrator._fill_to_target()`:
   * `invested = Σ(positions.qty × latest_price)`
   * `equity   = invested + cash`
   * `gap_eur  = max(0, equity × target − invested)`
   * Wenn `gap_eur > 0`, **upscalt** der Orchestrator die bereits
     emittierten Buy-Signals proportional ihrer `confidence`, bis
     entweder das Target erreicht oder der per-Position-Cap
     (`max_position_frac × equity`, NICHT mehr nur × `cash`)
     getroffen ist. Keine Konstruktion neuer Symbole — das bleibt
     die Hoheit der Strategie.

H-2. **Sizing auf Equity statt Cash.** `_size_buy()` benutzt aktuell
   `ctx.cash_eur × max_frac`. Das schrumpft mit jedem Kauf. Wechsel
   auf `ctx.equity_eur × max_frac` (siehe H-1 oben). `DecisionContext`
   bekommt `equity_eur: float`. Bestehende Strategien spüren das
   transparent; nur die Sentinel `eur_target == "max_position_frac"`
   wird neu ausgewertet.

H-3. **Kelly-Lite Sizing als opt-in.** Neuer Sizing-Modus
   `kelly_lite` in `dsl.py` und im Orchestrator:
   `frac = clip(confidence − risk, 0, 1) × max_position_frac`.
   Builtin-Strategien bleiben auf `max_position_frac`,
   LLM-generierte können `kelly_lite` wählen — ohne den Hot-Path
   alter Strategien anzufassen.

H-4. **MAX_FRESH_BUYS rauf, mit Diversifikationsgate.** `news_
   sentiment` und `social_buzz` heben `MAX_FRESH_BUYS` auf 8 an,
   aber per Symbol max.   1 Buy pro Cycle (steht schon implizit drin) UND per Sektor max. 2 (neu, via `ctx.asset_types` +
   späteres `ctx.asset_sectors` aus Phase K).

H-5. **Re-Balance-Cycle**, separater Cron (`*/30 min`):
   `POST /strategies/{name}/rebalance` deployt ungenutzten Cash
   in bestehende Positionen mit `confidence ≥ 0.7` ohne neue
   Symbole zu öffnen. Defensiv: aktiv nur, wenn
   `cash / equity > 1 − target × 0.9`.

**DoD H.** Nach 24 h Laufzeit: median `invested / equity ≥ 0.7`
über alle live-Strategien (sichtbar im neuen
`/strategies/portfolio`-Endpoint). `total_pnl_pct` korreliert mit
Marktrendite statt um 0 zu pendeln.

---

## I. Sell-Verifier & Loss-Discipline (3 d)

**Problem.** `news_sentiment` verkauft auf eine einzelne Headline
mit `sentiment ≤ -0.5`. `momentum_breakout` schließt auf 20-bar-Low.
Beide ignorieren (a) den aktuellen Buchverlust, (b) ob die Headline
ein Duplikat / Re-Print ist, (c) ob die News-Quelle reliability
< 0.5 hat (Quellen-Reliability liegt seit Phase B vor, wird aber
nicht im Sell-Pfad konsumiert).

**Plan.**

I-1. **Hard-Stop vs. Soft-Stop trennen.**
   * Hard-Stop: `pnl_pct ≤ FINANCE_GURU_STOP_LOSS_PCT` (Default
     −8 %) → Sell ohne weitere Prüfung, immer.
   * Soft-Stop (negative News, momentum-Bruch): nur ausführen, wenn
     **alle** zutreffen:
     - mindestens **2 distinkte Quellen** in `news` mit
       `sentiment ≤ −0.5` in den letzten 60 min, ODER
     - eine Quelle mit `reliability ≥ 0.7` (via
       `ctx.get_source_weight`).
     - Position hält ≥ `FINANCE_GURU_MIN_HOLD_MINUTES` (Default 90).
     - Mindestens 1 `finance_relations`-Treffer mit
       `mechanism` ≠ "noise" für das Symbol.

I-2. **Loss-Realisation-Gate.** Wenn ein Sell **gleichzeitig**
   Soft-Stop UND `pnl_pct < 0` ist, schickt der Orchestrator das
   Signal an `verifier.confirm_loss_sell()`. Diese ruft `llm.chat`
   mit `model='default'` (nicht `reasoning` — Kostendisziplin §10
   AGENT-OPS), `max_tokens=200`, JSON-Output
   `{"verdict": "sell" | "hold", "reason": "..."}`.
   Eingaben: aktuelle Headlines, RAG-Evidence-Bundle (s. Phase J),
   Position-Detail. Verdict `hold` ⇒ Skip, vermerkt in
   `cycle_log.payload.skipped[].why = "verifier_held_loss"`.

I-3. **Cooldown nach Sell.** Pro Symbol 30 min keine neuen
   Buy-Signals nach einem Sell — vermeidet Wash-Trade-Pattern.
   Implementierung: `ledger.last_sell_ts(strategy, symbol)`
   wird in `_build_context()` mitgeladen, Strategien filtern.

I-4. **Take-Profit gestaffelt.** Statt einmalig +5 % all-out
   ein Trailing-System: 50 % der Position bei +5 %, weitere 25 %
   bei +10 %, Rest läuft mit Stop bei Break-Even. Implementiert
   in der Strategie, nicht im Orchestrator (jede Strategie kann
   ihre eigene Treppe haben).

**DoD I.** `cycle_log` zeigt für jeden Loss-Sell mindestens einen
`verifier_*`-Eintrag. Hard-Stop-Frequenz ≤ 1× pro Strategie pro
Woche (Audit-Metrik in `/strategies/audit`).

---

## J. Unified RAG Evidence (2 d)

**Problem.** `news_sentiment._rag_evidence()` macht 3 Qdrant-Calls
sequentiell pro Signal. Bei 8 Signalen × 3 Strategien × ~80 ms pro
Call = **~1.9 s zusätzliche Decide-Latenz** pro Cycle.

**Warum nicht eine Collection?** Drei harte technische Gründe:

| Collection                | Schreibrate     | Retention     | Payload-Schema |
|---------------------------|-----------------|---------------|----------------|
| `finance_news`            | ~2k/Tag         | 30 d (TTL)    | title, source, urgency, sentiment, symbols[] |
| `finance_social`          | ~5k/Tag         | 14 d          | platform, score, sentiment, symbols[] |
| `finance_asset_analysis`  | ~500/Tag        | 365 d         | summary, confidence, ts |
| `finance_relations`       | ~50/Tag         | 365 d         | theme, mechanism, entities, symbols, sectors |
| `finance_strategy_lessons`| ~5/Woche        | unbegrenzt    | strategy, outcome, pnl_pct, lesson |
| `finance_assets`          | 1×/Tag rebuild  | bis Refresh   | hq, sector, isin |

Mischen würde alle Payload-Indexe auf den Lowest-Common-Denominator
zwingen und Retention wäre nicht mehr per-Domain steuerbar. Wir
behalten also sechs Collections.

**Was wir stattdessen tun:**

J-1. **`POST /rag/evidence`** — neuer Server-Endpoint, der pro
   Aufruf parallel (`asyncio.gather`) über N Collections sucht und
   ein **eines** JSON-Bundle zurückliefert:
   ```json
   {
     "symbol": "AAPL",
     "seed": "iPhone 17 demand soft",
     "analyses": [...], "news": [...], "relations": [...],
     "social": [...], "lessons": [...]
   }
   ```
   Filters pro Collection (z. B. `since` für news, `min_confidence`
   für relations) sind im Request-Body durchreichbar.

J-2. **`qdrant_rag.search_evidence(symbol, seed, blocks=...)`**
   Python-Helper, der intern `asyncio.gather` macht. `_rag_evidence`
   in `news_sentiment` und allen kommenden Strategien wird auf
   diesen Helper umgestellt → 1 Round-Trip statt 3.

J-3. **Per-Cycle-Cache.** `DecisionContext` bekommt einen
   `evidence_cache: dict[(symbol, seed_key), bundle]` mit TTL =
   1 Cycle. Bei wiederholten Buy- und Sell-Lookups zum gleichen
   Symbol → 0 zusätzliche Qdrant-Calls.

J-4. **Reranker als opt-in.** Bei `?rerank=true` läuft das
   gemergte Result-Set durch BGE-Reranker (TEI ist schon deployed,
   `text-rerank` Service). Default off, nur für Reasoning-Calls
   (Workflow 12 Genesis) sinnvoll.

J-5. **Doku-Update**: `docs/RAG-FINANCE.md` Sektion „Multi-Collection
   Retrieval Pattern" beschreibt warum 6 Collections + wann
   `/rag/evidence` vs. die granularen Endpoints zu wählen sind.

**DoD J.** `news_sentiment` Decide-Cycle-Median sinkt um ≥ 50 %
(Prometheus-Histogram `finance_guru_decide_seconds`). Keine
funktionalen Regressionen in `extra.rag`-Shape.

---

## K. Geo & Resource Graph (5–7 d)

**Problem.** „Iran-Konflikt → Brent +X %" lässt sich heute nur
über Volltext-Match in `finance_news` finden. Wir wissen aber
nicht, welche Assets eine Geo-Exposure zu Iran oder zum Persischen
Golf haben, oder welches Land wie viel Öl importiert/produziert.

**Plan.**

K-1. **`finance_assets` Payload-Erweiterung.** `finance-vector/
   seeder.py` zieht zusätzlich pro Symbol (yfinance + openfigi
   fallback):
   * `hq_country`, `hq_region` (ISO 3166-1 alpha-2 + UN region)
   * `exchange_country`
   * `revenue_geo_split` (best-effort aus 10-K / yfinance
     `info.country`), Format: `[{"country":"US","frac":0.62}, …]`
   * `sector_gics` und `industry_gics`
   * `commodity_exposure`: `[{"commodity":"oil_brent","direction":"long"}]`
     (kuratierte Heuristik aus `config/finance/commodity-map.json`,
     z. B. `XOM → oil_brent long`, `LH → oil_brent short`).
   Neue Payload-Indexe in `qdrant_rag.ensure_assets_collection()`:
   `hq_country`, `sector_gics`, `commodity_exposure.commodity`.

K-2. **Neue Tabelle (Timescale)** `finance.country_resources`
   * `(country_iso2, commodity, role, units_per_year, year, source)`
   * `role ∈ {producer, importer, exporter, reserves_holder}`
   * Erste Bestückung aus statischen Datasets (CIA Factbook
     Snapshot, USGS Mineral Commodity Summaries, World Bank
     Energy Statistics, EU Critical Raw Materials Act 2023 List).
   * Migration: `migrations/20260516_country_resources.sql`.
   * Refresh-Job (`finance-vector-refresh.json` erweitern,
     1×/Quartal) lädt neue Snapshots.

K-3. **Neue Qdrant-Collection `finance_geo_facts`**
   * Payload: `country_iso2`, `topic` (politik/handel/sanktionen/
     konflikt), `events[]` (`{ts, source, headline, sentiment}`)
   * Schreiber: neuer n8n-Workflow `14-finance-geo-events.json`
     (Cron `0 */6 h`), feedet aus `finance_news` mit Country-NER
     (Spacy/`en_core_web_sm` reicht; läuft im CPU-Profil).

K-4. **Causal-Extractor (Workflow 13) erweitern.**
   * Briefing-Schritt zieht zusätzlich
     `POST /rag/geo-facts {query: <theme>, limit:5}` und
     `GET /country/resources?commodity=<X>` für betroffene
     Rohstoffe.
   * LLM-Prompt bekommt explizite Geo-/Commodity-Felder
     (`affected_countries[]`, `commodities[]`).
   * Output-Schema von `relations` um genau diese Felder erweitert,
     mit Verifier (Whitelist gegen `country_resources` und
     `finance_assets.hq_country`).

K-5. **DSL-Signale neu.** In `dsl.py`:
   * `geo.country_exposure` → `{symbol, country_iso2}` boolean.
   * `geo.commodity_exposure` → `{symbol, commodity}` boolean.
   * `geo.relations_count_country` → analog
     `rag.relations_count` aber gefiltert auf Country-Tag.

K-6. **Sektor- und Geo-Diversifikations-Cap.** Strategie-Output
   wird vom Orchestrator nach Equity-Anteil pro `sector_gics` und
   pro `hq_country` gecapt (Defaults: 25 % je Sektor, 40 % je
   Country). Verhindert dass „Long Halbleiter"-Strategien implizit
   100 % Taiwan-Exposure aufbauen.

**DoD K.** `/rag/evidence` für ein Öl-Symbol liefert mindestens
einen `relations`-Treffer mit `commodities=["oil_brent"]` und
einen `geo_facts`-Treffer für mindestens ein produzierendes Land.
DSL-Catalog zeigt die drei neuen Signale.

---

## L. Live-Broker-Adapter (Skeleton, 4–5 d, KEINE Real-Orders)

**Problem.** `ledger.execute_trade()` ist hardcoded Paper.
Wechsel zu live wird hektisch wenn nicht vorbereitet. Wir bauen
**jetzt** das Interface + zwei Adapter im Read-only-Modus.

**Plan.**

L-1. **`app/brokers/base.py`** — `class Broker(Protocol)`:
   ```python
   def get_cash(strategy: str) -> float
   def get_positions(strategy: str) -> list[Position]
   def submit(order: Order) -> ExecutionReport      # may raise BrokerDryRun
   def cancel(order_id: str) -> bool
   def healthcheck() -> dict
   ```

L-2. **`app/brokers/paper.py`** — wrapt das bestehende
   `ledger.execute_trade` 1:1. Default-Broker.

L-3. **`app/brokers/trade_republic.py`** — Wrapper um `pytr`
   (https://pypi.org/project/pytr/). **Nur** `get_cash`,
   `get_positions`, `healthcheck` implementiert; `submit` raised
   `BrokerDryRun("TR live submit disabled by config")` bis
   `FINANCE_GURU_TR_LIVE=1` AND `FINANCE_GURU_TR_PIN` gesetzt.
   2FA-Flow: Operator macht `dream finance tr login` (CLI ruft
   `pytr.login`), Refresh-Token wird in `/data/secrets/tr.json`
   gespeichert (chmod 600, `.gitignore`d).

L-4. **`app/brokers/binance.py`** — Wrapper um `ccxt.binance`
   (oder `python-binance`); analoge Read-only-Implementierung,
   `submit` initial gegen `binance.testnet` möglich, gegen
   Prod hartes Flag `FINANCE_GURU_BINANCE_LIVE=1` plus
   `BINANCE_API_KEY/SECRET` aus `.env`.

L-5. **Orchestrator-Auswahl.** `StrategyDef.broker: str = "paper"`.
   `run_strategy_once()` resolved via `brokers.get(name)`. Builtins
   und Genesis-Output bleiben paper. Operator promotet zu live per
   `POST /strategies/{name}/broker {to: "trade_republic_live"}`,
   das setzt `strategies_meta.broker` UND validiert
   `broker.healthcheck()` + Backtest-Gate (`bt_pnl_pct ≥ target`)
   UND fragt ein zweites Approval-Token aus `.env`
   (`FINANCE_GURU_LIVE_APPROVAL_TOKEN`).

L-6. **Kill-Switch.** Datei `/data/STOP_LIVE_TRADING` (touch via
   `dream finance kill-live`). Orchestrator prüft am Anfang jedes
   Cycles; wenn da, schaltet ALLE non-paper Brokers für diesen
   Cycle auf `paper` und logged Warning. Reset nur per
   `rm` + Container-Restart, damit unfallartiges Re-Enable
   unmöglich ist.

L-7. **Dependency-Footprint.** `pytr` und `ccxt` werden als
   `extras=["live"]` im requirements gepinnt; default-Image
   installiert sie nicht. Erst beim Operator-Opt-in
   (`FINANCE_GURU_BROKER_EXTRAS=live`) baut das Compose-Profil
   ein neues `finance-guru-api-live`-Image. Hält das normale
   Image schlank und CVE-Surface klein.

**DoD L.** `dream finance broker status` zeigt `paper: ok`,
`trade_republic: read-only ok` (sofern Login durchgeführt),
`binance: read-only ok`. Kein einziger `submit`-Call gegen einen
echten Broker passiert ohne explizites Operator-Opt-in. CI-Test
prüft, dass `BrokerDryRun` per default geraised wird.

---

## M. Workflow-Intervalle & UX (2 d)

**Problem.** Cron-Slots sind historisch gewachsen. Aktuell:

| Workflow                      | Cron      | Lohnt sich? |
|-------------------------------|-----------|--------------|
| 09 finance-asset-behaviour    | `*/2 min` | ja, aber 5 Items/Run reichen |
| 10 finance-source-reliability | `0 * * *` | ok |
| 11 finance-strategy-audit     | Mo 00:05  | ok |
| 12 finance-strategy-genesis   | `0 */6 h` | borderline (Cost) |
| 13 finance-causal-extraction  | `*/15 min`| **zu viel** (96/Tag, ~3.5k Token/Run) |
| finance-vector-refresh        | `0 4 * * *` | ok |

**Plan.**

M-1. **Workflow 13 auf adaptiven Cron.** Statt `*/15` fester
   Slot, neuer Server-Endpoint `GET /news/throughput?window=1h`,
   der Headlines/h liefert. Workflow 13 reagiert:
   * `< 20 headlines/h` → skip diesen Tick.
   * `20–100` → normal.
   * `> 100` (Breaking) → 2× pro Slot.
   Erwartete Einsparung: 40–50 % LLM-Calls bei gleichem Recall.

M-2. **Strategie-Decide-Cron pro Strategie.** Aktuell APScheduler
   global. Pro Strategie eigener Cron in `strategies_meta.cron`
   (Default ererbt). Erlaubt z. B. `social_buzz` auf `*/2 min`
   während `momentum_breakout` auf `*/10 min` bleibt.

M-3. **Dashboard-Panel `PortfolioUtilizationPanel.vue`**
   * Equity / Cash / Invested-Ringdiagramm pro Strategie.
   * Heatmap-Zelle „pro Sektor/Geo Exposure" (nach Phase K).
   * Warn-Badge wenn `cash/equity > 0.5` für 3 Cycles in Folge
     (Symptom des Plan-H-Problems).

M-4. **Polling-Budget.** `useFinanceGuru.ts` setzt `usePolling`-
   Intervalle:
   * Strategien-Lifecycle: 60 s
   * Cycle-Log: 30 s (war: 15 s)
   * RAG-Insights: 90 s
   * Portfolio-Utilization: 30 s (neu)
   Mit ETag-Support (war Phase A.4 deferred). Reduziert
   API-Last um ~40 %.

M-5. **Sidebar-Badges.** `finance-guru.trading` zeigt rotes
   `UBadge` wenn (a) ≥ 1 Strategie im letzten Cycle gescheitert,
   (b) Cash-Utilization < 30 % für 2 h, oder (c) Hard-Stop
   gefeuert.

**DoD M.** Workflow 13 macht im 24-h-Schnitt < 60 LLM-Calls.
Cycle-Log-Polling-Last (Prometheus `http_requests_total{path="/cycles"}`)
sinkt ≥ 30 %. Portfolio-Panel rendert für jede live-Strategie.

---

## N. Reihenfolge & Abhängigkeiten Iteration 2

| Phase | Inhalt                                       | Aufwand | Abhängig    |
|-------|----------------------------------------------|---------|-------------|
| H     | Sizing & Cash-Utilization                    | 3–4 d   | —           |
| I     | Sell-Verifier & Loss-Discipline              | 3 d     | H           |
| J     | Unified RAG Evidence Endpoint                | 2 d     | —           |
| K     | Geo & Resource Graph                         | 5–7 d   | J           |
| L     | Live-Broker-Adapter (skeleton)               | 4–5 d   | —           |
| M     | Workflow-Intervalle & UX                     | 2 d     | H, K        |

Gesamt: ~20 d AI-Agent-Arbeit, parallelisierbar in 3 Tracks
(H+I+M Risk/UX, J+K RAG-Erweiterung, L Broker).

## O. Was wir bewusst auch in Iteration 2 NICHT tun

* **Echte Live-Orders ohne Operator-Opt-in.** Phase L liefert nur
  Read-only-Adapter und ein hartes Approval-Gate.
* **Reinforcement Learning auf Sizing.** Cash-Utilization-Target
  ist eine deterministische Heuristik. Wenn das nicht reicht,
  kommt Bayesian Sizing — nicht RL.
* **Eigene NER für Geo (Phase K).** Spacy `en_core_web_sm` reicht;
  Custom-Model erst wenn Recall < 70 %.
* **Multi-Collection-Merge in Qdrant.** Sechs Collections bleiben;
  Phase J liefert nur ein Multi-Search-API.
* **Dashboard-Echtzeit-WS.** Polling-Pattern bleibt; WS erst wenn
  Polling-Budget gesprengt wird.

---

# Iteration 2.5 — Daten-Wachstum & Price-Move-Learning (Phase P)

> Auslöser: Operator-Beobachtung 16.05.2026 22:20 CEST — „1 h vergangen
> und in Qdrant hat sich nichts verändert." Diagnose ergab eine
> Kaskade von **Silent-Skips** in fast allen Lern-Workflows + einen
> fehlenden Workflow für event-basiertes Lernen aus Kursbewegungen.

## P-0. Diagnose-Snapshot (16.05.2026, Samstag 22:20 CEST)

| Symptom                                                      | Root Cause |
|--------------------------------------------------------------|------------|
| `finance_asset_analysis` steht bei 102, Workflow 09 skipped alle 2 min | `next-candidate-batch` bekommt `universe` aus `/history/symbols?hours=168`. **Stocks**: leer (Markt zu am WE, `RESPECT_MARKET_HOURS=true`). **Crypto**: 100 Symbole, alle bereits innerhalb 168 h analysiert → 0 stale → skip. |
| `finance_relations` steht bei 1                              | Workflow 13 Verifier filtert Stock-Symbole raus weil Universe leer → alle Themen verlieren ihre Anker → 0 Upserts. Keine `enrichment_runs`-Reports, weil die Filter-Reject vor dem Report-Node greift. |
| `finance_social` Collection existiert nicht (0 Punkte)       | `finance-social` läuft, aber `WARNING Reddit credentials missing — skipping fetch` jeden Cycle. Qdrant-Collection wird erst beim ersten Upsert erzeugt. |
| `finance-prices` _stocks_async = market closed seit Fr.-Abend | Erwartetes Verhalten, aber die nachgelagerten Lern-Workflows dürfen **nicht** davon abhängen. |
| n8n `/api/v1/workflows`-Aufrufe schlugen fehl (`X-N8N-API-KEY required`) | Operator-Diagnostik: API-Key in `.env` muss explizit gesetzt sein, sonst `dream` CLI kann Workflows nicht inspizieren. |

**Quintessenz.** Die Lern-Pipelines (Workflow 09 + 13) nutzen die
**aktive Preis-Universe** als Symbol-Anker. Das ist falsch: die
**kanonische Universe** lebt in Qdrant `finance_assets` und ist
markt­zeit­unabhängig. Wochenenden und After-Hours haben das
gesamte Lernen schweigend abgeschaltet.

## P-1. Universe-Quelle entkoppeln (1 d, höchste Priorität)

P-1.1. **Neuer Endpoint `GET /assets/canonical`** in
  `finance-guru-api`. Liefert die volle Symbol-Liste (mit
  `asset_type`, `hq_country` sobald Phase K landet) aus Qdrant
  `finance_assets`. Cached 5 min in-process.
  Implementierung: `qdrant_rag.list_assets(limit=2000)`.

P-1.2. **Workflow 09** (`09-finance-asset-behaviour.json`) ersetzt
  `GET universe (stocks)` + `GET universe (crypto)` durch einen
  einzigen `GET /assets/canonical` und filtert clientseitig auf
  `asset_type`. So gibt es auch am Wochenende stale Symbole zum
  Analysieren (Stock-Behaviour über 6 Monate Historie braucht
  keinen Live-Tick).

P-1.3. **Workflow 13** (`13-finance-causal-extraction.json`)
  übernimmt das gleiche. Verifier-Universe = canonical, nicht
  active.

P-1.4. **Workflow 12** (Genesis): Universe-Lookup ebenfalls
  umstellen. Bonus: Backtests bekommen jetzt deterministisch
  immer denselben Symbol-Pool, unabhängig vom Wochentag.

P-1.5. **`next-candidate-batch` Stale-Default senken** von
  `168 h` (7 d) auf `48 h` (2 d). Wir wollen Symbole 2–3× pro
  Woche neu durchleuchten, nicht 1×.

**DoD P-1.** Workflow 09 produziert auch am Samstag mindestens
1 `asset_behaviour: ok` Report pro 2-min-Slot, solange mindestens
ein Symbol > 48 h alt ist. Workflow 13 erzeugt am Wochenende
mindestens 1 `finance_relations`-Upsert pro Tag.

## P-2. Sichtbarkeit: Silent-Skips brüllen lassen (0.5 d)

P-2.1. **`enrichment_runs` mit `note`-Pflicht für skipped.**
  Workflow 09 schreibt aktuell `note: "no stale candidate"`. Das
  ist gut, aber wir brauchen auch:
  * Workflow 13 → `note: "no theme survived verifier"` /
    `note: "universe empty"`.
  * Workflow 14/15 (neu) analog.

P-2.2. **Neuer Endpoint `GET /enrichment/health`** liefert pro
  Workflow die letzten 24 h: `runs_total, ok, skipped, error,
  last_ok_ts`. Dashboard-Panel `EnrichmentHealthCard.vue` zeigt
  rote Badges wenn `last_ok_ts > 6h` ago.

P-2.3. **Prometheus-Metriken**:
  `finance_enrichment_runs_total{workflow,status}` Counter,
  `finance_qdrant_points{collection}` Gauge (5-min scrape via
  bestehende `/rag/status`). Reduziert manuelles
  `docker logs`-Polling.

**DoD P-2.** `GET /enrichment/health` zeigt für jeden der vier
finance-Workflows `last_ok_ts` der letzten 24 h. Dashboard-Card
zeigt grün/gelb/rot pro Workflow.

## P-3. Reddit/Social-Pfad reanimieren (0.5 d)

P-3.1. **Doku-Patch in `docs/RAG-FINANCE.md`** + Service-README:
  exakte `.env`-Keys für Reddit-OAuth-App
  (`FINANCE_SOCIAL_REDDIT_CLIENT_ID`,
  `FINANCE_SOCIAL_REDDIT_CLIENT_SECRET`,
  `FINANCE_SOCIAL_REDDIT_USER_AGENT=DreamServerFinance/1.0 by
  <reddit_user>`).

P-3.2. **Fallback-Quelle StockTwits.** `finance-social/qdrant_sink.py`
  als zweite Quelle hinter Reddit. Macht das System unabhängig von der Reddit-API-Verfügbarkeit (die
  in den letzten 12 Monaten zweimal still gebrochen war).

P-3.3. **`finance_social` Collection-Bootstrap**: `finance-social/
  qdrant_sink.py` ruft `ensure_collection` defensiv bei jedem
  Service-Start, nicht erst beim ersten Upsert. Dann zeigt
  `/rag/status` `exists: true, points: 0` statt `exists: false`
  und die Dashboard-Card wird grün-mit-Hinweis statt rot.

**DoD P-3.** `finance_social` Collection existiert nach
Service-Restart auch ohne Reddit-Login. Sobald Creds gesetzt
sind, wächst sie um ≥ 20 Punkte/h.

## P-4. **Neuer Workflow 15 — Price-Move-Causal-Explainer** (3–4 d)

> Beantwortet die Operator-Frage:
> „Gibt es einen Workflow, der die History eines Kurses unter die
> Lupe nimmt und nach Relationen für Schwankungen sucht und diese
> dann als Learning verbindet?"
>
> Workflow 09 macht das bereits für **eine 6-Monats-Periode pro
> Symbol** (deep-dive). Was fehlt ist die **event-driven**
> Variante: sobald ein Symbol kurzfristig stark bewegt, das warum
> sofort extrahieren und als Relation persistieren.

### Architektur

```
APScheduler (alle 10 min)              ┌── finance_news (lookback 90 min)
         │                              │
         ▼                              ▼
 /assets/movers?window=1h&min_pct=3 → POST /llm explain(...)  → Verifier
   (neuer Server-Endpoint)             (model='default')        (Symbols & news_ids)
         │                                                            │
         └─ liefert [{symbol, return_pct,                              ▼
            volume_ratio, ts}]                              POST /rag/relation
                                                            (theme="price_move:<SYM>")
                                                                       │
                                                                       ▼
                                                            POST /enrichment/run
                                                            workflow="price_move_learn"
```

P-4.1. **Server-Endpoint `GET /assets/movers`**:
  Query: `window=1h|4h|1d`, `min_pct=2.5` (Default 3 %),
  `asset_type=stock|crypto|all`, `limit=10`.
  Liefert pro Symbol: `return_pct`, `volume_ratio` (vs. Median
  der gleichen Stunde der letzten 7 Tage), `latest_ts`,
  `latest_price`. Datenquelle: `finance.prices_intraday`,
  SQL ist günstig (Continuous Aggregate auf Timescale, ggf. neu
  als `ca_prices_1h`).

P-4.2. **n8n-Workflow `15-finance-price-move-explainer.json`**:
  * Cron `*/10 min` (anpassen je nach LLM-Budget).
  * Schritt 1: `GET /assets/movers?window=1h&min_pct=3` → bis zu
    10 Mover.
  * Schritt 2: Pro Mover (Per-Item, ähnlich WF 09 A.2):
    `GET /history/news?symbol=<X>&hours=4&min_urgency=0&limit=20`
    plus `POST /rag/evidence` (Phase J Endpoint) für das gleiche
    Symbol als RAG-Kontext.
  * Schritt 3: **LLM `default`** Prompt:
    ```
    System: You explain why <SYM> moved <±X%> in the last <Y>h.
    Use ONLY the supplied headlines and RAG snippets. Output
    strict JSON: {"mechanism":..., "drivers":[{"source":..,
    "headline":..,"weight":0..1}], "regime":"news_driven|
    technical|sympathy|unknown", "confidence":0..1,
    "evidence_ids":[news_id,...]}.
    ```
  * Schritt 4: **Verifier** (JS): `evidence_ids` ⊂ übergebene
    News-IDs; `mechanism` non-empty; `confidence ≥ 0.3` → sonst
    reject.
  * Schritt 5: **`POST /rag/relation`** mit
    `theme=price_move:<SYM>:<ts_bucket>`,
    `mechanism=<llm.mechanism>`,
    `symbols=[<SYM>]`,
    `sectors=[<asset.sector_gics>]` (falls Phase K),
    `evidence_ids=<verified>`,
    `confidence=<llm.confidence>`,
    `extra={return_pct, volume_ratio, regime}`.
  * Schritt 6: `POST /enrichment/run` mit
    `workflow="price_move_learn"`.

P-4.3. **Lessons-Schleife.** Wenn der Verifier `regime="unknown"`
  oder `confidence<0.3` wirft, wird das nicht als Failure verbucht
  sondern als `finance_strategy_lessons`-Eintrag mit
  `outcome="unexplained_move"` — der nächste Genesis-Cycle sieht
  damit, welche Movers sich nicht aus News erklären lassen
  (Sympathy-Trades, Index-Rebalance, Whale-Moves). Pattern, das
  später eine eigene Strategie wert sein kann.

P-4.4. **Anti-Spam-Bucket.** Pro Symbol max. 1 Explainer pro
  60-min-Bucket. Im Server-Endpoint `/assets/movers` deduplizieren
  (`ts_bucket = floor(ts, 60min)` + Existenz-Check in
  `finance_relations` Payload). Verhindert dass eine
  Range-Bound-Krypto bei jedem Cron-Tick einen neuen Explainer
  triggert.

P-4.5. **Strategie-Konsum.** `news_sentiment` und `social_buzz`
  ziehen via `_rag_evidence` jetzt automatisch `finance_relations`
  mit `theme: "price_move:<SYM>:*"` — Phase B's Bundle-Builder
  füllt sich auch für Symbole ohne aktive Causal-Themes, weil
  jeder relevante Mover binnen 10 min in Relations landet.

**DoD P-4.** Nach 24 h Laufzeit:
* `finance_relations` enthält mindestens `n_movers × 0.7`
  `price_move:`-Themen.
* Pro Cron-Tick werden max. 10 LLM-Calls gemacht (Budget-Cap).
* Dashboard-Panel `MoversExplainerPanel.vue` listet Top-10
  Mover der letzten 24 h mit Mechanism-Snippet.

## P-5. Workflow-Aktivitäts-Smoke pro Tag (0.5 d, läuft täglich)

P-5.1. **APScheduler-Job `workflow_smoke`** in `finance-guru-api`
  (Cron `0 5 * * *`, vor dem `auto_archive` 04:10):
  ```python
  for wf in ("asset_behaviour","source_reliability",
             "causal_extraction","price_move_learn"):
      r = enrichment.list_runs(workflow=wf, limit=1)
      if not r or _hours_since(r[0]["ts"]) > 24:
          alerts.append(f"{wf} stale: last={r[0]['ts'] if r else 'never'}")
  if alerts:
      llm.chat(..., model='fast', max_tokens=80)  # one-line summary
      ledger.append_alert(...)                     # surfaces in dashboard
  ```

P-5.2. **Sidebar-Badge `EnrichmentHealthBadge.vue`** rotes
  Symbol wenn (a) ≥ 1 Strategie im letzten Cycle gescheitert,
  (b) Cash-Utilization < 30 % für 2 h, oder (c) Hard-Stop
  gefeuert.

**DoD P-5.** Wenn ein finance-Workflow > 24 h keinen Report
geschrieben hat, sehen wir das innerhalb von 5 min im Dashboard.

## P. Reihenfolge & Aufwand

| Step  | Inhalt                                            | Aufwand | Abhängig |
|-------|---------------------------------------------------|---------|----------|
| P-1   | Universe-Quelle entkoppeln (canonical aus Qdrant) | 1 d     | —        |
| P-2   | Silent-Skip-Sichtbarkeit + `/enrichment/health`   | 0.5 d   | —        |
| P-3   | Reddit/StockTwits + Collection-Bootstrap          | 0.5 d   | —        |
| P-4   | **Workflow 15: Price-Move-Explainer**             | 3–4 d   | P-1, J   |
| P-5   | Daily-Smoke + Sidebar-Badge auf
  `/enrichment/health.verdict`.

Gesamt: ~5–6 d. **P-1 + P-2 + P-3 sollten innerhalb des nächsten
Deploy-Slots laufen**, weil ohne sie keine der Iteration-2-
Verbesserungen wirklich Lernfortschritt zeigt — alles weitere
ist auf wachsende Collections angewiesen.

## P. Was wir in Phase P bewusst NICHT tun

* **Echte Live-Orders ohne Operator-Opt-in.** Phase L liefert nur
  Read-only-Adapter und ein hartes Approval-Gate.
* **Reinforcement Learning auf Sizing.** Cash-Utilization-Target
  ist eine deterministische Heuristik. Wenn das nicht reicht,
  kommt Bayesian Sizing — nicht RL.
* **Eigene NER für Geo (Phase K).** Spacy `en_core_web_sm` reicht;
  Custom-Model erst wenn Recall < 70 %.
* **Multi-Collection-Merge in Qdrant.** Sechs Collections bleiben;
  Phase J liefert nur ein Multi-Search-API.
* **Dashboard-Echtzeit-WS.** Polling-Pattern bleibt; WS erst wenn
  Polling-Budget gesprengt wird.

---

# Iteration 2.5 — Phase P · Deploy-Status

### P-1 (Canonical-Universe) — **DEPLOYED 2026-05-16**

* `qdrant_rag.list_assets(asset_type, limit)` (Scroll, kein Embed) +
  `GET /assets/canonical?asset_type=&limit=&only_with_prices=&detail=`
  liefern marktzeit-unabhängig die Stammdaten aus `finance_assets`
  mit dreistufigem Fallback (Qdrant → enrichment-SQLite →
  `history/symbols` 90 d).
* `only_with_prices=true` schneidet die kanonische Liste mit dem
  Preis-History-Universum — verhindert WF09/13-Churn auf Symbolen,
  für die `finance-prices` nie Ticks gezogen hat (z. B. `2Z`,
  `1INCH` als Aktie).
* `enrichment.next_candidate{,_batch}` Default `stale_after_hours`
  168 h → 48 h (P-1.5).
* n8n-Workflows **09 / 12 / 13** auf
  `/assets/canonical?…&only_with_prices=true` umgestellt und via
  `scripts/n8n-import-workflows.sh --activate` re-importiert.
* **Verifikation (21:42 UTC, post-deploy):**
  `…stock&only_with_prices=true` → 0 (finance-prices hat seit
  ≥ 90 d keine Stock-Ticks geschrieben — Folge-Issue, s. unten);
  `…crypto&only_with_prices=true` → 101; WF09-Tick gibt jetzt sauber
  `skipped: no stale candidate` statt der vorherigen Silent-Skips.

**Follow-up (neu sichtbar dank P-2):** finance-prices schreibt 0
Stock-Ticks in den letzten 90 d. Vorher unsichtbar, weil die
Universe-Quelle dieselbe leere DB war. Eigener Fix-Track:
Yahoo-Finance/Polygon-Adapter prüfen, Wochenend-Backfill.

### P-2.1 (Silent-Skip-Visibility) — **DEPLOYED 2026-05-16**

* `GET /enrichment/health?window_hours=` aggregiert pro Workflow:
  `runs / ok / skip / error / skip_ratio / last_ts / last_ok_ts /
  last_skip_note / verdict ∈ {healthy, silent-skip, errors, no-progress}`.
* Erkennt Skip-Pattern aus `status` UND `note`
  (`"no stale candidate"`, `"empty universe"` …), damit
  Workflow-09-artige „läuft, tut aber nichts"-Zustände nicht mehr
  leise verschwinden.

### P-3.3 (Defensiver Social-Bootstrap) — **DEPLOYED 2026-05-16**

* `qdrant_rag.ensure_social_collection(dim=None)` läuft im
  FastAPI-`lifespan` und probt `finance_news → finance_assets →
  finance_asset_analysis` für die korrekte Dimension (Fallback 768).
* `/rag/status` zeigt jetzt alle 6 Collections (`finance_social
  exists=true dim=768 points=0`) statt der vorherigen leeren Zeile.

### Offen aus Phase P (nächster Slot)

* **P-3.2**: StockTwits-Fallback in `finance-social`, sobald Reddit
  weiter ohne Credentials bleibt.
* **P-5**: Daily-Smoke + Sidebar-Badge auf
  `/enrichment/health.verdict`.

### ✅ Phase P-1.x — finance-prices Stock-Pipeline repariert (2026-05-16)

* Root cause: `yfinance==0.2.50` konnte Yahoos Cloudflare-Auth seit
  Anfang 2025 nicht mehr passieren — jeder Ticker-Request lief in
  `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`. 90+
  Tage stille `0 stock ticks geschrieben`, vorher maskiert durch das
  Universe-Coupling von Phase P-1.
* Fix (Commit `7da939b2`): yfinance auf `>=0.2.65,<0.3`, `curl_cffi`
  als explizite Dep, `Session(impersonate="chrome")` an
  `yf.download(session=)`, `_run_stocks_blocking(force=True,
  period="5d")` umgeht den Market-Hours-Guard und wird beim
  Container-Start immer einmal getriggert (auch wenn DB nicht leer
  ist — vorher hat der Auto-Trigger geschlafen, sobald Crypto-Rows
  schon existierten).
* Verifiziert post-deploy (2026-05-16): `stocks fetch done: 12600
  bars upserted (100 symbols, period=5d, force=True)`;
  `/history/symbols?asset_type=stock&hours=168` → 98 (vorher 0);
  `/assets/canonical?asset_type=stock&only_with_prices=true` → 98;
  WF09 analysiert erstmals seit ≥ 90 d Aktien (AAPL conf 0.85, ABBV
  0.40, ADI 0.40) → `asset_analysis` 102 → 105.

### ✅ Phase P-4 — Workflow 15 (Price-Move-Causal-Explainer)

**Status**: Code-Patch fertig — neuer Endpoint `GET /assets/movers`,
neuer Qdrant-Helper `recent_relation_themes()` (60-min-Bucket-Dedup
gegen `finance_relations.theme = price_move:<SYM>:*`), neue Workflow-
Datei `config/n8n/15-finance-price-move-explainer.json`.

**Geliefert:**

* `app/data.py::recent_movers(window, min_abs_return_pct,
  asset_type, limit)` — reine SQL-Aggregation auf
  `finance.prices_intraday` mit Window-Function-basierter
  Volume-Baseline (Median der letzten 96 Bars) und „start_close =
  letzter Tick vor `now-window`"-Logik (so spannt 1h auch dann eine
  volle Stunde, wenn das Symbol gerade erst wieder ticken durfte).
* `app/qdrant_rag.py::recent_relation_themes(theme_prefix,
  since_ts_unix)` — Scroll-basierter Dedup-Lookup mit defensivem
  Failure-Mode (Outage ⇒ leere Menge ⇒ Workflow läuft trotzdem
  durch, statt durch False-Positive-Dedup stumm zu werden).
* `GET /assets/movers?window=&min_pct=&asset_type=&limit=&dedupe=
  &bucket_minutes=` — over-fetched `limit*4` Movers vor Dedup,
  trimmt nach Dedup auf `limit`, meldet `skipped_dedup` mit zurück.
* `15-finance-price-move-explainer.json` — Cron `*/10 min`,
  Manual-Trigger, Switch-Routing in drei Senken:
  * `relation` (regime≠unexplained ∧ conf≥0.4 ∧ ≥1 verifizierte
    `evidence_id`) → `POST /rag/relation` mit
    `theme=price_move:<SYM>:<bucket_ts>` (1h-Bucket aus
    `latest_ts`, damit Dedup deterministisch greift).
  * `lesson` (unexplained ∨ schwach) → `POST /rag/strategy-lesson`
    mit `outcome=note`, `keywords=[unexplained_move, <SYM>,
    <asset_type>, <regime>]` — Genesis-Loop kann später daraus
    Sympathy-/Whale-Strategien proposeren.
  * `reject` (JSON-Parse-Fehler, confidence-out-of-range) →
    `enrichment/run status=error` (kein Lessons-/Relations-Write).
* Verifier hält an alle Verifier-Pattern-Regeln: `evidence_ids ⊆
  Input`, Symbol = Mover-Symbol (single-asset by construction).

**DoD-Verifikation post-deploy:**

```bash
# 1) Endpoint smoke
curl -sf "http://localhost:8098/assets/movers?window=1h&min_pct=2&limit=5" | jq

# 2) WF15 importiert & aktiv
ssh sky-net@192.168.178.110 'curl -s -H "X-N8N-API-KEY: $N8N_API_KEY" \
  http://127.0.0.1:5678/api/v1/workflows | jq ".data[] | select(.id==\"FinPriceMoveExpl01\")"'

# 3) Nach 1 h: erste Relations mit price_move-Theme
ssh sky-net@192.168.178.110 'curl -s http://127.0.0.1:6333/collections/finance_relations/points/scroll \
  -H "content-type: application/json" \
  -d "{\"limit\":5,\"with_payload\":true,\"filter\":{\"must\":[{\"key\":\"theme\",\"match\":{\"text\":\"price_move:\"}}]}}" | jq'

# 4) Dedup wirkt: zweiter /assets/movers-Call innerhalb 60min liefert
#    skipped_dedup > 0 für dieselben Symbole
```

**Lessons learned** (aus Implementation):

* Switch-Node v3.2 in n8n verlangt `outputKey` + `renameOutput:true`
  pro Branch — sonst hat man unbeschriftete Pfade, die im UI als
  „Output 0/1/2" erscheinen und nach jedem Re-Import permutieren.
* `with_vectors=False` im scroll() schenkt einem 30× Bandbreite —
  Dedup-Lookup ist nur an Payload interessiert.
* Anti-Spam-Bucket sitzt server-seitig im Endpoint, nicht im Workflow
  — sonst hätten wir bei jedem Cron-Tick zuerst N LLM-Calls und
  *dann* das Filter (LLM-Budget weg).
* `price_move:<SYM>:<bucket>` als Theme statt nur `price_move:<SYM>`,
  damit ein neuer 1h-Bucket nach dem alten verfallenen explizit als
  „neuer Move" durchgeht, ohne dass wir Themes löschen müssen.

