import { useState, useEffect, useCallback, useMemo } from 'react'
import {
  TrendingUp, RefreshCw, AlertCircle, Play, Loader2,
  Wallet, Activity, Target, Clock, Info,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Finance Guru — paper-trade strategy engine dashboard tab.
//
// Talks exclusively to /api/finance-guru/* on dashboard-api, which proxies
// the upstream finance-guru-api service. See AGENT-OPERATIONS.md §11.
// ---------------------------------------------------------------------------

// 10 %/week is the AGENT-OPERATIONS.md §11 KPI target. Annualised compound
// would be silly; we score against the simple weekly figure (PnL since seed
// divided by seed) which is what the user asked for.
const WEEKLY_TARGET_PCT = 10

const POLL_MS = 30_000

function formatEur(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(v)
}

function formatPct(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}

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

function pnlColorClass(pct) {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return 'text-theme-text-muted'
  if (pct > 0.001) return 'text-green-400'
  if (pct < -0.001) return 'text-red-400'
  return 'text-theme-text-muted'
}

export default function FinanceGuru() {
  const [status, setStatus] = useState(null)
  const [strategies, setStrategies] = useState([])
  const [scheduleInfo, setScheduleInfo] = useState(null)
  const [historyExtent, setHistoryExtent] = useState(null)
  const [ledgers, setLedgers] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [decideLoading, setDecideLoading] = useState(false)
  const [decideMsg, setDecideMsg] = useState(null)
  const [selectedStrategy, setSelectedStrategy] = useState(null)

  const fetchAll = useCallback(async () => {
    try {
      // Status first — cheap, tells us whether the upstream is reachable.
      const sRes = await fetch('/api/finance-guru/status')
      const sBody = sRes.ok ? await sRes.json() : null
      setStatus(sBody)
      if (!sRes.ok || !sBody?.available) {
        setError(sBody?.message || `dashboard-api returned HTTP ${sRes.status}`)
        setLoading(false)
        return
      }

      const stratRes = await fetch('/api/finance-guru/strategies')
      if (!stratRes.ok) throw new Error(`strategies HTTP ${stratRes.status}`)
      const stratBody = await stratRes.json()
      const list = stratBody.strategies || []
      setStrategies(list)
      setScheduleInfo({
        cron: stratBody.schedule?.cron,
        tz: stratBody.schedule?.tz,
        next_run: stratBody.next_run,
      })
      setHistoryExtent(stratBody.history_extent || null)

      // Pull all ledgers in parallel — small payloads, one request per strategy.
      const ledgerEntries = await Promise.all(
        list.map(async (s) => {
          const res = await fetch(`/api/finance-guru/ledger?strategy=${encodeURIComponent(s.name)}`)
          if (!res.ok) return [s.name, { error: `HTTP ${res.status}` }]
          return [s.name, await res.json()]
        })
      )
      const newLedgers = Object.fromEntries(ledgerEntries)
      setLedgers(newLedgers)

      if (!selectedStrategy && list.length) {
        setSelectedStrategy(list[0].name)
      }
      setError(null)
    } catch (e) {
      setError(e?.message || String(e))
    } finally {
      setLoading(false)
    }
  }, [selectedStrategy])

  useEffect(() => {
    fetchAll()
    const id = setInterval(fetchAll, POLL_MS)
    return () => clearInterval(id)
  }, [fetchAll])

  const triggerDecide = useCallback(async (strategyName = null) => {
    setDecideLoading(true)
    setDecideMsg(null)
    try {
      const res = await fetch('/api/finance-guru/decide', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(strategyName ? { strategy: strategyName } : {}),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        setDecideMsg({
          tone: 'error',
          text: body?.detail || `HTTP ${res.status}`,
        })
      } else {
        setDecideMsg({
          tone: 'ok',
          text: `Queued: ${body?.queued_for || 'all-enabled'}`,
        })
        // Re-poll a few seconds later so the user sees the cycle results.
        setTimeout(fetchAll, 3000)
      }
    } catch (e) {
      setDecideMsg({ tone: 'error', text: e?.message || String(e) })
    } finally {
      setDecideLoading(false)
    }
  }, [fetchAll])

  const aggregate = useMemo(() => {
    const kpis = strategies
      .map((s) => ledgers[s.name]?.kpi)
      .filter(Boolean)
    if (!kpis.length) return null
    const seeded = kpis.reduce((sum, k) => sum + (k.seeded_eur || 0), 0)
    const equity = kpis.reduce((sum, k) => sum + (k.equity_eur || 0), 0)
    const realised = kpis.reduce((sum, k) => sum + (k.realised_pnl_eur || 0), 0)
    const trades = kpis.reduce((sum, k) => sum + (k.n_trades || 0), 0)
    const positions = kpis.reduce((sum, k) => sum + (k.n_positions || 0), 0)
    const totalPnlPct = seeded > 0 ? ((equity - seeded) / seeded) * 100 : 0
    return { seeded, equity, realised, trades, positions, totalPnlPct }
  }, [strategies, ledgers])

  const selectedLedger = selectedStrategy ? ledgers[selectedStrategy] : null
  const selectedMeta = strategies.find((s) => s.name === selectedStrategy)

  if (loading && !strategies.length) {
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
      {/* ------------------------------------------------------------- */}
      {/* Header                                                        */}
      {/* ------------------------------------------------------------- */}
      <div className="mb-8 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-theme-text flex items-center gap-2">
            <TrendingUp size={26} className="text-theme-accent" />
            Finance Guru
          </h1>
          <p className="text-theme-text-muted mt-1">
            Paper-trade strategy engine — €{1000} seed per strategy, 10 %/week target.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => fetchAll()}
            className="p-2 text-theme-text-muted hover:text-theme-text hover:bg-theme-surface-hover rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw size={20} />
          </button>
          <button
            type="button"
            onClick={() => triggerDecide(null)}
            disabled={decideLoading || !status?.available}
            className="px-3 py-2 text-sm font-medium bg-theme-accent text-theme-bg rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-opacity"
            title="Run one decision cycle for every enabled strategy"
          >
            {decideLoading ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            Run decide cycle
          </button>
        </div>
      </div>

      {/* ------------------------------------------------------------- */}
      {/* Errors / status banners                                       */}
      {/* ------------------------------------------------------------- */}
      {error && (
        <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm flex items-start gap-2">
          <AlertCircle size={18} className="shrink-0 mt-0.5" />
          <div>
            <div className="font-medium mb-1">finance-guru-api not reachable</div>
            <div className="opacity-80">{error}</div>
            <div className="opacity-60 mt-1 text-xs">
              Check <code className="font-mono">dream status finance-guru-api</code> on the host.
            </div>
          </div>
        </div>
      )}
      {decideMsg && (
        <div
          className={`mb-6 p-3 rounded-lg text-sm ${
            decideMsg.tone === 'ok'
              ? 'bg-green-500/10 border border-green-500/30 text-green-400'
              : 'bg-red-500/10 border border-red-500/30 text-red-400'
          }`}
        >
          {decideMsg.text}
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* Aggregate KPI strip                                           */}
      {/* ------------------------------------------------------------- */}
      {aggregate && (
        <div className="mb-8 grid grid-cols-2 md:grid-cols-5 gap-4">
          <KpiCard
            icon={Wallet}
            label="Total seeded"
            value={formatEur(aggregate.seeded)}
            sub={`${strategies.length} strategies`}
          />
          <KpiCard
            icon={Wallet}
            label="Equity"
            value={formatEur(aggregate.equity)}
            sub={formatPct(aggregate.totalPnlPct)}
            tone={aggregate.totalPnlPct >= 0 ? 'ok' : 'bad'}
          />
          <KpiCard
            icon={Target}
            label="Vs 10 %/wk target"
            value={formatPct(aggregate.totalPnlPct - WEEKLY_TARGET_PCT)}
            sub={`target ${WEEKLY_TARGET_PCT}%`}
            tone={aggregate.totalPnlPct >= WEEKLY_TARGET_PCT ? 'ok' : 'bad'}
          />
          <KpiCard
            icon={Activity}
            label="Realised PnL"
            value={formatEur(aggregate.realised)}
            sub={`${aggregate.trades} trades`}
            tone={aggregate.realised >= 0 ? 'ok' : 'bad'}
          />
          <KpiCard
            icon={TrendingUp}
            label="Open positions"
            value={String(aggregate.positions)}
            sub={
              scheduleInfo?.cron
                ? `next ${relTime(scheduleInfo.next_run)} (${scheduleInfo.cron})`
                : 'no schedule'
            }
          />
        </div>
      )}

      {/* ------------------------------------------------------------- */}
      {/* Strategy list (left)  +  detail (right)                       */}
      {/* ------------------------------------------------------------- */}
      <div className="grid lg:grid-cols-3 gap-6">
        <div className="lg:col-span-1 space-y-3">
          <h2 className="text-sm font-semibold text-theme-text-muted uppercase tracking-wider">
            Strategies
          </h2>
          {strategies.map((s) => {
            const kpi = ledgers[s.name]?.kpi
            const pnl = kpi?.total_pnl_pct
            const isSelected = s.name === selectedStrategy
            return (
              <button
                type="button"
                key={s.name}
                onClick={() => setSelectedStrategy(s.name)}
                className={`w-full text-left p-4 rounded-xl border transition-colors ${
                  isSelected
                    ? 'bg-theme-card border-theme-accent'
                    : 'bg-theme-card border-theme-border hover:border-theme-accent/50'
                }`}
              >
                <div className="flex items-start justify-between gap-3 mb-2">
                  <div>
                    <div className="font-mono text-sm text-theme-text">{s.name}</div>
                    <div className="text-xs text-theme-text-muted mt-0.5">
                      {s.asset_types?.join(' · ') || ''}
                    </div>
                  </div>
                  <span className={`text-sm font-semibold ${pnlColorClass(pnl)}`}>
                    {formatPct(pnl)}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-xs text-theme-text-muted">
                  <span>{formatEur(kpi?.equity_eur)}</span>
                  <span>· {kpi?.n_positions ?? 0} pos</span>
                  <span>· {kpi?.n_trades ?? 0} trades</span>
                  {!s.enabled && (
                    <span className="ml-auto text-amber-400 uppercase tracking-wider">
                      disabled
                    </span>
                  )}
                </div>
              </button>
            )
          })}
        </div>

        <div className="lg:col-span-2">
          {selectedMeta && selectedLedger ? (
            <StrategyDetail
              meta={selectedMeta}
              ledger={selectedLedger}
              decideLoading={decideLoading}
              onDecide={() => triggerDecide(selectedMeta.name)}
              historyExtent={historyExtent}
            />
          ) : (
            <div className="p-8 text-center text-theme-text-muted bg-theme-card border border-theme-border rounded-xl">
              {strategies.length ? 'Select a strategy' : 'No strategies registered'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function KpiCard({ icon: Icon, label, value, sub, tone }) {
  const valueClass =
    tone === 'ok' ? 'text-green-400' : tone === 'bad' ? 'text-red-400' : 'text-theme-text'
  return (
    <div className="p-4 bg-theme-card border border-theme-border rounded-xl">
      <div className="flex items-center gap-2 text-xs text-theme-text-muted mb-2 uppercase tracking-wider">
        {Icon ? <Icon size={14} /> : null}
        {label}
      </div>
      <div className={`text-xl font-semibold ${valueClass}`}>{value}</div>
      {sub && <div className="text-xs text-theme-text-muted mt-1">{sub}</div>}
    </div>
  )
}

function StrategyDetail({ meta, ledger, decideLoading, onDecide, historyExtent }) {
  const kpi = ledger?.kpi
  const positions = ledger?.positions || []
  const trades = ledger?.trades || []
  const lastSignals = meta?.last_signals
  const lastTs = meta?.last_ts

  return (
    <div className="space-y-6">
      {/* Header card */}
      <div className="p-5 bg-theme-card border border-theme-border rounded-xl">
        <div className="flex items-start justify-between gap-4 mb-3">
          <div>
            <h3 className="text-lg font-semibold text-theme-text font-mono">{meta.name}</h3>
            <p className="text-sm text-theme-text-muted mt-1">{meta.description}</p>
          </div>
          <button
            type="button"
            onClick={onDecide}
            disabled={decideLoading}
            className="px-3 py-1.5 text-xs font-medium border border-theme-border rounded-lg hover:border-theme-accent disabled:opacity-50 flex items-center gap-1.5"
          >
            {decideLoading ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
            Decide now
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
          <Stat label="Cash" value={formatEur(kpi?.cash_eur)} />
          <Stat label="Holdings" value={formatEur(kpi?.holdings_eur)} />
          <Stat label="Equity" value={formatEur(kpi?.equity_eur)} />
          <Stat
            label="PnL"
            value={formatPct(kpi?.total_pnl_pct)}
            valueClass={pnlColorClass(kpi?.total_pnl_pct)}
          />
        </div>
        <div className="mt-3 pt-3 border-t border-theme-border flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-theme-text-muted">
          <span className="flex items-center gap-1">
            <Clock size={12} /> last cycle {relTime(lastTs)}
          </span>
          <span>signals: {lastSignals ?? 0}</span>
          <span>executed: {meta?.last_executed ?? 0}</span>
          <span>skipped: {meta?.last_skipped ?? 0}</span>
          <span>max position: {(meta?.max_position_frac * 100).toFixed(0)}%</span>
        </div>
      </div>

      {/* Positions */}
      <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-theme-border flex items-center gap-2">
          <Wallet size={14} className="text-theme-text-muted" />
          <h4 className="text-sm font-semibold text-theme-text">
            Open positions ({positions.length})
          </h4>
        </div>
        {positions.length ? (
          <table className="w-full text-sm">
            <thead className="bg-theme-surface-hover/50">
              <tr className="text-xs text-theme-text-muted uppercase tracking-wider">
                <th className="text-left px-5 py-2 font-medium">Symbol</th>
                <th className="text-right px-3 py-2 font-medium">Qty</th>
                <th className="text-right px-3 py-2 font-medium">Avg</th>
                <th className="text-right px-3 py-2 font-medium">Mark</th>
                <th className="text-right px-5 py-2 font-medium">PnL</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const pnl = (p.mark_price - p.avg_price) * p.qty
                const pnlPct = p.avg_price > 0 ? ((p.mark_price - p.avg_price) / p.avg_price) * 100 : 0
                return (
                  <tr key={p.symbol} className="border-t border-theme-border">
                    <td className="px-5 py-2 font-mono text-theme-text">{p.symbol}</td>
                    <td className="text-right px-3 py-2">{p.qty?.toFixed?.(4) ?? p.qty}</td>
                    <td className="text-right px-3 py-2">{formatEur(p.avg_price)}</td>
                    <td className="text-right px-3 py-2">{formatEur(p.mark_price)}</td>
                    <td className={`text-right px-5 py-2 ${pnlColorClass(pnlPct)}`}>
                      {formatEur(pnl)} <span className="text-xs">({formatPct(pnlPct, 1)})</span>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <div className="px-5 py-6 text-sm text-theme-text-muted">
            No open positions. Strategy is sitting in cash.
          </div>
        )}
      </div>

      {/* Trade log — “why did it trade” */}
      <div className="bg-theme-card border border-theme-border rounded-xl overflow-hidden">
        <div className="px-5 py-3 border-b border-theme-border flex items-center gap-2">
          <Activity size={14} className="text-theme-text-muted" />
          <h4 className="text-sm font-semibold text-theme-text">
            Recent trades ({trades.length})
          </h4>
          <span className="ml-auto text-xs text-theme-text-muted">
            {historyExtent?.symbols
              ? `${historyExtent.symbols} symbols in history`
              : 'history loading…'}
          </span>
        </div>
        {trades.length ? (
          <ul className="divide-y divide-theme-border">
            {trades.slice(0, 25).map((t, i) => (
              <li key={i} className="px-5 py-3">
                <div className="flex items-center gap-3 mb-1">
                  <span
                    className={`text-xs font-mono uppercase px-2 py-0.5 rounded ${
                      t.side === 'BUY'
                        ? 'bg-green-500/15 text-green-400'
                        : 'bg-red-500/15 text-red-400'
                    }`}
                  >
                    {t.side}
                  </span>
                  <span className="font-mono text-sm text-theme-text">{t.symbol}</span>
                  <span className="text-xs text-theme-text-muted">
                    {t.qty?.toFixed?.(4) ?? t.qty} @ {formatEur(t.price)}
                  </span>
                  {t.pnl_eur !== undefined && t.pnl_eur !== null && (
                    <span className={`text-xs ${pnlColorClass(t.pnl_eur)}`}>
                      {t.pnl_eur >= 0 ? '+' : ''}{formatEur(t.pnl_eur)}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-theme-text-muted">
                    {relTime(t.ts)}
                  </span>
                </div>
                {t.reason && (
                  <div className="text-xs text-theme-text-muted pl-1 flex items-start gap-1.5">
                    <Info size={11} className="shrink-0 mt-0.5 opacity-60" />
                    <span className="italic">{t.reason}</span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <div className="px-5 py-6 text-sm text-theme-text-muted">
            No trades yet. The strategy hasn't found an entry signal.
          </div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, valueClass = 'text-theme-text' }) {
  return (
    <div>
      <div className="text-xs text-theme-text-muted uppercase tracking-wider">{label}</div>
      <div className={`mt-0.5 text-base font-semibold ${valueClass}`}>{value}</div>
    </div>
  )
}

