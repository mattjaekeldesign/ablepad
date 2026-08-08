/**
 * viz/lab/schema.js — the single source of truth for what a Launchpad config IS.
 *
 * Why it exists : every other Lab module (grid, inspector, flow, library) and — later —
 *                 the Python rig's mappings loader agree on one shape by importing/porting
 *                 THIS file. Change the schema here or nowhere.
 * Layer it owns : pure data definitions + validation. No DOM, no fetch, no state.
 * Who calls it  : store.js (defaults, validation), every UI component (enums, helpers).
 * What it returns: constants, factory functions, and a validator.
 *
 * Pad addressing follows PROGRAMMER-MODE numbering (docs/launchpad-x-sysex.md §5):
 *   id = row*10 + col, rows 1–9 bottom→top, cols 1–9 left→right.
 *   Rows 1–8 × cols 1–8  → the 8×8 note grid (corners VERIFIED, interior inferred)
 *   Row 9 cols 1–8       → top function row, CC 91–98            (UNVERIFIED)
 *   Col 9 rows 1–8       → right scene column, CC 19…89          (UNVERIFIED)
 *   99                   → logo LED (light-only, never a button)  (UNVERIFIED)
 */

export const SCHEMA_VERSION = 1

/* ═══════════════════════════════════════════════════════════════ pad addressing */

/** All 81 addressable LEDs, bottom-left to top-right, as string ids ("11"…"99"). */
export const PAD_IDS = []
for (let row = 1; row <= 9; row++) for (let col = 1; col <= 9; col++) PAD_IDS.push(String(row * 10 + col))

export const padRow = (id) => Math.floor(Number(id) / 10)
export const padCol = (id) => Number(id) % 10

/** 'grid' | 'cc-top' | 'cc-right' | 'logo' — drives both rendering and what a pad may do. */
export function padKind(id) {
  const r = padRow(id)
  const c = padCol(id)
  if (r === 9 && c === 9) return 'logo'
  if (r === 9) return 'cc-top'
  if (c === 9) return 'cc-right'
  return 'grid'
}

/** True when the pad sends events (the logo is light-only). */
export const padIsButton = (id) => padKind(id) !== 'logo'

/* ═══════════════════════════════════════════════════════════════════ LED states */

/**
 * An LED spec mirrors the hardware's lighting types (SysEx 03h, manual p.15):
 *   { type: 'off' }
 *   { type: 'static', palette: 0–127 }
 *   { type: 'flash',  palette: A, paletteB: B }   // alternates A/B, 1 beat period
 *   { type: 'pulse',  palette: 0–127 }            // dark↔full ramp, 2 beat period
 *   { type: 'rgb',    rgb: [r, g, b] }            // each 0–127, SysEx-only
 *
 * Flash/pulse are beat-clock slaved; free-run = 120 BPM → flash 0.5 s, pulse 1 s.
 * The Lab simulates at exactly those free-run periods.
 */
export const LED_TYPES = ['off', 'static', 'flash', 'pulse', 'rgb']

/**
 * Per-pad visual states the rig renderer will know about:
 *   idle    — resting look while the mode is showing
 *   pressed — while the finger is down (LED feedback)
 *   active  — this pad's thing is currently engaged (loaded set, running hotspot…)
 * Only `idle` is required; missing states fall back to `idle`.
 */
export const PAD_STATES = ['idle', 'pressed', 'active']

/* ═══════════════════════════════════════════════════════════════════ actions */

/**
 * The action catalogue. The inspector renders its editor form FROM this table —
 * add an action here and the UI grows the fields; no panel code changes.
 * (Same philosophy as the rig's future command dispatcher: enums, not one-off buttons.)
 *
 * Param spec types the inspector understands:
 *   number    → <input type=number>  { min, max, step }
 *   text      → <input type=text>
 *   select    → dropdown             { options: [{value, label}] }
 *   configRef → dropdown of configs in the library (value = config id)
 *
 * `defaultHold` (ms) pre-fills action.hold_ms — hold-to-confirm gates from the roadmap:
 * load set 2 s, reboot 4 s (System Mode), shutdown 6 s.
 */
export const ACTIONS = {
  NONE: { label: 'No action', params: {} },
  SWITCH_MODE: {
    label: 'Switch mode',
    params: { target: { type: 'configRef', label: 'Target mode' } },
  },
  LOAD_SET: {
    label: 'Load Ableton set',
    params: { slot: { type: 'number', label: 'Set slot', min: 0, max: 63, step: 1 } },
    defaultHold: 2000,
  },
  PAGE_NEXT: { label: 'Next page', params: {} },
  PAGE_PREV: { label: 'Previous page', params: {} },
  RESCAN_SETS: { label: 'Rescan set folder', params: {} },
  ABLETON_RESTART: { label: 'Restart Ableton', params: {}, defaultHold: 2000 },
  PANIC_MUTE: { label: 'Panic mute', params: {} },
  HOTSPOT_TOGGLE: { label: 'Hotspot on/off', params: {} },
  SYSTEM_REBOOT: { label: 'Reboot Beelink', params: {}, defaultHold: 4000 },
  SYSTEM_SHUTDOWN: { label: 'Shut down Beelink', params: {}, defaultHold: 6000 },
  SEND_MIDI: {
    label: 'Send raw MIDI',
    params: { message: { type: 'text', label: 'Bytes (hex, e.g. B0 07 7F)' } },
  },
}

export const ACTION_TYPES = Object.keys(ACTIONS)

/* ═══════════════════════════════════════════════════════════════════ factories */

/** A pad that does nothing and shows nothing — the state every pad starts in. */
export function defaultPad() {
  return {
    label: '',
    led: { idle: { type: 'off' } },
    action: { type: 'NONE', params: {} },
  }
}

/**
 * A fresh config. `kind` is 'mode' for now; 'page' and 'overlay' are reserved so
 * pagination and momentary layers don't need a schema bump later.
 */
export function defaultConfig(id, name, kind = 'mode') {
  return {
    schemaVersion: SCHEMA_VERSION,
    id,
    name,
    kind,
    description: '',
    background: { type: 'off' }, // painted on every pad that has no explicit binding
    pads: {}, // sparse: only pads that differ from defaultPad()
    transitions: [], // [{ on: 'ACTION or event name', to: 'config-id' }] — flow edges
    notes: '',
    meta: { flowPos: null }, // {x, y} in the flow view; null = auto-place
  }
}

/* ═══════════════════════════════════════════════════════════════════ validation */

function checkLed(led, where, errors) {
  if (!led || typeof led !== 'object') return errors.push(`${where}: not an object`)
  if (!LED_TYPES.includes(led.type)) return errors.push(`${where}: unknown LED type "${led.type}"`)
  const okIndex = (n) => Number.isInteger(n) && n >= 0 && n <= 127
  if ((led.type === 'static' || led.type === 'pulse' || led.type === 'flash') && !okIndex(led.palette))
    errors.push(`${where}: palette must be 0–127, got ${led.palette}`)
  if (led.type === 'flash' && !okIndex(led.paletteB))
    errors.push(`${where}: paletteB must be 0–127, got ${led.paletteB}`)
  if (led.type === 'rgb' && !(Array.isArray(led.rgb) && led.rgb.length === 3 && led.rgb.every(okIndex)))
    errors.push(`${where}: rgb must be [r,g,b] each 0–127`)
}

/**
 * Validate a whole config. Returns { ok, errors: [strings] }.
 * The Lab refuses to SAVE an invalid config; the Python loader will refuse to LOAD one.
 * Same rules, both sides — that is the point of this file.
 */
export function validateConfig(config) {
  const errors = []
  if (!config || typeof config !== 'object') return { ok: false, errors: ['config is not an object'] }
  if (config.schemaVersion !== SCHEMA_VERSION)
    errors.push(`schemaVersion ${config.schemaVersion} ≠ ${SCHEMA_VERSION}`)
  if (!/^[a-z0-9][a-z0-9_-]*$/.test(config.id ?? '')) errors.push(`bad id "${config.id}"`)
  if (!config.name) errors.push('name is empty')
  checkLed(config.background, 'background', errors)

  for (const [id, pad] of Object.entries(config.pads ?? {})) {
    if (!PAD_IDS.includes(id)) {
      errors.push(`pad "${id}" is not a valid programmer-mode index`)
      continue
    }
    for (const [state, led] of Object.entries(pad.led ?? {})) {
      if (!PAD_STATES.includes(state)) errors.push(`pad ${id}: unknown LED state "${state}"`)
      else checkLed(led, `pad ${id}.led.${state}`, errors)
    }
    const action = pad.action ?? { type: 'NONE' }
    if (!ACTION_TYPES.includes(action.type)) errors.push(`pad ${id}: unknown action "${action.type}"`)
    if (action.type !== 'NONE' && !padIsButton(id)) errors.push(`pad ${id} is the logo — light-only, no action`)
    if (action.hold_ms != null && !(Number.isInteger(action.hold_ms) && action.hold_ms >= 0))
      errors.push(`pad ${id}: hold_ms must be a non-negative integer`)
  }

  for (const [i, t] of (config.transitions ?? []).entries()) {
    if (!t || typeof t.on !== 'string' || typeof t.to !== 'string')
      errors.push(`transition ${i}: needs { on: string, to: string }`)
  }

  return { ok: errors.length === 0, errors }
}
