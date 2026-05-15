import { test, expect } from '@playwright/test'

/**
 * Smoke-Tests fuer dashboard-nuxt (Phase 6 E2E).
 *
 * Voraussetzungen:
 * - dashboard-nuxt laeuft auf $PLAYWRIGHT_BASE_URL (default
 *   http://127.0.0.1:3011), entweder via webServer (lokal) oder als
 *   externer Container (CI).
 * - Routen, die normalerweise auth-protected sind, werden hier nicht
 *   getestet — nur die SPA-Index-HTML, Manifest, Favicon, CSP-Headers
 *   und der Healthcheck-Endpoint.
 *
 * Smoke-Coverage analog zur React-Variante in
 * dashboard/tests/e2e/smoke.spec.ts.
 */

test.describe('dashboard-nuxt smoke', () => {
  test('Index-HTML liefert valide HTML mit Title + Theme-Color', async ({ page }) => {
    const res = await page.goto('/')
    expect(res?.status()).toBe(200)

    await expect(page).toHaveTitle(/Dream Server/i)

    // theme-color Meta sollte gesetzt sein (PWA / Browser-Chrome).
    const themeColor = await page.locator('meta[name="theme-color"]').getAttribute('content')
    expect(themeColor).toBe('#0f0f13')

    // unhead-payload-Script sollte vorhanden sein (Nuxt-Hydration).
    const unhead = await page.locator('script#unhead\\:payload').count()
    expect(unhead).toBeGreaterThanOrEqual(1)
  })

  test('CSP-Header ist via nuxt-security gesetzt', async ({ request }) => {
    const res = await request.get('/')
    const csp = res.headers()['content-security-policy']
    expect(csp).toBeDefined()
    expect(csp).toContain('default-src \'self\'')
    expect(csp).toContain('script-src \'self\'')
    expect(csp).toContain('frame-ancestors \'none\'')
    expect(csp).toContain('object-src \'none\'')
  })

  test('Security-Headers sind auf jeder Hauptdokument-Response gesetzt (nuxt-security)', async ({ request }) => {
    const res = await request.get('/')
    const h = res.headers()
    expect(h['x-content-type-options']).toBe('nosniff')
    expect(h['x-frame-options']).toBe('DENY')
    expect(h['referrer-policy']).toBe('strict-origin-when-cross-origin')
    expect(h['permissions-policy']).toContain('microphone=(self)')
    expect(h['cross-origin-resource-policy']).toBeDefined()
    expect(h['cross-origin-opener-policy']).toBeDefined()
    expect(h['origin-agent-cluster']).toBeDefined()
  })

  test('PWA-Manifest ist gueltig und enthaelt die erwarteten Felder', async ({ request }) => {
    const res = await request.get('/manifest.webmanifest')
    expect(res.status()).toBe(200)
    const manifest = await res.json()
    expect(manifest.name).toBe('Dream Server')
    expect(manifest.short_name).toBe('Dream')
    expect(manifest.theme_color).toBe('#0f0f13')
    expect(manifest.start_url).toBe('/')
    expect(Array.isArray(manifest.icons)).toBe(true)
    expect(manifest.icons.length).toBeGreaterThan(0)
  })

  test('Favicon SVG ist erreichbar', async ({ request }) => {
    const res = await request.get('/favicon.svg')
    expect(res.status()).toBe(200)
    expect(res.headers()['content-type']).toContain('image/svg')
  })

  test('Service-Worker hat no-cache-Header (route-rules)', async ({ request }) => {
    const res = await request.get('/sw.js')
    expect(res.status()).toBe(200)
    expect(res.headers()['cache-control']).toContain('must-revalidate')
  })

  test('Healthcheck-Endpoint /api/health antwortet', async ({ request }) => {
    const res = await request.get('/api/health')
    // 200 wenn /api/health am Nitro-Server haengt, 502/504 wenn nur via
    // dashboard-api-Proxy ohne Backend - in beiden Faellen sollte es
    // nicht 5xx-Internal-Server-Error sein.
    expect([200, 401, 403, 502, 504]).toContain(res.status())
  })
})

