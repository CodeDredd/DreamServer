# Dream Server Dashboard NG (Nuxt)
# Multi-stage build: Nuxt 4 SPA → Node runtime
#
# WICHTIG: Bis Phase 1 des Migrationsplans abgeschlossen ist, ist das
# Image NICHT lauffähig — `package.json` + `nuxt.config.ts` werden in
# Phase 1 hinzugefügt. Bauen erst danach (siehe ../../../docs/DASHBOARD-NUXT-MIGRATION.md).

# ---------- Stage 1: Build ----------
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

# ---------- Stage 2: Runtime ----------
FROM node:20-alpine

WORKDIR /app

# Non-root
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

