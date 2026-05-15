/**
 * Nitro-Response-Middleware: berechnet sha256-CSP-Hashes fuer
 * Inline-`<script>`-Bloecke der ausgehenden HTML-Antwort und setzt
 * den `Content-Security-Policy`-Header dynamisch pro Response.
 *
 * Begruendung: Nuxt 4 (SPA-Modus) rendert die Index-HTML zur Laufzeit
 * via Nitro — Color-Mode-IIFE, `__NUXT__`-Config, `unhead:payload` und
 * NUXT_DATA-JSON-Bloecke sind buildhash-abhaengig und aendern sich bei
 * jedem Build. Einen statischen Hash in `nuxt.config.ts > routeRules`
 * pflegen heisst lautlose Brueche bei jedem Edit (siehe React-
 * `nginx.conf`-Kommentar). Daher wird der Header on-the-fly
 * berechnet (~ 0.5 ms pro Request, da Single-Pass-Regex auf einer
 * < 5 KB grossen HTML).
 *
 * `connect-src 'self'` deckt /api/-Proxy ab; `microphone=(self)` ist
 * fuer Voice-Page noetig (Permissions-Policy).
 */

import { createHash } from 'node:crypto'

const INLINE_SCRIPT_RE = /<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi

function computeHashes(html: string): string[] {
  const hashes = new Set<string>()
  let m
  while ((m = INLINE_SCRIPT_RE.exec(html)) !== null) {
    const body = m[1]
    if (!body || !body.trim()) continue
    const h = createHash('sha256').update(body, 'utf8').digest('base64')
    hashes.add(`'sha256-${h}'`)
  }
  return [...hashes]
}

function buildCsp(scriptHashes: string[]): string {
  const scriptSrc = ['self', ...scriptHashes].map(s =>
    s.startsWith("'") ? s : `'${s}'`,
  ).join(' ')
  return [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    // 'unsafe-inline' fuer styles ist Nuxt-UI/Tailwind notwendig (CSS-in-JS-
    // Tokens beim Color-Mode-Switch). Style-Hashes wuerden die UA-Engine
    // sonst auf jeden Class-Change neu rechnen lassen.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "media-src 'self' blob:",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
  ].join('; ')
}

export default defineEventHandler(async (event) => {
  // Nur Hauptdokument-Requests behandeln; Assets/API ueberspringen.
  const url = event.node.req.url || ''
  if (url.startsWith('/api/') || url.startsWith('/_nuxt/') || url === '/sw.js'
    || url === '/manifest.webmanifest' || url === '/favicon.svg' || url === '/dream.svg') {
    return
  }

  // Common Security-Headers fuer alles - schaden nicht und decken die
  // Cases ab, wo der CSP-Hook nicht greift (304, statische Files, etc).
  setHeader(event, 'X-Content-Type-Options', 'nosniff')
  setHeader(event, 'Referrer-Policy', 'strict-origin-when-cross-origin')
  setHeader(event, 'Permissions-Policy', 'camera=(), microphone=(self), geolocation=()')

  // Hook in den Response-Body, sobald er fertig ist - dann koennen wir
  // die Inline-Scripts hashen. h3's `afterResponse` ist hier der Falsche;
  // wir brauchen den Body BEFORE er rausgeht. Daher patchen wir
  // `res.write` / `res.end`.
  //
  // Nitro liefert SPA-HTML i. d. R. via einem einzigen `res.end(html)` -
  // wir buffern und schreiben einmal mit gesetztem Header.
  const res = event.node.res
  const originalEnd = res.end.bind(res)
  let captured = ''
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  res.end = function patchedEnd(chunk?: any, ...rest: any[]) {
    try {
      const ct = String(res.getHeader('content-type') || '')
      if (ct.includes('text/html') && chunk) {
        captured = typeof chunk === 'string' ? chunk : Buffer.from(chunk).toString('utf8')
        const hashes = computeHashes(captured)
        if (!res.headersSent) {
          res.setHeader('Content-Security-Policy', buildCsp(hashes))
        }
        return originalEnd(captured, ...rest)
      }
    }
    catch {
      // Bei Fehler: Header weglassen statt den Response zu kippen.
    }
    return originalEnd(chunk, ...rest)
  } as typeof res.end
})

