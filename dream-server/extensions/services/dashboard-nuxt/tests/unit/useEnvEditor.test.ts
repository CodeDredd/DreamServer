/**
 * Unit-Tests fuer app/composables/useEnvEditor.ts (Phase 6, Welle A.5).
 *
 * Strategie:
 * - useApi via vi.mock() ersetzen, sodass get/put/post pro Test definierbar sind.
 * - State-Transitionen pruefen: initial -> refresh() -> save() -> apply().
 * - Computed-Properties (dirty, issueMap, canApply) bei verschiedenen
 *   Payload-Konstellationen.
 *
 * Begruendung Modul-State: useEnvEditor cached intern via Modul-Refs.
 * Wir importieren das Modul fresh per `vi.resetModules()` zwischen Tests,
 * damit kein State leakt.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// Module-Mock fuer useApi - jede Test-Suite kann die Mocks via
// `mockApi.get.mockResolvedValueOnce(...)` ueberschreiben.
const mockApi = {
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  raw: vi.fn(),
}

vi.mock('~/composables/useApi', () => ({
  useApi: () => mockApi,
  dreamFetch: vi.fn(),
}))

// Beispiel-Payload, der dem Backend-Format entspricht (siehe types/api.ts).
function makePayload(overrides: Record<string, unknown> = {}) {
  return {
    path: '/etc/dream/.env',
    saveHint: 'Save writes to .env',
    restartHint: 'Restart needed',
    agentAvailable: true,
    backupPath: '/etc/dream/.env.bak',
    sections: [
      { id: 'core', label: 'Core' },
      { id: 'auth', label: 'Auth' },
    ],
    fields: [
      { key: 'PORT', section: 'core', label: 'Port', type: 'integer' as const },
      { key: 'DEBUG', section: 'core', label: 'Debug', type: 'boolean' as const },
      { key: 'JWT_SECRET', section: 'auth', label: 'JWT Secret', type: 'string' as const, secret: true },
    ],
    values: { PORT: '8080', DEBUG: 'false', JWT_SECRET: 'top-secret' },
    issues: [],
    applyPlan: { supported: true, status: 'none' as const, services: [] },
    ...overrides,
  }
}

describe('useEnvEditor', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.values(mockApi).forEach(fn => fn.mockReset())
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('seedet values + original aus refresh()-Payload', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload())
    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()

    await editor.refresh()

    expect(editor.values.value.PORT).toBe('8080')
    expect(editor.original.value.PORT).toBe('8080')
    expect(editor.dirty.value).toBe(false)
    expect(mockApi.get).toHaveBeenCalledWith('/api/settings/env')
  })

  it('dirty=true sobald sich values von original unterscheiden', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload())
    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()

    editor.values.value.PORT = '9090'

    expect(editor.dirty.value).toBe(true)
  })

  it('canApply nur bei plan.supported && services.length > 0 && agentAvailable !== false', async () => {
    // Fall 1: applyPlan.supported=true, aber keine services
    mockApi.get.mockResolvedValueOnce(makePayload({
      applyPlan: { supported: true, status: 'pending', services: [] },
    }))
    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()
    expect(editor.canApply.value).toBe(false)
  })

  it('canApply=true bei kompletter Plan-Constraint-Erfuellung', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload({
      applyPlan: { supported: true, status: 'pending', services: ['svc-a', 'svc-b'] },
      agentAvailable: true,
    }))
    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()
    expect(editor.canApply.value).toBe(true)
  })

  it('issueMap aggregiert Validation-Issues nach key', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload({
      issues: [
        { key: 'PORT', message: 'Must be 1-65535' },
        { key: 'PORT', message: 'Already in use' },
        { key: 'JWT_SECRET', message: 'Too short' },
      ],
    }))
    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()
    expect(editor.issueMap.value.PORT).toEqual(['Must be 1-65535', 'Already in use'])
    expect(editor.issueMap.value.JWT_SECRET).toEqual(['Too short'])
    expect(Object.keys(editor.issueMap.value).length).toBe(2)
  })
  it('save() PUTtet { mode, values } und seedet Payload neu', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload())
    // save() ruft applyPayload(payload) — payload IST der EnvSaveResponse direkt.
    mockApi.put.mockResolvedValueOnce(makePayload({ values: { PORT: '7000', DEBUG: 'false', JWT_SECRET: 'top-secret' } }))

    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()
    editor.values.value.PORT = '7000'
    await editor.save()

    expect(mockApi.put).toHaveBeenCalledWith(
      '/api/settings/env',
      expect.objectContaining({ mode: 'form', values: expect.objectContaining({ PORT: '7000' }) }),
    )
    expect(editor.values.value.PORT).toBe('7000')
    expect(editor.original.value.PORT).toBe('7000')
    expect(editor.dirty.value).toBe(false)
  })

  it('apply() POSTtet service_ids aus dem Plan', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload({
      applyPlan: { supported: true, status: 'pending', services: ['llama', 'voice'] },
    }))
    mockApi.post.mockResolvedValueOnce({ ok: true })

    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()
    await editor.apply()

    expect(mockApi.post).toHaveBeenCalledWith('/api/settings/env/apply', { service_ids: ['llama', 'voice'] })
  })

  it('filteredSections respektiert search (key/label/description match)', async () => {
    mockApi.get.mockResolvedValueOnce(makePayload({
      sections: [
        { id: 'core', title: 'Core', keys: ['PORT'] },
        { id: 'auth', title: 'Auth', keys: ['JWT_SECRET', 'OAUTH_PROVIDER'] },
      ],
      fields: {
        PORT: { key: 'PORT', label: 'Port', type: 'integer' as const },
        JWT_SECRET: { key: 'JWT_SECRET', label: 'JWT Secret', type: 'string' as const, secret: true },
        OAUTH_PROVIDER: { key: 'OAUTH_PROVIDER', label: 'OAuth provider', description: 'github/google/...', type: 'string' as const },
      },
    }))
    const { useEnvEditor } = await import('~/composables/useEnvEditor')
    const editor = useEnvEditor()
    await editor.refresh()

    editor.search.value = 'jwt'
    // Nur die auth-section sollte das Feld enthalten
    const filtered = editor.filteredSections.value
    const authSection = filtered.find(s => s.id === 'auth')
    expect(authSection).toBeDefined()
    expect(authSection?.keys).toContain('JWT_SECRET')
    // Core wurde herausgefiltert (kein Match)
    expect(filtered.find(s => s.id === 'core')).toBeUndefined()
  })
})

