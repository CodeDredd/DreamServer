#!/usr/bin/env node
/**
 * Berechnet sha256-CSP-Hashes fuer alle Inline-`<script>`-Bloecke einer
 * SPA-Index-HTML und schreibt eine Liste im CSP-Format auf stdout, z. B.:
 *
 *   'sha256-abc=' 'sha256-def='
 *
 * Hinweis: Im laufenden Container wird die CSP von
 * `server/middleware/csp.ts` PRO RESPONSE neu berechnet. Dieses Skript
 * ist nur ein Dev-Tool, falls die Hashes vorab fuer einen externen
 * Reverse-Proxy (nginx, traefik, …) gebraucht werden.
 *
 * Verwendung:
 *
 *   # Aus der Build-Ausgabe (`nuxt generate`-Mode mit static index.html)
 *   pnpm run build && node scripts/csp-hash.mjs
 *
 *   # Aus einem laufenden Server (SPA-Mode, Index wird per-Request gerendert)
 *   node scripts/csp-hash.mjs --url http://localhost:3011/
 *
 * Optionen:
 *   --url <url>   HTTP(S)-Endpunkt statt File-System-Lookup.
 *   --styles      Zusaetzlich `<style>`-Inline-Hashes berechnen.
 *   --verbose     Hashes auf stderr nochmal mit Quelle anzeigen.
 *
 * Exit-Codes:
 *   0  - Hashes erfolgreich berechnet (auch wenn 0 Inline-Scripts).
 *   2  - Index-HTML nicht gefunden bzw. URL nicht erreichbar.
 */

import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'
import { argv, exit, stderr, stdout } from 'node:process'

const urlIndex = argv.indexOf('--url')
const url = urlIndex > -1 ? argv[urlIndex + 1] : null

let html = ''
let source = ''

if (url) {
  try {
    const res = await fetch(url, { headers: { Accept: 'text/html' } })
    if (!res.ok) {
      stderr.write(`[csp-hash] HTTP ${res.status} bei ${url}\n`)
      exit(2)
    }
    html = await res.text()
    source = url
  }
  catch (err) {
    stderr.write(`[csp-hash] Fetch-Fehler: ${(err as Error).message}\n`)
    exit(2)
  }
}
else {
  const projectRoot = resolve(import.meta.dirname, '..')
  const candidates = [
    resolve(projectRoot, '.output/public/index.html'),
    resolve(projectRoot, '.output/public/200.html'),
    resolve(projectRoot, 'dist/index.html'),
  ]

  const indexPath = candidates.find(p => existsSync(p))
  if (!indexPath) {
    stderr.write(
      `[csp-hash] Konnte keine SPA-Index-HTML finden. Erwartet eines von:\n  - ${candidates.join('\n  - ')}\n`
      + `Im SPA-Mode wird kein static index.html emittiert; nutze stattdessen --url http://localhost:3011/ gegen den laufenden Server.\n`,
    )
    exit(2)
  }

  html = await readFile(indexPath, 'utf8')
  source = indexPath
}

// Inline-Scripts: <script>...</script> ohne src-Attribut.
const inlineRegex = /<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi

const hashes = new Set()
let match
while ((match = inlineRegex.exec(html)) !== null) {
  const body = match[1]
  if (!body.trim()) continue
  const hash = createHash('sha256').update(body, 'utf8').digest('base64')
  hashes.add(`'sha256-${hash}'`)
}

if (argv.includes('--styles')) {
  const styleRegex = /<style\b[^>]*>([\s\S]*?)<\/style>/gi
  while ((match = styleRegex.exec(html)) !== null) {
    const body = match[1]
    if (!body.trim()) continue
    const hash = createHash('sha256').update(body, 'utf8').digest('base64')
    hashes.add(`'sha256-${hash}'`)
  }
}

if (argv.includes('--verbose')) {
  stderr.write(`[csp-hash] ${hashes.size} Inline-Hash(es) aus ${source}\n`)
  for (const h of hashes) stderr.write(`  ${h}\n`)
}

stdout.write([...hashes].join(' '))
stdout.write('\n')

