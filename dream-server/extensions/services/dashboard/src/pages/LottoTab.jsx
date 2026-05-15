import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Ticket, RefreshCw, Loader2, Play, Database, AlertCircle,
  Calendar, Clock, Sparkles, Copy, Check, Info, TrendingUp, BarChart3,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Lotto Oracle — second tab inside the Finance Guru page.
//
// Talks to /api/lotto/* on dashboard-api which proxies the lotto-oracle
// service. Handles all four supported games (lotto-6aus49, eurojackpot,
// spiel77, super6) — game type drives whether we render number balls or
// digit strings.
// See AGENT-OPERATIONS.md §13.
// ---------------------------------------------------------------------------

const POLL_MS = 60_000

function relTime(ts) {
  if (!ts) return '—'
  const t = new Date(ts).getTime()
  if (Number.isNaN(t)) return '—'
  const diffSec = Math.round((Date.now() - t) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso + 'T00:00:00').toLocaleDateString('de-DE', {
      weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric',
    })
  } catch {
    return iso
  }
}

export default function LottoTab() {
  const [status, setStatus]     = useState(null)
  const [games, setGames]       = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [draws, setDraws]       = useState([])
  const [tipsRun, setTipsRun]   = useState(null)
  const [stats, setStats]       = useState(null)
  const [strategies, setStrategies] = useState([])
  const [sweetSpot, setSweetSpot] = useState(null)
  const [recencyK, setRecencyK] = useState(1)         // K for the next /generate
  // Tracks whether the user has manually picked a K for the currently
  // selected game. As long as this is false we keep auto-syncing K to
  // either the persisted tip-run param or — better — the sweet-spot
  // recommendation, so the dropdown always lands on the *recommended*
  // K when a game is opened (instead of being stuck on whatever K the
  // bootstrap happened to use, which is always 1).
  const userPickedKRef = useRef(false)
  const [activeStrategy, setActiveStrategy] = useState(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState(null)
  const [busy, setBusy]         = useState(null)   // 'refresh' | 'generate' | 'backfill'
  const [busyMsg, setBusyMsg]   = useState(null)
  const [copied, setCopied]     = useState(null)

  // ── data load ─────────────────────────────────────────────────────────
  const fetchOverview = useCallback(async () => {
    try {
      const sRes = await fetch('/api/lotto/status')
      const sBody = sRes.ok ? await sRes.json() : null
      setStatus(sBody)
      if (!sRes.ok || !sBody?.available) {
        setError(sBody?.message || `dashboard-api returned HTTP ${sRes.status}`)
        setLoading(false)
        return
      }
      const gRes = await fetch('/api/lotto/games')
      if (!gRes.ok) throw new Error(`/api/lotto/games HTTP ${gRes.status}`)
      const gBody = await gRes.json()
      setGames(gBody.games || [])
      setSelectedId((cur) => cur || (gBody.games?.[0]?.id ?? null))
      setError(null)
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchSelected = useCallback(async (gameId, kForList) => {
    if (!gameId) return
    try {
      const k = kForList ?? recencyK
      const [drawRes, tipsRes, statsRes, stratRes, sweetRes] = await Promise.all([
        fetch(`/api/lotto/draws?game=${encodeURIComponent(gameId)}&limit=20`),
        fetch(`/api/lotto/tips?game=${encodeURIComponent(gameId)}`),
        fetch(`/api/lotto/stats?game=${encodeURIComponent(gameId)}`),
        fetch(`/api/lotto/games/${encodeURIComponent(gameId)}/strategies?recency_k=${k}`),
        fetch(`/api/lotto/games/${encodeURIComponent(gameId)}/sweet-spot`),
      ])
      setDraws(drawRes.ok ? (await drawRes.json()).draws || [] : [])
      const tipsBody = tipsRes.ok ? await tipsRes.json() : null
      const run = tipsBody?.run || null
      setTipsRun(run)
      setStats(statsRes.ok ? await statsRes.json() : null)
      setStrategies(stratRes.ok ? (await stratRes.json()).strategies || [] : [])
      const sweetBody = sweetRes.ok ? await sweetRes.json() : null
      setSweetSpot(sweetBody)
      // Auto-pick K for the user *only* until they take over manually:
      // prefer the empirical sweet-spot, fall back to whatever K was used
      // for the persisted tip run, fall back to 1.
      if (!userPickedKRef.current) {
        const recommended = sweetBody?.recommended_k
        const usedK = run?.params?.recency_k
        const next = (typeof recommended === 'number' ? recommended
                    : typeof usedK === 'number' ? usedK
                    : 1)
        setRecencyK(next)
      }
    } catch (e) {
      setError(e?.message || String(e))
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    fetchOverview()
    const id = setInterval(fetchOverview, POLL_MS)
    return () => clearInterval(id)
  }, [fetchOverview])

  useEffect(() => {
    // Reset the manual-K-override flag when switching to a different game,
    // so each game lands on its own recommended K initially.
    userPickedKRef.current = false
    fetchSelected(selectedId)
  }, [selectedId, fetchSelected])

  const selectedGame = useMemo(
    () => games.find((g) => g.id === selectedId) || null,
    [games, selectedId],
  )

  // ── actions ───────────────────────────────────────────────────────────
  const doAction = useCallback(async (kind, opts = {}) => {
    setBusy(kind)
    setBusyMsg(null)
    try {
      let res
      if (kind === 'refresh') {
        res = await fetch('/api/lotto/refresh', { method: 'POST' })
      } else if (kind === 'backfill') {
        res = await fetch('/api/lotto/refresh/full', { method: 'POST' })
      } else if (kind === 'generate') {
        const kForRequest = (typeof opts.recencyK === 'number')
          ? opts.recencyK : recencyK
        const body = selectedId
          ? { game: selectedId, recency_k: kForRequest }
          : { recency_k: kForRequest }
        res = await fetch('/api/lotto/tips/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        setBusyMsg({ tone: 'error', text: body?.detail || `HTTP ${res.status}` })
      } else {
        const kForRequest = (typeof opts.recencyK === 'number')
          ? opts.recencyK : recencyK
        setBusyMsg({
          tone: 'ok',
          text: kind === 'backfill'
            ? 'Backfill gestartet — kann 1-3 Minuten dauern.'
            : kind === 'refresh'
              ? 'Inkrementeller Fetch gestartet.'
              : `Neue Tipps generiert (Recency K=${kForRequest}).`,
        })
        setTimeout(() => { fetchOverview(); fetchSelected(selectedId) }, 1500)
      }
    } catch (e) {
      setBusyMsg({ tone: 'error', text: e?.message || String(e) })
    } finally {
      setBusy(null)
    }
  }, [selectedId, recencyK, fetchOverview, fetchSelected])

  // K-Selector change: update state + immediately re-generate so the
  // dropdown actually feels like it does something. Without this the
  // user has to click "Tipps generieren" afterwards, which is what
  // confused the operator.
  const handleKChange = useCallback((newK) => {
    userPickedKRef.current = true
    setRecencyK(newK)
    if (selectedId) doAction('generate', { recencyK: newK })
  }, [selectedId, doAction])

  const handleCopy = useCallback(async (key, text) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(key)
      setTimeout(() => setCopied(null), 1500)
    } catch { /* ignore */ }
  }, [])

  // ── render ────────────────────────────────────────────────────────────
  if (loading && !games.length) {
    return (
      <div className="p-8">
        <div className="animate-pulse">
          <div className="h-8 bg-theme-card rounded w-1/3 mb-8" />
          <div className="h-32 bg-theme-card rounded-xl mb-6" />
          <div className="h-64 bg-theme-card rounded-xl" />
        </div>
      </div>
    )
  }

  return (
    <div className="p-8">
      {/* Header */}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-theme-text flex items-center gap-2">
            <Ticket size={26} className="text-theme-accent" />
            Lotto Oracle
          </h1>
          <p className="text-theme-text-muted mt-1 max-w-2xl">
            Sammelt Ziehungen (Lotto 6 aus 49, Eurojackpot, Spiel 77, Super 6)
            und generiert nach jeder Ziehung neue Tipps via mehrerer Strategien.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <RecencyKSelector
            value={recencyK}
            onChange={handleKChange}
            sweetSpot={sweetSpot}
            disabled={!!busy || !status?.available}
            busy={busy === 'generate'}
          />
          <button
            type="button"
            onClick={() => { fetchOverview(); fetchSelected(selectedId) }}
            className="p-2 text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw size={20} />
          </button>
          <button
            type="button"
            onClick={() => doAction('refresh')}
            disabled={!!busy || !status?.available}
            className="px-3 py-2 text-sm font-medium border border-theme-border rounded-lg hover:border-theme-accent disabled:opacity-50 flex items-center gap-2"
            title="Inkrementell neue Ziehungen abholen"
          >
            {busy === 'refresh' ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
            Fetch
          </button>
          <button
            type="button"
            onClick={() => doAction('backfill')}
            disabled={!!busy || !status?.available}
            className="px-3 py-2 text-sm font-medium border border-theme-border rounded-lg hover:border-theme-accent disabled:opacity-50 flex items-center gap-2"
            title="Komplette Historie nachladen (kann Minuten dauern)"
          >
            {busy === 'backfill' ? <Loader2 size={14} className="animate-spin" /> : <Database size={14} />}
            Backfill
          </button>
          <button
            type="button"
            onClick={() => doAction('generate')}
            disabled={!!busy || !status?.available || !selectedId}
            className="px-3 py-2 text-sm font-medium bg-theme-accent text-theme-bg rounded-lg hover:opacity-90 disabled:opacity-50 flex items-center gap-2"
            title="Neue Tipps für die ausgewählte Spielart generieren"
          >
            {busy === 'generate' ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            Tipps generieren
          </button>
        </div>
      </div>

      {/* Submission-API hinweis */}
      <SubmissionNotice notice={status?.submission_api} />

      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm flex items-start gap-2">
          <AlertCircle size={18} className="shrink-0 mt-0.5" />
          <div>
            <div className="font-medium mb-1">lotto-oracle nicht erreichbar</div>
            <div className="opacity-80">{error}</div>
            <div className="opacity-60 mt-1 text-xs">
              Prüfe <code className="font-mono">dream status lotto-oracle</code> auf dem Host.
            </div>
          </div>
        </div>
      )}
      {busyMsg && (
        <div
          className={`mb-6 p-3 rounded-lg text-sm ${
            busyMsg.tone === 'ok'
              ? 'bg-green-500/10 border border-green-500/30 text-green-400'
              : 'bg-red-500/10 border border-red-500/30 text-red-400'
          }`}
        >
          {busyMsg.text}
        </div>
      )}

      {/* Game selector cards */}
      <div className="mb-6 grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {games.map((g) => {
          const active = g.id === selectedId
          return (
            <button
              type="button"
              key={g.id}
              onClick={() => setSelectedId(g.id)}
              className={`p-4 rounded-xl text-left border transition-colors ${
                active
                  ? 'bg-theme-card border-theme-accent'
                  : 'bg-theme-card border-theme-border hover:border-theme-accent/50'
              }`}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="font-medium text-theme-text">{g.label}</span>
                <span className="text-xs text-theme-text-muted">{g.n_draws} Ziehungen</span>
              </div>
              <div className="text-xs text-theme-text-muted">
                {g.kind === 'digit'
                  ? `${g.digits}-stellige Losnummer`
                  : g.pools?.map((p) => `${p.pick}/${p.high}`).join(' + ')}
              </div>
              <div className="text-xs text-theme-text-muted mt-1 flex items-center gap-1">
                <Calendar size={11} /> {(g.draw_days || []).join(' · ').toUpperCase()}
              </div>
              <div className="text-xs text-theme-text-muted mt-1">
                Letzte: <span className="font-mono">{formatDate(g.last_in_db)}</span>
              </div>
            </button>
          )
        })}
      </div>

      {/* Schedule strip */}
      {status?.schedule && (
        <div className="mb-6 p-3 bg-theme-card border border-theme-border rounded-lg flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-theme-text-muted">
          <span className="flex items-center gap-1">
            <Clock size={12} /> Auto-Update Cron <code className="font-mono">{status.schedule.cron}</code> ({status.schedule.tz})
          </span>
          <span>• Tipps werden nach jedem Fetch automatisch neu generiert</span>
          <span>• Quelle: lotto-oracle</span>
        </div>
      )}

      {/* Two-column detail */}
      {selectedGame && (
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Left: tips + recency overlap + draws */}
          <div className="lg:col-span-2 space-y-6">
            <RecencyOverlapCard game={selectedGame} run={tipsRun} />
            <TipsCard
              game={selectedGame}
              run={tipsRun}
              strategies={strategies}
              copied={copied}
              onCopy={handleCopy}
              activeStrategy={activeStrategy}
              setActiveStrategy={setActiveStrategy}
              sweetSpot={sweetSpot}
              recencyK={recencyK}
            />
            <DrawsCard game={selectedGame} draws={draws} />
          </div>

          {/* Right: stats */}
          <div className="lg:col-span-1">
            <StatsCard game={selectedGame} stats={stats} />
          </div>
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SubmissionNotice({ notice }) {
  if (!notice) return null
  return (
    <div className="mb-6 p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg text-amber-300 text-xs flex items-start gap-2">
      <Info size={14} className="shrink-0 mt-0.5" />
      <div>
        <span className="font-medium">Keine reale Tippabgabe via API möglich.</span>
        {' '}{notice.note}
      </div>
    </div>
  )
}


function TipsCard({ game, run, strategies, copied, onCopy,
                   activeStrategy, setActiveStrategy, sweetSpot, recencyK }) {
  const tips = run?.tips || []
  const meta = run?.strategy_meta || {}
  const strategyMap = useMemo(() => {
    const m = new Map()
    for (const s of strategies) m.set(s.name, s)
    return m
  }, [strategies])

  // Group tips by strategy, then sort by backtested edge (best first).
  const groups = useMemo(() => {
    const byStrat = new Map()
    tips.forEach((t, idx) => {
      if (!byStrat.has(t.strategy)) byStrat.set(t.strategy, [])
      byStrat.get(t.strategy).push({ ...t, _idx: idx })
    })
    const arr = Array.from(byStrat.entries()).map(([name, items]) => {
      const m = meta[name] || {}
      const edge = (typeof m.edge === 'number') ? m.edge : null
      return {
        name,
        items,
        meta:  m,
        edge,
        sortKey: edge === null ? -Infinity : edge,
      }
    })
    arr.sort((a, b) => b.sortKey - a.sortKey)
    return arr
  }, [tips, meta])

  // Keep the active tab valid as the group set changes (e.g. game switch
  // or fresh /generate that drops a strategy).
  const activeName = useMemo(() => {
    if (!groups.length) return null
    if (activeStrategy && groups.some((g) => g.name === activeStrategy)) {
      return activeStrategy
    }
    return groups[0].name
  }, [groups, activeStrategy])

  useEffect(() => {
    if (activeName && activeName !== activeStrategy) {
      setActiveStrategy(activeName)
    }
  }, [activeName, activeStrategy, setActiveStrategy])

  const activeGroup = groups.find((g) => g.name === activeName) || null
  const usedK = run?.params?.recency_k

  return (
    <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-theme-border flex items-center gap-2 flex-wrap">
        <Sparkles size={14} className="text-theme-text-muted" />
        <h4 className="text-sm font-semibold text-theme-text">
          Vorschläge ({tips.length})
        </h4>
        <span className="ml-auto text-xs text-theme-text-muted">
          {run
            ? <>generiert {relTime(run.generated_at)}
                {' · basierend auf '}{run.based_on_draw || '—'}
                {typeof usedK === 'number' && <> · K={usedK}</>}
                {' · sortiert nach Backtest-Edge'}</>
            : 'Noch keine Tipps generiert — auf "Tipps generieren" klicken.'}
        </span>
      </div>

      {groups.length ? (
        <>
          {/* Tab strip — one per strategy */}
          <div className="flex flex-wrap gap-1 px-3 pt-3 pb-0 border-b border-theme-border bg-theme-surface-hover/20">
            {groups.map((g) => {
              const isActive = g.name === activeName
              const desc = strategyMap.get(g.name)
              const m = g.meta || {}
              const hasScore = typeof m.edge === 'number' && (m.n_trials || 0) > 0
              let tone = 'neutral'
              if (hasScore) {
                if (m.edge > 0.05) tone = 'good'
                else if (m.edge < -0.05) tone = 'warn'
              }
              const edgeColor = isActive
                ? ''
                : tone === 'good'
                  ? 'text-emerald-400/70'
                  : tone === 'warn'
                    ? 'text-amber-300/70'
                    : 'text-theme-text-muted'
              return (
                <button
                  key={g.name}
                  type="button"
                  onClick={() => setActiveStrategy(g.name)}
                  className={`px-3 py-1.5 text-xs font-medium rounded-t-md border-b-2 transition-colors flex items-center gap-2 ${
                    isActive
                      ? 'border-theme-accent text-theme-text bg-theme-card'
                      : 'border-transparent text-theme-text-muted hover:text-theme-text hover:bg-theme-card/50'
                  }`}
                  title={desc?.description || g.name}
                >
                  <span>{desc?.label || g.name}</span>
                  <span className="text-[10px] opacity-70">({g.items.length})</span>
                  {hasScore && (
                    <span className={`text-[10px] font-mono ${edgeColor}`}>
                      {m.edge >= 0 ? '+' : ''}{m.edge}
                    </span>
                  )}
                </button>
              )
            })}
          </div>

          {/* Active tab body */}
          {activeGroup && (
            <StrategyTabBody
              game={game}
              group={activeGroup}
              strategyMap={strategyMap}
              copied={copied}
              onCopy={onCopy}
              sweetSpot={sweetSpot}
              recencyK={recencyK}
            />
          )}
        </>
      ) : (
        <div className="px-5 py-8 text-sm text-theme-text-muted text-center">
          Noch keine Vorschläge. Klicke oben auf <strong>Tipps generieren</strong>.
        </div>
      )}
    </div>
  )
}


function StrategyTabBody({ game, group, strategyMap, copied, onCopy,
                          sweetSpot, recencyK }) {
  const desc = strategyMap.get(group.name)
  const m = group.meta || {}
  const hasScore = typeof m.edge === 'number' && (m.n_trials || 0) > 0
  let tone = 'neutral'
  if (hasScore) {
    if (m.edge > 0.05) tone = 'good'
    else if (m.edge < -0.05) tone = 'warn'
  }
  const toneCls = {
    good:    'text-emerald-400 bg-emerald-500/10 border-emerald-500/30',
    warn:    'text-amber-300   bg-amber-500/10   border-amber-500/30',
    neutral: 'text-theme-text-muted bg-theme-surface-hover border-theme-border',
  }[tone]
  const pAtLeast1 = m.hit_rates?.[0]?.prob ?? null

  return (
    <div className="px-5 py-4">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0">
          {desc?.description && (
            <div className="text-xs text-theme-text-muted max-w-xl">
              {desc.description}
            </div>
          )}
        </div>
        {hasScore ? (
          <div
            className={`shrink-0 text-[10px] font-mono px-2 py-1 rounded border flex items-center gap-1 ${toneCls}`}
            title={
              `Backtest über ${m.n_trials} Tipps gegen ${m.window} echte Ziehungen.\n` +
              `⌀ Treffer: ${m.avg_match} (random: ${m.expected_random})\n` +
              `Edge = avg − random = ${m.edge >= 0 ? '+' : ''}${m.edge}\n` +
              `P(≥1 Treffer) = ${pAtLeast1 != null ? Math.round(pAtLeast1 * 100) + ' %' : '—'}`
            }
          >
            <TrendingUp size={11} />
            <span>⌀ {m.avg_match} {m.edge >= 0 ? '+' : ''}{m.edge}</span>
          </div>
        ) : (
          <div className="shrink-0 text-[10px] text-theme-text-muted px-2 py-1 rounded border border-theme-border">
            Backtest n/a
          </div>
        )}
      </div>

      {/* Sweet-spot panel only on the recency_exclude tab */}
      {group.name === 'recency_exclude' && sweetSpot?.per_k?.length > 0 && (
        <SweetSpotPanel sweetSpot={sweetSpot} recencyK={recencyK} />
      )}

      <div className="space-y-3">
        {group.items.map((t) => (
          <div
            key={t._idx}
            className="rounded-lg bg-theme-surface-hover/40 border border-theme-border/60 p-3"
          >
            <div className="flex items-start justify-between gap-3 mb-2">
              {t.rationale && (
                <div className="text-[11px] text-theme-text-muted italic max-w-xl">
                  {t.rationale}
                </div>
              )}
              <button
                type="button"
                onClick={() => onCopy(`tip-${t._idx}`, t.display)}
                className="shrink-0 text-xs text-theme-text-muted hover:text-theme-text flex items-center gap-1"
                title="Tipp in die Zwischenablage kopieren"
              >
                {copied === `tip-${t._idx}`
                  ? <><Check size={12} /> kopiert</>
                  : <><Copy size={12} /> kopieren</>}
              </button>
            </div>
            <TipDisplay game={game} tip={t} />
          </div>
        ))}
      </div>
    </div>
  )
}


function SweetSpotPanel({ sweetSpot, recencyK }) {
  const recommended = sweetSpot.recommended_k
  return (
    <div className="mb-4 p-3 rounded-lg border border-theme-border bg-theme-surface-hover/30">
      <div className="flex items-center gap-2 mb-2 text-xs text-theme-text-muted">
        <BarChart3 size={12} />
        <span>
          Recency-Backtest pro K (Ø Treffer im Hauptpool über
          {' '}{sweetSpot.window || 0} historische Ziehungen)
        </span>
        {recommended && (
          <span className="ml-auto text-emerald-400">
            Empfehlung: K={recommended}
          </span>
        )}
      </div>
      <div className="grid grid-cols-5 gap-1.5">
        {sweetSpot.per_k.map((row) => {
          const isRec = row.k === recommended
          const isCur = row.k === recencyK
          const cls = isCur
            ? 'border-theme-accent bg-theme-accent/10 text-theme-text'
            : isRec
              ? 'border-emerald-500/40 bg-emerald-500/5 text-theme-text'
              : 'border-theme-border bg-theme-card text-theme-text-muted'
          return (
            <div
              key={row.k}
              className={`text-center text-[11px] py-1.5 rounded border ${cls}`}
              title={
                `K=${row.k}: ⌀ Treffer ${row.avg_match ?? '—'} ` +
                `(random ${row.expected_random ?? '—'}, ` +
                `Edge ${row.edge ?? '—'}, n=${row.n_trials ?? 0})`
              }
            >
              <div className="font-mono">K={row.k}</div>
              <div className="font-mono opacity-80">
                {row.avg_match != null ? row.avg_match.toFixed(2) : '—'}
              </div>
            </div>
          )
        })}
      </div>
      <div className="mt-2 text-[10px] text-theme-text-muted leading-snug">
        Lotto ist statistisch unabhängig — Unterschiede zwischen den K-Werten
        sind klein (≪ ±0.1 Treffer). Empfohlen wird das K mit dem höchsten
        empirischen Ø-Treffer; bei Gleichstand das kleinere K, weil jedes
        zusätzlich ausgeschlossene Spiel den Pool unnötig verkleinert.
      </div>
    </div>
  )
}


function RecencyKSelector({ value, onChange, sweetSpot, disabled, busy }) {
  const recommended = sweetSpot?.recommended_k
  const options = [1, 2, 3, 4, 5]
  return (
    <label
      className="flex items-center gap-2 text-xs text-theme-text-muted px-2 py-1.5 rounded-lg border border-theme-border bg-theme-card"
      title="Wie viele der jüngsten Ziehungen soll die recency_exclude-Strategie ausschließen? Eine Änderung generiert sofort neue Tipps mit dem gewählten K."
    >
      <span className="font-medium">Recency K</span>
      <select
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        disabled={disabled}
        className="bg-transparent text-theme-text font-mono text-sm focus:outline-none disabled:opacity-50 cursor-pointer"
      >
        {options.map((k) => (
          <option key={k} value={k}>
            {k}{recommended === k ? '  ✓ empfohlen' : ''}
          </option>
        ))}
      </select>
      {busy && <Loader2 size={12} className="animate-spin text-theme-accent" />}
    </label>
  )
}


function RecencyOverlapCard({ game, run }) {
  const stats = run?.recency_stats
  if (!stats || !stats.lookbacks) return null
  const isCombo = stats.kind === 'combinatorial'
  const lookbacks = ['1', '2', '3'].filter((k) => stats.lookbacks[k])
  if (!lookbacks.length) return null
  // Don't render at all if NO lookback has any samples — happens on a
  // cold install with only the bundled seed draw (n_history=1).  No
  // point showing a card full of "—" placeholders.
  const hasSamples = lookbacks.some((N) => (stats.lookbacks[N]?.samples || 0) > 0)
  if (!hasSamples) return null

  const unitLabel = isCombo
    ? `Zahlen aus ${stats.main_pool || 'Hauptpool'}`
    : 'Positionen mit gleicher Ziffer'

  return (
    <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-theme-border flex items-center gap-2">
        <BarChart3 size={14} className="text-theme-text-muted" />
        <h4 className="text-sm font-semibold text-theme-text">
          Wiederholungs-Wahrscheinlichkeiten
        </h4>
        <span className="ml-auto text-[11px] text-theme-text-muted">
          empirisch über {stats.n_history} Ziehung(en) · Vergleich: {unitLabel}
        </span>
      </div>
      <div className="p-5 grid sm:grid-cols-3 gap-4">
        {lookbacks.map((N) => {
          const b = stats.lookbacks[N]
          if (!b || b.samples === 0) return null
          // Build the "P(>= k)" strip — typically 1, 2, 3 are interesting.
          const tail = (b.p_at_least || []).slice(0, 4)
          return (
            <div
              key={N}
              className="border border-theme-border rounded-lg p-3 bg-theme-surface-hover/40"
            >
              <div className="text-xs text-theme-text-muted mb-1">
                Letzte {N} Ziehung{N === '1' ? '' : 'en'}
              </div>
              <div className="text-2xl font-mono text-theme-text">
                {b.mean != null ? b.mean.toFixed(2) : '—'}
              </div>
              <div className="text-[11px] text-theme-text-muted mb-2">
                ⌀ wieder gezogen (random ≈ {b.expected_random})
              </div>
              <ul className="space-y-1">
                {tail.map((row) => (
                  <li
                    key={row.k}
                    className="flex items-center justify-between gap-2 text-[11px]"
                  >
                    <span className="text-theme-text-muted">P(≥ {row.k} Treffer)</span>
                    <ProbBar prob={row.prob} />
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
      <div className="px-5 pb-3 text-[11px] text-theme-text-muted">
        {isCombo
          ? <>Lies dies als: „Wie oft kamen aus den letzten <em>N</em> Ziehungen noch <em>k</em> Hauptzahlen wieder?". Werte ≈ Random-Erwartung sind das Lehrbuch (Ziehungen sind unabhängig).</>
          : <>Lies dies als: „Wie oft hatte die nächste Ziehung an gleicher Position dieselbe Ziffer wie eine der letzten <em>N</em>?". P(≥1) liegt für N=3 nahe 100 % — die ‚letzte-Ziehung-ausschließen'-Strategie verschenkt also bewusst diese Treffer.</>
        }
      </div>
    </div>
  )
}


function ProbBar({ prob }) {
  const pct = Math.round((prob || 0) * 100)
  return (
    <div className="flex items-center gap-2 w-32">
      <div className="flex-1 h-2 bg-theme-border/60 rounded-sm overflow-hidden">
        <div
          className="h-full bg-theme-accent/70"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="font-mono text-theme-text-muted w-9 text-right">{pct}%</span>
    </div>
  )
}


function TipDisplay({ game, tip }) {
  if (game.kind === 'digit') {
    return (
      <div className="flex items-center gap-1 font-mono text-2xl tracking-widest text-theme-text">
        {(tip.digits || '').split('').map((d, i) => (
          <span
            key={i}
            className="inline-flex items-center justify-center w-9 h-11 rounded bg-theme-surface-hover border border-theme-border"
          >
            {d}
          </span>
        ))}
      </div>
    )
  }
  return (
    <div className="space-y-2">
      {game.pools.map((p) => {
        const nums = tip[p.name] || []
        return (
          <div key={p.name} className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-theme-text-muted w-28 shrink-0">{p.name}</span>
            {nums.map((n, i) => (
              <NumberBall key={i} value={n} pad={p.high >= 10} accent={p.name !== 'Hauptzahlen'} />
            ))}
          </div>
        )
      })}
    </div>
  )
}


function NumberBall({ value, pad, accent }) {
  const cls = accent
    ? 'bg-theme-accent text-theme-bg'
    : 'bg-theme-surface-hover text-theme-text border border-theme-border'
  return (
    <span
      className={`inline-flex items-center justify-center w-9 h-9 rounded-full text-sm font-mono font-semibold ${cls}`}
    >
      {pad ? String(value).padStart(2, '0') : value}
    </span>
  )
}


function DrawsCard({ game, draws }) {
  return (
    <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-theme-border flex items-center gap-2">
        <Calendar size={14} className="text-theme-text-muted" />
        <h4 className="text-sm font-semibold text-theme-text">
          Letzte Ziehungen ({draws.length})
        </h4>
      </div>
      {draws.length ? (
        <ul className="divide-y divide-theme-border">
          {draws.map((d, i) => (
            <li key={i} className="px-5 py-3 flex items-start gap-4">
              <div className="text-xs font-mono text-theme-text-muted w-24 shrink-0 mt-1">
                {formatDate(d.draw_date)}
              </div>
              <div className="flex-1">
                <TipDisplay game={game} tip={d} />
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="px-5 py-6 text-sm text-theme-text-muted">
          Keine Ziehungen geladen — bitte zuerst <strong>Backfill</strong> klicken.
        </div>
      )}
    </div>
  )
}


function StatsCard({ game, stats }) {
  if (!stats || stats.n === 0) {
    return (
      <div className="bg-theme-card border border-theme-border rounded-xl p-5 text-sm text-theme-text-muted">
        Keine Statistik verfügbar (noch keine Ziehungen).
      </div>
    )
  }

  if (game.kind === 'digit') {
    return (
      <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-theme-border">
          <h4 className="text-sm font-semibold text-theme-text">
            Häufigkeit pro Position
          </h4>
          <div className="text-xs text-theme-text-muted">
            über {stats.n} Ziehung(en)
          </div>
        </div>
        <div className="p-5 space-y-3">
          {(stats.per_position || []).map((pp) => {
            const max = Math.max(1, ...pp.frequency.map((f) => f.count))
            return (
              <div key={pp.position}>
                <div className="text-xs text-theme-text-muted mb-1">Position {pp.position + 1}</div>
                <div className="flex items-end gap-1 h-12">
                  {pp.frequency.map((f) => (
                    <div key={f.digit} className="flex-1 flex flex-col items-center gap-0.5">
                      <div
                        className="w-full bg-theme-accent/60 rounded-sm"
                        style={{ height: `${(f.count / max) * 100}%`, minHeight: '2px' }}
                        title={`Ziffer ${f.digit}: ${f.count}×`}
                      />
                      <span className="text-[10px] text-theme-text-muted font-mono">{f.digit}</span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  // Combinatorial: show frequency for the main pool only.
  const mainPool = game.pools[0]
  const data = stats[mainPool.name]?.frequency || []
  const max = Math.max(1, ...data.map((d) => d.count))

  return (
    <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
      <div className="px-5 py-3 border-b border-theme-border">
        <h4 className="text-sm font-semibold text-theme-text">
          Frequenz: {mainPool.name}
        </h4>
        <div className="text-xs text-theme-text-muted">
          über {stats.n} Ziehung(en) · Erwartet pro Zahl: ~{Math.round(stats.n * mainPool.pick / (mainPool.high - mainPool.low + 1))}×
        </div>
      </div>
      <div className="p-5">
        <div className="grid grid-cols-7 gap-1">
          {data.map((row) => {
            const heat = row.count / max
            const bg = `rgba(56, 189, 248, ${0.15 + heat * 0.7})`
            return (
              <div
                key={row.number}
                className="text-center text-xs font-mono py-1 rounded"
                style={{ background: bg, color: heat > 0.6 ? '#0b1220' : undefined }}
                title={`${row.number}: ${row.count}× (Gap ${row.gap})`}
              >
                {String(row.number).padStart(2, '0')}
              </div>
            )
          })}
        </div>
        <div className="mt-3 text-xs text-theme-text-muted">
          Helle Felder = häufiger gezogen. Hover für genaue Zählung + aktuelle
          Pause (Gap) seit letzter Ziehung.
        </div>
      </div>
    </div>
  )
}

