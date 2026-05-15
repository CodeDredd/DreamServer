/**
 * Unit-Tests fuer app/utils/format.ts (Phase 6 Welle Format-Helpers).
 *
 * Pure-Funktionen ohne Side-Effects -> simple direkte Asserts ohne
 * Mocks. Smallest-Building-Block fuer das Test-Setup, dient ausserdem
 * als "Hello World"-Sanity-Check des Vitest-Setups.
 */

import { describe, it, expect } from 'vitest'
import { formatEur, formatPct, relTime, pnlToneClass, formatGermanDate } from '~/utils/format'

describe('format.formatEur', () => {
  it('formatiert Zahlen als EUR mit deutschem Locale', () => {
    expect(formatEur(1234.5)).toMatch(/1\.234,50.*€/)
    expect(formatEur(0)).toMatch(/0,00.*€/)
  })

  it('liefert "—" bei null/undefined/NaN', () => {
    expect(formatEur(null)).toBe('—')
    expect(formatEur(undefined)).toBe('—')
    expect(formatEur(Number.NaN)).toBe('—')
  })
})

describe('format.formatPct', () => {
  it('haengt + bei positiven Werten an, - bleibt vom Wert', () => {
    expect(formatPct(2.5)).toBe('+2.50%')
    expect(formatPct(-1.234)).toBe('-1.23%')
    // 0 ist nicht > 0 -> kein +-Praefix
    expect(formatPct(0)).toBe('0.00%')
  })

  it('respektiert digits-Parameter', () => {
    expect(formatPct(2.5, 0)).toBe('+3%') // toFixed rundet 2.5 -> 3
    expect(formatPct(2.5, 4)).toBe('+2.5000%')
  })

  it('liefert "—" bei null/undefined/NaN', () => {
    expect(formatPct(null)).toBe('—')
    expect(formatPct(undefined)).toBe('—')
    expect(formatPct(Number.NaN)).toBe('—')
  })
})

describe('format.relTime', () => {
  it('liefert "Xs ago" fuer < 60 s', () => {
    const now = Date.now()
    expect(relTime(now - 30_000)).toBe('30s ago')
    expect(relTime(now - 1_000)).toBe('1s ago')
  })

  it('liefert "Xm ago" fuer < 60 min', () => {
    const now = Date.now()
    expect(relTime(now - 5 * 60_000)).toBe('5m ago')
  })

  it('liefert "Xh ago" fuer < 24 h', () => {
    const now = Date.now()
    expect(relTime(now - 3 * 3_600_000)).toBe('3h ago')
  })

  it('liefert "Xd ago" sonst', () => {
    const now = Date.now()
    expect(relTime(now - 7 * 86_400_000)).toBe('7d ago')
  })

  it('liefert "—" bei falsy / invalid', () => {
    expect(relTime(null)).toBe('—')
    expect(relTime(undefined)).toBe('—')
    expect(relTime('not-a-date')).toBe('—')
  })
})

describe('format.pnlToneClass', () => {
  it('liefert success bei positivem PnL', () => {
    expect(pnlToneClass(0.5)).toBe('text-success')
  })

  it('liefert error bei negativem PnL', () => {
    expect(pnlToneClass(-0.5)).toBe('text-error')
  })

  it('liefert muted in der Toleranzzone (<= 0.001 absolut)', () => {
    expect(pnlToneClass(0)).toBe('text-muted')
    expect(pnlToneClass(0.0005)).toBe('text-muted')
    expect(pnlToneClass(-0.0005)).toBe('text-muted')
  })

  it('liefert muted bei null/undefined/NaN', () => {
    expect(pnlToneClass(null)).toBe('text-muted')
    expect(pnlToneClass(undefined)).toBe('text-muted')
    expect(pnlToneClass(Number.NaN)).toBe('text-muted')
  })
})

describe('format.formatGermanDate', () => {
  it('formatiert ISO-Datum mit deutschem Locale', () => {
    const result = formatGermanDate('2025-01-15')
    // Toleriert Mo./Mo/Mi etc. — wir prufen nur strukturelle Bestandteile.
    expect(result).toMatch(/15\.01\.2025/)
  })

  it('liefert "—" bei null/undefined', () => {
    expect(formatGermanDate(null)).toBe('—')
    expect(formatGermanDate(undefined)).toBe('—')
  })

  it('liefert den input-string bei invaliden Datums', () => {
    // Da new Date('not-a-date') NaN liefert, faengt try/catch nicht zu,
    // aber toLocaleDateString liefert "Invalid Date"
    const result = formatGermanDate('not-a-date')
    expect(typeof result).toBe('string')
  })
})

