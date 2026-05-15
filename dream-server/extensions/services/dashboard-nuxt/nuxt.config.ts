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
    'nuxt-security',
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
        { name: 'theme-color', content: '#0f0f13' },
        { name: 'apple-mobile-web-app-capable', content: 'yes' },
        { name: 'apple-mobile-web-app-status-bar-style', content: 'black-translucent' },
        { name: 'apple-mobile-web-app-title', content: 'Dream' },
      ],
      link: [
        { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
        { rel: 'apple-touch-icon', href: '/dream.svg' },
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

  // PWA-Manifest 1:1 zum React-Stand (dashboard/public/manifest.webmanifest),
  // damit Installations-Prompt auf installierten PWAs identisch funktioniert
  // und der Cutover keinen Re-Install erzwingt.
  pwa: {
    registerType: 'autoUpdate',
    manifest: {
      name: 'Dream Server',
      short_name: 'Dream',
      description: 'Control center for your local Dream Server — chat, agents, models, settings.',
      theme_color: '#0f0f13',
      background_color: '#0f0f13',
      display: 'standalone',
      orientation: 'any',
      start_url: '/',
      scope: '/',
      categories: ['productivity', 'utilities'],
      icons: [
        { src: '/dream.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        { src: '/dream.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'maskable' },
      ],
    },
    workbox: {
      // /api/** darf NIE gecacht werden — Live-Daten.
      navigateFallbackDenylist: [/^\/api\//],
      // Auth-Endpoints + SSE-Streams ebenfalls pass-through.
      navigateFallback: '/',
      globPatterns: ['**/*.{js,css,html,svg,ico,png,woff2}'],
      runtimeCaching: [],
      cleanupOutdatedCaches: true,
    },
    devOptions: { enabled: false },
    client: {
      installPrompt: true,
    },
  },

  // CSP + Security-Header werden vom `nuxt-security`-Modul gesetzt
  // (siehe security-Block weiter unten). Hier nur cache-relevante
  // routeRules fuer PWA-Assets.
  routeRules: {
    '/sw.js': { headers: { 'Cache-Control': 'public, max-age=0, must-revalidate' } },
    '/manifest.webmanifest': { headers: { 'Cache-Control': 'public, max-age=3600' } },
  },

  // nuxt-security: Helmet-aehnliche Security-Header inkl. CSP. Ersetzt
  // unsere fruehere selbstgebaute server/middleware/csp.ts. Begruendung:
  // Maintainer-betreut, breiter Test-Footprint, deckt Headers ab, die
  // wir manuell nachpflegen muessten (CSP, Permissions-Policy, COEP/
  // COOP/CORP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy,
  // Origin-Agent-Cluster).
  //
  // Configured via top-level `security`-Key (Nuxt-Security 2.x).
  // contentSecurityPolicy explizit konfiguriert, alles andere
  // benutzt nuxt-security-Defaults.
  security: {
    headers: {
      contentSecurityPolicy: {
        'default-src': ['\'self\''],
        // Nuxt UI emittiert dynamische Inline-Scripts (Color-Mode IIFE,
        // __NUXT__-Config, unhead-payload, NUXT_DATA-JSON). Deren Hash
        // aendert sich pro Build, daher 'unsafe-inline' in script-src.
        // SPA-Mode hat kein nonce; Build-Zeit-Hashes funktionieren nur
        // mit `ssg.hashScripts: true` und nuxt generate (nicht unser Setup).
        'script-src': ['\'self\'', '\'unsafe-inline\''],
        // Tailwind/Nuxt UI emittiert Inline-Styles fuer Theme-Variablen.
        'style-src': ['\'self\'', '\'unsafe-inline\''],
        'img-src': ['\'self\'', 'data:', 'blob:'],
        'font-src': ['\'self\'', 'data:'],
        'connect-src': ['\'self\''],
        'media-src': ['\'self\'', 'blob:'],
        'frame-ancestors': ['\'none\''],
        'base-uri': ['\'self\''],
        'form-action': ['\'self\''],
        'object-src': ['\'none\''],
        // Halo Strix laeuft per Default auf http://, daher kein
        // upgrade-insecure-requests (sonst koennen interne Calls brechen).
        'upgrade-insecure-requests': false,
      },
      // COEP=require-corp bricht LiveKit/WebRTC, daher ausschalten.
      crossOriginEmbedderPolicy: 'unsafe-none',
      // HSTS deaktiviert: Halo Strix oft ohne TLS, sonst werden alle
      // HTTP-Requests zukuenftiger 6 Monate gewaltsam HTTPS-redirected.
      strictTransportSecurity: false,
      // Default ist 'no-referrer' (zu strikt fuer interne Navigation —
      // /api-Aufrufe verlieren ihren Origin-Header und das Backend
      // kann CSRF-Header-Pruefung nicht mehr durchziehen).
      referrerPolicy: 'strict-origin-when-cross-origin',
      // Permissions-Policy default verbietet Mikrofon - das brauchen
      // wir aber fuer die Voice-Page (LiveKit). Self erlauben.
      permissionsPolicy: {
        camera: [],
        microphone: ['self'],
        geolocation: [],
        'display-capture': [],
        fullscreen: ['self'],
      },
      // X-Frame-Options DENY (default ist SAMEORIGIN) - der Dashboard
      // soll nirgends iframed werden, auch nicht von uns selbst.
      xFrameOptions: 'DENY',
    },
    // Rate-Limit fuer den /api-Proxy bewusst aus — Backend handhabt das.
    rateLimiter: false,
    // CORS: SPA + Same-Origin, kein Cross-Origin geplant.
    corsHandler: {
      origin: '*',
      methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'],
    },
    // /api/** ist transparent zum Backend gereicht — wir wollen nicht
    // doppelt validieren, das macht das Backend.
    xssValidator: false,
    requestSizeLimiter: {
      maxRequestSizeInBytes: 2_000_000, // 2 MB
      maxUploadFileRequestInBytes: 8_000_000, // 8 MB
    },
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

