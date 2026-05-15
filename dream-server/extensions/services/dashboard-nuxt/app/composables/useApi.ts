// Zentrale API-Hülle. Spielt zwei Rollen:
//
//   1. Single point of contact für alle dashboard-api-Requests. Pages
//      und Stores rufen ausschließlich `$api(path)` auf — kein
//      `$fetch('/api/…')` außerhalb dieses Files.
//   2. Setzt sinnvolle Defaults: Default-Headers, JSON-Rückgabe,
//      Fehler-Wrapper. Auth (Bearer-Injection) passiert in der
//      Nitro-Middleware (`server/middleware/api-proxy.ts`) — der
//      Browser sendet hier nichts Geheimes.

import type { FetchOptions } from 'ofetch'

export interface ApiError extends Error {
  status?: number
  data?: unknown
}

function makeError(message: string, status?: number, data?: unknown): ApiError {
  const err = new Error(message) as ApiError
  err.status = status
  err.data = data
  return err
}

/**
 * Typed wrapper around `$fetch` that always targets the same-origin
 * `/api/**` namespace. Throws an `ApiError` with status/payload on
 * non-2xx responses.
 */
export async function dreamFetch<T = unknown>(
  path: string,
  opts: FetchOptions<'json'> = {},
): Promise<T> {
  if (!path.startsWith('/api/')) {
    throw new Error(`dreamFetch: path must start with /api/ (got "${path}")`)
  }
  try {
    return await $fetch<T>(path, {
      ...opts,
      // ofetch defaults to text for non-JSON; we always expect JSON.
      responseType: opts.responseType ?? 'json',
    })
  }
  catch (err: unknown) {
    const e = err as { status?: number, statusCode?: number, data?: unknown, message?: string }
    throw makeError(
      e.message || `Request to ${path} failed`,
      e.status ?? e.statusCode,
      e.data,
    )
  }
}

/**
 * Composable form — exposes the same wrapper plus a few helpers (POST,
 * DELETE) so call-sites read more declaratively.
 */
export function useApi() {
  return {
    get: <T = unknown>(path: string, opts?: FetchOptions<'json'>) =>
      dreamFetch<T>(path, { ...opts, method: 'GET' }),
    post: <T = unknown>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      dreamFetch<T>(path, { ...opts, method: 'POST', body }),
    put: <T = unknown>(path: string, body?: unknown, opts?: FetchOptions<'json'>) =>
      dreamFetch<T>(path, { ...opts, method: 'PUT', body }),
    delete: <T = unknown>(path: string, opts?: FetchOptions<'json'>) =>
      dreamFetch<T>(path, { ...opts, method: 'DELETE' }),
    raw: dreamFetch,
  }
}

