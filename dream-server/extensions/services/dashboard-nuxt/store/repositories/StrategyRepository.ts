import { useRepo } from 'pinia-orm'
import BaseRepository from '~~/store/BaseRepository'
import Strategy from '~~/store/models/Strategy'
import Position from '~~/store/models/Position'
import Trade from '~~/store/models/Trade'
import { dreamFetch } from '~/composables/useApi'

interface DecideResult {
  strategy_id: string
  action: 'buy' | 'sell' | 'hold'
  reason: string
}

interface BacktestResult {
  strategy_id: string
  trades: Array<{ symbol: string, pnl: number, executed_at: string }>
  cagr: number
  sharpe: number
  max_drawdown: number
}

/**
 * StrategyRepository — Wrapper um die finance-guru-api Endpunkte.
 *
 * Pattern (vom Referenz-Projekt):
 *   const repo = useRepo(StrategyRepository)
 *   await repo.api().fetchAll()
 *   const all = repo.with('positions').with('trades').all()
 *   const winner = repo.where('id', strategyId).first()
 */
export default class StrategyRepository extends BaseRepository<Strategy> {
  use = Strategy

  api() {
    return {
      async fetchAll() {
        const data = await dreamFetch<{ strategies: Strategy[] }>('/api/finance-guru/strategies')
        if (data.strategies) {
          useRepo(Strategy).fresh(data.strategies)
        }
        return data
      },

      async fetchStatus() {
        const data = await dreamFetch<{
          strategies: Strategy[]
          positions: Position[]
          trades: Trade[]
        }>('/api/finance-guru/status')

        if (data.strategies) useRepo(Strategy).fresh(data.strategies)
        if (data.positions) useRepo(Position).fresh(data.positions)
        if (data.trades) useRepo(Trade).fresh(data.trades)
        return data
      },

      async decide(strategyId?: string): Promise<DecideResult[]> {
        return await dreamFetch<DecideResult[]>('/api/finance-guru/decide', {
          method: 'POST',
          body: strategyId ? { strategy_id: strategyId } : undefined,
        })
      },

      async backtest(strategyId: string, params: { from: string, to: string }): Promise<BacktestResult> {
        return await dreamFetch<BacktestResult>('/api/finance-guru/backtest', {
          method: 'POST',
          body: { strategy_id: strategyId, ...params },
        })
      },
    }
  }
}

