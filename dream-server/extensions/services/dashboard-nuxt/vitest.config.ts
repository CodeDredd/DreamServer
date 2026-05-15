/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

/**
 * Vitest-Konfiguration fuer das dashboard-nuxt-Projekt (Phase 6).
 *
 * Benutzt happy-dom als DOM-Implementierung (kleiner und schneller als
 * jsdom). Alias-Aufloesung spiegelt die Nuxt-internen `~`/`@`/`#imports`-
 * Pfade wider, damit Tests Composables/Stores/Components ohne `nuxt
 * prepare`-Roundtrip importieren koennen.
 *
 * Coverage: v8 (nativ), Output nach `coverage/`. Nuxt-spezifische Files
 * (`.output/**`, `.nuxt/**`, `app.vue`, `nuxt.config.ts`, server/middleware
 * /api-proxy.ts) sind ausgeschlossen, weil sie via E2E getestet werden,
 * nicht via Unit.
 */

export default defineConfig({
  resolve: {
    alias: {
      '~': fileURLToPath(new URL('./app', import.meta.url)),
      '@': fileURLToPath(new URL('./app', import.meta.url)),
      '~~': fileURLToPath(new URL('.', import.meta.url)),
      '#imports': fileURLToPath(new URL('./tests/stubs/imports.ts', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['tests/**/*.{test,spec}.ts'],
    exclude: ['tests/e2e/**', 'node_modules', '.output', '.nuxt'],
    setupFiles: ['./tests/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      reportsDirectory: './coverage',
      include: ['app/composables/**', 'app/utils/**', 'app/stores/**', 'app/components/**'],
      exclude: [
        'app/components/**/*.stories.*',
        '**/*.d.ts',
        '**/*.config.*',
      ],
    },
  },
})

