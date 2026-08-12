/**
 * viz/trees.js — the .mmd sources, and the ONLY module that talks to Vite's HMR.
 *
 * Why it exists : a raw-string import cannot be hot-updated, so editing a tree used to force a
 *                 full page reload and throw away your section, zoom and pan. This module
 *                 self-accepts, so a .mmd edit swaps the text in place and the page never reloads.
 * Layer it owns : content loading. No DOM, no rendering.
 * Who calls it  : main.js — once for `trees`, once for `onTreesChange`.
 */
const load = () => {
  const raw = import.meta.glob('./trees/*.mmd', { query: '?raw', import: 'default', eager: true })
  return {
    projected: raw['./trees/projected.mmd'] ?? '',
    master: raw['./trees/master.mmd'] ?? '',
  }
}

export let trees = load()

const subscribers = new Set()

/** Register a callback fired with the new sources whenever a .mmd changes on disk. */
export function onTreesChange(fn) {
  subscribers.add(fn)
  return () => subscribers.delete(fn)
}

if (import.meta.hot) {
  // Self-accept. The callback runs in the OLD module instance — which still holds the
  // subscriber set — and receives the NEW module's exports. That is what stops the reload.
  import.meta.hot.accept((next) => {
    if (!next) return
    trees = next.trees
    subscribers.forEach((fn) => fn(next.trees))
  })
}
