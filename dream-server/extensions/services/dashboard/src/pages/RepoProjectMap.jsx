/**
 * Repo → Project Map Page
 *
 * UI for the dashboard-api `/api/repo-map/*` endpoints. Lets the user
 * map GitHub `owner/repo` → Vikunja project id, plus pick a default
 * fallback project. Consumed at runtime by the n8n
 * "GitHub Issue → Vikunja Task" workflow via /api/repo-map/lookup.
 *
 * Auth: nginx injects Authorization: Bearer for /api/* requests.
 */

import {
  GitBranch,
  Loader2,
  AlertCircle,
  CheckCircle,
  Plus,
  RefreshCw,
  Trash2,
  Save,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

const REPO_RE = /^[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/

function ProjectSelect({ projects, value, onChange, disabled }) {
  return (
    <select
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      disabled={disabled}
      className="bg-theme-card border border-theme-border rounded-lg px-2 py-1.5 text-sm text-theme-text disabled:opacity-50 min-w-[180px]"
    >
      <option value="">— select project —</option>
      {projects.map((p) => (
        <option key={p.id} value={p.id}>
          {p.title || `Project #${p.id}`} (#{p.id})
        </option>
      ))}
    </select>
  )
}

function MappingRow({ entry, projects, onDelete, busy }) {
  const project = projects.find((p) => p.id === entry.project_id)
  return (
    <tr className="border-b border-theme-border last:border-b-0">
      <td className="px-4 py-3 text-sm text-theme-text font-mono">{entry.repo}</td>
      <td className="px-4 py-3 text-sm text-theme-text">
        {project ? (
          <span>
            {project.title}
            <span className="text-theme-text-muted ml-1">(#{entry.project_id})</span>
          </span>
        ) : (
          <span className="text-yellow-400">Project #{entry.project_id} (not found)</span>
        )}
      </td>
      <td className="px-4 py-3 text-xs text-theme-text-muted">
        {entry.updated_at ? new Date(entry.updated_at).toLocaleString() : '—'}
      </td>
      <td className="px-4 py-3 text-right">
        <button
          onClick={() => onDelete(entry.repo)}
          disabled={busy}
          className="text-red-400 hover:text-red-300 disabled:opacity-50 transition-colors"
          title="Delete mapping"
        >
          <Trash2 size={16} />
        </button>
      </td>
    </tr>
  )
}

function AddMappingForm({ projects, existingRepos, onAdded, disabled }) {
  const [repo, setRepo] = useState('')
  const [projectId, setProjectId] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const repoValid = REPO_RE.test(repo.trim())
  const isDuplicate = existingRepos.includes(repo.trim().toLowerCase())
  const canSubmit = repoValid && !isDuplicate && projectId && !disabled && !busy

  const submit = async (e) => {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    setErr(null)
    const res = await fetch('/api/repo-map', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo: repo.trim(), project_id: projectId }),
    })
    setBusy(false)
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      setErr(payload.detail || `Failed (HTTP ${res.status})`)
      return
    }
    setRepo('')
    setProjectId(null)
    onAdded()
  }

  return (
    <form onSubmit={submit} className="p-4 border-t border-theme-border bg-theme-surface-hover/30">
      <div className="flex gap-2 items-start flex-wrap">
        <div className="flex-1 min-w-[240px]">
          <input
            type="text"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            placeholder="owner/repo (e.g. CodeDredd/DreamServer)"
            disabled={disabled || busy}
            className="w-full bg-theme-card border border-theme-border rounded-lg px-3 py-2 text-sm text-theme-text font-mono disabled:opacity-50"
          />
          {repo && !repoValid ? (
            <p className="text-xs text-red-400 mt-1">Must look like &quot;owner/name&quot;.</p>
          ) : null}
          {repo && repoValid && isDuplicate ? (
            <p className="text-xs text-yellow-400 mt-1">Mapping already exists — delete it first to re-add.</p>
          ) : null}
        </div>
        <ProjectSelect projects={projects} value={projectId} onChange={setProjectId} disabled={disabled || busy} />
        <button
          type="submit"
          disabled={!canSubmit}
          className="px-4 py-2 bg-theme-accent hover:bg-theme-accent-hover disabled:opacity-50 text-white rounded-lg text-sm flex items-center gap-1"
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
          Add mapping
        </button>
      </div>
      {err ? <p className="text-xs text-red-400 mt-2">{String(err)}</p> : null}
    </form>
  )
}

function DefaultProjectCard({ projects, defaultId, mappings, onSave, disabled }) {
  const [draft, setDraft] = useState(defaultId)
  const [busy, setBusy] = useState(false)
  const [savedAt, setSavedAt] = useState(null)
  const [err, setErr] = useState(null)

  useEffect(() => {
    setDraft(defaultId)
  }, [defaultId])

  const dirty = draft !== defaultId

  const save = async () => {
    setBusy(true)
    setErr(null)
    // PUT replaces the whole map — re-send the current mappings unchanged
    // so we only mutate `default_project_id`.
    const payload = {
      default_project_id: draft,
      mappings: mappings.map(({ repo, project_id, label }) => ({
        repo,
        project_id,
        ...(label ? { label } : {}),
      })),
    }
    const res = await fetch('/api/repo-map', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    setBusy(false)
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      setErr(payload.detail || `Failed (HTTP ${res.status})`)
      return
    }
    setSavedAt(Date.now())
    onSave()
  }

  return (
    <div className="p-4 bg-theme-card border border-theme-border rounded-xl">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-sm font-medium text-theme-text">Default project (fallback)</h3>
          <p className="text-xs text-theme-text-muted mt-1">
            Used by the n8n workflow when a GitHub repo has no explicit mapping.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ProjectSelect projects={projects} value={draft} onChange={setDraft} disabled={disabled || busy} />
          <button
            onClick={save}
            disabled={!dirty || busy || disabled}
            className="px-3 py-1.5 bg-theme-accent hover:bg-theme-accent-hover disabled:opacity-50 text-white rounded-lg text-sm flex items-center gap-1"
          >
            {busy ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            Save
          </button>
        </div>
      </div>
      {err ? <p className="text-xs text-red-400 mt-2">{String(err)}</p> : null}
      {savedAt && !err ? <p className="text-xs text-green-400 mt-2">Saved.</p> : null}
    </div>
  )
}

export default function RepoProjectMap() {
  const [vikunjaStatus, setVikunjaStatus] = useState(null)
  const [projects, setProjects] = useState([])
  const [map, setMap] = useState({ default_project_id: null, mappings: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [busyRepo, setBusyRepo] = useState(null)

  const fetchStatus = useCallback(async () => {
    const res = await fetch('/api/projects/status')
    if (res.ok) setVikunjaStatus(await res.json())
  }, [])

  const fetchProjects = useCallback(async () => {
    const res = await fetch('/api/projects')
    if (res.ok) {
      const data = await res.json()
      setProjects(Array.isArray(data) ? data : [])
    }
  }, [])

  const fetchMap = useCallback(async () => {
    const res = await fetch('/api/repo-map')
    if (!res.ok) {
      setError(`Failed to load repo map (HTTP ${res.status})`)
      return
    }
    setMap(await res.json())
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    await Promise.all([fetchStatus(), fetchProjects(), fetchMap()])
    setLoading(false)
  }, [fetchStatus, fetchProjects, fetchMap])

  useEffect(() => {
    refresh()
  }, [refresh])

  const deleteMapping = async (repo) => {
    if (!confirm(`Delete mapping for ${repo}?`)) return
    setBusyRepo(repo)
    const res = await fetch(`/api/repo-map/${encodeURIComponent(repo)}`, { method: 'DELETE' })
    setBusyRepo(null)
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      setError(payload.detail || `Delete failed (HTTP ${res.status})`)
      return
    }
    fetchMap()
  }

  const existingRepos = useMemo(
    () => map.mappings.map((m) => (m.repo || '').toLowerCase()),
    [map.mappings],
  )

  const vikunjaReady = vikunjaStatus?.available && vikunjaStatus?.configured

  return (
    <div className="h-full flex flex-col overflow-y-auto">
      {/* Header */}
      <div className="p-6 border-b border-theme-border">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <GitBranch size={24} className="text-theme-accent" />
            <div>
              <h1 className="text-2xl font-bold text-theme-text">Repo → Project Map</h1>
              <p className="text-theme-text-muted mt-1 text-sm">
                Tell the GitHub → Vikunja n8n workflow which Vikunja project receives issues from each repo.
              </p>
            </div>
          </div>
          <button
            onClick={refresh}
            className="text-theme-text-muted hover:text-theme-text transition-colors"
            title="Refresh"
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </div>

      <div className="p-6 space-y-6">
        {/* Vikunja status */}
        {vikunjaStatus && !vikunjaReady ? (
          <div className="p-4 bg-yellow-500/10 border border-yellow-500/30 rounded-xl flex items-start gap-3">
            <AlertCircle size={18} className="text-yellow-400 shrink-0 mt-0.5" />
            <div className="text-sm text-yellow-400">
              <p className="font-medium">Vikunja is not ready</p>
              <p className="text-xs text-theme-text-muted mt-1">
                {vikunjaStatus.message || 'Vikunja must be reachable so we can list projects to map against.'}
              </p>
            </div>
          </div>
        ) : null}

        {vikunjaReady ? (
          <div className="p-3 bg-green-500/10 border border-green-500/30 rounded-xl flex items-center gap-3">
            <CheckCircle size={16} className="text-green-400" />
            <span className="text-sm text-green-400">
              Vikunja ready — {projects.length} project{projects.length === 1 ? '' : 's'} available.
            </span>
          </div>
        ) : null}

        {error ? (
          <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl flex items-start gap-3">
            <AlertCircle size={18} className="text-red-400 shrink-0 mt-0.5" />
            <p className="text-sm text-red-400">{String(error)}</p>
          </div>
        ) : null}

        {/* Default project */}
        <DefaultProjectCard
          projects={projects}
          defaultId={map.default_project_id}
          mappings={map.mappings}
          onSave={fetchMap}
          disabled={!vikunjaReady}
        />

        {/* Mappings table */}
        <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-theme-border flex items-center justify-between">
            <div>
              <h2 className="text-sm font-medium text-theme-text">Repository mappings</h2>
              <p className="text-xs text-theme-text-muted mt-0.5">
                {map.mappings.length} mapping{map.mappings.length === 1 ? '' : 's'} configured.
              </p>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 p-6 text-sm text-theme-text-muted">
              <Loader2 size={14} className="animate-spin" /> Loading…
            </div>
          ) : map.mappings.length === 0 ? (
            <div className="p-6 text-sm text-theme-text-muted">
              No mappings yet. Add one below — issues from unmapped repos fall back to the default project.
            </div>
          ) : (
            <table className="w-full">
              <thead>
                <tr className="bg-theme-surface-hover/40 border-b border-theme-border">
                  <th className="px-4 py-2 text-left text-xs uppercase tracking-wider text-theme-text-muted">
                    Repository
                  </th>
                  <th className="px-4 py-2 text-left text-xs uppercase tracking-wider text-theme-text-muted">
                    Vikunja project
                  </th>
                  <th className="px-4 py-2 text-left text-xs uppercase tracking-wider text-theme-text-muted">
                    Updated
                  </th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {map.mappings.map((entry) => (
                  <MappingRow
                    key={entry.repo}
                    entry={entry}
                    projects={projects}
                    onDelete={deleteMapping}
                    busy={busyRepo === entry.repo}
                  />
                ))}
              </tbody>
            </table>
          )}

          <AddMappingForm
            projects={projects}
            existingRepos={existingRepos}
            onAdded={fetchMap}
            disabled={!vikunjaReady}
          />
        </div>

        {/* Hint */}
        <div className="text-xs text-theme-text-muted leading-relaxed">
          The n8n workflow <code className="text-theme-text-secondary">GitHub Issue → Vikunja Task</code> calls{' '}
          <code className="text-theme-text-secondary">GET /api/repo-map/lookup?repo=&lt;owner/name&gt;</code> on every
          incoming GitHub webhook. Make sure the n8n container has{' '}
          <code className="text-theme-text-secondary">DASHBOARD_API_KEY</code> and{' '}
          <code className="text-theme-text-secondary">DASHBOARD_API_URL</code> in its environment.
        </div>
      </div>
    </div>
  )
}

