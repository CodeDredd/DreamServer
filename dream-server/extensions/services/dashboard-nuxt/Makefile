# See ../../../docs/DASHBOARD-NUXT-MIGRATION.md
.PHONY: help install dev build typecheck lint test

help:
	@echo "Targets (require Node 24 + pnpm 10):"
	@echo "  install    pnpm install"
	@echo "  dev        Nuxt dev-server (Port 3011)"
	@echo "  build      Production build (.output/)"
	@echo "  typecheck  vue-tsc"
	@echo "  lint       eslint"
	@echo "  test       vitest"

install:
	pnpm install

dev:
	pnpm run dev

build:
	pnpm run build

typecheck:
	pnpm run typecheck

lint:
	pnpm run lint

test:
	pnpm run test

