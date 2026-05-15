import { useRepo } from 'pinia-orm'
import BaseRepository from '~~/store/BaseRepository'
import Game from '~~/store/models/Game'
import Draw from '~~/store/models/Draw'
import TipSet from '~~/store/models/TipSet'
import { dreamFetch } from '~/composables/useApi'

interface LottoStatus {
  games: Array<{
    id: string
    name: string
    pool: string
    days: string
    n_history: number
    n_tips: number
    last_draw_at: string | null
    next_expected_draw: string | null
  }>
}

interface RefreshResult {
  fetched: number
  saved: number
  errors: string[]
}

interface GenerateTipsParams {
  game_id: string
  recency_k?: number
  rows_per_strategy?: number
}

/**
 * GameRepository — Wrapper um die lotto-oracle Endpunkte.
 *
 * Spielt zwei Rollen:
 *   1. Lotto-Stammdaten: Game/Draw/TipSet im ORM-Store halten
 *   2. Strategie-Calls (sweet-spot, /tips/generate, /refresh)
 */
export default class GameRepository extends BaseRepository<Game> {
  use = Game

  api() {
    return {
      async fetchStatus() {
        const data = await dreamFetch<LottoStatus>('/api/lotto/status')
        if (data.games) {
          useRepo(Game).fresh(data.games.map(g => ({
            id: g.id,
            name: g.name,
            pool: g.pool,
            days: g.days,
          })))
        }
        return data
      },

      async fetchGames() {
        const data = await dreamFetch<{ items: Game[] }>('/api/lotto/games')
        if (data.items) {
          useRepo(Game).fresh(data.items)
        }
        return data
      },

      async fetchDraws(gameId: string, limit = 50) {
        const data = await dreamFetch<{ items: Draw[] }>(
          `/api/lotto/games/${gameId}/draws?limit=${limit}`,
        )
        if (data.items) {
          useRepo(Draw).save(
            data.items.map(d => ({ ...d, game_id: gameId })),
          )
        }
        return data
      },

      async fetchTipSets(gameId: string) {
        const data = await dreamFetch<{ items: TipSet[] }>(
          `/api/lotto/games/${gameId}/tipsets`,
        )
        if (data.items) {
          useRepo(TipSet).save(
            data.items.map(t => ({ ...t, game_id: gameId })),
          )
        }
        return data
      },

      async refresh(gameId?: string): Promise<RefreshResult> {
        const path = gameId ? `/api/lotto/refresh?game_id=${gameId}` : '/api/lotto/refresh'
        return await dreamFetch<RefreshResult>(path, { method: 'POST' })
      },

      async refreshFull(): Promise<RefreshResult> {
        return await dreamFetch<RefreshResult>('/api/lotto/refresh/full', { method: 'POST' })
      },

      async generateTips(params: GenerateTipsParams) {
        const data = await dreamFetch<{ items: TipSet[] }>('/api/lotto/tips/generate', {
          method: 'POST',
          body: params,
        })
        if (data.items) {
          useRepo(TipSet).save(
            data.items.map(t => ({ ...t, game_id: params.game_id })),
          )
        }
        return data
      },

      async sweetSpot(gameId: string) {
        return await dreamFetch<{
          recommended_k: number
          per_k: Array<{ k: number, mean_match: number }>
        }>(`/api/lotto/games/${gameId}/sweet-spot`)
      },
    }
  }
}

