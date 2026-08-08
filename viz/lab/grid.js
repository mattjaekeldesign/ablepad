/**
 * viz/lab/grid.js — the on-screen Launchpad X.
 *
 * Why it exists : the Lab needs a faithful 9×9 surface to click on — edit mode selects
 *                 pads for the inspector, simulate mode runs LED feedback + hold gates
 *                 exactly as the rig will, minus the hardware.
 * Layer it owns : grid presentation + press simulation. No config mutation beyond the
 *                 store actions it calls (selectPad, openConfig); no fetch, no schema logic.
 * Who calls it  : lab.js, once at boot via initGrid(rootEl), after palette + library load.
 * What it returns: nothing — it renders into rootEl and stays subscribed to the store.
 *
 * Pad numbering and layout follow programmer mode (docs/launchpad-x-sysex.md §5):
 * row 9 on top (CC 91–98, logo 99 top-right), rows 8→1 below, col 9 the right CC column.
 * The 81 pad elements are built ONCE; every repaint only restyles them.
 */
import { PAD_IDS, padKind, padIsButton, ACTIONS } from './schema.js'
import { ledHex, paletteIsUnverified } from './palette.js'
import { store, selectPad, openConfig, toast } from './store.js'

/* ═══════════════════════════════════════════════════════════ timing constants */

// Free-run animation periods (docs/launchpad-x-sysex.md §6): flash/pulse are beat-clock
// slaved on hardware; unclocked they free-run at 120 BPM → flash 0.5 s, pulse 1 s.
const FLASH_PERIOD_MS = 500 // alternates palette/paletteB, 50% duty
const PULSE_PERIOD_MS = 1000 // dark↔full brightness ramp

/** What an unlit LED looks like — matches palette.js's index-0 rendering. */
const LED_OFF_HEX = '#101013'

/* ═══════════════════════════════════════════════════════════════ module state */

const padEls = new Map() // padId → { root, label } — built once in buildBoard()
const animated = new Map() // padId → led spec currently needing per-frame colour
let rafId = 0 // the ONE requestAnimationFrame handle; 0 = loop stopped

let press = null // sim press in flight: { padId, startedAt, holdMs, fired }
let holdRingEl = null // single progress-ring overlay, moved onto whichever pad is held

let stageEl = null
let boardEl = null
let nameEl = null
let simBadgeEl = null

/* ══════════════════════════════════════════════════════════════════════ boot */

/** Build the DOM once, subscribe to the store, paint the current state. */
export function initGrid(rootEl) {
  rootEl.classList.add('lg-root')
  rootEl.innerHTML = ''
  rootEl.append(buildHeader(), buildStage())

  store.on('config:loaded', () => {
    cancelPress() // the surface under the finger just changed meaning
    paintAll()
  })
  store.on('config:changed', (payload) => {
    if (payload?.padId) paintPad(payload.padId)
    else paintAll() // name / background / bulk edits
  })
  store.on('pad:selected', showSelection)
  store.on('sim:changed', (on) => {
    cancelPress()
    simBadgeEl.classList.toggle('lg-on', on)
    stageEl.classList.toggle('lg-simming', on)
  })

  paintAll()
  showSelection(store.state.selectedPad)
}

/* ═══════════════════════════════════════════════════════════════ DOM building */

/** Header strip: config name, SIM badge, and the palette-truth disclaimer. */
function buildHeader() {
  const head = document.createElement('header')
  head.className = 'lg-head'

  nameEl = document.createElement('span')
  nameEl.className = 'lg-name'

  simBadgeEl = document.createElement('span')
  simBadgeEl.className = 'lg-sim-badge'
  simBadgeEl.textContent = 'SIM'

  head.append(nameEl, simBadgeEl)

  // Honesty tax: the colour table is sampled from the Mini MK3 manual (palette.js header).
  if (paletteIsUnverified()) {
    const legend = document.createElement('span')
    legend.className = 'lg-legend'
    legend.textContent = 'palette UNVERIFIED — Mini MK3 candidate table'
    head.append(legend)
  }
  return head
}

/** The flexing pane: empty-state message + the 9×9 board, centred and square. */
function buildStage() {
  stageEl = document.createElement('div')
  stageEl.className = 'lg-stage'

  const empty = document.createElement('p')
  empty.className = 'lg-empty'
  empty.textContent = 'open a config from the library'

  stageEl.append(empty, buildBoard())

  // Edit mode: clicking past the pads deselects. Sim mode never touches selection.
  stageEl.addEventListener('click', (e) => {
    if (!store.state.sim && !e.target.closest('.lg-pad')) selectPad(null)
  })
  return stageEl
}

/**
 * 81 pads in display order: row 9 first (top), then 8→1; cols always 1→9 so the
 * CC column and logo land on the right edge. CSS grid does the placement.
 */
function buildBoard() {
  boardEl = document.createElement('div')
  boardEl.className = 'lg-board'

  for (let row = 9; row >= 1; row--) {
    for (let col = 1; col <= 9; col++) {
      const id = String(row * 10 + col)
      boardEl.append(buildPad(id))
    }
  }
  return boardEl
}

function buildPad(id) {
  const root = document.createElement('button')
  root.type = 'button'
  root.className = `lg-pad lg-kind-${padKind(id)}`
  root.dataset.pad = id

  const idEl = document.createElement('span')
  idEl.className = 'lg-pad-id'
  idEl.textContent = id

  const label = document.createElement('span')
  label.className = 'lg-pad-label'

  root.append(idEl, label)
  padEls.set(id, { root, label })

  root.addEventListener('click', (e) => {
    e.stopPropagation()
    if (!store.state.sim) selectPad(id) // logo included: LED-only editing is legitimate
  })
  root.addEventListener('pointerdown', (e) => onSimPress(e, id))
  root.addEventListener('pointerup', onSimRelease)
  root.addEventListener('pointercancel', onSimRelease)

  return root
}

/* ═══════════════════════════════════════════════════════════════════ painting */

/**
 * The LED spec a pad should show right now: sim-pressed override first, then the
 * pad's idle binding, then the config background. Bound-but-stateless falls to 'off',
 * never to background — a binding claims the pad.
 */
function ledFor(id) {
  const config = store.state.config
  if (!config) return { type: 'off' }
  const pad = config.pads?.[id]
  if (store.state.sim && press?.padId === id && pad)
    return pad.led?.pressed ?? pad.led?.idle ?? { type: 'off' }
  if (pad) return pad.led?.idle ?? { type: 'off' }
  return config.background ?? { type: 'off' }
}

/** Restyle one pad and (de)register it with the animation loop. Cheap by design. */
function paintPad(id) {
  const refs = padEls.get(id)
  if (!refs) return
  const config = store.state.config
  const led = ledFor(id)

  if (led.type === 'flash' || led.type === 'pulse') {
    animated.set(id, led)
    refs.root.style.background = animColor(led, performance.now())
    ensureLoop()
  } else {
    animated.delete(id)
    refs.root.style.background = ledHex(led)
  }

  const pad = config?.pads?.[id]
  refs.label.textContent = pad?.label ?? ''
  refs.root.classList.toggle('lg-bound', !!pad)
}

/** Full repaint + header refresh. Still just 81 restyles — no DOM rebuilding. */
function paintAll() {
  const config = store.state.config
  stageEl.classList.toggle('lg-no-config', !config)
  nameEl.textContent = config ? config.name : 'no config open'
  nameEl.classList.toggle('lg-muted', !config)
  animated.clear()
  for (const id of PAD_IDS) paintPad(id)
}

function showSelection(padId) {
  for (const { root } of padEls.values()) root.classList.remove('lg-selected')
  if (padId) padEls.get(padId)?.root.classList.add('lg-selected')
}

/* ═══════════════════════════════════════════════════════════ animation loop */

/** Colour of a flash/pulse LED at time `now`. Static/off/rgb never reach here. */
function animColor(led, now) {
  if (led.type === 'flash') {
    const phase = now % FLASH_PERIOD_MS < FLASH_PERIOD_MS / 2 ? 'a' : 'b'
    return ledHex(led, phase)
  }
  // Pulse: triangle wave 0→1→0 across the period, blended dark↔full.
  const p = (now % PULSE_PERIOD_MS) / PULSE_PERIOD_MS
  return mixHex(LED_OFF_HEX, ledHex(led), 1 - Math.abs(p * 2 - 1))
}

/** The loop runs only while something on screen actually moves. */
function loopNeeded() {
  return animated.size > 0 || (press !== null && press.holdMs > 0 && !press.fired)
}

function ensureLoop() {
  if (!rafId && loopNeeded()) rafId = requestAnimationFrame(tick)
}

function tick(now) {
  rafId = 0
  for (const [id, led] of animated) {
    const refs = padEls.get(id)
    if (refs) refs.root.style.background = animColor(led, now)
  }
  if (press && press.holdMs > 0 && !press.fired) advanceHold(now)
  if (loopNeeded()) rafId = requestAnimationFrame(tick)
}

/** Linear blend of two CSS colours. Accepts #rrggbb and rgb(r, g, b) (ledHex emits both). */
function mixHex(from, to, t) {
  const a = parseColor(from)
  const b = parseColor(to)
  const ch = (i) => Math.round(a[i] + (b[i] - a[i]) * t)
  return `rgb(${ch(0)}, ${ch(1)}, ${ch(2)})`
}

function parseColor(str) {
  if (str.startsWith('#'))
    return [parseInt(str.slice(1, 3), 16), parseInt(str.slice(3, 5), 16), parseInt(str.slice(5, 7), 16)]
  const m = str.match(/(\d+)\D+(\d+)\D+(\d+)/)
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : [0, 0, 0]
}

/* ═══════════════════════════════════════════════════════════ simulate mode */

/**
 * pointerdown = the hardware's Note On (velocity > 0). Pressed LED shows immediately;
 * the action fires now (no hold gate) or after hold_ms of sustained pressure.
 */
function onSimPress(e, id) {
  if (!store.state.sim || !store.state.config) return
  if (!padIsButton(id)) return // the logo is light-only — it never sends events
  cancelPress() // a stray second pointer replaces, never stacks

  const action = store.state.config.pads?.[id]?.action
  const armed = action && action.type !== 'NONE'
  const holdMs = armed ? (action.hold_ms ?? 0) : 0

  e.currentTarget.setPointerCapture(e.pointerId) // release lands on us even off-pad
  press = { padId: id, startedAt: performance.now(), holdMs, fired: false }
  padEls.get(id).root.classList.add('lg-pressed')
  paintPad(id) // pressed LED override

  if (!armed) return
  if (holdMs > 0) {
    attachHoldRing(id)
    ensureLoop()
  } else {
    press.fired = true
    fireAction(action) // no gate → fires instantly on press
  }
}

/**
 * pointerup = the hardware's release — a Note On with velocity 0, NOT a Note Off
 * (docs/launchpad-x-sysex.md §5). Same semantic here: releasing before the hold
 * gate completes cancels the action; the pad drops back to idle either way.
 */
function onSimRelease() {
  if (!press) return
  const id = press.padId
  press = null
  detachHoldRing()
  padEls.get(id)?.root.classList.remove('lg-pressed')
  paintPad(id)
}

/** Abort any in-flight press without firing — mode toggles and config swaps call this. */
function cancelPress() {
  if (press) onSimRelease()
}

function advanceHold(now) {
  const progress = (now - press.startedAt) / press.holdMs
  if (progress < 1) {
    holdRingEl?.style.setProperty('--lg-progress', progress)
    return
  }
  press.fired = true
  detachHoldRing()
  fireAction(store.state.config?.pads?.[press.padId]?.action)
}

/* ── hold-progress ring: one element, parked on whichever pad is gating ── */

function attachHoldRing(padId) {
  if (!holdRingEl) {
    holdRingEl = document.createElement('span')
    holdRingEl.className = 'lg-hold-ring'
  }
  holdRingEl.style.setProperty('--lg-progress', 0)
  padEls.get(padId).root.append(holdRingEl)
}

function detachHoldRing() {
  holdRingEl?.remove()
}

/* ─────────────────────────────── action firing ─────────────────────────────── */

/**
 * The Lab SIMULATES actions, it does not execute them — a toast is the whole payload.
 * The one exception is SWITCH_MODE, which the Lab can honour for real by opening the
 * target config, because that is exactly what the rig's mode machine will do.
 */
function fireAction(action) {
  const type = action?.type ?? 'NONE'
  if (type === 'NONE') return

  if (type === 'SWITCH_MODE') {
    const target = action.params?.target
    if (!target) return toast('warn', 'Switch mode: no target mode set')
    if (!store.state.library.some((c) => c.id === target))
      return toast('warn', `Switch mode: "${target}" is not in the library`)
    openConfig(target)
      .then(() => toast('ok', `→ switched to ${target}`))
      .catch((err) => toast('warn', `Switch mode failed: ${err?.message ?? err}`))
    return
  }

  toast('ok', `▶ ${ACTIONS[type]?.label ?? type}${paramSummary(action)}`)
}

/** " · slot=3" style suffix so the toast says what would have happened, exactly. */
function paramSummary(action) {
  const entries = Object.entries(action.params ?? {}).filter(([, v]) => v !== '' && v != null)
  return entries.length ? ` · ${entries.map(([k, v]) => `${k}=${v}`).join(' ')}` : ''
}
