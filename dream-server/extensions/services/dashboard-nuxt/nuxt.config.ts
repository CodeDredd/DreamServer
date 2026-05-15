// Nuxt 4 — SPA-Mode (siehe DASHBOARD-NUXT-MIGRATION.md §0).
// Alle Logik ist client-side; SSR brächte nur Komplexität (Auth-Bearer,
// GPU-Polling, GSAP-Splash). Halo Strix ist kein Render-Server.
//
// Der `/api/**`-Pfad wird von einer Nitro-Server-Middleware
// (`server/middleware/api-proxy.ts`, kommt in Phase 2) an
// `dashboard-api:3002` durchgereicht — Drop-in-Ersatz für den
// nginx-Reverse-Proxy der React-Variante.

export default defineNuxtConfig({
  compatibilityDate: '2025-05-01',

  // Client-rendered. Nitro übernimmt nur den /api/-Proxy + Healthcheck.
  ssr: false,

  devtools: { enabled: true },

  modules: [
    '@nuxt/ui',
    '@nuxt/eslint',
    '@pinia/nuxt',
    '@pinia-orm/nuxt',
    'pinia-plugin-persistedstate/nuxt',
    '@vueuse/nuxt',
    '@vueuse/motion/nuxt',
    '@nuxtjs/i18n',
    '@vite-pwa/nuxt',
  ],

  css: ['~/assets/css/main.css'],

  // Pinia ORM erwartet die Models/Repos unter `~~/store/{models,repositories}`
  // (Best-Practice-Layout: store/BaseModel.ts, store/BaseRepository.ts,
  // store/models/<Name>.ts, store/repositories/<Name>Repository.ts).
  // Models/Repos werden manuell importiert, kein Auto-Import — das erzwingt
  // expliziten Daten-Flow und ist der gleiche Stil wie im Referenz-Projekt.
  imports: {
    dirs: ['composables/**'],
  },

  colorMode: {
    // SPA: keine Hydration, daher kein Flash — aber Transition stoert
    // ohnehin (Theme-Switch ist instant, nicht animiert).
    disableTransition: true,
    classSuffix: '',
  },

  ui: {
    // Nuxt UI 4 — App-Config (app.config.ts) liefert das Theme.
    // Hier nur, was modul-global gilt:
    fonts: false, // Wir verwenden System-Fonts (JetBrains Mono).
  },



  // Server-only secrets via runtimeConfig (Bearer wird in
  // server/middleware/api-proxy.ts injiziert, nie zum Client geschickt).
  // Bridges existing env-Konvention (`DASHBOARD_API_KEY`,
  // `NUXT_API_BASE_INTERNAL`) auf Nuxt-`runtimeConfig`. Default für
  // apiBaseInternal ist der Docker-DNS-Name; lokal überschreibbar.
  runtimeConfig: {
    apiKey: process.env.DASHBOARD_API_KEY || '',
    apiBaseInternal: process.env.NUXT_API_BASE_INTERNAL || 'http://dashboard-api:3002',
    public: {
      appName: 'Dream Server',
      appVersion: '0.1.0',
    },
  },

  nitro: {
    // Der Healthcheck schlägt sonst fehl, weil der Container per
    // Default auf der Loopback-Adresse lauscht.
    devProxy: {},
  },

  app: {
    head: {
      title: 'Dream Server — Dashboard NG',
      htmlAttrs: { lang: 'de' },
      meta: [
        { charset: 'utf-8' },
        { name: 'viewport', content: 'width=device-width, initial-scale=1, viewport-fit=cover' },
        { name: 'description', content: 'Dream Server Control Center (Nuxt)' },
        { name: 'theme-color', content: '#0a0a0a' },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
      ],
    },
  },

  i18n: {
    strategy: 'no_prefix',
    defaultLocale: 'de',
    locales: [
      { code: 'de', name: 'Deutsch', file: 'de.json' },
      { code: 'en', name: 'English', file: 'en.json' },
    ],
    bundle: { optimizeTranslationDirective: false },
  },

  pwa: {
    registerType: 'autoUpdate',
    manifest: {
      name: 'Dream Server',
      short_name: 'Dream',
      description: 'Dream Server Dashboard',
      theme_color: '#0a0a0a',
      background_color: '#0a0a0a',
      display: 'standalone',
      start_url: '/',
      scope: '/',
      icons: [],
    },
    workbox: {
      // /api/** darf NIE gecacht werden — Live-Daten.
      navigateFallbackDenylist: [/^\/api\//],
      runtimeCaching: [],
    },
    devOptions: { enabled: false },
  },


  typescript: {
    strict: true,
    typeCheck: false, // explizit über `npm run typecheck`
  },

  eslint: {
    config: { stylistic: true },
  },

  experimental: {
    payloadExtraction: false,
  },
})

