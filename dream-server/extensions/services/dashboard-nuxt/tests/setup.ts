/**
 * Globaler Test-Setup. Wird vor jedem Test-File geladen (siehe
 * vitest.config.ts > test.setupFiles).
 *
 * Aufgaben:
 * - `globalThis.fetch` als vi.fn-Mock, damit `$fetch`/`fetch`-Aufrufe in
 *   Composables in Unit-Tests deterministisch sind.
 * - Pinia frische Instanz pro Test (vermeidet State-Leaks zwischen Tests).
 * - LocalStorage / sessionStorage Polyfill via happy-dom (vorhanden).
 */

import { afterEach, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

beforeEach(() => {
  setActivePinia(createPinia())
  // Default fetch-Mock: jeder Aufruf liefert {} mit 200, kann pro Test
  // ueber vi.mocked(fetch).mockResolvedValueOnce(...) ueberschrieben werden.
  globalThis.fetch = vi.fn(async () => new Response(JSON.stringify({}), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })) as typeof fetch
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
  sessionStorage.clear()
})

