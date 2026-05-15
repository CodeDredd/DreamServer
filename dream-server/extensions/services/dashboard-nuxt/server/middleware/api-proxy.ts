// Nitro-Server-Middleware: Drop-in-Ersatz für den nginx-`/api/`-Proxy
// der React-Variante (siehe `dashboard/nginx.conf` Z. 27–41).
//
//   1. Reicht alle Requests auf `/api/**` (außer `/api/health`) an
//      `runtimeConfig.apiBaseInternal` (= dashboard-api:3002) weiter.
//   2. Injiziert `Authorization: Bearer ${DASHBOARD_API_KEY}`. Der
//      Key bleibt serverseitig — Browser sieht ihn nie.
//   3. Trägt Original-Method/Body/Streaming durch (SSE-Endpunkte
//      wie /api/models/download-status oder /api/gpu/history).
//
// Phase 1 liefert die Mindest-Implementierung — Phase 2 erweitert um
// Rate-Limit-Toleranz, Tracing-Headers, und Mapping-Tests gegen alle
// 33 dokumentierten Endpunkte.

import { joinURL } from 'ufo'

export default defineEventHandler(async (event) => {
  const url = getRequestURL(event)
  if (!url.pathname.startsWith('/api/')) return
  // /api/health ist lokal (siehe ./api/health.get.ts) — nicht weiterreichen.
  if (url.pathname === '/api/health') return

  const config = useRuntimeConfig(event)
  // runtimeConfig wird zur Build-Zeit aufgelöst (siehe nuxt.config.ts);
  // wir lesen die ENV-Vars zusätzlich zur Laufzeit, damit DASHBOARD_API_KEY
  // / NUXT_API_BASE_INTERNAL jederzeit aus dem Container-Env nachgezogen
  // werden, ohne Re-Build.
  const apiKey = config.apiKey || process.env.DASHBOARD_API_KEY || process.env.NUXT_API_KEY || ''
  const apiBase = config.apiBaseInternal
    || process.env.NUXT_API_BASE_INTERNAL
    || 'http://dashboard-api:3002'

  const target = joinURL(apiBase, url.pathname.replace(/^\/api/, '/api')) + url.search

  const headers = new Headers()
  // Forward Header außer Hop-by-Hop / Auth (wir setzen unsere eigene).
  for (const [k, v] of Object.entries(getRequestHeaders(event))) {
    if (!v) continue
    const key = k.toLowerCase()
    if (['host', 'connection', 'content-length', 'authorization'].includes(key)) continue
    headers.set(k, Array.isArray(v) ? v.join(',') : String(v))
  }
  if (apiKey) {
    headers.set('Authorization', `Bearer ${apiKey}`)
  }

  const method = event.method
  const body = ['GET', 'HEAD'].includes(method) ? undefined : await readRawBody(event, false)

  const upstream = await fetch(target, {
    method,
    headers,
    body: body as BodyInit | undefined,
    redirect: 'manual',
  })

  // Antwort-Header durchreichen (außer hop-by-hop).
  for (const [k, v] of upstream.headers.entries()) {
    if (['transfer-encoding', 'connection', 'keep-alive'].includes(k.toLowerCase())) continue
    setResponseHeader(event, k, v)
  }
  setResponseStatus(event, upstream.status, upstream.statusText)

  // Body als Stream durchreichen (wichtig für SSE).
  return upstream.body
})

