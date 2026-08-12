/**
 * viz/lab/store.js — the Lab's single state container.
 *
 * Why it exists : four independent panels (library, grid, inspector, flow) must agree on
 *                 which config is open, which pad is selected, and whether anything is
 *                 unsaved. One store, event-driven — no panel imports another panel.
 * Layer it owns : application state + the actions that mutate it. No DOM.
 * Who calls it  : every UI component. Components subscribe to events and call actions;
 *                 they never write state directly.
 * What it returns: `store` (state + on/emit) and named action functions.
 *
 * Events (payloads in parens):
 *   'library:changed'  (index array)         — the config list was (re)fetched
 *   'config:loaded'    (config)              — a config was opened / reverted
 *   'config:changed'   ({ padId? })          — the open config mutated; padId when pad-scoped
 *   'pad:selected'     (padId | null)        — inspector target changed
 *   'dirty:changed'    (bool)                — unsaved-changes flag flipped
 *   'sim:changed'      (bool)                — simulate mode toggled
 *   'toast'            ({ kind, text })      — user-visible notice ('ok' | 'warn' | 'error')
 *
 *   'animlib:changed'  (index array)         — the animation list was (re)fetched
 *   'anim:loaded'      (anim | null)         — an animation was opened / reverted / closed
 *   'anim:changed'     ({})                  — the open animation mutated
 *   'animdirty:changed'(bool)                — unsaved-animation flag flipped
 *   'animframe:selected'(index)              — the Anim editor's active frame changed
 */
import * as api from './api.js'
import { defaultConfig, defaultPad, defaultAnimation, validateConfig, validateAnimation } from './schema.js'

/* ═══════════════════════════════════════════════════════════════ state + events */

const listeners = new Map() // event → Set<fn>

export const store = {
  state: {
    library: [], // [{ id, name, kind, modified }]
    config: null, // the OPEN config — a working copy; mutations here are unsaved
    dirty: false,
    selectedPad: null, // "11"…"99" or null (null → inspector shows config-level settings)
    sim: false, // simulate mode: grid presses run LED feedback + actions

    animLibrary: [], // [{ id, name, engine, modified }]
    anim: null, // the OPEN animation — a working copy, independent of the open config
    animDirty: false,
    animFrame: 0, // which frame the Anim editor is painting (frames engine)
  },
  on(event, fn) {
    if (!listeners.has(event)) listeners.set(event, new Set())
    listeners.get(event).add(fn)
    return () => listeners.get(event).delete(fn)
  },
  emit(event, payload) {
    for (const fn of listeners.get(event) ?? []) fn(payload)
  },
}

const S = store.state

function setDirty(v) {
  if (S.dirty === v) return
  S.dirty = v
  store.emit('dirty:changed', v)
}

function setAnimDirty(v) {
  if (S.animDirty === v) return
  S.animDirty = v
  store.emit('animdirty:changed', v)
}

export const toast = (kind, text) => store.emit('toast', { kind, text })

/** Anything unsaved anywhere? The topbar dirty flag and beforeunload guard use this. */
export const anyDirty = () => S.dirty || S.animDirty

/** One save entry point for ⌘S and the Save buttons: flush whatever is dirty. */
export async function saveAll() {
  if (S.dirty) await saveConfig()
  if (S.animDirty) await saveAnimation()
}

/* ═══════════════════════════════════════════════════════════════ library actions */

export async function loadLibrary() {
  S.library = await api.listConfigs()
  store.emit('library:changed', S.library)
  return S.library
}

export async function openConfig(id) {
  const config = await api.getConfig(id)
  const { ok, errors } = validateConfig(config)
  if (!ok) toast('warn', `${id}.json has issues: ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1})` : ''}`)
  S.config = config
  S.selectedPad = null
  setDirty(false)
  store.emit('config:loaded', config)
  store.emit('pad:selected', null)
  return config
}

export async function saveConfig() {
  if (!S.config) return
  const { ok, errors } = validateConfig(S.config)
  if (!ok) {
    toast('error', `not saved — ${errors[0]}`)
    return
  }
  await api.putConfig(S.config)
  setDirty(false)
  toast('ok', `saved ${S.config.id}.json`)
  await loadLibrary()
}

export async function createConfig(id, name, kind = 'mode') {
  const config = defaultConfig(id, name, kind)
  await api.putConfig(config)
  await loadLibrary()
  return openConfig(id)
}

export async function duplicateConfig(sourceId, newId, newName) {
  const source = await api.getConfig(sourceId)
  const copy = { ...structuredClone(source), id: newId, name: newName }
  await api.putConfig(copy)
  await loadLibrary()
  return openConfig(newId)
}

export async function deleteConfig(id) {
  await api.deleteConfig(id)
  if (S.config?.id === id) {
    S.config = null
    S.selectedPad = null
    setDirty(false)
    store.emit('config:loaded', null)
    store.emit('pad:selected', null)
  }
  await loadLibrary()
}

/** Throw away unsaved edits by re-fetching from disk. */
export async function revertConfig() {
  if (S.config) await openConfig(S.config.id)
}

/* ═══════════════════════════════════════════════════════════════ editing actions */

/** Objects merge, everything else (arrays, scalars, null) replaces. */
function mergeDeep(target, patch) {
  for (const [k, v] of Object.entries(patch)) {
    if (v && typeof v === 'object' && !Array.isArray(v) && target[k] && typeof target[k] === 'object' && !Array.isArray(target[k])) {
      mergeDeep(target[k], v)
    } else {
      target[k] = v
    }
  }
}

/** Patch one pad. Creates the pad from defaultPad() on first touch (pads are sparse). */
export function updatePad(padId, patch) {
  if (!S.config) return
  if (!S.config.pads[padId]) S.config.pads[padId] = defaultPad()
  mergeDeep(S.config.pads[padId], patch)
  setDirty(true)
  store.emit('config:changed', { padId })
}

/** Remove a pad binding entirely — back to background colour, no action. */
export function clearPad(padId) {
  if (!S.config?.pads[padId]) return
  delete S.config.pads[padId]
  setDirty(true)
  store.emit('config:changed', { padId })
}

/** Patch config-level fields: name, description, background, transitions, notes, meta. */
export function updateConfigMeta(patch) {
  if (!S.config) return
  mergeDeep(S.config, patch)
  setDirty(true)
  store.emit('config:changed', {})
}

/** Replace the transitions array wholesale (flow view edits edges as a unit). */
export function setTransitions(transitions) {
  if (!S.config) return
  S.config.transitions = transitions
  setDirty(true)
  store.emit('config:changed', {})
}

/* ═══════════════════════════════════════════════════════════ animation library
   Mirrors the config lifecycle exactly — a second entity type, same discipline.
   The resolve cache exists for the grid's compositor: screens reference animations
   by id, and repainting must never wait on a fetch mid-frame. */

const animCache = new Map() // id → animation, as last seen on disk

export async function loadAnimLibrary() {
  S.animLibrary = await api.listAnimations()
  store.emit('animlib:changed', S.animLibrary)
  return S.animLibrary
}

export async function openAnimation(id) {
  const anim = await api.getAnimation(id)
  const { ok, errors } = validateAnimation(anim)
  if (!ok) toast('warn', `${id}.json has issues: ${errors[0]}${errors.length > 1 ? ` (+${errors.length - 1})` : ''}`)
  S.anim = anim
  S.animFrame = 0
  setAnimDirty(false)
  store.emit('anim:loaded', anim)
  store.emit('animframe:selected', 0)
  return anim
}

export async function saveAnimation() {
  if (!S.anim) return
  const { ok, errors } = validateAnimation(S.anim)
  if (!ok) {
    toast('error', `not saved — ${errors[0]}`)
    return
  }
  await api.putAnimation(S.anim)
  animCache.set(S.anim.id, structuredClone(S.anim))
  setAnimDirty(false)
  toast('ok', `saved ${S.anim.id}.json`)
  await loadAnimLibrary()
}

export async function createAnimation(id, name, engine) {
  const anim = defaultAnimation(id, name, engine)
  await api.putAnimation(anim)
  await loadAnimLibrary()
  return openAnimation(id)
}

export async function duplicateAnimation(sourceId, newId, newName) {
  const source = await api.getAnimation(sourceId)
  const copy = { ...structuredClone(source), id: newId, name: newName }
  await api.putAnimation(copy)
  await loadAnimLibrary()
  return openAnimation(newId)
}

export async function deleteAnimation(id) {
  await api.deleteAnimationFile(id)
  animCache.delete(id)
  if (S.anim?.id === id) {
    S.anim = null
    setAnimDirty(false)
    store.emit('anim:loaded', null)
  }
  await loadAnimLibrary()
}

export async function revertAnimation() {
  if (S.anim) await openAnimation(S.anim.id)
}

/**
 * Animation for a config's ref, for RENDERING. The open working copy wins so edits
 * preview live on the mapper; otherwise disk, cached until a save/delete replaces it.
 */
export async function resolveAnimation(id) {
  if (S.anim?.id === id) return S.anim
  if (!animCache.has(id)) animCache.set(id, await api.getAnimation(id))
  return animCache.get(id)
}

/** Patch the open animation. Objects merge; arrays and scalars replace (mergeDeep). */
export function updateAnim(patch) {
  if (!S.anim) return
  mergeDeep(S.anim, patch)
  setAnimDirty(true)
  store.emit('anim:changed', {})
}

/** Replace the frame list wholesale — the Anim editor edits frames as a unit. */
export function updateAnimFrames(frames) {
  if (!S.anim) return
  S.anim.frames = frames
  if (S.animFrame >= frames.length) selectAnimFrame(Math.max(0, frames.length - 1))
  setAnimDirty(true)
  store.emit('anim:changed', {})
}

export function selectAnimFrame(index) {
  S.animFrame = index
  store.emit('animframe:selected', index)
}

/* ═══════════════════════════════════════════════════════════════ selection + sim */

export function selectPad(padId) {
  S.selectedPad = padId
  store.emit('pad:selected', padId)
}

export function setSim(on) {
  S.sim = on
  store.emit('sim:changed', on)
}
