// /api/models — Liste + Lifecycle (download/load/delete). Lokale
// `actionLoading` ist pro modelId, damit die UI gleichzeitige Aktionen
// auf verschiedenen Karten unabhängig spinnen kann.
//
// Achtung: `loadModel` kann 20–60 s dauern und die Browser-Verbindung
// kann währenddessen droppen. Wir feuern den POST nicht-blockierend
// und pollen `/api/models` bis `currentModel === modelId` (oder
// Timeout 2:30 min) — exakt wie in der React-Variante.

import { defineStore } from 'pinia'
import { useApi } from '~/composables/useApi'
import type { ModelEntry, ModelsResponse } from '~/types/api'

interface ModelsState {
  models: ModelEntry[]
  gpu: ModelsResponse['gpu'] | null
  currentModel: string | null
  loading: boolean
  error: string | null
  actionLoading: string | null
  loadInFlight: boolean
}

export const useModelsStore = defineStore('models', {
  state: (): ModelsState => ({
    models: [],
    gpu: null,
    currentModel: null,
    loading: true,
    error: null,
    actionLoading: null,
    loadInFlight: false,
  }),

  actions: {
    async refresh() {
      const api = useApi()
      try {
        const data = await api.get<ModelsResponse>('/api/models')
        this.models = data.models
        this.gpu = data.gpu
        this.currentModel = data.currentModel
        this.error = null
      }
      catch (err: unknown) {
        this.error = (err as Error).message
      }
      finally {
        this.loading = false
      }
    },

    async download(modelId: string) {
      this.actionLoading = modelId
      const api = useApi()
      try {
        await api.post(`/api/models/${encodeURIComponent(modelId)}/download`)
        await this.refresh()
      }
      catch (err: unknown) {
        this.error = (err as Error).message
      }
      finally {
        this.actionLoading = null
      }
    },

    async load(modelId: string) {
      if (this.loadInFlight) return
      this.loadInFlight = true
      this.actionLoading = modelId
      this.error = null

      const api = useApi()
      let serverError: string | null = null

      // Fire-and-forget — connection often drops before backend completes.
      api.post(`/api/models/${encodeURIComponent(modelId)}/load`)
        .catch(async (err: unknown) => {
          const e = err as { data?: { detail?: string }, message?: string }
          const detail = e.data?.detail || e.message || ''
          if (/in progress|lock|already/i.test(detail)) return
          serverError = detail || 'Failed to load model'
        })

      // Poll until model loads, server error, or timeout (2:30 min).
      for (let i = 0; i < 30; i++) {
        await new Promise(r => setTimeout(r, 5000))
        if (serverError) {
          this.error = serverError
          break
        }
        try {
          const data = await api.get<ModelsResponse>('/api/models')
          if (data.currentModel === modelId) {
            this.models = data.models
            this.gpu = data.gpu
            this.currentModel = data.currentModel
            break
          }
        }
        catch { /* retry */ }
      }

      await this.refresh()
      this.actionLoading = null
      this.loadInFlight = false
    },

    async delete(modelId: string) {
      this.actionLoading = modelId
      const api = useApi()
      try {
        await api.delete(`/api/models/${encodeURIComponent(modelId)}`)
        await this.refresh()
      }
      catch (err: unknown) {
        this.error = (err as Error).message
      }
      finally {
        this.actionLoading = null
      }
    },
  },
})

