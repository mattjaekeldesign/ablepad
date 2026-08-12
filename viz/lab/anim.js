/**
 * viz/lab/anim.js — the animation engines. Pure math: no DOM, no fetch, no state.
 *
 * Why it exists : "stunning visual effects" on a Launchpad X are NOT hardware features —
 *                 the device only knows static/flash/pulse. Every effect is the host
 *                 computing frames and streaming them as batch SysEx (manual p.15,
 *                 81 pads per message, VERIFIED). This file is that computation. The
 *                 Python rig ports THIS file (launchpad/animations.py, Phase 5) — keep
 *                 it free of anything browser-specific so the port is mechanical.
 * Layer it owns : frame generation. Given an animation spec and a time, what colour is
 *                 every pad? Nothing else.
 * Who calls it  : grid.js (compositing animations under/over the open config) and
 *                 animeditor.js (previewing the open animation).
 * What it returns: animationFrame(anim, tMs) → Map(padId → LED spec) for that instant,
 *                 or null when a non-looping animation has finished.
 *
 * Determinism contract: same spec + same t = same frame, in JS and in Python. All
 * randomness comes from mulberry32 seeded by (seed, streamIndex) — never Math.random().
 * That is what makes "random" rain and "random" sweep directions reproducible, and it
 * is how the Python port will be verified (golden-frame comparison).
 */
import { PAD_IDS, padRow, padCol, GENERATORS, generatorDefaults } from './schema.js'

/**
 * The rig will stream one batch-SysEx frame per tick. 30 fps is the design target —
 * plausible on USB MIDI (~330 bytes/frame) but sustained throughput is UNVERIFIED
 * until the Phase 1 bench tool runs on hardware. The Lab quantises to this grid so
 * the preview shows hardware cadence, not silky 120 Hz monitor cadence.
 */
export const ANIM_TICK_MS = 1000 / 30

/* ═══════════════════════════════════════════════════ deterministic randomness */

/** mulberry32 — tiny, fast, and trivially portable to Python (mask with 0xFFFFFFFF). */
function mulberry32(seed) {
  let a = seed >>> 0
  return function () {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** Independent stream n of a seed — drop 3's colour must not disturb drop 4's column. */
const rngFor = (seed, n) => mulberry32((((seed ?? 0) * 0x9e3779b1) + n * 0x85ebca6b) >>> 0)

/* ═══════════════════════════════════════════════════════════════════ colour */

/** Hue [0,1) → unit RGB at full saturation/value (standard HSV k-formula). */
function hueRgb(h) {
  const f = (n) => {
    const k = (n + h * 6) % 6
    return 1 - Math.max(0, Math.min(k, 4 - k, 1))
  }
  return [f(5), f(3), f(1)]
}

/** Unit RGB × brightness → the LED spec the grid and the rig's SysEx layer both eat. */
const toLed = (unit, b) => ({ type: 'rgb', rgb: unit.map((v) => Math.round(v * b * 127)) })

/**
 * The generator colour policy: 'random' draws a fresh hue from the element's own rng
 * stream (per drop, per sweep, per revolution — no colour picking for the user);
 * 'hue' locks every element to params.hue. The rng is consumed either way so both
 * modes see identical geometry for the same seed.
 */
function colorFor(params, rng) {
  const random = rng()
  return params.colorMode === 'hue' ? hueRgb((params.hue ?? 0) / 360) : hueRgb(random)
}

/** Two elements on one pad: keep the brighter. Cheaper than real blending, looks right. */
function blendMax(out, id, spec) {
  const prev = out.get(id)
  if (!prev || sum(spec.rgb) > sum(prev.rgb)) out.set(id, spec)
}
const sum = (rgb) => rgb[0] + rgb[1] + rgb[2]

/* ═══════════════════════════════════════════════════════════════ generators
   One pure function per entry in schema.js's GENERATORS catalogue. Signature:
   (params-with-defaults, tMs) → Map(padId → LED spec). Unpainted pads are
   TRANSPARENT — the compositor decides what shows through. */

/** Ring of perimeter cells for SPIN_SQUARE, ordered clockwise from top-left. */
const ringCache = new Map()
function ringCells(size) {
  if (ringCache.has(size)) return ringCache.get(size)
  const lo = 5 - size / 2 // centred on the 8×8 note grid (cols/rows 1–8)
  const hi = lo + size - 1
  const cells = []
  for (let c = lo; c <= hi; c++) cells.push(String(hi * 10 + c)) // top edge →
  for (let r = hi - 1; r >= lo; r--) cells.push(String(r * 10 + hi)) // right edge ↓
  for (let c = hi - 1; c >= lo; c--) cells.push(String(lo * 10 + c)) // bottom edge ←
  for (let r = lo + 1; r <= hi - 1; r++) cells.push(String(r * 10 + lo)) // left edge ↑
  ringCache.set(size, cells)
  return cells
}

const IMPL = {
  /** Drops fall top→bottom in random columns; a new column + colour every pass. */
  RAIN(p, t) {
    const out = new Map()
    const travelMs = ((8 + p.tail) / p.speed) * 1000
    for (let d = 0; d < p.density; d++) {
      const offset = rngFor(p.seed, d)() * travelMs // de-phase the drop slots
      const pass = Math.floor((t + offset) / travelMs)
      const rng = rngFor(p.seed, d * 7919 + pass * 104729) // primes: streams never collide
      const col = 1 + Math.floor(rng() * 9)
      const color = colorFor(p, rng)
      const head = 9 - (((t + offset) % travelMs) / travelMs) * (8 + p.tail)
      for (let row = 1; row <= 9; row++) {
        const trail = row - head // the tail hangs above the falling head
        if (trail < 0 || trail >= p.tail) continue
        const b = 1 - trail / p.tail
        blendMax(out, String(row * 10 + col), toLed(color, b * b))
      }
    }
    return out
  },

  /** A soft band of light sweeping across the surface — THE background pulse.
      direction 'random' redraws direction AND colour from the rng every sweep. */
  PULSE_WAVE(p, t) {
    const out = new Map()
    const sweep = Math.floor(t / p.period_ms)
    const rng = rngFor(p.seed, sweep)
    const dirDraw = rng() // consumed even when direction is fixed — keeps streams aligned
    const dir = p.direction === 'random' ? ['up', 'down', 'left', 'right'][Math.floor(dirDraw * 4)] : p.direction
    const color = colorFor(p, rng)
    const frac = (t % p.period_ms) / p.period_ms
    const span = 8 + 2 * p.width // start and end fully off-surface so the pulse breathes
    const pos = dir === 'up' || dir === 'right' ? 1 - p.width + frac * span : 9 + p.width - frac * span
    const along = dir === 'up' || dir === 'down' ? padRow : padCol
    for (const id of PAD_IDS) {
      const d = Math.abs(along(id) - pos)
      if (d >= p.width) continue
      const b = 1 - d / p.width
      out.set(id, toLed(color, b * b)) // squared falloff — soft edges, bright core
    }
    return out
  },

  /** A comet chasing the perimeter of a centred square — reads as rotation. */
  SPIN_SQUARE(p, t) {
    const out = new Map()
    const cells = ringCells(p.size)
    const n = cells.length
    const rng = rngFor(p.seed, Math.floor(t / p.period_ms)) // new colour per revolution
    const color = colorFor(p, rng)
    const head = ((t % p.period_ms) / p.period_ms) * n
    const tail = Math.min(p.tail, n - 1)
    for (let i = 0; i < n; i++) {
      const behind = (head - i + n) % n
      if (behind >= tail) continue
      const b = 1 - behind / tail
      out.set(cells[i], toLed(color, b * b))
    }
    return out
  },
}

/* ═══════════════════════════════════════════════════════════ frames engine */

export const framesTotalMs = (anim) => (anim.frames ?? []).reduce((s, f) => s + (f.duration_ms || 0), 0)

/** The hand-drawn engine: walk the frame list at time t. Frame pads are LED specs. */
function framesFrame(anim, t) {
  const frames = anim.frames ?? []
  const total = framesTotalMs(anim)
  if (!frames.length || total <= 0) return new Map()
  if (!anim.loop && t >= total) return null // finished
  let tt = t % total
  for (const f of frames) {
    if (tt < (f.duration_ms || 0)) return new Map(Object.entries(f.pads ?? {}))
    tt -= f.duration_ms || 0
  }
  return new Map(Object.entries(frames[frames.length - 1].pads ?? {}))
}

/* ═══════════════════════════════════════════════════════════════ public API */

/** Generator params with catalogue defaults filled in — saved files stay sparse. */
function genParams(generator) {
  return { ...generatorDefaults(generator?.type), ...stripUndefined(generator?.params) }
}
function stripUndefined(obj) {
  const out = {}
  for (const [k, v] of Object.entries(obj ?? {})) if (v !== undefined) out[k] = v
  return out
}

/**
 * THE entry point. Time is quantised to the rig's tick so the Lab previews hardware
 * cadence. Returns:
 *   Map(padId → LED spec)  — the frame to composite (may be empty; unpainted = transparent)
 *   null                   — the animation is over (non-loop, past its end)
 */
export function animationFrame(anim, tMs) {
  if (!anim) return null
  // Integer tick index first — Math.floor(t / ANIM_TICK_MS) drops 1000 ms into tick 29
  // (1000/33.33… = 29.9999…). tick*1000/30 is exact where it matters, in JS and Python.
  const t = (Math.floor((tMs * 30) / 1000) * 1000) / 30
  if (anim.engine === 'frames') return framesFrame(anim, t)
  if (!anim.loop && anim.duration_ms != null && t >= anim.duration_ms) return null
  const impl = IMPL[anim.generator?.type]
  if (!impl || !GENERATORS[anim.generator?.type]) return new Map() // unknown type: transparent, never crash
  return impl(genParams(anim.generator), t)
}

/** Total length in ms, or null for "runs forever" (loop, or generator with no duration). */
export function animationDuration(anim) {
  if (!anim) return 0
  if (anim.loop) return null
  if (anim.engine === 'frames') return framesTotalMs(anim)
  return anim.duration_ms ?? null
}
