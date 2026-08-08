/**
 * viz/main.js — the only JavaScript in this project.
 *
 * Why it exists : renders the projected and master trees, and makes them navigable
 *                 section by section so the roadmap can be read in steps.
 * Layer it owns : presentation only. Knows nothing about MIDI, Ableton or the rig.
 * Who calls it  : viz/index.html via `npm run dev`.
 * What it returns: nothing — it mutates the DOM.
 *
 * Content lives in viz/trees/*.mmd. Sections in the sidebar are DERIVED from the
 * `subgraph` blocks in those files, so adding a section is a .mmd edit, never a JS edit.
 */
import mermaid from 'mermaid'

// Eager raw glob → Vite treats the .mmd files as module deps → saving one hot-reloads.
const SOURCES = import.meta.glob('./trees/*.mmd', { query: '?raw', import: 'default', eager: true })

const TREES = {
  projected: { src: SOURCES['./trees/projected.mmd'], label: 'Plan' },
  master: { src: SOURCES['./trees/master.mmd'], label: 'Truth' },
}

const STATUS_LABEL = {
  done: 'done',
  partial: 'partial',
  todo: 'not started',
  verified: 'verified',
  unverified: 'unverified',
  decision: 'decision',
  branch: 'branch',
  riskhigh: 'high risk',
  next: 'next',
}

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  flowchart: { curve: 'basis', nodeSpacing: 26, rankSpacing: 56, htmlLabels: true, padding: 12 },
  themeVariables: {
    background: '#09090b',
    fontFamily: 'ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif',
    fontSize: '15px',
    lineColor: '#52525b',
    clusterBkg: '#0c0c0f',
    clusterBorder: '#3f3f46',
    titleColor: '#fafafa',
  },
})

/* ═════════════════════════════════════════════════════ parse the .mmd source */

/** Sections are the `subgraph ID["Title"]` blocks. Order in the file = order in the UI. */
function parseSections(src) {
  const out = []
  const re = /^\s*subgraph\s+([A-Za-z0-9_]+)\s*\[\s*"([^"]+)"\s*\]/gm
  let m
  while ((m = re.exec(src))) out.push({ id: m[1], title: m[2] })
  return out
}

/** Status chips in each pane header — counted straight from the `:::class` suffixes. */
function countStatuses(src) {
  const counts = {}
  for (const m of src.matchAll(/:::([a-z]+)/g)) {
    if (m[1] in STATUS_LABEL) counts[m[1]] = (counts[m[1]] ?? 0) + 1
  }
  return counts
}

/* ═════════════════════════════════════════════════════════════════ rendering */

let renderToken = 0

/**
 * Layout is a VIEW concern, so it is rewritten here rather than edited into the .mmd files.
 * "tall"  → each section becomes a narrow vertical column; the doc stacks and stays readable.
 * "wide"  → the section's own `direction LR`; wide rows, good for an overview, hard to read.
 */
function sourceFor(name) {
  const src = TREES[name].src ?? ''
  return layout === 'tall' ? src.replace(/^(\s*)direction\s+LR\s*$/gm, '$1direction TB') : src
}

async function render(name) {
  const canvas = document.getElementById(`canvas-${name}`)
  const src = sourceFor(name)

  if (!src) {
    canvas.innerHTML = `<div class="error">Missing viz/trees/${name}.mmd</div>`
    return
  }

  try {
    const { svg } = await mermaid.render(`mmd-${name}-${renderToken++}`, src)
    canvas.innerHTML = svg
  } catch (err) {
    // A .mmd syntax error must name its file. Silent blank panes waste hours.
    canvas.innerHTML = `<div class="error">${name}.mmd failed to parse\n\n${err?.message ?? err}</div>`
  }

  // Re-read the SVG's intrinsic size — zoom is applied as element size, not as a CSS scale.
  PANES[name]?.syncBase()

  const chips = document.querySelector(`[data-chips="${name}"]`)
  const counts = countStatuses(src)
  chips.innerHTML = Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `<span class="chip"><b>${n}</b> ${STATUS_LABEL[k]}</span>`)
    .join('')
}

/* ═══════════════════════════════════════════════════════ pan / zoom per pane */

// 100% is now the SVG's intrinsic size — since zoom sets element size rather than CSS-scaling,
// 100% renders at mermaid's own 15px type and is already readable. Hence the plain range.
const MIN_K = 0.25 // floor: whole-tree overview
const MAX_K = 1.0 // ceiling: native size
const STEP = 1.12 // button/key step — ~12 clicks across the range
const WHEEL_GAIN = 0.0022 // wheel/trackpad: continuous exponential zoom, no notches

/** Dumb on purpose: no dependency, no inertia, no animation. One transform per pane. */
function attachPanZoom(viewport, onZoom) {
  const canvas = viewport.querySelector('.canvas')
  const t = { x: 0, y: 0, k: MAX_K }
  /**
   * One writer for the transform. `glide` turns on a CSS transition for deliberate jumps
   * (section focus, fit, buttons); direct input — wheel and drag — must never animate or it
   * feels like lag.
   */
  let glideTimer = 0

  /**
   * Zoom is applied as the SVG's own layout SIZE, not as a CSS scale.
   *
   * A CSS `scale()` on an SVG is a raster operation the moment the browser caches the layer —
   * at 488% that is visibly blurry text. Resizing the element instead makes the browser lay the
   * vectors out at the real size, so glyphs are drawn sharp at any zoom. The transform is left
   * doing translation only. Geometry is unchanged: rendered size is still base * k, so every
   * rect/t.k conversion below still holds.
   */
  let baseW = 0
  let baseH = 0

  function syncBase() {
    const svg = canvas.querySelector('svg')
    if (!svg) return
    const vb = svg.viewBox?.baseVal
    baseW = vb?.width || svg.getBoundingClientRect().width
    baseH = vb?.height || svg.getBoundingClientRect().height
    svg.style.maxWidth = 'none'
    apply(false)
  }

  const apply = (glide) => {
    canvas.classList.toggle('glide', !!glide)
    canvas.style.transform = `translate(${t.x}px,${t.y}px)`
    const svg = canvas.querySelector('svg')
    if (svg && baseW) {
      svg.style.width = `${baseW * t.k}px`
      svg.style.height = `${baseH * t.k}px`
    }
    onZoom?.(t.k)
    if (glide) {
      clearTimeout(glideTimer)
      glideTimer = setTimeout(() => canvas.classList.remove('glide'), 340)
    }
  }

  /** Zoom about a point in viewport coordinates. Defaults to the centre of the pane. */
  function zoomAt(factor, px, py, glide = true) {
    const r = viewport.getBoundingClientRect()
    const cx = px ?? r.width / 2
    const cy = py ?? r.height / 2
    const k = Math.min(MAX_K, Math.max(MIN_K, t.k * factor))
    t.x = cx - ((cx - t.x) / t.k) * k
    t.y = cy - ((cy - t.y) / t.k) * k
    t.k = k
    apply(glide)
  }

  // Wheel and trackpad are continuous — exponential in deltaY, so slow scrolls creep and fast
  // scrolls travel. Coalesced into one write per frame so a trackpad flick cannot flood layout.
  let wheelDelta = 0
  let wheelPos = null
  let wheelFrame = 0
  viewport.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault()
      const r = viewport.getBoundingClientRect()
      wheelPos = [e.clientX - r.left, e.clientY - r.top]
      wheelDelta += e.ctrlKey ? e.deltaY * 4 : e.deltaY // ctrl+wheel is a pinch: coarser
      if (wheelFrame) return
      wheelFrame = requestAnimationFrame(() => {
        wheelFrame = 0
        const f = Math.exp(-wheelDelta * WHEEL_GAIN)
        wheelDelta = 0
        zoomAt(f, wheelPos[0], wheelPos[1], false)
      })
    },
    { passive: false },
  )

  // Double-click any box to fill the pane with it. The fastest path to "I can read this".
  viewport.addEventListener('dblclick', (e) => {
    const box = e.target.closest('g.node, g.cluster')
    if (box) frame(box, MAX_K)
  })

  let dragging = false
  let ox = 0
  let oy = 0
  viewport.addEventListener('pointerdown', (e) => {
    dragging = true
    ox = e.clientX - t.x
    oy = e.clientY - t.y
    viewport.classList.add('dragging')
    viewport.setPointerCapture(e.pointerId)
  })
  // Pan writes at most once per frame. Pointer events can outrun the compositor on a trackpad.
  let dragFrame = 0
  viewport.addEventListener('pointermove', (e) => {
    if (!dragging) return
    t.x = e.clientX - ox
    t.y = e.clientY - oy
    if (dragFrame) return
    dragFrame = requestAnimationFrame(() => {
      dragFrame = 0
      apply(false)
    })
  })
  const stop = () => {
    dragging = false
    viewport.classList.remove('dragging')
  }
  viewport.addEventListener('pointerup', stop)
  viewport.addEventListener('pointercancel', stop)

  /** Frame an element that is already inside this canvas. Uses screen rects, no viewBox maths. */
  function frame(el, maxScale) {
    const vp = viewport.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return
    const x = (r.left - vp.left - t.x) / t.k // element position in canvas space at scale 1
    const y = (r.top - vp.top - t.y) / t.k
    const w = r.width / t.k
    const h = r.height / t.k
    const pad = 24
    const k = Math.min((vp.width - pad * 2) / w, (vp.height - pad * 2) / h, maxScale)
    t.k = Math.min(MAX_K, Math.max(MIN_K, k))
    t.x = (vp.width - w * t.k) / 2 - x * t.k
    t.y = (vp.height - h * t.k) / 2 - y * t.k
    apply(true) // deliberate jump — glide to it
  }

  const clearFocus = () => {
    canvas.classList.remove('focusing')
    canvas.querySelectorAll('.is-focused').forEach((n) => n.classList.remove('is-focused'))
  }

  return {
    canvas,
    zoomAt,
    syncBase,
    scale: () => t.k,
    reset() {
      t.x = 0
      t.y = 0
      t.k = MAX_K // 100% — native size
      apply(true)
      clearFocus()
    },
    fit() {
      const svg = canvas.querySelector('svg')
      if (svg) frame(svg, MAX_K) // clamps at the 25% floor on the biggest trees
      clearFocus()
    },
    focus(sectionId, title) {
      const svg = canvas.querySelector('svg')
      if (!svg) return false
      // Mermaid ids each cluster "<diagramId>-<subgraphId>", e.g. "mmd-master-3-MF".
      // Verified against a headless render of mermaid 11. Title match is the fallback.
      const clusters = [...svg.querySelectorAll('g.cluster')]
      const el =
        clusters.find((c) => c.id === sectionId || c.id.endsWith(`-${sectionId}`)) ??
        clusters.find((c) => (c.textContent ?? '').trim().startsWith(title.slice(0, 18)))
      if (!el) return false
      canvas.classList.add('focusing')
      clusters.forEach((c) => c.classList.toggle('is-focused', c === el))
      frame(el, MAX_K)
      return true
    },
  }
}

/** Wire each pane to its own zoom readout so the two panes never share a number. */
function makePane(name) {
  const label = document.querySelector(`[data-zoom="${name}"] .zlabel`)
  const pane = attachPanZoom(
    document.querySelector(`.pane[data-pane="${name}"] .viewport`),
    (k) => (label.textContent = `${Math.round(k * 100)}%`),
  )
  document.querySelectorAll(`[data-zoom="${name}"] .zbtn`).forEach((b) => {
    b.addEventListener('click', () => pane.zoomAt(b.dataset.zdir === 'in' ? STEP : 1 / STEP))
  })
  return pane
}

const PANES = { projected: makePane('projected'), master: makePane('master') }

/* ═══════════════════════════════════════════════════════════ section navigator */

const listEl = document.getElementById('section-list')
const countEl = document.getElementById('section-count')
const stepLabel = document.getElementById('step-label')

let flatSections = [] // [{ tree, id, title }] — the walkable order for the stepper
let cursor = -1

function visibleTrees() {
  if (view === 'split') return ['projected', 'master']
  return [view]
}

function buildSectionList() {
  flatSections = []
  listEl.innerHTML = ''

  for (const tree of visibleTrees()) {
    const sections = parseSections(TREES[tree].src ?? '')
    const group = document.createElement('div')
    group.className = 'section-group'
    group.textContent = TREES[tree].label
    listEl.append(group)

    sections.forEach((s) => {
      const i = flatSections.length
      flatSections.push({ tree, ...s })

      const btn = document.createElement('button')
      btn.className = 'section-item'
      btn.dataset.index = String(i)
      // Titles read "PHASE 3 — LAUNCHPAD SERVICE · Risk MEDIUM"; split off the head as the index chip.
      const [head, ...rest] = s.title.split(/\s+—\s+/)
      btn.innerHTML =
        `<span class="idx">${head.replace(/PHASE\s*/i, 'P').replace(/\s+/g, '')}</span>` +
        `<span class="label">${rest.join(' — ') || s.title}</span>`
      btn.title = s.title
      btn.addEventListener('click', () => goTo(i))
      listEl.append(btn)
    })
  }

  countEl.textContent = `${flatSections.length}`
  cursor = -1
  updateStepper()
}

function goTo(i) {
  if (!flatSections.length) return
  cursor = (i + flatSections.length) % flatSections.length
  const s = flatSections[cursor]
  const ok = PANES[s.tree].focus(s.id, s.title)
  // The other pane stays put — comparing while one side is zoomed is the point.
  listEl.querySelectorAll('.section-item').forEach((b) => {
    b.classList.toggle('active', Number(b.dataset.index) === cursor)
  })
  listEl.querySelector('.section-item.active')?.scrollIntoView({ block: 'nearest' })
  updateStepper(ok ? null : 'section not found in the rendered SVG')
}

function updateStepper(warning) {
  if (cursor < 0) {
    stepLabel.textContent = flatSections.length
      ? `${flatSections.length} sections · pick one to start`
      : 'no sections found'
    stepLabel.classList.add('muted')
    return
  }
  const s = flatSections[cursor]
  stepLabel.classList.remove('muted')
  stepLabel.textContent = warning
    ? `${cursor + 1}/${flatSections.length} — ${warning}`
    : `${cursor + 1}/${flatSections.length} · ${TREES[s.tree].label} · ${s.title}`
}

document.getElementById('next').addEventListener('click', () => goTo(cursor + 1))
document.getElementById('prev').addEventListener('click', () => goTo(cursor - 1))

/* ════════════════════════════════════════════════════════════════ view state */

const stage = document.getElementById('stage')
const shell = document.querySelector('.shell')
const VIEW_KEY = 'ablepad.viz.view'
const SIDEBAR_KEY = 'ablepad.viz.sidebar'
const LAYOUT_KEY = 'ablepad.viz.layout'

let view = 'split'
let layout = 'tall'

function setView(next) {
  view = next
  stage.className = `stage view-${view}`
  document
    .querySelectorAll('.tabs:not(.small) .tab')
    .forEach((b) => b.classList.toggle('active', b.dataset.view === view))
  localStorage.setItem(VIEW_KEY, view)
  buildSectionList()
  // Land on the first section, not on a fit-to-everything view — fit is unreadable on
  // a 130-node tree, and "I can't read it" is the first thing that kills a diagram.
  requestAnimationFrame(() => goTo(0))
}

document
  .querySelectorAll('.tabs:not(.small) .tab')
  .forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)))

/** Re-render both trees under a new layout, then return to the section you were on. */
async function setLayout(next) {
  layout = next
  localStorage.setItem(LAYOUT_KEY, layout)
  document
    .querySelectorAll('.tabs.small .tab')
    .forEach((b) => b.classList.toggle('active', b.dataset.layout === layout))
  const at = cursor
  await Promise.all([render('projected'), render('master')])
  requestAnimationFrame(() => goTo(at < 0 ? 0 : at))
}

document
  .querySelectorAll('.tabs.small .tab')
  .forEach((b) => b.addEventListener('click', () => setLayout(b.dataset.layout)))

function setSidebar(hidden) {
  shell.classList.toggle('no-sidebar', hidden)
  localStorage.setItem(SIDEBAR_KEY, hidden ? '1' : '0')
  requestAnimationFrame(() => Object.values(PANES).forEach((p) => p.fit()))
}

document.getElementById('sidebar-toggle').addEventListener('click', () =>
  setSidebar(!shell.classList.contains('no-sidebar')),
)
document.getElementById('fit').addEventListener('click', () => Object.values(PANES).forEach((p) => p.fit()))

/** Keyboard zoom hits the visible panes only, so Plan/Truth views behave as expected. */
const zoomVisible = (f) => visibleTrees().forEach((t) => PANES[t].zoomAt(f))

window.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const views = { 1: 'projected', 2: 'master', 3: 'split' }
  const k = e.key.toLowerCase()
  if (views[e.key]) setView(views[e.key])
  else if (k === 'j') goTo(cursor + 1)
  else if (k === 'k') goTo(cursor - 1)
  else if (k === 'f') Object.values(PANES).forEach((p) => p.fit())
  else if (k === 'l') setLayout(layout === 'tall' ? 'wide' : 'tall')
  else if (e.key === '+' || e.key === '=') zoomVisible(STEP)
  else if (e.key === '-' || e.key === '_') zoomVisible(1 / STEP)
  else if (e.key === '0') Object.values(PANES).forEach((p) => p.reset())
  else if (k === 's') setSidebar(!shell.classList.contains('no-sidebar'))
})

/* ══════════════════════════════════════════════════════════════════════ boot */

layout = localStorage.getItem(LAYOUT_KEY) ?? 'tall'
document
  .querySelectorAll('.tabs.small .tab')
  .forEach((b) => b.classList.toggle('active', b.dataset.layout === layout))

setSidebar(localStorage.getItem(SIDEBAR_KEY) === '1')
await Promise.all([render('projected'), render('master')])
setView(localStorage.getItem(VIEW_KEY) ?? 'split')
