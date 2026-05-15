// Composable für /api/repo-map/* (Welle B.3 — Repo-zu-Projekt Mapping
// für den GitHub-Issue-zu-Vikunja-Task-n8n-Workflow).
import { ref, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import type { RepoMap, RepoMapEntry } from '~/types/api'

const map: Ref<RepoMap> = ref({ default_project_id: null, mappings: [] })
const loading = ref(true)
const error: Ref<string | null> = ref(null)

let started = false

export function useRepoMap() {
  const api = useApi()

  async function refresh() {
    loading.value = true
    try {
      map.value = await api.get<RepoMap>('/api/repo-map')
      error.value = null
    }
    catch (err: unknown) {
      error.value = (err as Error).message
    }
    finally {
      loading.value = false
    }
  }

  async function addMapping(repo: string, projectId: number | string) {
    await api.post('/api/repo-map', { repo, project_id: projectId })
    await refresh()
  }

  async function deleteMapping(repo: string) {
    await api.delete(`/api/repo-map/${encodeURIComponent(repo)}`)
    await refresh()
  }

  async function setDefaultProject(projectId: number | string | null) {
    // PUT erwartet das ganze Replacement-Set. Wir senden die aktuellen
    // Mappings unverändert mit, damit nur default_project_id mutiert.
    const payload = {
      default_project_id: projectId,
      mappings: map.value.mappings.map((m: RepoMapEntry) => ({
        repo: m.repo,
        project_id: m.project_id,
        ...(m.label ? { label: m.label } : {}),
      })),
    }
    await api.put('/api/repo-map', payload)
    await refresh()
  }

  if (!started) {
    started = true
    refresh()
  }

  return { map, loading, error, refresh, addMapping, deleteMapping, setDefaultProject }
}

export const REPO_RE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/

