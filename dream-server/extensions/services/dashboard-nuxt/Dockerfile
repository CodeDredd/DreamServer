# Dream Server Dashboard NG (Nuxt 4 / Node 24 / pnpm)
# Multi-stage build: pnpm install → nuxt build → Node-24 runtime.
#
# WICHTIG: Bis Phase 1 grün auf der Halo Strix gebaut hat, bleibt der
# Service disabled (siehe README + `dream-server/docs/DASHBOARD-NUXT-MIGRATION.md`).

# ---------- Stage 1: Build ----------
FROM node:24-alpine AS builder

# pnpm via corepack (in den offiziellen node-Images bereits vorhanden).
RUN corepack enable && corepack prepare pnpm@10.0.0 --activate

WORKDIR /app

# Lockfile + manifest separat kopieren -> bessere Layer-Cache-Hits.
COPY package.json pnpm-lock.yaml* .npmrc ./

# Strikt frozen lockfile in CI/Container-Builds; Build schlägt fehl,
# wenn die lockfile nicht mit package.json übereinstimmt.
RUN pnpm install --frozen-lockfile --prefer-offline

COPY . .
RUN pnpm run build

# ---------- Stage 2: Runtime ----------
FROM node:24-alpine

WORKDIR /app

# node:24-alpine ships with the `node` user (uid 1000) — reuse it.
COPY --from=builder --chown=node:node /app/.output ./.output
# CSP-Hash-Skript fuer Dev-Tools / externe Reverse-Proxies mitnehmen
# (Runtime-CSP wird via server/middleware/csp.ts pro Response gesetzt;
# scripts/csp-hash.mjs ist nur fuer Builds, die Hashes vorab brauchen,
# z. B. fuer einen vorgelagerten nginx mit statischer CSP-Kette).
COPY --from=builder --chown=node:node /app/scripts ./scripts

USER node

ENV NODE_ENV=production \
    NITRO_PORT=3011 \
    NITRO_HOST=0.0.0.0

EXPOSE 3011

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:3011/api/health || exit 1

CMD ["node", ".output/server/index.mjs"]

