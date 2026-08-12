/**
 * viz/lab/animeditor.js — centre view 3: create and edit animations.
 *
 * Why it exists : animations are first-class saved entities; they need an authoring
 *                 surface the way configs need the Mapper. Generators are previewed
 *                 here and parameterised in the inspector; frames are PAINTED here —
 *                 click/drag pads with a brush colour, frame by frame.
 * Layer it owns : animation presentation + paint gestures + transport. All mutation
 *                 goes through store actions (updateAnimFrames, selectAnimFrame);
 *                 all math comes from anim.js; properties/params belong to the
 *                 inspector, exactly like the Mapper/pad-properties split.
 * Who calls it  : lab.js, once at boot, with the <section id="stage-anim"> element.
 * What it returns: nothing — it renders into rootEl and stays subscribed to the store.
 */
import { PAD_IDS, padKind } from './schema.js'
import { ledHex, paletteHex, paletteIndices } from './palette.js'
import { animationFrame, animationDuration, framesTotalMs } from './anim.js'
import { store, updateAnimFrames, selectAnimFrame } from './store.js'

/** Preview window for endless animations — the scrub bar needs SOME finite length. */
const ENDLESS_PREVIEW_MS = 8000
const LED_OFF_HEX = '#101013'
const DEFAULT_BRUSH = 5 // red in the candidate palette — visible on a black surface
const PALETTE_COLUMNS = 16

/* ═══════════════════════════════════════════════════════════════ module state */

const cellEls = new Map() // padId → cell element
let rootEl = null
let stageEl = null
let nameEl = null
let engineEl = null
let playBtn = null
let timeEl = null
let scrubEl = null
let toolbarEl = null
let stripEl = null
let brushBtn = null
let brushChip = null
let eraseBtn = null
let popEl = null // open palette popover, or null

let playing = false
let rafId = 0
let t = 0 // preview time, ms
let playWallStart = 0
let playTStart = 0
let brush = DEFAULT_BRUSH
let erasing = false
let painting = false // a paint drag is in flight

/* Render-loop economy (mirrors grid.js): frames change 30×/s, displays run 60+ Hz.
   Gate recomputes to tick boundaries and diff every style write. */
let lastTickIdx = -1
const lastHex = new Map() // padId → the background we last wrote

/* ══════════════════════════════════════════════════════════════════════ boot */

export function initAnimEditor(el) {
  rootEl = el
  rootEl.classList.add('ae-root')
  rootEl.innerHTML = ''
  rootEl.append(buildHeader(), buildToolbar(), buildStage())

  store.on('anim:loaded', () => {
    stopPlayback()
    t = 0
    refreshAll()
  })
  store.on('anim:changed', () => refreshAll())
  store.on('animframe:selected', () => {
    refreshStrip()
    paintBoard()
  })
  // Painting only makes sense while the pane is visible; pause when leaving it.
  store.on('view:changed', (view) => {
    if (view !== 'anim') stopPlayback()
  })
  window.addEventListener('pointerup', () => (painting = false))
  document.addEventListener('click', (e) => {
    if (popEl && !popEl.contains(e.target) && !brushBtn.contains(e.target)) closePop()
  })

  refreshAll()
}

/* ═══════════════════════════════════════════════════════════════ DOM building */

function buildHeader() {
  const head = document.createElement('header')
  head.className = 'ae-head'

  nameEl = document.createElement('span')
  nameEl.className = 'ae-name'
  engineEl = document.createElement('span')
  engineEl.className = 'ae-chip'

  playBtn = document.createElement('button')
  playBtn.type = 'button'
  playBtn.className = 'ae-btn'
  playBtn.addEventListener('click', () => (playing ? stopPlayback() : startPlayback()))

  timeEl = document.createElement('span')
  timeEl.className = 'ae-time'

  scrubEl = document.createElement('input')
  scrubEl.type = 'range'
  scrubEl.className = 'ae-scrub'
  scrubEl.min = '0'
  scrubEl.step = '33' // one 30 fps tick
  scrubEl.addEventListener('input', () => {
    stopPlayback()
    t = Number(scrubEl.value)
    paintBoard()
    refreshTransport()
  })

  head.append(nameEl, engineEl, playBtn, scrubEl, timeEl)
  return head
}

/** Frames-only strip: brush, eraser, and one chip per frame. Hidden for generators. */
function buildToolbar() {
  toolbarEl = document.createElement('div')
  toolbarEl.className = 'ae-toolbar'

  brushBtn = document.createElement('button')
  brushBtn.type = 'button'
  brushBtn.className = 'ae-btn ae-brush'
  brushChip = document.createElement('span')
  brushChip.className = 'ae-brush-chip'
  brushChip.style.background = paletteHex(brush) // palette is loaded before panels boot
  brushBtn.append(brushChip, document.createTextNode('Brush'))
  brushBtn.title = 'Brush colour — click a pad to paint it into the current frame'
  brushBtn.addEventListener('click', () => (popEl ? closePop() : openPop()))

  eraseBtn = document.createElement('button')
  eraseBtn.type = 'button'
  eraseBtn.className = 'ae-btn'
  eraseBtn.textContent = 'Erase'
  eraseBtn.title = 'Eraser — click a painted pad to make it transparent again'
  eraseBtn.addEventListener('click', () => {
    erasing = !erasing
    eraseBtn.classList.toggle('ae-on', erasing)
  })

  stripEl = document.createElement('div')
  stripEl.className = 'ae-strip'

  toolbarEl.append(brushBtn, eraseBtn, stripEl)
  return toolbarEl
}

function buildStage() {
  stageEl = document.createElement('div')
  stageEl.className = 'ae-stage'

  const empty = document.createElement('p')
  empty.className = 'ae-empty'
  empty.textContent = 'open or create an animation in the library'

  const board = document.createElement('div')
  board.className = 'ae-board'
  for (let row = 9; row >= 1; row--) {
    for (let col = 1; col <= 9; col++) {
      const id = String(row * 10 + col)
      const cell = document.createElement('button')
      cell.type = 'button'
      cell.className = `ae-pad ae-kind-${padKind(id)}`
      cell.dataset.pad = id
      // Paint gestures: press starts a stroke, dragging across pads continues it.
      cell.addEventListener('pointerdown', (e) => {
        e.preventDefault()
        painting = true
        applyBrush(id)
      })
      cell.addEventListener('pointerenter', () => {
        if (painting) applyBrush(id)
      })
      cellEls.set(id, cell)
      board.append(cell)
    }
  }

  stageEl.append(empty, board)
  return stageEl
}

/* ═══════════════════════════════════════════════════════════════════ painting */

function applyBrush(id) {
  const anim = store.state.anim
  if (!anim || anim.engine !== 'frames' || playing) return
  const frames = structuredClone(anim.frames ?? [])
  const frame = frames[store.state.animFrame]
  if (!frame) return
  frame.pads ??= {}
  if (erasing) delete frame.pads[id]
  else frame.pads[id] = { type: 'static', palette: brush }
  updateAnimFrames(frames) // marks dirty, echoes anim:changed → board repaints
}

/* ═══════════════════════════════════════════════════════════════════ rendering */

function refreshAll() {
  const anim = store.state.anim
  stageEl.classList.toggle('ae-no-anim', !anim)
  rootEl.classList.toggle('ae-frames', anim?.engine === 'frames')
  nameEl.textContent = anim ? anim.name || anim.id : 'no animation open'
  nameEl.classList.toggle('ae-muted', !anim)
  engineEl.textContent = anim?.engine ?? ''
  engineEl.hidden = !anim
  playBtn.disabled = !anim
  scrubEl.disabled = !anim
  refreshStrip()
  refreshTransport()
  paintBoard()
}

/** How long the scrub bar represents. Endless animations preview a fixed window. */
function previewDuration() {
  const anim = store.state.anim
  if (!anim) return ENDLESS_PREVIEW_MS
  if (anim.engine === 'frames') return Math.max(framesTotalMs(anim), 33)
  return animationDuration(anim) ?? ENDLESS_PREVIEW_MS
}

function refreshTransport() {
  const dur = previewDuration()
  scrubEl.max = String(dur)
  scrubEl.value = String(Math.min(t % (dur + 1), dur))
  playBtn.textContent = playing ? '■ Pause' : '▶ Play'
  const endless = store.state.anim && animationDuration(store.state.anim) == null && store.state.anim.engine === 'generator'
  timeEl.textContent = `${(t / 1000).toFixed(1)} s${endless ? ' · endless' : ` / ${(dur / 1000).toFixed(1)} s`}`
}

function refreshStrip() {
  stripEl.innerHTML = ''
  const anim = store.state.anim
  if (!anim || anim.engine !== 'frames') return
  const frames = anim.frames ?? []
  const selected = store.state.animFrame

  frames.forEach((frame, i) => {
    const chip = document.createElement('button')
    chip.type = 'button'
    chip.className = 'ae-frame'
    if (i === selected) chip.classList.add('ae-on')
    chip.textContent = String(i + 1)
    chip.title = `Frame ${i + 1} — ${frame.duration_ms} ms, ${Object.keys(frame.pads ?? {}).length} pads`
    chip.addEventListener('click', () => {
      stopPlayback()
      selectAnimFrame(i)
    })
    stripEl.append(chip)
  })

  stripEl.append(
    stripBtn('+', 'Add a frame (copies the current one) after the current frame', () => {
      const frames = structuredClone(store.state.anim.frames)
      const at = store.state.animFrame
      frames.splice(at + 1, 0, structuredClone(frames[at]))
      updateAnimFrames(frames)
      selectAnimFrame(at + 1)
    }),
    stripBtn('✕', 'Delete the current frame', () => {
      const frames = structuredClone(store.state.anim.frames)
      if (frames.length <= 1) return // an empty animation is a schema violation — keep one
      frames.splice(store.state.animFrame, 1)
      updateAnimFrames(frames) // store clamps the selected index
    }),
  )
}

function stripBtn(glyph, title, onClick) {
  const btn = document.createElement('button')
  btn.type = 'button'
  btn.className = 'ae-frame ae-frame-op'
  btn.textContent = glyph
  btn.title = title
  btn.addEventListener('click', onClick)
  return btn
}

/**
 * The board shows the EDIT surface when a frames animation is paused (the selected
 * frame, paintable) and the PLAYBACK composite otherwise (whatever anim.js computes
 * for time t). Unpainted cells render LED-off: this pane previews the animation
 * alone — compositing with a screen's pads is the Mapper's job.
 */
function paintBoard() {
  const anim = store.state.anim
  if (!anim) return
  let frame
  if (anim.engine === 'frames' && !playing) {
    frame = new Map(Object.entries(anim.frames?.[store.state.animFrame]?.pads ?? {}))
  } else {
    frame = animationFrame(anim, t) ?? new Map()
  }
  for (const id of PAD_IDS) {
    const spec = frame.get(id)
    const hex = spec ? ledHex(spec) : LED_OFF_HEX
    if (lastHex.get(id) !== hex) {
      lastHex.set(id, hex)
      cellEls.get(id).style.background = hex
    }
  }
}

/* ═══════════════════════════════════════════════════════════════════ playback */

function startPlayback() {
  if (!store.state.anim || playing) return
  playing = true
  painting = false
  playWallStart = performance.now()
  playTStart = t
  rafId = requestAnimationFrame(tickPlay)
  refreshTransport()
}

function stopPlayback() {
  playing = false
  if (rafId) cancelAnimationFrame(rafId)
  rafId = 0
  refreshTransport()
  paintBoard() // frames engine: drop back to the editable selected frame
}

function tickPlay(now) {
  rafId = 0
  if (!playing) return
  const anim = store.state.anim
  t = playTStart + (now - playWallStart)
  const end = anim ? animationDuration(anim) : null
  if (end != null && t >= end) {
    t = end
    stopPlayback() // a one-shot ran out — park the head at the end
    return
  }
  const dur = previewDuration()
  if (t > dur && end == null) {
    // Endless preview: wrap the WINDOW, not the animation — t keeps its true value
    // modulo the window so generator streams (sweep counters etc.) stay honest.
    playTStart -= dur
    t -= dur
  }
  // Frames only change on 30 fps ticks — between ticks a rAF call is one compare.
  // The transport readout rides the same gate; nobody needs a 60 Hz time label.
  const tickIdx = Math.floor((t * 30) / 1000)
  if (tickIdx !== lastTickIdx) {
    lastTickIdx = tickIdx
    paintBoard()
    refreshTransport()
  }
  rafId = requestAnimationFrame(tickPlay)
}

/* ═══════════════════════════════════════════════════════ brush palette popover */

function openPop() {
  closePop()
  popEl = document.createElement('div')
  popEl.className = 'ae-pop'
  const grid = document.createElement('div')
  grid.className = 'ae-pop-grid'
  grid.style.gridTemplateColumns = `repeat(${PALETTE_COLUMNS}, 1fr)`
  for (const i of paletteIndices()) {
    const cell = document.createElement('button')
    cell.type = 'button'
    cell.className = i === brush ? 'ae-pop-cell ae-on' : 'ae-pop-cell'
    cell.title = String(i)
    cell.style.background = paletteHex(i)
    cell.addEventListener('click', () => {
      brush = i
      erasing = false
      eraseBtn.classList.remove('ae-on')
      brushChip.style.background = paletteHex(brush)
      closePop()
    })
    grid.append(cell)
  }
  popEl.append(grid)
  toolbarEl.append(popEl)
  brushChip.style.background = paletteHex(brush)
}

function closePop() {
  popEl?.remove()
  popEl = null
}
