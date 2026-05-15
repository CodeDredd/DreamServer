import type { Model } from 'pinia-orm'
import { Repository } from 'pinia-orm'

/**
 * Gemeinsame Basisklasse fuer alle Repositories.
 *
 * Pattern (1:1 vom Referenz-Projekt):
 *
 *   class StrategyRepository extends BaseRepository<Strategy> {
 *     use = Strategy
 *
 *     api() {
 *       return {
 *         get: async () => {
 *           const data = await dreamFetch('/api/finance-guru/strategies')
 *           useRepo(Strategy).save(data)
 *           return data
 *         },
 *         decide: async (id: string) => { … },
 *       }
 *     }
 *   }
 *
 * Aufruf in Pages/Composables:
 *
 *   const repo = useRepo(StrategyRepository)
 *   await repo.api().get()
 *   const strategies = repo.with('positions').all()
 */
export default class BaseRepository<M extends Model = Model> extends Repository<M> {}

