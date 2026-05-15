# Dashboard → Nuxt-Migration (parallel Service `dashboard-nuxt`)

> Aufgaben­plan für die Re­implementierung des React-Dashboards
> (`extensions/services/dashboard`, ~12 900 LoC JSX/JS) als Nuxt-4 SPA mit
> **Nuxt UI v3, VueUse, Pinia, Pinia ORM**.
>
> Das React-Dashboard bleibt auf Port `3001` produktiv. Die Nuxt-Variante
> läuft als eigener Service `dashboard-nuxt` auf Port `3011`. Beide
> sprechen unverändert dieselbe `dashboard-api` (`:3002`) — die Python-API
> wird **nicht** angefasst.
>
> Vorlage / Orientierung: <https://github.com/nuxt-ui-templates/dashboard>
> (ohne Login-Layer; SSO/Auth läuft bei uns über Magic-Link gegen
> `dashboard-api`, das ist bereits gelöst und wird 1:1 wieder­verwendet).

---

## 0  Status-Quo-Analyse

### Was migriert wird

| Bereich | Pfad | Größe | Komplexität |
|---|---|---|---|
| Pages | `dashboard/src/pages/*.jsx` (15 Dateien) | ~7 100 Zeilen | hoch (Dashboard, Extensions, LottoTab, FinanceGuru, Voice, FirstBoot je 500–1 500 LoC) |
| Komponenten | `dashboard/src/components/*.jsx` (14 Dateien + `settings/`) | ~2 800 Zeilen | mittel |
| Hooks | `dashboard/src/hooks/*.js` (8 Hooks) | ~1 000 Zeilen | werden zu **Composables** + **Pinia-Stores** |
| Plugin-Registry | `dashboard/src/plugins/{core,registry}.js` | ~250 Zeilen | bleibt im Konzept identisch (Nuxt-`runtimeConfig` + Module) |
| Theming / Tailwind | `tailwind.config.js`, `src/index.css` | ~ | wandert in `app.config.ts` (Nuxt UI Themes) |
| SplashScreen + GSAP | `components/SplashScreen.jsx`, `gsap` 3.x | 403 LoC | bleibt 1:1 (GSAP läuft mit Vue) |
| PWA / Service-Worker | `public/sw.js`, `usePwaInstallPrompt.js` | 172 LoC | über `@vite-pwa/nuxt` |

### Was **nicht** migriert wird

- `dashboard-api/` (FastAPI) — keine Änderungen.
- `dashboard/templates/`, `nginx.conf`, `entrypoint.sh` — nur als
  Referenz, nicht migriert. Der nginx-Reverse-Proxy auf `/api/` wird im
  Nuxt-Service durch **Nitro server middleware** ersetzt (Bearer
  injecten + Pass-Through nach `dashboard-api:3002`). Damit ist
  derselbe Dev-/Prod-Auth-Pfad nochmal eingebaut.
- `manifest.yaml` des React-Dashboards bleibt unangetastet, der neue
  Service hat einen **eigenen** `service.id: dashboard-nuxt`.

### Vom React-Dashboard genutzte API-Endpunkte

(automatisch via `grep -r "fetch('/api/"`; vollständig — keine weiteren
URLs werden eingeführt)

```
/api/auth/magic-link/generate       /api/lotto/games
/api/extensions/catalog             /api/lotto/refresh
/api/external-links                 /api/lotto/refresh/full
/api/features                       /api/lotto/status
/api/finance-guru/decide            /api/lotto/tips/generate
/api/finance-guru/status            /api/models
/api/finance-guru/strategies        /api/models/download-status
/api/gpu/detailed                   /api/models/download/cancel
/api/gpu/history                    /api/preflight/{disk,docker,gpu,ports,required-ports}
/api/gpu/topology                   /api/projects[/status]
                                    /api/repo-map
                                    /api/service-tokens
                                    /api/services/resources
                                    /api/setup/{complete,status,test}
                                    /api/status
                                    /api/templates
```

→ exakt diese 33 Endpunkte werden in Phase 2 als typisierte
Pinia/Composable-Calls neu modelliert.

### Architektur-Entscheidungen

| Entscheidung | Begründung |
|---|---|
| **Nuxt 4 SPA-Mode** (`ssr: false`) | Die gesamte Logik ist client-side; SSR brächte nur Komplexität (Auth-Bearer, GPU-Polling, GSAP-Splash). Halo Strix ist kein Render-Server. |
| **Nitro Server-Routes** für `/api/**` | Drop-in-Ersatz für nginx-Bearer-Injection. Keine zusätzlichen Container/Sidecars. Gleicher Path → kein CORS-Bruch. |
| **Pinia + Pinia ORM** | Pinia für UI-State (Sidebar collapsed, Splash gesehen, Theme); Pinia ORM für strukturierte Entitäten mit Relationen (Service ↔ Resource ↔ Token, Strategy ↔ Position ↔ Trade, GameDraw ↔ Tip). |
| **VueUse** | Ersetzt selbstgebaute Hooks (`usePwaInstallPrompt`, `useDownloadProgress` SSE-Reconnect, Storage-Wrapper). |
| **Nuxt UI v3** | App-Shell (`UDashboardSidebar`, `UDashboardPanel`, `UCard`, `UTable`, `UBadge`, `UButton`, …) deckt 80 % der Komponenten ab. Theme via `app.config.ts`. |
| **`@vueuse/motion` statt Framer** | GSAP behalten wir für SplashScreen (battle-tested). Sonst Motion-Direktive. |
| **Tailwind 4** (von Nuxt UI v3 mitgebracht) | Migrationsaufwand: keine custom Plugins im React-Stand → unkritisch. |
| **Locale-Strategie** | `@nuxtjs/i18n` mit `de` (default) + `en`. React-Dashboard hat hartkodierte de/en-Mischung; sauber bei Migration. |

---

## 1  Service-Skelett (`extensions/services/dashboard-nuxt/`)

Bereits in diesem Commit angelegt — minimale Files damit `dream sync`
den Service entdeckt aber **als disabled** ausliefert (Operator
flippt `compose.yaml.disabled` → `compose.yaml` über `dream enable
dashboard-nuxt`, sobald das Image gebaut ist).

| Datei | Zweck |
|---|---|
| `manifest.yaml` | `service.id: dashboard-nuxt`, Port `3011`, `category: experimental`, `depends_on: [dashboard-api]` |
| `compose.yaml.disabled` | Build-context = dieser Ordner, Port `${DASHBOARD_NUXT_PORT:-3011}:3011`, `BIND_ADDRESS`-Pin, `DASHBOARD_API_KEY` env, `dream-network` |
| `Dockerfile` | Multi-stage: `node:20-alpine` Build → `node:20-alpine` Runtime (`node .output/server/index.mjs`). Non-root user `dreamer`. |
| `README.md` | Operator-Doku: enable/disable, Dev-Befehle, Cutover-Hinweis. |
| `.dockerignore`, `package.json`, `nuxt.config.ts`, `app.config.ts` | Bootstrap (siehe Phase 1). |
| `tsconfig.json` | `extends: "./.nuxt/tsconfig.json"` |
| `app/`, `pages/`, `components/`, `composables/`, `stores/`, `models/`, `server/`, `assets/`, `public/` | Verzeichnisstruktur (Phasen 2–5). |

**Port-Plan**: `3011` (frei laut `config/ports.json`). Nach Cutover
wird der React-Service auf einen Wegwerf-Port verschoben oder
abgeschaltet, und `dashboard-nuxt` übernimmt `3001`.

**Image-Pin-Disziplin**: Sobald der Build steht, `installers/phases/08-images.sh`
um die `dream-server/dashboard-nuxt:0.1.0`-Zeile ergänzen (analog
`finance-vector` / `lotto-oracle`).

---

## 2  Phasenplan

Jede Phase ist ein eigener Commit-Block (`feat(dashboard-nuxt): …`)
und hinterlässt einen lauffähigen Stand. Reihenfolge ist verbindlich;
Pages können innerhalb Phase 4 parallelisiert werden.

### Phase 1 — Projekt-Bootstrap

- [ ] `package.json` mit `nuxt@^4`, `@nuxt/ui@^3`, `@pinia/nuxt`,
      `pinia`, `pinia-orm`, `@pinia-orm/nuxt`, `@vueuse/nuxt`,
      `@vueuse/motion`, `@nuxtjs/i18n`, `@vite-pwa/nuxt`, `gsap`.
- [ ] `nuxt.config.ts`: `ssr: false`, Module-Liste, `runtimeConfig`
      (`apiKey`, `apiBaseInternal: 'http://dashboard-api:3002'`),
      `app.head` (Title, CSP-konformes `<script>` für Theme-Flash).
- [ ] `app.config.ts`: Nuxt-UI-Theme (Primärfarbe = Theme-Accent aus
      `tailwind.config.js`, Border-Radius, Font-Stack).
- [ ] `tsconfig.json`, ESLint via `@nuxt/eslint`.
- [ ] `nuxt prepare` lokal grün, `nuxt build` produziert
      `.output/server/index.mjs`.

**Akzeptanzkriterium**: `docker compose -f compose.local.yaml up
dashboard-nuxt` liefert eine leere "DREAM SERVER"-Seite auf `:3011`.

### Phase 2 — Datenschicht (Composables, Stores, Models)

#### 2.1 Server-Proxy (Nitro)

- [ ] `server/middleware/api-proxy.ts`: alle Requests auf `/api/**`
      werden mit `Authorization: Bearer ${runtimeConfig.apiKey}` an
      `runtimeConfig.apiBaseInternal` weitergereicht. Streaming
      (SSE für `download-status`, `gpu/history`) via `sendStream`.
- [ ] Health-Probe `server/api/health.get.ts` → `200` für Docker-HC.

#### 2.2 Composable-Schicht (Mapping React-Hook → Nuxt-Composable)

| React-Hook | Neues Composable | Backend-State |
|---|---|---|
| `useSystemStatus` | `useSystemStatus()` | Pinia-Store `system` (Polling 5 s) |
| `useVersion` | `useVersion()` | Pinia-Store `system` (Sub-Slice `version`) |
| `useFirstRun` | `useFirstRun()` | Pinia-Store `setup` |
| `useGPUDetailed` | `useGpuDetailed()` | Pinia-Store `gpu` (Polling 2 s, `useIntervalFn` aus VueUse) |
| `useModels` | `useModels()` | Pinia-Store `models` |
| `useDownloadProgress` | `useDownloadProgress()` | SSE via `useEventSource` (VueUse), in Pinia-Store `downloads` |
| `usePwaInstallPrompt` | `usePwaInstall()` | VueUse `useEventListener('beforeinstallprompt')` + `usePreferredDark` |
| `useVoiceAgent` | `useVoiceAgent()` | Eigener Store wegen WebSocket-State |

#### 2.3 Pinia ORM Modelle

Nur dort wo Relationen Mehrwert bringen. Liste:

| Model | Relationen |
|---|---|
| `Service` | `hasMany(Resource)`, `belongsToMany(Token)` |
| `Strategy` | `hasMany(Position)`, `hasMany(Trade)` |
| `Position` | `belongsTo(Strategy)` |
| `Trade` | `belongsTo(Strategy)`, `belongsTo(Position)` |
| `Game` | `hasMany(Draw)`, `hasMany(TipSet)` |
| `Draw` | `belongsTo(Game)` |
| `TipSet` | `belongsTo(Game)`, `belongsTo(Draw)` |
| `RepoMapEntry` | `belongsTo(Project)`, `hasMany(Workflow)` |

UI-only State (`sidebarCollapsed`, `splashShown`, `theme`,
`activeTab`) → klassische Pinia-Stores ohne ORM.

**Akzeptanzkriterium**: alle 33 Endpunkte sind in Composables typisiert;
ein Vue-Devtools-Snapshot zeigt `Service`/`Strategy`-Relationen korrekt.

### Phase 3 — App-Shell + Sidebar

- [ ] `app.vue` + `layouts/default.vue` mit `UDashboardGroup`,
      `UDashboardSidebar`, `UDashboardPanel`. Collapsed-State per
      `useStorage('dream-sidebar-collapsed')` aus VueUse.
- [ ] `BootstrapBanner.vue` (1:1 React-Logik aus `App.jsx`).
- [ ] `SplashScreen.vue` — GSAP-Timeline 1:1 portiert (GSAP ist
      framework-agnostisch). Sichtbarkeit aus
      `useSessionStorage('dream-splash-shown')`.
- [ ] `composables/useDashboardRoutes.ts` ersetzt
      `plugins/{core,registry}.js`. Sidebar-Predikate
      (`status?.gpu?.gpu_count > 1`, `services.includes('vikunja')` …)
      bleiben als Vorhersage-Funktionen pro Route. Pages werden über
      `definePageMeta({ sidebar: { … } })` typisiert.
- [ ] `InstallPromptBanner.vue` — über `usePwaInstall()`.

### Phase 4 — Pages (in 4 Wellen)

Jede Welle = ein PR, jeweils visuelle Parität mit React-Original
prüfen (`docker compose up dashboard dashboard-nuxt` → vergleichen).

**Welle A — Statusflächen** (geringes Risiko)

- [ ] `pages/index.vue` ← `Dashboard.jsx` (1 480 LoC; aufteilen in
      `<KpiStrip>`, `<ServicesGrid>`, `<RecentActivity>` Komponenten)
- [ ] `pages/gpu.vue` ← `GPUMonitor.jsx` + `GPUCard`, `GPUChart`,
      `TopologyView`
- [ ] `pages/models.vue` ← `Models.jsx`
- [ ] `pages/settings.vue` ← `Settings.jsx` + `EnvEditor.jsx`

**Welle B — Operative Pages**

- [ ] `pages/extensions/index.vue` ← `Extensions.jsx` (1 254 LoC)
- [ ] `pages/extensions/integrations.vue` ← `ServiceMap.jsx`
- [ ] `pages/projects.vue` ← `Projects.jsx`
- [ ] `pages/repo-map.vue` ← `RepoProjectMap.jsx`
- [ ] `pages/invites.vue` ← `Invites.jsx`

**Welle C — Finance-Stack** (siehe AGENT-OPERATIONS §11/§13)

- [ ] `pages/finance-guru/index.vue` mit `<UTabs>`:
  - Tab 1 `<StrategiesTab>` ← `FinanceGuru.jsx` (594 LoC)
  - Tab 2 `<LottoTab>` ← `LottoTab.jsx` (1 011 LoC, größte Page)
- [ ] `pages/voice.vue` ← `Voice.jsx`

**Welle D — Onboarding**

- [ ] `pages/first-boot.vue` ← `FirstBoot.jsx` (581 LoC) +
      `SetupWizard`, `PreFlightChecks`, `TemplatePicker`,
      `AssignmentTable`, `DependencyBadges`, `SuccessValidation`,
      `TroubleshootingAssistant`, `FeatureDiscovery`. Sub-Seiten
      über `<NuxtPage>` im Wizard-Layout.
- [ ] Middleware `middleware/first-run.global.ts`: leitet auf
      `/first-boot` um, wenn `useFirstRun().firstRun.value === true`.

### Phase 5 — PWA, Theming, i18n

- [ ] `@vite-pwa/nuxt` mit Manifest aus `public/manifest.json`
      (vorhandener Stand).
- [ ] Theme-Flash-Skript (`<script>` in `app.head`) inline + CSP-Hash
      neu berechnen (Anleitung aus `nginx.conf` Kommentar
      übernehmen). Hash-Generierung im Build-Step automatisieren
      (`scripts/csp-hash.mjs`), damit künftige Edits nicht stumm
      brechen.
- [ ] `@nuxtjs/i18n` mit `de`/`en`, Default `de`. React-Dashboard
      hartkodierte deutsche Strings (FinanceGuru, LottoTab) → in
      `i18n/locales/de.json` extrahieren.

### Phase 6 — Tests

- [ ] **Unit**: `vitest` + `@nuxt/test-utils` für Composables und
      Pinia-Stores (`useSystemStatus`, `useDownloadProgress`,
      Lotto-Strategie-Reactivity).
- [ ] **Component**: `@nuxt/test-utils`/`vue-test-utils` für jede
      Page-Welle (Snapshot + Role-basiert wie das React-Pendant).
- [ ] **E2E**: Playwright-Profil `dashboard-nuxt` (Smoke-Test:
      Splash → Dashboard → Sidebar collapse → Settings öffnen).
- [ ] CI: neuer Workflow-Job `dashboard-nuxt-lint-test`, läuft
      parallel zum bestehenden `dashboard`-Job.

### Phase 7 — Cutover

- [ ] `docker-compose.base.yml`: `dashboard-nuxt` neben `dashboard`
      eintragen (gleiche Volumes nicht nötig, kein Read-State).
- [ ] `dream check-image-updates`-Datenbank um den Build-Tag
      ergänzen.
- [ ] **Soak**: 14 Tage Parallelbetrieb; Issues über Sentry-Integration
      (falls aktiv) oder manuell erfassen. KPI = "Page lädt in <2 s
      auf Halo Strix iGPU-Browser, kein API-Polling-Spam, identisches
      Verhalten gegenüber React-Stand".
- [ ] **Switch**: `manifest.yaml` des React-Service auf
      `external_port_default: 3010` umziehen, `dashboard-nuxt` auf
      `3001`. Nach 30 Tagen ohne Regressionen: React-Service in
      `extensions/services/_archive/` verschieben + ADR
      `ADR-DASHBOARD-MIGRATION.md` schreiben.

---

## 3  Risiken & Gegenmaßnahmen

| Risiko | Mitigation |
|---|---|
| Nuxt-UI v3 ist im Mai 2026 noch jung — Breaking Changes möglich. | Pin auf konkrete Minor + Renovate-Branch; Monatlicher Re-Test. |
| Pinia ORM v2 hat Bundle-Overhead (~30 KB gz). | SPA-Mode lädt einmalig; kein SSR-Pfad betroffen. Akzeptabel. |
| GSAP läuft mit Vue 3, aber nicht mit dessen Reactivity-Refs ohne `markRaw()`. | Splash-Komponente kapselt GSAP-Tween in `markRaw`-Wrapper, wie in den GSAP-Docs für Vue 3 vorgesehen. |
| Magic-Link-Auth schreibt heute in `localStorage`. | VueUse `useStorage` mit identischem Key — 1:1 wieder­verwendbar. Kein User-Re-Login nötig, da Token serverseitig (Cookie) sitzt. |
| Service-Worker (PWA) bricht durch URL-Wechsel `:3001 → :3011`. | Pre-Cutover: Manifest-`scope` und `start_url` relativ halten; Service-Worker-Update-Toast aus React-Stand übernehmen. |
| CSP-Hashes müssen für Inline-Theme-Skript neu berechnet werden. | Build-Skript (Phase 5) macht das automatisch und schreibt sie in den Nginx-Header bzw. den `Nuxt-CSP`-Hook. |

---

## 4  Definition of Done

- [ ] `dashboard-nuxt` ist im Repo enabled-by-default-disabled,
      Image baut reproduzierbar, Healthcheck grün.
- [ ] Alle 15 React-Pages haben ein Vue-Pendant mit identischer
      Funktionalität (visuell ≥ 95 % Parität, funktional 100 %).
- [ ] 33 API-Endpunkte sind durch Composables abgedeckt; keine
      direkten `$fetch('/api/…')` außerhalb von `composables/`.
- [ ] Lighthouse-Score (Mobile, Halo Strix LAN) ≥ React-Stand.
- [ ] Operator-README erklärt: enable, disable, Cutover, Rollback.
- [ ] AGENT-OPERATIONS §14 verweist auf diesen Plan und nennt den
      Service in der Inventarliste.

---

## 5  Referenzen

- Nuxt UI Dashboard Template: <https://github.com/nuxt-ui-templates/dashboard>
- Nuxt 4 Migration Notes: <https://nuxt.com/docs/4.x>
- Pinia ORM: <https://pinia-orm.codedredd.de/>
- VueUse: <https://vueuse.org/>
- React-Stand: `dream-server/extensions/services/dashboard/`
- API-Stand: `dream-server/extensions/services/dashboard-api/`
- Operator-Kontext: `AGENT-OPERATIONS.md` §3, §14

