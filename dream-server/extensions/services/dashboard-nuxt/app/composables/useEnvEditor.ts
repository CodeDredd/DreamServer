// useEnvEditor — kapselt /api/settings/env fuer den Settings-Tab
// (Phase 4 Welle A.5). Pendant zur in-component-Logik in
// dashboard/src/pages/Settings.jsx (~Z. 73-228) sowie zum Sub-
// Component-State in EnvEditor.jsx.
//
// Modul-cached state (kein Polling — der Operator triggert manuell
// reload/save/apply). Mehrere Component-Mounts teilen denselben
// Stand, damit Settings + ggf. eine spaetere Sidebar-Anzeige nicht
// aus dem Sync laufen.

import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import type {
  EnvApplyPlan,
  EnvApplyResponse,
  EnvEditorPayload,
  EnvFieldDef,
  EnvSaveResponse,
  EnvSection,
  EnvValidationIssue,
} from '~/types/api'

const editor: Ref<EnvEditorPayload | null> = ref(null)
const values: Ref<Record<string, string>> = ref({})
const original: Ref<Record<string, string>> = ref({})
const issues: Ref<EnvValidationIssue[]> = ref([])
const applyPlan: Ref<EnvApplyPlan | null> = ref(null)
const revealed: Ref<Record<string, boolean>> = ref({})
const search = ref('')
const activeSectionId: Ref<string | null> = ref(null)

const loading = ref(false)
const saving = ref(false)
const applying = ref(false)
const error: Ref<string | null> = ref(null)
const notice: Ref<{ tone: 'info' | 'warn' | 'danger', text: string } | null> = ref(null)

function applyPayload(payload: EnvEditorPayload): void {
  editor.value = payload
  values.value = { ...(payload.values || {}) }
  original.value = { ...(payload.values || {}) }
  issues.value = payload.issues || []
  applyPlan.value = payload.applyPlan ?? null
  revealed.value = {}
  // Aktive Sektion behalten falls noch gueltig, sonst erste.
  const sections = payload.sections || []
  if (
    !activeSectionId.value
    || !sections.some(s => s.id === activeSectionId.value)
  ) {
    activeSectionId.value = sections[0]?.id ?? null
  }
}

export function useEnvEditor() {
  const api = useApi()

  async function refresh(opts: { announce?: boolean } = {}): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const data = await api.get<EnvEditorPayload>('/api/settings/env')
      applyPayload(data)
      if (opts.announce) {
        notice.value = { tone: 'info', text: 'Environment editor reloaded from disk.' }
      }
    }
    catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      error.value = msg
      if (opts.announce) {
        notice.value = { tone: 'danger', text: msg }
      }
    }
    finally {
      loading.value = false
    }
  }

  async function save(): Promise<void> {
    if (!editor.value) return
    saving.value = true
    notice.value = null
    try {
      const payload = await api.put<EnvSaveResponse>('/api/settings/env', {
        mode: 'form',
        values: values.value,
      })
      applyPayload(payload)
      const backup = payload.backupPath ? ` Backup: ${payload.backupPath}.` : ''
      const summary = payload.applyPlan?.summary
        || 'Restart or rebuild the stack to apply service-level changes.'
      notice.value = { tone: 'info', text: `.env saved.${backup} ${summary}` }
    }
    catch (e: unknown) {
      const err = e as { data?: { detail?: { issues?: EnvValidationIssue[], message?: string } } }
      if (err?.data?.detail?.issues?.length) {
        issues.value = err.data.detail.issues
      }
      const msg
        = err?.data?.detail?.message
        || (e instanceof Error ? e.message : String(e))
      notice.value = { tone: 'danger', text: msg }
    }
    finally {
      saving.value = false
    }
  }

  async function apply(): Promise<void> {
    const plan = applyPlan.value
    if (!plan?.supported || !plan.services?.length) return
    applying.value = true
    notice.value = null
    try {
      const payload = await api.post<EnvApplyResponse>('/api/settings/env/apply', {
        service_ids: plan.services,
      })
      applyPlan.value = null
      notice.value = {
        tone: 'info',
        text: payload.message || 'Runtime changes applied successfully.',
      }
    }
    catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      notice.value = { tone: 'danger', text: msg }
    }
    finally {
      applying.value = false
    }
  }

  function setFieldValue(key: string, value: string): void {
    values.value = { ...values.value, [key]: value }
  }
  function toggleReveal(key: string): void {
    revealed.value = { ...revealed.value, [key]: !revealed.value[key] }
  }
  function dismissNotice(): void {
    notice.value = null
  }

  // ---------- computed ----------
  const fields: ComputedRef<Record<string, EnvFieldDef>> = computed(
    () => editor.value?.fields || {},
  )

  const filteredSections: ComputedRef<EnvSection[]> = computed(() => {
    const query = search.value.trim().toLowerCase()
    const all = editor.value?.sections || []
    if (!query) return all
    return all
      .map(section => ({
        ...section,
        keys: section.keys.filter((key) => {
          const f = fields.value[key]
          const haystack = [key, f?.label, f?.description]
            .filter(Boolean)
            .join(' ')
            .toLowerCase()
          return haystack.includes(query)
        }),
      }))
      .filter(section => section.keys.length > 0)
  })

  const activeSection: ComputedRef<EnvSection | null> = computed(() => {
    const list = filteredSections.value
    if (!list.length) return null
    return list.find(s => s.id === activeSectionId.value) ?? list[0] ?? null
  })

  const dirty: ComputedRef<boolean> = computed(
    () => JSON.stringify(values.value) !== JSON.stringify(original.value),
  )

  const issueMap: ComputedRef<Record<string, string[]>> = computed(() => {
    const acc: Record<string, string[]> = {}
    for (const issue of issues.value) {
      if (!issue.key) continue
      if (!acc[issue.key]) acc[issue.key] = []
      acc[issue.key].push(issue.message)
    }
    return acc
  })

  const canApply: ComputedRef<boolean> = computed(() => {
    const plan = applyPlan.value
    return Boolean(
      plan?.supported
      && (plan?.services?.length ?? 0) > 0
      && editor.value?.agentAvailable !== false,
    )
  })

  return {
    // state
    editor,
    values,
    original,
    issues,
    applyPlan,
    revealed,
    search,
    activeSectionId,
    loading,
    saving,
    applying,
    error,
    notice,
    // actions
    refresh,
    save,
    apply,
    setFieldValue,
    toggleReveal,
    dismissNotice,
    // computed
    fields,
    filteredSections,
    activeSection,
    dirty,
    issueMap,
    canApply,
  }
}

