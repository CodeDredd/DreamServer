# Dashboard NG (Nuxt-Variante) — `dashboard-nuxt`

> Experimenteller Parallelbetrieb zur produktiven React-Variante
> (`extensions/services/dashboard`, Port `3001`). Spricht dieselbe
> `dashboard-api` (`:3002`), läuft auf Port **`3011`**.

## Status

**Phase 0** — Service-Skelett. Noch keine Pages, kein Build im
Image-Pin. Der Plan + alle Phasen sind in
[`dream-server/docs/DASHBOARD-NUXT-MIGRATION.md`](../../../docs/DASHBOARD-NUXT-MIGRATION.md)
beschrieben.

## Stack

- Nuxt 4 (SPA-Mode, `ssr: false`)
- Nuxt UI v3 (App-Shell, Theme via `app.config.ts`)
- Pinia + Pinia ORM (UI-State + Entity-Layer)
- VueUse (`useStorage`, `useIntervalFn`, `useEventSource`,
  `usePreferredDark`, `useEventListener('beforeinstallprompt')`)
- Nitro Server-Middleware: ersetzt den nginx-`/api/`-Proxy aus der
  React-Variante, injiziert `Authorization: Bearer ${DASHBOARD_API_KEY}`
  und reicht an `dashboard-api:3002` weiter.

## Dev (lokal)

```bash
# Innerhalb des Service-Verzeichnisses
npm install
DASHBOARD_API_KEY=... \
  NUXT_API_BASE_INTERNAL=http://127.0.0.1:3002 \
  npm run dev   # http://127.0.0.1:3011
```

Die `dashboard-api` muss separat laufen
(`dream restart dashboard-api`), und `DASHBOARD_API_KEY` aus
`~/dream-server/.env` exportiert sein.

## Enable / Disable (Halo Strix)

```bash
# 1. Image bauen (einmalig nach Phase 1 / nach jedem Bump)
dream build dashboard-nuxt

# 2. Aktivieren (Parallelbetrieb)
dream enable dashboard-nuxt
dream restart dashboard-nuxt

# 3. Deaktivieren (zurück zur React-Variante als alleiniges UI)
dream disable dashboard-nuxt
```

`dream sync --pull` respektiert den per-Service-Toggle (siehe
AGENT-OPERATIONS §5).

## Cutover-Plan

Siehe `DASHBOARD-NUXT-MIGRATION.md` Phase 7. Kurzfassung:

1. 14 Tage Parallelbetrieb auf `:3011`.
2. Wenn kein Regress: React-Service auf Port `3010` umziehen,
   `dashboard-nuxt` auf `3001` heben.
3. 30 Tage stabil → React-Service nach
   `extensions/services/_archive/` verschieben + ADR.

## Operator-Notiz

Service-Volume gibt es nicht — alles UI ist statelessly client-side.
`dream-network` ist die einzige Abhängigkeit zur API.

