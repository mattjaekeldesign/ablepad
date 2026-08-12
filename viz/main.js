/**
 * viz/main.js — the viewer's controller.
 *
 * Why it exists : wires the two trees to two reading modes, a section navigator and a
 *                 position memory that survives a reload.
 * Layer it owns : behaviour. Content is trees.js, structure is parse.js, text view is
 *                 outline.js, diagram is mermaid. This file owns none of those.
 * Who calls it  : viz/index.html.
 *
 * Two reading modes, because they are good at different things:
 *   OUTLINE (default) — indented text. Scroll, search, select, copy. No zoom, no blur.
 *   DIAGRAM           — mermaid SVG. Shows the branching shape; needs zoom and pan.
 *
 * Position is persisted to sessionStorage on every change. A reload — from editing main.js,
 * from a vite restart, from anything — lands you back on the same section, scroll and zoom.
 */
import mermaid from 'mermaid'
import { trees, onTreesChange } from './trees.js'
import { parseTree } from './parse.js'
import { createOutline } from './outline.js'
import { createProgressBar } from './progressbar.js'

const NAMES = ['projected', 'master']
const TREE_LABEL = { projected: 'Plan', master: 'Truth' }

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

/* ════════════════════════════════════════════════════════ persisted position */

const STATE_KEY = 'ablepad.viz.state'

const state = {
  view: 'split',
  mode: 'outline',
  layout: 'tall',
  sidebar: true,
  cursor: -1,
  search: '',
  panes: { projected: { x: 0, y: 0, k: 1, scroll: 0 }, master: { x: 0, y: 0, k: 1, scroll: 0 } },
  ...safeLoad(),
}

function safeLoad() {
  try {
    return JSON.parse(sessionStorage.getItem(STATE_KEY) ?? '{}')
  } catch {
    return {} // a corrupt blob must never stop the page from opening
  }
}

let saveTimer = 0
function save() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => sessionStorage.setItem(STATE_KEY, JSON.stringify(state)), 200)
}
window.addEventListener('pagehide', () => sessionStorage.setItem(STATE_KEY, JSON.stringify(state)))

/* ═══════════════════════════════════════════════════════════════ diagram pane */

const MIN_K = 0.25
const MAX_K = 1.0
const STEP = 1.12
const WHEEL_GAIN = 0.0022

/**
 * Zoom is applied as the SVG's layout SIZE, not as a CSS scale — a cached layer scaled 4x is
 * blurry. Never add will-change/backface-visibility to .canvas; see style.css.
 */
function attachPanZoom(viewport, memory, onZoom) {
  const canvas = viewport.querySelector('.canvas')
  const t = { x: memory.x ?? 0, y: memory.y ?? 0, k: memory.k ?? MAX_K }
  let baseW = 0
  let baseH = 0
  let glideTimer = 0

  const apply = (glide) => {
    canvas.classList.toggle('glide', !!glide)
    canvas.style.transform = `translate(${t.x}px,${t.y}px)`
    const svg = canvas.querySelector('svg')
    if (svg && baseW) {
      svg.style.width = `${baseW * t.k}px`
      svg.style.height = `${baseH * t.k}px`
    }
    memory.x = t.x
    memory.y = t.y
    memory.k = t.k
    save()
    onZoom?.(t.k)
    if (glide) {
      clearTimeout(glideTimer)
      glideTimer = setTimeout(() => canvas.classList.remove('glide'), 340)
    }
  }

  function syncBase() {
    const svg = canvas.querySelector('svg')
    if (!svg) return
    const vb = svg.viewBox?.baseVal
    baseW = vb?.width || svg.getBoundingClientRect().width
    baseH = vb?.height || svg.getBoundingClientRect().height
    svg.style.maxWidth = 'none'
    apply(false)
  }

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

  let wheelDelta = 0
  let wheelPos = [0, 0]
  let wheelFrame = 0
  viewport.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault()
      const r = viewport.getBoundingClientRect()
      wheelPos = [e.clientX - r.left, e.clientY - r.top]
      wheelDelta += e.ctrlKey ? e.deltaY * 4 : e.deltaY
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

  viewport.addEventListener('dblclick', (e) => {
    const box = e.target.closest('g.node, g.cluster')
    if (box) frame(box, MAX_K)
  })

  let dragging = false
  let ox = 0
  let oy = 0
  let dragFrame = 0
  viewport.addEventListener('pointerdown', (e) => {
    dragging = true
    ox = e.clientX - t.x
    oy = e.clientY - t.y
    viewport.classList.add('dragging')
    viewport.setPointerCapture(e.pointerId)
  })
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

  function frame(el, maxScale) {
    const vp = viewport.getBoundingClientRect()
    const r = el.getBoundingClientRect()
    if (!r.width || !r.height) return
    const x = (r.left - vp.left - t.x) / t.k
    const y = (r.top - vp.top - t.y) / t.k
    const w = r.width / t.k
    const h = r.height / t.k
    const pad = 24
    const k = Math.min((vp.width - pad * 2) / w, (vp.height - pad * 2) / h, maxScale)
    t.k = Math.min(MAX_K, Math.max(MIN_K, k))
    t.x = (vp.width - w * t.k) / 2 - x * t.k
    t.y = (vp.height - h * t.k) / 2 - y * t.k
    apply(true)
  }

  const clearFocus = () => {
    canvas.classList.remove('focusing')
    canvas.querySelectorAll('.is-focused').forEach((n) => n.classList.remove('is-focused'))
  }

  return {
    syncBase,
    zoomAt,
    reset() {
      t.x = 0
      t.y = 0
      t.k = MAX_K
      apply(true)
      clearFocus()
    },
    fit() {
      const svg = canvas.querySelector('svg')
      if (svg) frame(svg, MAX_K)
      clearFocus()
    },
    focus(sectionId, title) {
      const svg = canvas.querySelector('svg')
      if (!svg) return false
      // Mermaid ids clusters "<diagramId>-<subgraphId>". Title text is the fallback.
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

/* ═══════════════════════════════════════════════════════════════════ panes */

/** One pane = one tree, one parsed model, one outline, one diagram. */
const panes = {}

for (const name of NAMES) {
  const zoomLabel = document.querySelector(`[data-zoom="${name}"] .zlabel`)
  const memory = (state.panes[name] ??= { x: 0, y: 0, k: MAX_K, scroll: 0 })
  const pz = attachPanZoom(
    document.querySelector(`.pane[data-pane="${name}"] .viewport`),
    memory,
    (k) => (zoomLabel.textContent = `${Math.round(k * 100)}%`),
  )
  document.querySelectorAll(`[data-zoom="${name}"] .zbtn`).forEach((b) => {
    b.addEventListener('click', () => pz.zoomAt(b.dataset.zdir === 'in' ? STEP : 1 / STEP))
  })

  const host = document.getElementById(`outline-${name}`)
  host.addEventListener('scroll', () => {
    memory.scroll = host.scrollTop
    save()
  })

  panes[name] = { name, pz, host, memory, model: null, outline: null, diagramSource: null }
}

/* ════════════════════════════════════════════════════════════════ rendering */

/** Layout is a view concern, so Tall is a rewrite here, not an edit to the .mmd files. */
function sourceFor(name) {
  const src = trees[name] ?? ''
  return state.layout === 'tall' ? src.replace(/^(\s*)direction\s+LR\s*$/gm, '$1direction TB') : src
}

function renderOutline(name) {
  const pane = panes[name]
  pane.model = parseTree(trees[name] ?? '')
  pane.outline = createOutline(pane.host, pane.model, name)
  if (state.search) pane.outline.filter(state.search)
  pane.host.scrollTop = pane.memory.scroll ?? 0

  const chips = document.querySelector(`[data-chips="${name}"]`)
  chips.innerHTML = Object.entries(pane.model.counts)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `<span class="chip"><b>${n}</b> ${STATUS_LABEL[k] ?? k}</span>`)
    .join('')
}

let renderToken = 0

/** The diagram is rendered lazily — it costs ~130 SVG nodes, and outline is the default mode. */
async function renderDiagram(name, force = false) {
  const pane = panes[name]
  const src = sourceFor(name)
  if (!force && pane.diagramSource === src) return
  pane.diagramSource = src

  const canvas = document.getElementById(`canvas-${name}`)
  try {
    const { svg } = await mermaid.render(`mmd-${name}-${renderToken++}`, src)
    canvas.innerHTML = svg
  } catch (err) {
    canvas.innerHTML = `<div class="error">${name}.mmd failed to parse\n\n${err?.message ?? err}</div>`
  }
  pane.pz.syncBase()
}

/* ═══════════════════════════════════════════════════════ section navigator */

const listEl = document.getElementById('section-list')
const countEl = document.getElementById('section-count')
const stepLabel = document.getElementById('step-label')

let flatSections = []

const visibleTrees = () => (state.view === 'split' ? NAMES : [state.view])

function buildSectionList() {
  flatSections = []
  listEl.innerHTML = ''

  for (const name of visibleTrees()) {
    const sections = panes[name].model?.sections ?? []
    const group = document.createElement('div')
    group.className = 'section-group'
    group.textContent = TREE_LABEL[name]
    listEl.append(group)

    sections.forEach((s) => {
      const i = flatSections.length
      flatSections.push({ tree: name, id: s.id, title: s.title })

      const [head, ...rest] = s.title.split(/\s+—\s+/)
      const btn = document.createElement('button')
      btn.className = 'section-item'
      btn.dataset.index = String(i)
      btn.title = s.title
      btn.innerHTML =
        `<span class="idx">${head.replace(/PHASE\s*/i, 'P').replace(/\s+/g, '')}</span>` +
        `<span class="label">${rest.join(' — ') || s.title}</span>`
      btn.addEventListener('click', () => goTo(i))
      listEl.append(btn)
    })
  }

  countEl.textContent = String(flatSections.length)
  if (state.cursor >= flatSections.length) state.cursor = -1
  markActive()
  updateStepper()
}

function markActive() {
  listEl.querySelectorAll('.section-item').forEach((b) => {
    b.classList.toggle('active', Number(b.dataset.index) === state.cursor)
  })
}

function goTo(i, { scroll = true } = {}) {
  if (!flatSections.length) return
  state.cursor = (i + flatSections.length) % flatSections.length
  const s = flatSections[state.cursor]
  const pane = panes[s.tree]
  const ok = state.mode === 'outline' ? pane.outline?.scrollToSection(s.id) : pane.pz.focus(s.id, s.title)
  markActive()
  if (scroll) listEl.querySelector('.section-item.active')?.scrollIntoView({ block: 'nearest' })
  updateStepper(ok === false ? 'section not found in this view' : null)
  save()
}

function updateStepper(warning) {
  if (state.cursor < 0) {
    stepLabel.textContent = flatSections.length ? `${flatSections.length} sections` : 'no sections found'
    stepLabel.classList.add('muted')
    return
  }
  const s = flatSections[state.cursor]
  stepLabel.classList.remove('muted')
  stepLabel.textContent = warning
    ? `${state.cursor + 1}/${flatSections.length} — ${warning}`
    : `${state.cursor + 1}/${flatSections.length} · ${TREE_LABEL[s.tree]} · ${s.title}`
}

document.getElementById('next').addEventListener('click', () => goTo(state.cursor + 1))
document.getElementById('prev').addEventListener('click', () => goTo(state.cursor - 1))

/* ══════════════════════════════════════════════════════════════ view state */

const stage = document.getElementById('stage')
const shell = document.querySelector('.shell')

function paintStage() {
  stage.className = `stage view-${state.view} mode-${state.mode}`
  syncTabs('view', 'view', state.view)
  syncTabs('mode', 'mode', state.mode)
  syncTabs('layout', 'layout', state.layout)
  shell.classList.toggle('no-sidebar', !state.sidebar)
}

function syncTabs(group, attr, value) {
  document
    .querySelectorAll(`.tabs[data-group="${group}"] .tab`)
    .forEach((b) => b.classList.toggle('active', b.dataset[attr] === value))
}

async function setView(view) {
  state.view = view
  paintStage()
  buildSectionList()
  if (state.mode === 'diagram') await Promise.all(visibleTrees().map((n) => renderDiagram(n)))
  save()
}

async function setMode(mode) {
  state.mode = mode
  paintStage()
  if (mode === 'diagram') {
    await Promise.all(visibleTrees().map((n) => renderDiagram(n)))
    // Restoring a section beats restoring a transform: the tree may have re-laid out.
    if (state.cursor >= 0) requestAnimationFrame(() => goTo(state.cursor, { scroll: false }))
  } else if (state.cursor >= 0) {
    goTo(state.cursor, { scroll: false })
  }
  save()
}

async function setLayout(layout) {
  state.layout = layout
  paintStage()
  await Promise.all(visibleTrees().map((n) => renderDiagram(n, true)))
  if (state.cursor >= 0) requestAnimationFrame(() => goTo(state.cursor, { scroll: false }))
  save()
}

function setSidebar(on) {
  state.sidebar = on
  paintStage()
  save()
}

document.querySelectorAll('.tabs[data-group="view"] .tab').forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)))
document.querySelectorAll('.tabs[data-group="mode"] .tab').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)))
document.querySelectorAll('.tabs[data-group="layout"] .tab').forEach((b) => b.addEventListener('click', () => setLayout(b.dataset.layout)))
document.getElementById('sidebar-toggle').addEventListener('click', () => setSidebar(!state.sidebar))
document.getElementById('fit').addEventListener('click', () => visibleTrees().forEach((n) => panes[n].pz.fit()))

let allCollapsed = false
document.getElementById('collapse').addEventListener('click', () => {
  allCollapsed = !allCollapsed
  NAMES.forEach((n) => panes[n].outline?.setCollapsed(allCollapsed))
  document.getElementById('collapse').textContent = allCollapsed ? 'Expand' : 'Collapse'
})

/* ═════════════════════════════════════════════════════════════════ search */

const searchEl = document.getElementById('search')
const hitEl = document.getElementById('hit-count')

searchEl.value = state.search ?? ''
searchEl.addEventListener('input', () => {
  state.search = searchEl.value
  const hits = visibleTrees().reduce((n, name) => n + (panes[name].outline?.filter(state.search) ?? 0), 0)
  hitEl.textContent = state.search ? `${hits} rows` : ''
  if (state.search && state.mode !== 'outline') setMode('outline') // search is an outline feature
  save()
})

/* ═════════════════════════════════════════════════════════════ keyboard */

window.addEventListener('keydown', (e) => {
  const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement
  if (typing) {
    if (e.key === 'Escape') {
      searchEl.value = ''
      searchEl.dispatchEvent(new Event('input'))
      searchEl.blur()
    }
    return
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return

  const k = e.key.toLowerCase()
  const views = { 1: 'projected', 2: 'master', 3: 'split' }
  if (e.key === '/') {
    e.preventDefault()
    searchEl.focus()
  } else if (views[e.key]) setView(views[e.key])
  else if (k === 'm') setMode(state.mode === 'outline' ? 'diagram' : 'outline')
  else if (k === 'j') goTo(state.cursor + 1)
  else if (k === 'k') goTo(state.cursor - 1)
  else if (k === 'c') document.getElementById('collapse').click()
  else if (k === 'l') setLayout(state.layout === 'tall' ? 'wide' : 'tall')
  else if (k === 'f') visibleTrees().forEach((n) => panes[n].pz.fit())
  else if (e.key === '0') visibleTrees().forEach((n) => panes[n].pz.reset())
  else if (e.key === '+' || e.key === '=') visibleTrees().forEach((n) => panes[n].pz.zoomAt(STEP))
  else if (e.key === '-' || e.key === '_') visibleTrees().forEach((n) => panes[n].pz.zoomAt(1 / STEP))
  else if (k === 's') setSidebar(!state.sidebar)
})

/* ══════════════════════════════════════════ hot content swap, without reload */

onTreesChange(() => {
  const at = state.cursor
  progress.refresh(trees) // the score moves the moment a status class changes
  NAMES.forEach((n) => {
    renderOutline(n)
    panes[n].diagramSource = null // force a re-render next time the diagram is shown
  })
  buildSectionList()
  if (state.mode === 'diagram') {
    Promise.all(visibleTrees().map((n) => renderDiagram(n, true))).then(() => {
      if (at >= 0) goTo(at, { scroll: false })
    })
  } else if (at >= 0) {
    goTo(at, { scroll: false })
  }
  document.getElementById('foot-hint').textContent = 'trees reloaded from disk — position kept'
})

/* ══════════════════════════════════════════════════════════════════ boot */

const progress = createProgressBar(document.getElementById('progress-strip'))
progress.refresh(trees)

paintStage()
NAMES.forEach(renderOutline)
buildSectionList()
if (state.mode === 'diagram') await Promise.all(visibleTrees().map((n) => renderDiagram(n)))
if (state.cursor >= 0) goTo(state.cursor)
if (state.search) hitEl.textContent = `${visibleTrees().reduce((n, name) => n + (panes[name].outline?.filter(state.search) ?? 0), 0)} rows`
