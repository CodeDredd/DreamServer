// Format-Helpers — shared zwischen finance-guru, lotto und ggf. weiteren
// Pages (Phase 4 Welle C.1). Pendant zu den lokalen Helpern in
// dashboard/src/pages/FinanceGuru.jsx und LottoTab.jsx.

export function formatEur(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat('de-DE', {
    style: 'currency',
    currency: 'EUR',
    maximumFractionDigits: 2,
  }).format(v)
}

export function formatPct(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(digits)}%`
}

/**
 * Relative-Zeit-Helper analog zu dashboard/src/pages/FinanceGuru.jsx
 * — bewusst englisch, weil das React-Original es so hat und die
 * Strings ueber den ganzen Stack identisch sein sollen.
 */
export function relTime(ts: string | number | null | undefined): string {
  if (!ts) return '—'
  const t = new Date(ts).getTime()
  if (Number.isNaN(t)) return '—'
  const diffSec = Math.round((Date.now() - t) / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`
  return `${Math.floor(diffSec / 86400)}d ago`
}

export function pnlToneClass(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return 'text-muted'
  if (pct > 0.001) return 'text-success'
  if (pct < -0.001) return 'text-error'
  return 'text-muted'
}

export function formatGermanDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString('de-DE', {
      weekday: 'short',
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
    })
  }
  catch {
    return iso
  }
}

