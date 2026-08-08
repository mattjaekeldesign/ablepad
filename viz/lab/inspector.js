/**
 * viz/lab/inspector.js — the right-hand properties panel.
 *
 * Why it exists : every editable field of a config — mode metadata, background LED,
 *                 transitions, and per-pad label / LED states / action — gets a compact
 *                 form here, driven entirely by schema.js. Add an action to the
 *                 catalogue and this panel grows the fields; no panel code changes.
 * Layer it owns : presentation + form wiring only. All mutation goes through store
 *                 actions, all shape truth comes from schema.js, all colour comes
 *                 from palette.js.
 * Who calls it  : lab.js, once at boot (after palette + library load), with the
 *                 <aside id="inspector"> element.
 * What it returns: nothing — initInspector() owns the inside of that element from then on.
 *
 * Re-render policy: full renders on 'pad:selected' / 'config:loaded' / 'library:changed',
 * and on 'config:changed' ONLY when the change came from another panel. Edits made here
 * run inside apply(), which raises the `applying` flag — so a keystroke never rebuilds
 * the very input the user is typing into.
 */
import {
  store,
  updatePad,
  clearPad,
  updateConfigMeta,
  setTransitions,
} from './store.js'
import {
  ACTIONS,
  ACTION_TYPES,
  LED_TYPES,
  PAD_STATES,
  PAD_IDS,
  padKind,
  padIsButton,
  validateConfig,
} from './schema.js'
import { paletteHex, paletteIndices, paletteIsUnverified, ledHex } from './palette.js'

/* ═══════════════════════════════════════════════════════════════════ constants */

const PAD_TOTAL = PAD_IDS.length // all 81 addressable LEDs
const RGB_MAX = 127 // MIDI data byte ceiling — SysEx RGB channels are 7-bit
const RGB_CHANNELS = ['R', 'G', 'B']
const HOLD_STEP_MS = 250 // hold-to-confirm granularity in the number input
const HOLD_HINT = 'Roadmap gates: load set 2 s · reboot 4 s · shutdown 6 s. 0 / empty = instant.'
const FLASH_HINT = 'Alternates A/B each beat — free-run 0.5 s.'
const RGB_HINT = 'RGB is SysEx-only (type 3).'
const TRANSITIONS_HINT = 'Edges in the Flow view come from these + SWITCH_MODE pads.'
const CC_UNVERIFIED_HINT = 'CC frame map is UNVERIFIED — inferred from the manual’s page image, not hardware-tested.'
const PALETTE_COLUMNS = 16 // 128 indices → 16 × 8 picker grid (set in inspector.css too)
const FALLBACK_PALETTE_INDEX = 3 // white in the candidate palette — a fresh pick must be visible
const POPOVER_GAP_PX = 4

/** What each pad kind physically emits (programmer mode: number = pad id). */
const SENDS_TEXT = {
  grid: (id) => `sends note ${id}`,
  'cc-top': (id) => `sends CC ${id}`,
  'cc-right': (id) => `sends CC ${id}`,
  logo: () => 'light-only — no input',
}

/* ═══════════════════════════════════════════════════════════════════ module state */

let root = null // the <aside id="inspector"> we render into
let applying = false // true while THIS panel is calling store actions — see header
let activePopover = null // { pop, anchor } — at most one palette popover at a time
const ledOpenOverride = new Map() // LED state name → user's manual open/closed choice
let validationBox = null // live-updated nodes in the config view; null in other views
let summaryLine = null

/* ═══════════════════════════════════════════════════════════════════ public API */

/** Wire the panel into rootEl and the store. Call once at boot. */
export function initInspector(rootEl) {
  root = rootEl
  store.on('pad:selected', () => {
    ledOpenOverride.clear()
    render()
  })
  store.on('config:loaded', () => {
    ledOpenOverride.clear()
    render()
  })
  store.on('library:changed', () => render()) // configRef / transition dropdowns refresh
  store.on('config:changed', () => {
    if (!applying) render() // another panel edited the config — reflect it
  })
  document.addEventListener('click', onDocumentClick)
  render()
}

/* ═══════════════════════════════════════════════════════════════ store guard */

/**
 * Run a store mutation with the `applying` flag raised, so our own
 * 'config:changed' echo does not clobber the focused input. Diagnostics
 * (validation list, pad count) still refresh — they must stay live.
 */
function apply(fn) {
  applying = true
  try {
    fn()
  } finally {
    applying = false
  }
  refreshDiagnostics()
}

/**
 * Build a patch that behaves like a full REPLACEMENT under store.mergeDeep.
 * mergeDeep merges objects key-by-key, so switching an LED from flash to static
 * would silently keep paletteB, and switching action type would keep old params.
 * Writing every previous key as undefined clears the leftovers; JSON.stringify
 * drops undefined values on save, so files stay clean.
 */
function replacingKeys(previous, next) {
  const cleared = {}
  for (const key of Object.keys(previous ?? {})) cleared[key] = undefined
  return { ...cleared, ...next }
}

/* ═══════════════════════════════════════════════════════════════════ rendering */

function render() {
  closePopover()
  validationBox = null
  summaryLine = null
  root.innerHTML = ''
  const { config, selectedPad } = store.state
  if (!config) renderEmpty()
  else if (selectedPad === null) renderConfigView(config)
  else renderPadView(config, selectedPad)
}

/* ── display A: nothing open ─────────────────────────────────────────────────── */

function renderEmpty() {
  const box = el('div', 'ins-empty')
  box.append(
    el('div', 'ins-empty-title', 'No config open'),
    el('div', 'ins-hint', 'Open or create a config in the library to edit it here.'),
  )
  root.append(box)
}

/* ── display B: config-level settings ────────────────────────────────────────── */

function renderConfigView(config) {
  const panel = el('div', 'ins-root')

  // Header — what is open, and how much of the surface it binds.
  const head = el('div', 'ins-head')
  const titleRow = el('div', 'ins-title-row')
  titleRow.append(el('div', 'ins-title', config.name || config.id))
  head.append(titleRow, el('div', 'ins-sub', `${config.id}.json`))
  summaryLine = el('div', 'ins-summary', padsBoundText(config))
  head.append(summaryLine)
  panel.append(head)

  // Mode ­— identity fields.
  {
    const { root: sec, body } = makeSection('Mode')
    body.append(
      makeRow('Name', makeTextInput(config.name, (v) => apply(() => updateConfigMeta({ name: v })))),
      makeRow('Kind', el('span', 'ins-chip', config.kind)),
      makeStackRow('Description', makeTextarea(config.description, (v) => apply(() => updateConfigMeta({ description: v })))),
    )
    panel.append(sec)
  }

  // Background LED — painted on every pad with no explicit binding.
  {
    const { root: sec, body } = makeSection('Background LED')
    body.append(ledEditor(config.background, (led) => apply(() => updateConfigMeta({ background: led }))))
    panel.append(sec)
  }

  // Transitions — the flow graph's explicit edges.
  {
    const { root: sec, body } = makeSection('Transitions')
    renderTransitionRows(body, config)
    panel.append(sec)
  }

  // Notes — free text for future-you.
  {
    const { root: sec, body } = makeSection('Notes')
    body.append(makeTextarea(config.notes, (v) => apply(() => updateConfigMeta({ notes: v }))))
    panel.append(sec)
  }

  // Validation — the same rules the save path and the Python loader enforce.
  {
    const { root: sec, body } = makeSection('Validation')
    validationBox = el('div', 'ins-validation')
    body.append(validationBox)
    panel.append(sec)
  }

  root.append(panel)
  refreshDiagnostics()
}

function padsBoundText(config) {
  return `${Object.keys(config.pads ?? {}).length} pads bound of ${PAD_TOTAL}`
}

/** Re-fill the live diagnostic nodes without rebuilding the forms around them. */
function refreshDiagnostics() {
  const config = store.state.config
  if (!config) return
  if (summaryLine?.isConnected) summaryLine.textContent = padsBoundText(config)
  if (!validationBox?.isConnected) return
  validationBox.innerHTML = ''
  const { ok, errors } = validateConfig(config)
  if (ok) validationBox.append(el('div', 'ins-valid-ok', 'valid — no issues'))
  else for (const err of errors) validationBox.append(el('div', 'ins-valid-err', err))
}

/* ── transitions ─────────────────────────────────────────────────────────────── */

function renderTransitionRows(body, config) {
  const transitions = config.transitions ?? []

  transitions.forEach((t, i) => {
    const row = el('div', 'ins-trans-row')
    const on = makeTextInput(t.on, (v) => commitTransition(i, { on: v }))
    on.placeholder = 'on (event)'
    const to = makeSelect(libraryOptions('— target —'), t.to, (v) => commitTransition(i, { to: v }))
    const del = el('button', 'ins-icon-btn', '×')
    del.type = 'button'
    del.title = 'Delete transition'
    del.addEventListener('click', () => {
      apply(() => setTransitions(store.state.config.transitions.filter((_, j) => j !== i)))
      render() // structural change — safe to rebuild, nothing is mid-typing
    })
    row.append(on, to, del)
    body.append(row)
  })

  const add = el('button', 'ins-btn', '+ Add transition')
  add.type = 'button'
  add.addEventListener('click', () => {
    apply(() => setTransitions([...store.state.config.transitions, { on: '', to: '' }]))
    render()
  })
  body.append(add, el('div', 'ins-hint', TRANSITIONS_HINT))
}

/** Patch one transition and hand the store the FULL array (its contract). */
function commitTransition(index, patch) {
  const next = store.state.config.transitions.map((t, i) => (i === index ? { ...t, ...patch } : { ...t }))
  apply(() => setTransitions(next))
}

/* ── display C: pad settings ─────────────────────────────────────────────────── */

function renderPadView(config, padId) {
  const panel = el('div', 'ins-root')
  const kind = padKind(padId)
  const pad = config.pads[padId] ?? null // sparse — null means "unbound, all defaults"

  // Header — where you are and what the hardware does there.
  const head = el('div', 'ins-head')
  const titleRow = el('div', 'ins-title-row')
  titleRow.append(el('div', 'ins-title', `Pad ${padId}`), el('span', 'ins-chip', kind))
  const sends = el('div', 'ins-sub', SENDS_TEXT[kind](padId))
  if (kind === 'cc-top' || kind === 'cc-right') sends.title = CC_UNVERIFIED_HINT
  head.append(titleRow, sends)
  if (kind === 'cc-top' || kind === 'cc-right') head.append(el('div', 'ins-hint ins-hint--warn', CC_UNVERIFIED_HINT))
  panel.append(head)

  // Label — shown in the grid, searchable later.
  panel.append(
    makeRow('Label', makeTextInput(pad?.label ?? '', (v) => apply(() => updatePad(padId, { label: v })))),
  )

  // One LED editor per visual state. idle is the required one and starts open;
  // pressed/active start collapsed until they hold a value or the user opens them.
  for (const state of PAD_STATES) {
    const current = pad?.led?.[state]
    const open = ledOpenOverride.get(state) ?? (state === 'idle' || current != null)
    const { root: sec, body } = makeSection(`LED · ${state}`, { open })
    sec.addEventListener('toggle', () => ledOpenOverride.set(state, sec.open))
    body.append(
      ledEditor(current, (led) => apply(() => updatePad(padId, { led: { [state]: led } }))),
    )
    panel.append(sec)
  }

  // Action — buttons only; the logo is light-only and validation rejects actions on it.
  if (padIsButton(padId)) panel.append(actionSection(padId, pad))

  // Clear — back to background colour, no action; selection stays put.
  const clear = el('button', 'ins-btn ins-btn--danger', 'Clear pad')
  clear.type = 'button'
  clear.addEventListener('click', () => {
    apply(() => clearPad(padId))
    render() // pad stays selected; the view now shows defaults
  })
  panel.append(clear)

  root.append(panel)
}

/* ── action editor — rendered FROM the catalogue, never hand-built per action ── */

function actionSection(padId, pad) {
  const action = pad?.action ?? { type: 'NONE', params: {} }
  const spec = ACTIONS[action.type] ?? ACTIONS.NONE
  const { root: sec, body } = makeSection('Action')

  const typeOptions = ACTION_TYPES.map((t) => ({ value: t, label: ACTIONS[t].label }))
  body.append(
    makeRow('Type', makeSelect(typeOptions, action.type, (type) => {
      // Replace the WHOLE action: mergeDeep would otherwise keep the old
      // type's params and hold gate. hold_ms comes from the catalogue or clears.
      apply(() =>
        updatePad(padId, {
          action: {
            type,
            params: replacingKeys(action.params, {}),
            hold_ms: ACTIONS[type].defaultHold,
          },
        }),
      )
      render() // new type → new param fields
    })),
  )

  for (const [key, paramSpec] of Object.entries(spec.params)) {
    body.append(makeRow(paramSpec.label ?? key, paramControl(padId, key, paramSpec, action.params?.[key])))
  }

  if (action.type !== 'NONE') {
    const hold = makeNumberInput(action.hold_ms ?? '', { min: 0, step: HOLD_STEP_MS }, (v) =>
      apply(() => updatePad(padId, { action: { hold_ms: v > 0 ? v : undefined } })),
    )
    body.append(makeRow('Hold (ms)', hold), el('div', 'ins-hint', HOLD_HINT))
  }

  return sec
}

/** One form control per param-spec type — the four shapes schema.js promises. */
function paramControl(padId, key, spec, value) {
  const write = (v) => apply(() => updatePad(padId, { action: { params: { [key]: v } } }))
  switch (spec.type) {
    case 'number':
      return makeNumberInput(value ?? '', { min: spec.min, max: spec.max, step: spec.step }, write)
    case 'select':
      return makeSelect(spec.options, value, write)
    case 'configRef':
      return makeSelect(libraryOptions('— choose a mode —'), value, write)
    default: // 'text'
      return makeTextInput(value ?? '', write)
  }
}

/** Library index → dropdown options; the placeholder keeps "unset" representable. */
function libraryOptions(placeholder) {
  return [
    { value: '', label: placeholder },
    ...store.state.library.map((c) => ({ value: c.id, label: c.name || c.id })),
  ]
}

/* ═══════════════════════════════════════════════ LED editor (shared sub-component) */

/**
 * One editor for any LED spec — background, or any per-pad state.
 * Emits a FULL replacement object through onChange on every change, and redraws
 * itself locally (the global render is suppressed for our own edits).
 */
function ledEditor(initial, onChange) {
  const host = el('div', 'ins-led')
  let current = initial ?? { type: 'off' }

  function commit(next) {
    const full = replacingKeys(current, next) // full replacement under mergeDeep
    current = next
    onChange(full)
    draw()
  }

  function swatchRow(label, index, onPick) {
    const btn = el('button', 'ins-swatch')
    btn.type = 'button'
    const chip = el('span', 'ins-swatch-chip')
    chip.style.background = paletteHex(index)
    btn.append(chip, el('span', 'ins-swatch-idx', String(index)))
    btn.addEventListener('click', () => {
      if (activePopover?.anchor === btn) closePopover()
      else openPalettePopover(host, btn, index, onPick)
    })
    return makeRow(label, btn)
  }

  function rgbRows() {
    const rgb = [...(current.rgb ?? [0, 0, 0])]
    const preview = el('div', 'ins-preview')
    preview.style.background = ledHex({ type: 'rgb', rgb })
    RGB_CHANNELS.forEach((name, i) => {
      const row = el('div', 'ins-slider-row')
      const slider = el('input', 'ins-range')
      slider.type = 'range'
      slider.min = '0'
      slider.max = String(RGB_MAX)
      slider.value = String(rgb[i])
      const val = el('span', 'ins-slider-val', String(rgb[i]))
      slider.addEventListener('input', () => {
        // No redraw here — replacing a slider mid-drag would break the drag.
        rgb[i] = Number(slider.value)
        val.textContent = slider.value
        current = { type: 'rgb', rgb: [...rgb] }
        preview.style.background = ledHex(current)
        onChange(replacingKeys(current, current))
      })
      row.append(el('span', 'ins-label', name), slider, val)
      host.append(row)
    })
    host.append(preview, el('div', 'ins-hint', RGB_HINT))
  }

  function draw() {
    closePopover()
    host.innerHTML = ''
    host.append(
      makeRow('Type', makeSelect(
        LED_TYPES.map((t) => ({ value: t, label: t })),
        current.type,
        (type) => commit(ledDefaultsFor(type, current)),
      )),
    )
    if (current.type === 'static' || current.type === 'pulse') {
      host.append(swatchRow('Colour', current.palette ?? 0, (i) => commit({ ...current, palette: i })))
    } else if (current.type === 'flash') {
      host.append(
        swatchRow('Colour A', current.palette ?? 0, (i) => commit({ ...current, palette: i })),
        swatchRow('Colour B', current.paletteB ?? 0, (i) => commit({ ...current, paletteB: i })),
        el('div', 'ins-hint', FLASH_HINT),
      )
    } else if (current.type === 'rgb') {
      rgbRows()
    }
  }

  draw()
  return host
}

/** Sensible starting values on a type switch — keep colours the user already picked. */
function ledDefaultsFor(type, prev) {
  switch (type) {
    case 'static':
    case 'pulse':
      return { type, palette: prev.palette ?? FALLBACK_PALETTE_INDEX }
    case 'flash':
      return {
        type,
        palette: prev.palette ?? FALLBACK_PALETTE_INDEX,
        paletteB: prev.paletteB ?? FALLBACK_PALETTE_INDEX,
      }
    case 'rgb':
      return { type, rgb: prev.rgb ?? [0, 0, 0] }
    default: // 'off'
      return { type: 'off' }
  }
}

/* ── palette popover ─────────────────────────────────────────────────────────── */

function openPalettePopover(host, anchor, currentIndex, onPick) {
  closePopover()
  const pop = el('div', 'ins-pop')
  pop.append(el('div', 'ins-pop-head', paletteIsUnverified() ? 'candidate palette — UNVERIFIED' : 'palette'))
  const grid = el('div', 'ins-pop-grid')
  grid.style.gridTemplateColumns = `repeat(${PALETTE_COLUMNS}, 1fr)`
  for (const i of paletteIndices()) {
    const cell = el('button', i === currentIndex ? 'ins-pop-cell ins-pop-cell--current' : 'ins-pop-cell')
    cell.type = 'button'
    cell.title = String(i) // index on hover
    cell.style.background = paletteHex(i)
    cell.addEventListener('click', () => {
      onPick(i)
      closePopover()
    })
    grid.append(cell)
  }
  pop.append(grid)
  host.append(pop)
  pop.style.top = `${anchor.offsetTop + anchor.offsetHeight + POPOVER_GAP_PX}px`
  activePopover = { pop, anchor }
}

function closePopover() {
  activePopover?.pop.remove()
  activePopover = null
}

/** Click anywhere outside the popover (and its anchor) dismisses it. */
function onDocumentClick(e) {
  if (!activePopover) return
  if (activePopover.pop.contains(e.target) || activePopover.anchor.contains(e.target)) return
  closePopover()
}

/* ═══════════════════════════════════════════════════════════ small DOM builders */

function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text
  return node
}

/** Compact property row: label left, control right. */
function makeRow(label, control) {
  const row = el('div', 'ins-row')
  row.append(el('label', 'ins-label', label), control)
  return row
}

/** Full-width row for controls that need the whole column (textareas). */
function makeStackRow(label, control) {
  const row = el('div', 'ins-row ins-row--stack')
  row.append(el('label', 'ins-label', label), control)
  return row
}

/** Collapsible section with a tiny uppercase header. Returns { root, body }. */
function makeSection(title, { open = true } = {}) {
  const details = el('details', 'ins-section')
  details.open = open
  const body = el('div', 'ins-body')
  details.append(el('summary', 'ins-section-head', title), body)
  return { root: details, body }
}

function makeTextInput(value, onInput) {
  const input = el('input', 'ins-input')
  input.type = 'text'
  input.value = value ?? ''
  input.addEventListener('input', () => onInput(input.value))
  return input
}

function makeTextarea(value, onInput) {
  const area = el('textarea', 'ins-textarea')
  area.value = value ?? ''
  area.addEventListener('input', () => onInput(area.value))
  return area
}

/** Number input committing on 'change' (blur/enter) so half-typed values never land. */
function makeNumberInput(value, { min, max, step } = {}, onChange) {
  const input = el('input', 'ins-input')
  input.type = 'number'
  if (min != null) input.min = String(min)
  if (max != null) input.max = String(max)
  if (step != null) input.step = String(step)
  input.value = value === '' || value == null ? '' : String(value)
  input.addEventListener('change', () => onChange(input.value === '' ? undefined : Number(input.value)))
  return input
}

function makeSelect(options, value, onChange) {
  const select = el('select', 'ins-select')
  for (const o of options) {
    const opt = el('option', '', o.label)
    opt.value = o.value
    select.append(opt)
  }
  select.value = value ?? ''
  select.addEventListener('change', () => onChange(select.value))
  return select
}
