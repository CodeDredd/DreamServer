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

# Non-root.
RUN addgroup -g 1000 dreamer && \
    adduser -D -u 1000 -G dreamer dreamer

COPY --from=builder --chown=dreamer:dreamer /app/.output ./.output

USER dreamer

ENV NODE_ENV=production \
    NITRO_PORT=3011 \
    NITRO_HOST=0.0.0.0

EXPOSE 3011

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://127.0.0.1:3011/api/health || exit 1

CMD ["node", ".output/server/index.mjs"]

