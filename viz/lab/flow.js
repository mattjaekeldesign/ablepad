/**
 * viz/lab/flow.js — the mode-flow map: every config is a node, every way OUT of it is an edge.
 *
 * Why it exists : the rig's story ("boot shows this, that pad leads there") lives spread
 *                 across N json files. This view draws it as one n8n-style graph so a
 *                 broken chain — a SWITCH_MODE pad pointing at nothing — is visible,
 *                 not something you discover on stage.
 * Layer it owns : presentation + flow-position persistence. It never edits pads or
 *                 transitions — the grid and inspector own those.
 * Who calls it  : the lab shell — initFlow(rootEl) once at boot. After that it is
 *                 event-driven: it refreshes itself on 'view:changed'/'config:changed'/
 *                 'library:changed'/'config:loaded' and asks the shell to switch views
 *                 via store.emit('view:request', 'grid').
 * What it returns: nothing — it owns everything inside #stage-flow.
 *
 * Edges come from two places, deliberately merged into one visual language:
 *   config.transitions[]                      → labelled with the `on` event
 *   pads with action.type === 'SWITCH_MODE'   → labelled "pad <id>" (+ hold time)
 * The second kind is the heart of the metaphor — buttons ARE the wiring between modes.
 */
import * as api from './api.js'
import { store, openConfig, updateConfigMeta, toast } from './store.js'
import { ledHex } from './palette.js'

/* ═══════════════════════════════════════════════════════════════════ constants */

const NODE_W = 224 // card width in px — must match .fl-node width in flow.css
const COL_GAP = 320 // horizontal distance between BFS layers
const ROW_GAP = 160 // vertical distance between nodes in one layer
const ORIGIN_X = 60 // where the root layer starts, in layer space
const ORIGIN_Y = 60
const GHOST_STACK_GAP = 72 // vertical stacking for ghost stubs hanging off one source

const MIN_ZOOM = 0.4
const MAX_ZOOM = 2
const WHEEL_GAIN = 0.0022 // same exponential feel as viz/main.js
const FIT_PAD = 60 // breathing room around the graph when fitting
const CLICK_SLOP_PX = 4 // pointer travel below this = click (select), above = drag (move)
const REFRESH_DEBOUNCE_MS = 200
const EDGE_MIN_REACH = 48 // minimum horizontal pull on bezier control points

const SVG_DEFS =
  '<defs>' +
  '<marker id="fl-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
  '<path d="M0 0 L8 4 L0 8 Z" class="fl-arrowhead"></path></marker>' +
  '<marker id="fl-arrow-hot" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">' +
  '<path d="M0 0 L8 4 L0 8 Z" class="fl-arrowhead fl-arrowhead-hot"></path></marker>' +
  '</defs>'

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v))

/* ═══════════════════════════════════════════════════════════════════ init */

export function initFlow(rootEl) {
  /* Scaffold is built once; refresh() only replaces the layer's contents. */
  rootEl.innerHTML = `
    <div class="fl-toolbar">
      <button type="button" class="fl-btn" data-fl="arrange">Auto-arrange</button>
      <button type="button" class="fl-btn" data-fl="fit">Fit</button>
      <span class="fl-hint">double-click a node to open it · edges = transitions + SWITCH_MODE pads</span>
    </div>
    <div class="fl-viewport">
      <div class="fl-layer"></div>
      <div class="fl-empty hidden">no configs in the library yet</div>
    </div>`

  const viewport = rootEl.querySelector('.fl-viewport')
  const layer = rootEl.querySelector('.fl-layer')
  const emptyEl = rootEl.querySelector('.fl-empty')

  let visible = false
  let needsFit = true // fit once, after the first real render — then respect the user's camera
  let selectedId = null
  let nodes = new Map() // id → { id, ghost, config?, pos: {x,y}, el }
  let edges = [] // [{ from, to, label, ghost }]

  /* ─────────────────────────────────────────────── pan / zoom — one rAF writer */

  const t = { x: 0, y: 0, k: 1 }
  let tFrame = 0

  /** The only place the layer transform is written. Coalesced so a trackpad cannot flood layout. */
  function applyTransform() {
    if (tFrame) return
    tFrame = requestAnimationFrame(() => {
      tFrame = 0
      layer.style.transform = `translate(${t.x}px, ${t.y}px) scale(${t.k})`
    })
  }

  /** Pointer event → layer-space coordinates (undo pan, undo zoom). */
  function layerPoint(e) {
    const r = viewport.getBoundingClientRect()
    return { x: (e.clientX - r.left - t.x) / t.k, y: (e.clientY - r.top - t.y) / t.k }
  }

  /** Zoom about a viewport point so the pixel under the cursor stays put. */
  function zoomAt(factor, px, py) {
    const k = clamp(t.k * factor, MIN_ZOOM, MAX_ZOOM)
    if (k === t.k) return
    t.x = px - ((px - t.x) / t.k) * k
    t.y = py - ((py - t.y) / t.k) * k
    t.k = k
    applyTransform()
  }

  // Wheel is continuous-exponential, coalesced to one zoom per frame (same as viz/main.js).
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
        zoomAt(f, wheelPos[0], wheelPos[1])
      })
    },
    { passive: false },
  )

  /* ───────────────────────────────────────────────────────────── data refresh */

  let refreshToken = 0

  /**
   * Re-fetch every library config from disk EXCEPT the open one, which comes from the
   * store so unsaved edits show. Individual fetch failures drop that node, not the view.
   */
  async function refresh() {
    const token = ++refreshToken
    const entries = store.state.library.filter((e) => e.kind !== 'broken')
    const fetched = await Promise.all(
      entries.map((e) =>
        api.getConfig(e.id).catch((err) => {
          console.warn(`flow: could not load ${e.id}`, err)
          return null
        }),
      ),
    )
    if (token !== refreshToken || !visible) return // a newer refresh superseded this one

    const open = store.state.config
    const configs = fetched.filter(Boolean).map((c) => (open && c.id === open.id ? open : c))
    if (open && !configs.some((c) => c.id === open.id)) configs.push(open)

    build(configs)
    render()
    emptyEl.classList.toggle('hidden', nodes.size > 0)
    if (needsFit && nodes.size) {
      needsFit = false
      fit()
    }
  }

  let refreshTimer = 0
  function debouncedRefresh() {
    if (!visible) return
    clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      if (!visible) return
      if (drag) return debouncedRefresh() // never rebuild the DOM out from under a drag
      refresh()
    }, REFRESH_DEBOUNCE_MS)
  }

  /* ─────────────────────────────────────────────────────── graph construction */

  /** Every way out of every config, as flat edge records. */
  function collectEdges(configs) {
    const out = []
    for (const cfg of configs) {
      for (const tr of cfg.transitions ?? []) out.push({ from: cfg.id, to: tr.to, label: tr.on })
      for (const [padId, pad] of Object.entries(cfg.pads ?? {})) {
        const a = pad.action
        if (a?.type !== 'SWITCH_MODE' || !a.params?.target) continue
        const hold = a.hold_ms ? ` · hold ${a.hold_ms / 1000}s` : ''
        out.push({ from: cfg.id, to: a.params.target, label: `pad ${padId}${hold}` })
      }
    }
    return out
  }

  /**
   * BFS layering, left→right, from the config whose id is 'boot' (that IS the story:
   * what happens after power-on). Unreachable nodes park in a final column so nothing
   * silently disappears. Returns id → {x, y} for every real node.
   */
  function autoLayout() {
    const real = [...nodes.values()].filter((n) => !n.ghost)
    const adj = new Map(real.map((n) => [n.id, []]))
    for (const e of edges) if (adj.has(e.from) && adj.has(e.to)) adj.get(e.from).push(e.to)

    const rootId = adj.has('boot') ? 'boot' : real[0]?.id
    const depth = new Map()
    if (rootId != null) {
      depth.set(rootId, 0)
      const queue = [rootId]
      while (queue.length) {
        const id = queue.shift()
        for (const next of adj.get(id)) {
          if (depth.has(next)) continue
          depth.set(next, depth.get(id) + 1)
          queue.push(next)
        }
      }
    }
    const maxDepth = Math.max(-1, ...depth.values())

    const rowInCol = new Map() // column → next free row
    const pos = new Map()
    for (const n of real) {
      const col = depth.has(n.id) ? depth.get(n.id) : maxDepth + 1 // unreachable → last column
      const row = rowInCol.get(col) ?? 0
      rowInCol.set(col, row + 1)
      pos.set(n.id, { x: ORIGIN_X + col * COL_GAP, y: ORIGIN_Y + row * ROW_GAP })
    }
    return pos
  }

  /** Ghost stubs hang just right of their (first) source, stacked if one source has several. */
  function placeGhosts() {
    const stacked = new Map() // sourceId → how many ghosts already hung off it
    for (const n of nodes.values()) {
      if (!n.ghost) continue
      const src = nodes.get(edges.find((e) => e.to === n.id)?.from)
      const slot = stacked.get(src?.id) ?? 0
      stacked.set(src?.id, slot + 1)
      n.pos = src?.pos
        ? { x: src.pos.x + COL_GAP, y: src.pos.y + slot * GHOST_STACK_GAP }
        : { x: ORIGIN_X, y: ORIGIN_Y + slot * GHOST_STACK_GAP }
    }
  }

  /** Rebuild the node/edge model. meta.flowPos wins; null falls back to the BFS layout. */
  function build(configs) {
    nodes = new Map()
    for (const cfg of configs) nodes.set(cfg.id, { id: cfg.id, ghost: false, config: cfg, pos: null, el: null })
    edges = collectEdges(configs)

    // Dangling targets become ghost nodes — a broken reference must be SEEN, not swallowed.
    for (const e of edges) {
      if (nodes.has(e.to)) continue
      e.ghost = true
      nodes.set(e.to, { id: e.to, ghost: true, pos: null, el: null })
    }

    const auto = autoLayout()
    for (const n of nodes.values()) {
      if (n.ghost) continue
      const saved = n.config.meta?.flowPos
      n.pos = saved && typeof saved.x === 'number' ? { x: saved.x, y: saved.y } : auto.get(n.id)
    }
    placeGhosts()
  }

  /* ──────────────────────────────────────────────────────────────── rendering */

  let edgeSvg = null

  function render() {
    layer.innerHTML = ''

    // Edge layer first so nodes stack above it. 1×1 + overflow:visible: paths may live
    // anywhere in layer space without the SVG needing a size.
    edgeSvg = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
    edgeSvg.setAttribute('class', 'fl-edges')
    edgeSvg.setAttribute('width', '1')
    edgeSvg.setAttribute('height', '1')
    layer.appendChild(edgeSvg)

    for (const n of nodes.values()) {
      n.el = n.ghost ? ghostEl(n) : nodeEl(n)
      positionNode(n)
      layer.appendChild(n.el)
    }
    drawEdges() // needs offsetHeight, so strictly after the nodes hit the DOM
  }

  function positionNode(n) {
    n.el.style.left = `${n.pos.x}px`
    n.el.style.top = `${n.pos.y}px`
  }

  /** The n8n card: header (name + kind chip), LED thumbnail, "N pads · M edges" footer. */
  function nodeEl(n) {
    const cfg = n.config
    const el = document.createElement('div')
    el.className = 'fl-node'
    el.dataset.id = cfg.id
    el.style.width = `${NODE_W}px`
    if (cfg.id === store.state.config?.id) el.classList.add('fl-open')
    if (cfg.id === selectedId) el.classList.add('fl-selected')
    if (cfg.description) el.title = cfg.description

    const head = document.createElement('div')
    head.className = 'fl-node-head'
    const name = document.createElement('span')
    name.className = 'fl-node-name'
    name.textContent = cfg.name || cfg.id
    const chip = document.createElement('span')
    chip.className = 'fl-chip'
    chip.textContent = cfg.kind
    head.append(name, chip)

    const padCount = Object.keys(cfg.pads ?? {}).length
    const edgeCount = edges.filter((e) => e.from === cfg.id).length
    const foot = document.createElement('div')
    foot.className = 'fl-node-foot'
    foot.textContent = `${padCount} pads · ${edgeCount} edges`

    el.append(head, thumbEl(cfg), foot)
    return el
  }

  /**
   * 9×9 mini Launchpad, idle LEDs only — the "what does this mode look like" glance.
   * PAD_IDS run bottom→top (programmer numbering); the screen wants top row first,
   * so rows iterate 9→1. Unbound pads paint the config background, same as the rig will.
   */
  function thumbEl(cfg) {
    const wrap = document.createElement('div')
    wrap.className = 'fl-thumb'
    const bg = ledHex(cfg.background)
    for (let row = 9; row >= 1; row--) {
      for (let col = 1; col <= 9; col++) {
        const cell = document.createElement('span')
        const led = cfg.pads?.[String(row * 10 + col)]?.led?.idle
        cell.style.background = led ? ledHex(led) : bg
        wrap.appendChild(cell)
      }
    }
    return wrap
  }

  /** Dashed stub for a target id that no config in the library owns. */
  function ghostEl(n) {
    const el = document.createElement('div')
    el.className = 'fl-node fl-ghost'
    el.dataset.id = n.id
    el.style.width = `${NODE_W}px`
    el.title = 'referenced as a target, but no such config exists'
    const head = document.createElement('div')
    head.className = 'fl-node-head'
    const name = document.createElement('span')
    name.className = 'fl-node-name'
    name.textContent = n.id
    const chip = document.createElement('span')
    chip.className = 'fl-chip fl-chip-missing'
    chip.textContent = 'missing'
    head.append(name, chip)
    el.append(head)
    return el
  }

  /**
   * Cubic beziers, right edge of source → left edge of target, arrowhead at the target.
   * Fully redrawn on every call — trivial at library scale, and it keeps drag-follow simple.
   * With symmetric control pulls the curve midpoint is exactly the endpoint average,
   * which is where the label pill sits.
   */
  function drawEdges() {
    for (const pill of layer.querySelectorAll('.fl-pill')) pill.remove()
    let paths = ''
    const pills = []

    edges.forEach((e, i) => {
      const a = nodes.get(e.from)
      const b = nodes.get(e.to)
      if (!a?.el || !b?.el) return
      const x1 = a.pos.x + a.el.offsetWidth
      const y1 = a.pos.y + a.el.offsetHeight / 2
      const x2 = b.pos.x
      const y2 = b.pos.y + b.el.offsetHeight / 2
      const pull = Math.max(EDGE_MIN_REACH, Math.abs(x2 - x1) / 2)
      const d = `M ${x1} ${y1} C ${x1 + pull} ${y1}, ${x2 - pull} ${y2}, ${x2} ${y2}`

      paths +=
        `<g class="fl-edge${e.ghost ? ' fl-edge-ghost' : ''}" data-edge="${i}">` +
        `<path class="fl-edge-hit" d="${d}"></path>` +
        `<path class="fl-edge-line" d="${d}" marker-end="url(#fl-arrow)"></path>` +
        `</g>`

      if (e.label) {
        const pill = document.createElement('span')
        pill.className = 'fl-pill'
        pill.dataset.edge = String(i)
        pill.textContent = e.label
        pill.style.left = `${(x1 + x2) / 2}px`
        pill.style.top = `${(y1 + y2) / 2}px`
        pills.push(pill)
      }
    })

    edgeSvg.innerHTML = SVG_DEFS + paths // labels never enter this string — no escaping needed
    for (const p of pills) layer.appendChild(p)
  }

  // Edge hover: path and label pill live in different layers (SVG vs HTML), so CSS :hover
  // cannot link them — a delegated data-edge lookup lights both at once.
  function setEdgeHot(target, on) {
    const hit = target.closest?.('[data-edge]')
    if (!hit) return
    for (const el of layer.querySelectorAll(`[data-edge="${hit.dataset.edge}"]`))
      el.classList.toggle('fl-hot', on)
  }
  viewport.addEventListener('pointerover', (e) => setEdgeHot(e.target, true))
  viewport.addEventListener('pointerout', (e) => setEdgeHot(e.target, false))

  /* ───────────────────────────────────────── dragging — one delegate, no per-node listeners */

  let drag = null // { kind: 'pan', ox, oy } | { kind: 'node', node, dx, dy, sx, sy, moved }
  let dragFrame = 0

  viewport.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return
    const el = e.target.closest('.fl-node')
    if (el && !el.classList.contains('fl-ghost')) {
      const node = nodes.get(el.dataset.id)
      const p = layerPoint(e)
      drag = { kind: 'node', node, dx: p.x - node.pos.x, dy: p.y - node.pos.y, sx: e.clientX, sy: e.clientY, moved: false }
    } else {
      drag = { kind: 'pan', ox: e.clientX - t.x, oy: e.clientY - t.y }
    }
    viewport.classList.add('fl-grabbing')
    viewport.setPointerCapture(e.pointerId)
  })

  viewport.addEventListener('pointermove', (e) => {
    if (!drag) return
    if (drag.kind === 'pan') {
      t.x = e.clientX - drag.ox
      t.y = e.clientY - drag.oy
      applyTransform()
      return
    }
    if (Math.abs(e.clientX - drag.sx) + Math.abs(e.clientY - drag.sy) > CLICK_SLOP_PX) drag.moved = true
    const p = layerPoint(e)
    drag.node.pos = { x: p.x - drag.dx, y: p.y - drag.dy }
    if (dragFrame) return
    dragFrame = requestAnimationFrame(() => {
      dragFrame = 0
      if (!drag || drag.kind !== 'node') return
      positionNode(drag.node)
      drawEdges() // edges follow the node live
    })
  })

  function endDrag() {
    const d = drag
    drag = null
    viewport.classList.remove('fl-grabbing')
    if (!d || d.kind !== 'node') return
    if (d.moved) persistPos(d.node) // debounced-to-pointerup by construction: one write per drop
    else selectNode(d.node.id) // a still click is a select, not a 0px move
  }
  viewport.addEventListener('pointerup', endDrag)
  viewport.addEventListener('pointercancel', endDrag)

  /** Single click raises + outlines a node — a reading aid, nothing more. */
  function selectNode(id) {
    selectedId = id
    for (const n of nodes.values()) n.el?.classList.toggle('fl-selected', n.id === id)
  }

  // Double-click = walk into the mode: open it and ask the shell for the grid view.
  viewport.addEventListener('dblclick', async (e) => {
    const el = e.target.closest('.fl-node')
    if (!el || el.classList.contains('fl-ghost')) return
    try {
      await openConfig(el.dataset.id)
      store.emit('view:request', 'grid')
    } catch (err) {
      toast('error', `could not open ${el.dataset.id}: ${err.message}`)
    }
  })

  /* ────────────────────────────────────────────────────── position persistence */

  /**
   * Where a dropped node's position goes:
   *   open config  → the store working copy (marks dirty, rides the next explicit Save)
   *   anyone else  → read-modify-write straight to disk. Position-only edits to files
   *                  that are not open in the editor are safe to autosave; re-fetching
   *                  first means we never clobber pad data with a stale in-memory copy.
   */
  async function persistPos(node) {
    const flowPos = { x: Math.round(node.pos.x), y: Math.round(node.pos.y) }
    if (store.state.config?.id === node.id) {
      updateConfigMeta({ meta: { flowPos } })
      return
    }
    try {
      const cfg = await api.getConfig(node.id)
      cfg.meta = { ...(cfg.meta ?? {}), flowPos }
      await api.putConfig(cfg)
    } catch (err) {
      toast('error', `could not save position of ${node.id}: ${err.message}`)
    }
  }

  /* ────────────────────────────────────────────────────────────────── toolbar */

  /** Throw away hand placement: recompute the BFS layout, move everything, persist it all. */
  async function autoArrange() {
    const auto = autoLayout()
    for (const n of nodes.values()) {
      if (n.ghost) continue
      n.pos = auto.get(n.id) ?? n.pos
      positionNode(n)
    }
    placeGhosts()
    for (const n of nodes.values()) if (n.ghost) positionNode(n)
    drawEdges()
    fit()
    // Persist sequentially (a handful of small PUTs), disk-backed configs FIRST: the open
    // config's updateConfigMeta fires config:changed → a debounced refresh that re-reads
    // the others from disk, so their writes must already be down when it runs.
    const openId = store.state.config?.id
    for (const n of nodes.values()) if (!n.ghost && n.id !== openId) await persistPos(n)
    const openNode = nodes.get(openId)
    if (openNode && !openNode.ghost) persistPos(openNode)
  }

  /** Frame every node with padding. Capped at 1:1 so two nodes don't render poster-sized. */
  function fit() {
    const placed = [...nodes.values()].filter((n) => n.el)
    if (!placed.length) return
    let minX = Infinity
    let minY = Infinity
    let maxX = -Infinity
    let maxY = -Infinity
    for (const n of placed) {
      minX = Math.min(minX, n.pos.x)
      minY = Math.min(minY, n.pos.y)
      maxX = Math.max(maxX, n.pos.x + n.el.offsetWidth)
      maxY = Math.max(maxY, n.pos.y + n.el.offsetHeight)
    }
    const r = viewport.getBoundingClientRect()
    const k = clamp(
      Math.min((r.width - FIT_PAD * 2) / (maxX - minX), (r.height - FIT_PAD * 2) / (maxY - minY), 1),
      MIN_ZOOM,
      MAX_ZOOM,
    )
    t.k = k
    t.x = (r.width - (maxX - minX) * k) / 2 - minX * k
    t.y = (r.height - (maxY - minY) * k) / 2 - minY * k
    applyTransform()
  }

  rootEl.querySelector('[data-fl="arrange"]').addEventListener('click', autoArrange)
  rootEl.querySelector('[data-fl="fit"]').addEventListener('click', fit)

  /* ──────────────────────────────────────────────────────────── subscriptions */

  store.on('view:changed', (view) => {
    visible = view === 'flow'
    if (visible) refresh() // fresh data every time the tab lands here — edits happen elsewhere
  })
  store.on('library:changed', debouncedRefresh)
  store.on('config:changed', debouncedRefresh)
  store.on('config:loaded', debouncedRefresh)
}
