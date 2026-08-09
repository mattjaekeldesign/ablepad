// tools/dump_golden_frames.mjs — regenerate tests/golden/animation-frames.json
// from the REAL Lab engine (viz/lab/anim.js).
//
// LAYER: none. Bench instrument for the determinism contract between the Lab's
// JS engine and launchpad/animations.py. Run after ANY edit to viz/lab/anim.js
// or viz/lab/schema.js, then re-run pytest:
//
//     node tools/dump_golden_frames.mjs
//     .venv/bin/python -m pytest tests/test_animations_golden.py
//
// If the Python tests fail after regeneration, the ENGINES have diverged and the
// port must be updated to match the Lab — the Lab is the design authority.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const REPO = dirname(dirname(fileURLToPath(import.meta.url)))
const { animationFrame } = await import(join(REPO, 'viz/lab/anim.js'))

const readAnim = (name) => JSON.parse(readFileSync(join(REPO, 'animations', name), 'utf-8'))

// Times chosen to hit: t=0, one-tick boundaries, mid-sweep, fractional ms
// (quantisation), pass/sweep/revolution rollovers, and past-the-end for
// non-looping specs.
const TIMES = [0, 33.4, 100, 333.3333, 500, 999, 1000, 1234.56, 1999, 2000, 2500, 3999, 4000, 5000, 12345]

const CASES = {
  // The committed assets, exactly as shipped.
  'asset:boot-rain': readAnim('boot-rain.json'),
  'asset:error-spin': readAnim('error-spin.json'),
  'asset:pulse-sweep': readAnim('pulse-sweep.json'),

  // Sparse params — defaults must fill identically in both languages.
  'rain-sparse-defaults': { engine: 'generator', loop: true, generator: { type: 'RAIN', params: { seed: 42 } } },

  // Fixed-hue rain (rng still consumed for geometry alignment).
  'rain-fixed-hue': {
    engine: 'generator', loop: true,
    generator: { type: 'RAIN', params: { density: 12, speed: 4, tail: 8, colorMode: 'hue', hue: 210, seed: 99 } },
  },

  // Every fixed pulse direction + fractional width.
  ...Object.fromEntries(['up', 'down', 'left', 'right'].map((dir) => [
    `pulse-${dir}`,
    { engine: 'generator', loop: true, generator: { type: 'PULSE_WAVE', params: { direction: dir, period_ms: 900, width: 1.5, colorMode: 'hue', hue: 120, seed: 5 } } },
  ])),

  // Spin at both non-default sizes; tail longer than the ring must clamp.
  'spin-4-long-tail': { engine: 'generator', loop: true, generator: { type: 'SPIN_SQUARE', params: { size: 4, period_ms: 800, tail: 16, colorMode: 'random', seed: 11 } } },
  'spin-8': { engine: 'generator', loop: true, generator: { type: 'SPIN_SQUARE', params: { size: 8, period_ms: 3000, tail: 6, colorMode: 'hue', hue: 300, seed: 2 } } },

  // Non-looping generator with a duration — must return null past the end.
  'rain-ends': { engine: 'generator', loop: false, duration_ms: 2000, generator: { type: 'RAIN', params: { seed: 7 } } },

  // Frames engine: loop and non-loop, mixed spec styles, last-frame fallback.
  'frames-loop': {
    engine: 'frames', loop: true,
    frames: [
      { duration_ms: 400, pads: { 11: { type: 'rgb', rgb: [127, 0, 0] }, 55: { type: 'palette', color: 21 } } },
      { duration_ms: 600, pads: { 99: { type: 'rgb', rgb: [0, 127, 0] } } },
    ],
  },
  'frames-once': {
    engine: 'frames', loop: false,
    frames: [
      { duration_ms: 1000, pads: { 45: { type: 'rgb', rgb: [10, 20, 30] } } },
      { duration_ms: 1000, pads: {} },
    ],
  },
  'frames-empty': { engine: 'frames', loop: true, frames: [] },

  // Unknown generator: transparent frame, never a crash.
  'unknown-generator': { engine: 'generator', loop: true, generator: { type: 'LASER_SHARKS', params: {} } },
}

const out = {}
for (const [name, spec] of Object.entries(CASES)) {
  const samples = {}
  for (const t of TIMES) {
    const frame = animationFrame(spec, t)
    samples[String(t)] = frame === null ? null : Object.fromEntries(frame)
  }
  out[name] = { spec, samples }
}

mkdirSync(join(REPO, 'tests/golden'), { recursive: true })
const path = join(REPO, 'tests/golden/animation-frames.json')
writeFileSync(path, JSON.stringify(out, null, 1))
const frames = Object.values(out).reduce((s, c) => s + Object.keys(c.samples).length, 0)
console.log(`wrote ${path}: ${Object.keys(out).length} cases, ${frames} sampled frames`)
