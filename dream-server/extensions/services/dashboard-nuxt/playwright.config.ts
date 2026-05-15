import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright-Konfiguration fuer dashboard-nuxt E2E-Tests (Phase 6).
 *
 * Smoke-Tests laufen gegen einen lokal gestarteten Nuxt-Production-
 * Build (preview, port 3011). Auth ist nicht via Magic-Link
 * automatisiert — Tests, die geschuetzte Routen brauchen, muessen
 * die Auth-Cookies via storageState seeden.
 *
 * baseURL via PLAYWRIGHT_BASE_URL ueberschreibbar (CI vs. lokal).
 */

export default defineConfig({
  testDir: './tests/e2e',
  testMatch: '**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [['list'], ['github']] : 'list',

  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:3011',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Lokal: starte den preview-Server automatisch. In CI wird der Server
  // typischerweise extern hochgefahren (siehe dashboard-nuxt.yml).
  webServer: process.env.CI
    ? undefined
    : {
        command: 'pnpm run preview',
        port: 3011,
        timeout: 60_000,
        reuseExistingServer: true,
      },
})

