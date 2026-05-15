// Composable für /api/auth/magic-link/* (Welle B.2 — Invites).
// Tokens werden zentral gehalten, Mutationen rufen `refresh()` selbst.
import { ref, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import type {
  GeneratedMagicLink,
  InviteScope,
  MagicLinkListResponse,
  MagicLinkQrResponse,
  MagicLinkToken,
} from '~/types/api'

const tokens: Ref<MagicLinkToken[]> = ref([])
const loading = ref(true)
const refreshing = ref(false)
const error: Ref<string | null> = ref(null)

let started = false

export interface GenerateInvitePayload {
  target_username: string
  scope: InviteScope
  expires_in: number
  reusable: boolean
  note?: string | null
}

export function useInvites() {
  const api = useApi()

  async function refresh() {
    refreshing.value = true
    try {
      const data = await api.get<MagicLinkListResponse>('/api/auth/magic-link/list')
      tokens.value = data.tokens ?? []
      error.value = null
    }
    catch (err: unknown) {
      error.value = (err as Error).message
    }
    finally {
      loading.value = false
      refreshing.value = false
    }
  }

  async function generate(payload: GenerateInvitePayload): Promise<GeneratedMagicLink> {
    const out = await api.post<GeneratedMagicLink>(
      '/api/auth/magic-link/generate',
      payload,
    )
    refresh()
    return out
  }

  async function revoke(prefix: string) {
    try {
      await api.delete(`/api/auth/magic-link/${prefix}`)
    }
    catch (err: unknown) {
      const e = err as { status?: number }
      if (e.status !== 404) throw err
    }
    await refresh()
  }

  async function fetchQr(url: string): Promise<string | null> {
    try {
      const out = await api.get<MagicLinkQrResponse>(
        `/api/auth/magic-link/qr?url=${encodeURIComponent(url)}`,
      )
      return out.data_url
    }
    catch {
      return null
    }
  }

  if (!started) {
    started = true
    refresh()
  }

  return { tokens, loading, refreshing, error, refresh, generate, revoke, fetchQr }
}

export function tokenStatusBadge(token: MagicLinkToken): {
  label: string
  color: 'success' | 'neutral' | 'info' | 'warning'
} {
  if (token.revoked_at) return { label: 'revoked', color: 'neutral' }
  if (new Date(token.expires_at).getTime() < Date.now()) {
    return { label: 'expired', color: 'neutral' }
  }
  if (token.redemption_count > 0 && !token.reusable) {
    return { label: 'used', color: 'neutral' }
  }
  if (token.redemption_count > 0) {
    return { label: `reused ×${token.redemption_count}`, color: 'info' }
  }
  return { label: 'active', color: 'success' }
}

export function formatRelative(iso: string | null | undefined): string | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  const diff = t - Date.now()
  const abs = Math.abs(diff)
  const minutes = Math.round(abs / 60_000)
  const hours = Math.round(abs / 3_600_000)
  const future = diff > 0
  if (minutes < 1) return future ? 'in seconds' : 'just now'
  if (minutes < 60) return future ? `in ${minutes}m` : `${minutes}m ago`
  if (hours < 24) return future ? `in ${hours}h` : `${hours}h ago`
  const days = Math.round(abs / 86_400_000)
  return future ? `in ${days}d` : `${days}d ago`
}

