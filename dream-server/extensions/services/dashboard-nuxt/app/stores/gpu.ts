// /api/gpu/{detailed,history,topology} — alle 5 s parallel polled.

import { defineStore } from 'pinia'
import { useApi } from '~/composables/useApi'
import type { GpuDetailed, GpuHistory, GpuTopology } from '~/types/api'

interface GpuState {
  detailed: GpuDetailed | null
  history: GpuHistory | null
  topology: GpuTopology | null
  loading: boolean
  error: string | null
}

export const useGpuStore = defineStore('gpu', {
  state: (): GpuState => ({
    detailed: null,
    history: null,
    topology: null,
    loading: true,
    error: null,
  }),

  actions: {
    async fetchAll() {
      const api = useApi()
      try {
        const [detailed, history, topology] = await Promise.allSettled([
          api.get<GpuDetailed>('/api/gpu/detailed'),
          api.get<GpuHistory>('/api/gpu/history'),
          api.get<GpuTopology>('/api/gpu/topology'),
        ])
        if (detailed.status === 'fulfilled') this.detailed = detailed.value
        if (history.status === 'fulfilled') this.history = history.value
        if (topology.status === 'fulfilled') this.topology = topology.value
        this.error = null
      }
      catch (err: unknown) {
        this.error = (err as Error).message
      }
      finally {
        this.loading = false
      }
    },
  },
})

