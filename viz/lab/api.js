/**
 * viz/lab/api.js — the only file that talks HTTP.
 *
 * Why it exists : one place to change if the persistence layer ever moves off the
 *                 Vite middleware (vite.config.js, plugin `ablepad-config-api`).
 * Layer it owns : transport. No app state, no DOM.
 * Who calls it  : store.js (all config CRUD), palette.js (palette fetch).
 * What it returns: parsed JSON, or throws Error with the server's message.
 */

async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try {
    data = await res.json()
  } catch {
    /* non-JSON error body — fall through to status check */
  }
  if (!res.ok) throw new Error(data?.error ?? `${method} ${url} → HTTP ${res.status}`)
  return data
}

export const listConfigs = () => request('GET', '/api/configs')
export const getConfig = (id) => request('GET', `/api/configs/${id}`)
export const putConfig = (config) => request('PUT', `/api/configs/${config.id}`, config)
export const deleteConfig = (id) => request('DELETE', `/api/configs/${id}`)
export const getPalette = () => request('GET', '/api/palette')
