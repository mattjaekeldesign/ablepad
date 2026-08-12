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
import { store, selectPad, openConfig, resolveAnimation, toast } from './store.js'
import { animationFrame } from './anim.js'

/* ═══════════════════════════════════════════════════════════ timing constants */

// Free-run animation periods (docs/launchpad-x-sysex.md §6): flash/pulse are beat-clock
// slaved on hardware; unclocked they free-run at 120 BPM → flash 0.5 s, pulse 1 s.
const FLASH_PERIOD_MS = 500 // alternates palette/paletteB, 50% duty
const PULSE_PERIOD_MS = 1000 // dark↔full brightness ramp

/** What an unlit LED looks like — matches palette.js's index-0 rendering. */
const LED_OFF_HEX = '#101013'

/**
 * Failsafe: an intro that never reports "finished" (loop on, or no duration) would
 * cover the surface forever. The rig must never feel bricked by eye candy — hard cap.
 */
const INTRO_MAX_MS = 15000

/* ═══════════════════════════════════════════════════════════════ module state */

const padEls = new Map() // padId → { root, label } — built once in buildBoard()
const animated = new Map() // padId → led spec currently needing per-frame colour
let rafId = 0 // the ONE requestAnimationFrame handle; 0 = loop stopped

/* Screen-animation compositor state. The stack, top first:
     intro (full cover) → sim-pressed LED → during 'over' → bound pads → during 'under'
     (unbound pads only) → background.
   Specs are resolved animation objects; the open working copy resolves live, so
   editing an animation animates the mapper in real time. */
let introAnim = null // playing intro, or null
let introStart = 0
let duringAnim = null // looping ambient, or null
let duringLayer = 'under'
let duringStart = 0
let overlay = null // this tick's composite: { frame: Map, cover, layer } | null
let armToken = 0 // guards against a stale async resolve landing after a config switch

/* Render-loop economy. Screen animations only change 30×/s (ANIM_TICK_MS), so:
   - lastTickIdx gates frame recomputes to tick boundaries, not 60 Hz rAF;
   - lastHex makes every style write a diff — a pad the frame didn't change
     costs a string compare, not a browser restyle;
   - gridVisible parks the whole loop while another centre view is showing. */
let lastTickIdx = -1
const lastHex = new Map() // padId → the background we last wrote
let gridVisible = true // the Mapper section is the visible centre view

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
    armAnimations({ intro: store.state.sim }) // mode entry — repaints when resolved
    paintAll()
  })
  store.on('config:changed', (payload) => {
    if (payload?.padId) paintPad(payload.padId)
    else {
      armAnimations({ intro: false }) // animation slots may have changed; never replay intro
      paintAll() // name / background / bulk edits
    }
  })
  store.on('pad:selected', showSelection)
  store.on('sim:changed', (on) => {
    cancelPress()
    simBadgeEl.classList.toggle('lg-on', on)
    stageEl.classList.toggle('lg-simming', on)
    armAnimations({ intro: on }) // entering sim = entering the mode: intro plays
  })
  // Live preview: the open animation IS the resolved object when referenced, but a
  // fresh open/save/delete changes which object the refs resolve to — re-arm.
  store.on('anim:loaded', () => armAnimations({ intro: false }))
  store.on('anim:changed', () => ensureLoop()) // same object mutated — just keep ticking
  store.on('animlib:changed', () => armAnimations({ intro: false }))
  // Park the loop while Flow/Anim is showing — a hidden Mapper must cost nothing.
  store.on('view:changed', (view) => {
    gridVisible = view === 'grid'
    if (gridVisible) {
      paintAll() // catch up on whatever moved while we were parked
      ensureLoop()
    } else if (rafId) {
      cancelAnimationFrame(rafId)
      rafId = 0
    }
  })

  paintAll()
  showSelection(store.state.selectedPad)
}

/* ═══════════════════════════════════════════════════════ screen animations */

/**
 * Resolve the open config's intro/during refs into playable specs. Async because a
 * ref may need a fetch; the token discards a resolve that a config switch outran.
 * Dangling refs resolve to null and simply do not play — never an error mid-set.
 */
async function armAnimations({ intro }) {
  const token = ++armToken
  const slots = store.state.config?.animations
  const wantDuring = slots?.during?.ref ?? null
  const wantIntro = intro ? (slots?.intro?.ref ?? null) : null

  const [nextDuring, nextIntro] = await Promise.all([
    wantDuring ? resolveAnimation(wantDuring).catch(() => null) : null,
    wantIntro ? resolveAnimation(wantIntro).catch(() => null) : null,
  ])
  if (token !== armToken) return // a newer arm superseded this one

  const now = performance.now()
  duringAnim = nextDuring
  duringLayer = slots?.during?.layer ?? 'under'
  duringStart = now
  introAnim = nextIntro
  introStart = now
  ensureLoop()
  if (!rafId) paintAll() // nothing animates (e.g. slots cleared) — still repaint once
}

/** The composite frame for this instant, or null when no screen animation shows. */
function computeOverlay(now) {
  if (introAnim) {
    const t = now - introStart
    const frame = t < INTRO_MAX_MS ? animationFrame(introAnim, t) : null
    if (frame) return { frame, cover: true }
    endIntro(now) // finished (or hit the failsafe cap) — reveal the mode
  }
  if (duringAnim) {
    const frame = animationFrame(duringAnim, now - duringStart)
    if (frame) return { frame, cover: false, layer: duringLayer }
    duringAnim = null // a non-looping 'during' ran out — back to the static screen
  }
  return null
}

/** Intro over (finished, capped, or skipped by a press): the during-loop starts NOW. */
function endIntro(now) {
  introAnim = null
  duringStart = now
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

/**
 * What the current screen-animation overlay contributes to pad `id`, or null to let
 * the pad's own LED show. Unpainted overlay cells are transparent — except an intro,
 * which covers the whole surface (its unpainted cells read as LED off).
 */
function overlaySpecFor(id) {
  if (!overlay) return null
  const spec = overlay.frame.get(id)
  if (overlay.cover) return spec ?? { type: 'off' } // intro: full cover
  if (!spec) return null
  if (store.state.sim && press?.padId === id) return null // pressed feedback beats ambient
  if (overlay.layer === 'over') return spec
  return store.state.config?.pads?.[id] ? null : spec // 'under': bound pads win
}

/** Write a pad background ONLY if it differs from what is already on screen. */
function setPadColor(id, hex) {
  if (lastHex.get(id) === hex) return
  lastHex.set(id, hex)
  const refs = padEls.get(id)
  if (refs) refs.root.style.background = hex
}

/** The colour a pad shows at `now` — overlay first, then its own LED. No DOM. */
function padHexAt(id, now) {
  const led = overlaySpecFor(id) ?? ledFor(id)
  return led.type === 'flash' || led.type === 'pulse' ? animColor(led, now) : ledHex(led)
}

/**
 * Restyle one pad and (de)register it with the animation loop. Cheap by design.
 *
 * Two different questions, deliberately answered from two different LEDs:
 *   what the pad IS   → `own`, its own binding. Decides whether it needs animating.
 *   what is ON SCREEN → `shown`, the overlay composited over it. Decides the colour.
 *
 * Keeping these apart matters. A screen animation HIDES a flash/pulse pad; it does not
 * cancel it. Registering from the composite deregisters every flash/pulse pad for as
 * long as an intro covers the surface — and when the intro ends, `animated` is empty,
 * loopNeeded() goes false, the loop stops, and every flash/pulse pad is stranded
 * mid-phase with no repaint to rescue it.
 */
function paintPad(id, now = performance.now()) {
  const refs = padEls.get(id)
  if (!refs) return
  const config = store.state.config
  const own = ledFor(id)
  const shown = overlaySpecFor(id) ?? own

  const ownAnimates = own.type === 'flash' || own.type === 'pulse'
  if (ownAnimates) animated.set(id, own)
  else animated.delete(id)

  const shownAnimates = shown.type === 'flash' || shown.type === 'pulse'
  setPadColor(id, shownAnimates ? animColor(shown, now) : ledHex(shown))
  if (ownAnimates) ensureLoop()

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
  overlay = computeOverlay(performance.now())
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
  return (
    animated.size > 0 ||
    introAnim !== null ||
    duringAnim !== null ||
    (press !== null && press.holdMs > 0 && !press.fired)
  )
}

function ensureLoop() {
  if (!rafId && loopNeeded()) rafId = requestAnimationFrame(tick)
}

function tick(now) {
  rafId = 0
  if (!gridVisible) return // parked — view:changed restarts us

  if (introAnim || duringAnim || overlay) {
    // Screen animation running: frames only change on 30 fps tick boundaries, so
    // rAF calls between ticks (60+ Hz displays) cost one integer compare and exit.
    // On a tick: recompute the composite, diff-paint the surface — setPadColor
    // touches only pads whose colour actually changed this frame.
    const tickIdx = Math.floor((now * 30) / 1000)
    if (tickIdx !== lastTickIdx) {
      lastTickIdx = tickIdx
      overlay = store.state.config ? computeOverlay(now) : null
      for (const id of PAD_IDS) setPadColor(id, padHexAt(id, now))
    }
  } else if (animated.size) {
    // No screen animation — just flash/pulse pads, smooth at full rAF rate.
    for (const [id, led] of animated) setPadColor(id, animColor(led, now))
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
  if (introAnim) {
    // The press SKIPS the intro and is consumed by it — the pad underneath must not
    // fire, because the player couldn't see what they were pressing. Rig rule too.
    endIntro(performance.now())
    paintAll()
    return
  }
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
