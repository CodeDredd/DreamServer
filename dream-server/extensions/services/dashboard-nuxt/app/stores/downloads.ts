// /api/models/download-status — adaptives Polling: 1 s während aktiv,
// 10 s im Idle. Spiegelt 1:1 die React-Variante in
// `dashboard/src/hooks/useDownloadProgress.js`.

import { defineStore } from 'pinia'
import { useApi } from '~/composables/useApi'
import type { DownloadProgressRaw, DownloadProgressView } from '~/types/api'

interface DownloadsState {
  isDownloading: boolean
  progress: DownloadProgressView | null
  error: string | null
}

export const useDownloadsStore = defineStore('downloads', {
  state: (): DownloadsState => ({
    isDownloading: false,
    progress: null,
    error: null,
  }),

  actions: {
    async refresh() {
      const api = useApi()
      try {
        const data = await api.get<DownloadProgressRaw>('/api/models/download-status')

        if (data.status === 'downloading' || data.status === 'verifying') {
          const downloaded = data.bytesDownloaded ?? 0
          const total = data.bytesTotal ?? 0
          const percent = total > 0 ? (downloaded / total) * 100 : 0
          this.isDownloading = true
          this.progress = {
            model: data.model,
            status: data.status,
            percent,
            bytesDownloaded: downloaded,
            bytesTotal: total,
            speedMbps: data.speedBytesPerSec ? data.speedBytesPerSec / (1024 * 1024) : 0,
            eta: data.eta,
            startedAt: data.startedAt,
          }
        }
        else if (data.status === 'complete' || data.status === 'idle') {
          this.isDownloading = false
          this.progress = null
        }
        else if (
          data.status === 'failed'
          || data.status === 'error'
          || data.status === 'cancelled'
        ) {
          this.isDownloading = false
          this.progress = {
            status: data.status,
            model: data.model,
            percent: 0,
            bytesDownloaded: 0,
            bytesTotal: 0,
            speedMbps: 0,
            error: data.error
              ?? data.message
              ?? (data.status === 'cancelled' ? 'Download cancelled' : 'Download failed'),
          }
        }
        this.error = null
      }
      catch {
        // API kann während Restarts kurz weg sein — leise schlucken,
        // gleiches Verhalten wie React-Hook.
      }
    },

    async cancel() {
      const api = useApi()
      try {
        await api.post('/api/models/download/cancel')
        await this.refresh()
      }
      catch (err: unknown) {
        this.error = (err as Error).message
      }
    },
  },
})

// ---------- Format-Helper (von der React-Variante übernommen) -------------

export function formatBytes(bytes?: number): string {
  if (!bytes) return '0 B'
  const gb = bytes / (1024 ** 3)
  if (gb >= 1) return `${gb.toFixed(2)} GB`
  const mb = bytes / (1024 ** 2)
  if (mb >= 1) return `${mb.toFixed(1)} MB`
  return `${(bytes / 1024).toFixed(0)} KB`
}

export function formatEta(eta?: number | string): string {
  if (eta === undefined || eta === null || eta === 'calculating...') return 'calculating...'
  if (typeof eta === 'number') {
    const mins = Math.floor(eta / 60)
    const secs = eta % 60
    if (mins > 0) return `${mins}m ${secs}s`
    return `${secs}s`
  }
  return eta
}

