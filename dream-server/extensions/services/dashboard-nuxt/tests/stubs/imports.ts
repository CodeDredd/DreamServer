/**
 * Stub fuer `#imports` — der Auto-Import-Layer von Nuxt.
 * Die Module die in Composables/Components verwendet werden, mappen wir
 * hier auf direkte Vue-/Pinia-/VueUse-Imports, damit Vitest sie ohne
 * `nuxt prepare`-Roundtrip aufloesen kann.
 *
 * Wenn ein Composable einen Nuxt-spezifischen Helper braucht (z. B.
 * `useFetch`, `useRoute`, `useNuxtApp`), wird hier ein vi.fn-Stub
 * eingehaengt — Tests koennen ihn pro Suite via `vi.mocked(useRoute)`
 * konfigurieren.
 */

import { vi } from 'vitest'

export {
  ref,
  reactive,
  computed,
  watch,
  watchEffect,
  onMounted,
  onUnmounted,
  onBeforeUnmount,
  nextTick,
  defineComponent,
  h,
  shallowRef,
  toRefs,
  toRef,
  unref,
  isRef,
  markRaw,
  readonly,
  customRef,
  triggerRef,
} from 'vue'

export { defineStore, storeToRefs } from 'pinia'

// Nuxt-spezifische Helpers — als no-op-Stubs, individuell mockbar pro Test.
export const useNuxtApp = vi.fn(() => ({
  $config: { public: {}, apiBaseInternal: '' },
  hook: vi.fn(),
  callHook: vi.fn(),
}))

export const useRoute = vi.fn(() => ({
  path: '/',
  fullPath: '/',
  hash: '',
  query: {},
  params: {},
  name: 'index',
}))

export const useRouter = vi.fn(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  back: vi.fn(),
  go: vi.fn(),
}))

export const navigateTo = vi.fn(async () => {})

export const useRuntimeConfig = vi.fn(() => ({ public: {}, apiBaseInternal: '' }))

export const useState = <T>(_key: string, init?: () => T) => {
  // Per Test eigene Instanz reichen aus, kein Persisting noetig.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ref } = require('vue')
  return ref(init ? init() : undefined)
}

export const useCookie = vi.fn(() => ({ value: null }))

export const defineNuxtRouteMiddleware = (fn: unknown) => fn
export const defineNuxtPlugin = (fn: unknown) => fn
export const defineEventHandler = (fn: unknown) => fn

export const useI18n = vi.fn(() => ({
  t: (key: string) => key,
  locale: { value: 'de' },
  availableLocales: ['de', 'en'],
}))

// $fetch / useFetch via globalThis.fetch (gemockt in tests/setup.ts).
export const $fetch = vi.fn(async (url: string, opts?: RequestInit) => {
  const res = await globalThis.fetch(url, opts)
  return res.json()
})

export const useFetch = vi.fn(async (url: string, opts?: RequestInit) => {
  const data = await $fetch(url, opts)
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { ref } = require('vue')
  return { data: ref(data), error: ref(null), pending: ref(false), refresh: vi.fn() }
})

