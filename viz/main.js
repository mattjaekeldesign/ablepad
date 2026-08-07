/**
 * viz/main.js — the only JavaScript in this project.
 *
 * Why it exists : renders the two architecture trees so the roadmap is readable at a glance.
 * Layer it owns : presentation only. It knows nothing about the rig, MIDI, or Ableton.
 * Who calls it  : viz/index.html, via `npm run dev`.
 * What it returns: nothing — it mutates the DOM.
 *
 * Content lives in viz/trees/*.mmd. Edit those files, never this one. Vite's eager raw
 * glob below makes a save on a .mmd file hot-reload the page.
 */
import mermaid from 'mermaid'

// Eager + raw so Vite tracks the .mmd files as real module dependencies → HMR on save.
const SOURCES = import.meta.glob('./trees/*.mmd', { query: '?raw', import: 'default', eager: true })

const TREES = {
  projected: SOURCES['./trees/projected.mmd'],
  master: SOURCES['./trees/master.mmd'],
}

mermaid.initialize({
  startOnLoad: false,
  theme: 'dark',
  securityLevel: 'loose',
  flowchart: { curve: 'basis', nodeSpacing: 34, rankSpacing: 80, htmlLabels: true },
  themeVariables: {
    background: '#0f1520',
    fontFamily: 'ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif',
    fontSize: '13px',
    lineColor: '#475569',
  },
})

/* ------------------------------------------------------------------ render */

async function render(name) {
  const canvas = document.getElementById(`canvas-${name}`)
  const source = TREES[name]

  if (!source) {
    canvas.innerHTML = `<div class="error">Missing viz/trees/${name}.mmd</div>`
    return
  }

  try {
    const { svg } = await mermaid.render(`mmd-${name}-${renderToken++}`, source)
    canvas.innerHTML = svg
  } catch (err) {
    // A syntax error in a .mmd must be loud and must name the file — silent blanks waste hours.
    canvas.innerHTML = `<div class="error">${name}.mmd failed to parse\n\n${err?.message ?? err}</div>`
  }
}

let renderToken = 0

/* ---------------------------------------------------- pan + zoom per pane */

/**
 * Each viewport owns its own transform so the two trees can be inspected independently.
 * Kept deliberately dumb: no dependency, no inertia, no animation.
 */
function attachPanZoom(viewport) {
  const canvas = viewport.querySelector('.canvas')
  const t = { x: 0, y: 0, k: 1 }

  const apply = () => {
    canvas.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.k})`
  }

  viewport.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault()
      const rect = viewport.getBoundingClientRect()
      const px = e.clientX - rect.left
      const py = e.clientY - rect.top
      const next = Math.min(4, Math.max(0.08, t.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)))
      // Zoom about the cursor, not the origin.
      t.x = px - ((px - t.x) / t.k) * next
      t.y = py - ((py - t.y) / t.k) * next
      t.k = next
      apply()
    },
    { passive: false },
  )

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
  viewport.addEventListener('pointermove', (e) => {
    if (!dragging) return
    t.x = e.clientX - ox
    t.y = e.clientY - oy
    apply()
  })
  const stop = () => {
    dragging = false
    viewport.classList.remove('dragging')
  }
  viewport.addEventListener('pointerup', stop)
  viewport.addEventListener('pointercancel', stop)

  return {
    reset() {
      t.x = 0
      t.y = 0
      t.k = 1
      apply()
    },
    fit() {
      const svg = canvas.querySelector('svg')
      if (!svg) return
      const box = svg.getBoundingClientRect()
      const w = box.width / t.k
      const h = box.height / t.k
      if (!w || !h) return
      const k = Math.min((viewport.clientWidth - 40) / w, (viewport.clientHeight - 40) / h)
      t.k = Math.min(4, Math.max(0.05, k))
      t.x = 20
      t.y = 20
      apply()
    },
  }
}

const controls = [...document.querySelectorAll('.viewport')].map(attachPanZoom)

/* --------------------------------------------------------------- view mode */

const stage = document.getElementById('stage')
const VIEW_KEY = 'ablepad.viz.view'
const LEGEND_KEY = 'ablepad.viz.legend'

function setView(view) {
  stage.className = `stage view-${view}${legendHidden() ? ' legend-off' : ''}`
  document.querySelectorAll('.views button').forEach((b) => {
    b.classList.toggle('active', b.dataset.view === view)
  })
  localStorage.setItem(VIEW_KEY, view)
  // Layout changed → refit so nothing is stranded off-screen.
  requestAnimationFrame(() => controls.forEach((c) => c.fit()))
}

document.querySelectorAll('.views button').forEach((b) => {
  b.addEventListener('click', () => setView(b.dataset.view))
})

/* ------------------------------------------------------------------ legend */

const legend = document.getElementById('legend')
const legendHidden = () => legend.classList.contains('hidden')

function setLegend(hidden) {
  legend.classList.toggle('hidden', hidden)
  stage.classList.toggle('legend-off', hidden)
  localStorage.setItem(LEGEND_KEY, hidden ? '1' : '0')
}

document.getElementById('legend-toggle').addEventListener('click', () => setLegend(!legendHidden()))
document.getElementById('fit').addEventListener('click', () => controls.forEach((c) => c.fit()))
document.getElementById('reset').addEventListener('click', () => controls.forEach((c) => c.reset()))

// Keyboard: 1 projected · 2 master · 3 split · f fit · 0 reset · l legend
window.addEventListener('keydown', (e) => {
  if (e.metaKey || e.ctrlKey || e.altKey) return
  const map = { 1: 'projected', 2: 'master', 3: 'split' }
  if (map[e.key]) setView(map[e.key])
  else if (e.key === 'f') controls.forEach((c) => c.fit())
  else if (e.key === '0') controls.forEach((c) => c.reset())
  else if (e.key === 'l') setLegend(!legendHidden())
})

/* -------------------------------------------------------------------- boot */

setLegend(localStorage.getItem(LEGEND_KEY) === '1')
await Promise.all([render('projected'), render('master')])
setView(localStorage.getItem(VIEW_KEY) ?? 'split')
