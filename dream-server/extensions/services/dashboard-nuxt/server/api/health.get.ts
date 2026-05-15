// Container-Healthcheck (Dockerfile HEALTHCHECK ruft genau diesen Pfad).
// Liegt unter /api/health, weil:
//   1. der Docker-HC sonst auf dem Vue-SPA-Index landen würde (200 zwar,
//      aber inhaltlich nichtssagend),
//   2. der Pfad in der nginx-CSP der React-Variante bereits als
//      same-origin akzeptiert ist — gleiche Semantik in beiden Stacks.

export default defineEventHandler(() => ({
  status: 'ok',
  service: 'dashboard-nuxt',
  timestamp: new Date().toISOString(),
}))

