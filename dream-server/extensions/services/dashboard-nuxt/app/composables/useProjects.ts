// Composable für /api/projects/* (Vikunja Proxy). Wird ausschließlich
// von pages/projects.vue und pages/repo-map.vue genutzt — wir cachen
// daher die Project-Liste auf Modul-Ebene und hängen das Polling an die
// erste Verwendung.
import { ref, type Ref } from 'vue'
import { useApi } from '~/composables/useApi'
import type {
  VikunjaProject,
  VikunjaStatus,
  VikunjaTask,
} from '~/types/api'

const status: Ref<VikunjaStatus | null> = ref(null)
const projects: Ref<VikunjaProject[]> = ref([])
const loading = ref(false)
const error: Ref<string | null> = ref(null)

let started = false

export function useProjects() {
  const api = useApi()

  async function fetchStatus() {
    try {
      status.value = await api.get<VikunjaStatus>('/api/projects/status')
    }
    catch (err: unknown) {
      status.value = null
      error.value = (err as Error).message
    }
  }

  async function fetchProjects() {
    loading.value = true
    try {
      const data = await api.get<VikunjaProject[]>('/api/projects')
      projects.value = Array.isArray(data) ? data : []
      error.value = null
    }
    catch (err: unknown) {
      error.value = (err as Error).message
    }
    finally {
      loading.value = false
    }
  }

  async function fetchTasks(projectId: string | number): Promise<VikunjaTask[]> {
    try {
      const data = await api.get<VikunjaTask[]>(
        `/api/projects/${projectId}/tasks`,
      )
      return Array.isArray(data) ? data : []
    }
    catch {
      return []
    }
  }

  async function addTask(projectId: string | number, title: string) {
    return api.put(`/api/projects/${projectId}/tasks`, { title })
  }

  async function toggleTaskDone(task: VikunjaTask) {
    return api.post(`/api/projects/tasks/${task.id}`, { done: !task.done })
  }

  async function refresh() {
    await Promise.all([fetchStatus(), fetchProjects()])
  }

  if (!started) {
    started = true
    refresh()
  }

  return {
    status,
    projects,
    loading,
    error,
    fetchTasks,
    addTask,
    toggleTaskDone,
    refresh,
  }
}

