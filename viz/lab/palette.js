/**
 * viz/lab/palette.js — the 128-colour candidate palette, as CSS-usable hex.
 *
 * Why it exists : grid LEDs and inspector swatches must agree on what palette index N
 *                 looks like. One cache, one lookup.
 * Layer it owns : palette data only. No app state.
 * Who calls it  : grid.js (painting LEDs), inspector.js (colour picker).
 * What it returns: hex strings. UNVERIFIED against real hardware — the table is sampled
 *                 from the Launchpad Mini MK3 manual (different device; 8 indices
 *                 confirmed for the X). The Lab shows colours as a design aid, not truth.
 */
import { getPalette } from './api.js'

let colors = null // { "0": "#616161", … } once loaded
let unverified = true

/** Call once at boot, before any render. Failure paints everything grey, loudly. */
export async function loadPalette() {
  try {
    const data = await getPalette()
    colors = data.colors
    unverified = !!data.unverified
  } catch (err) {
    console.error('palette load failed — all indices render #444', err)
    colors = {}
  }
}

/** Hex for a palette index. Index 0 is "off" — rendered as near-black, not the doc's grey. */
export function paletteHex(index) {
  if (index === 0) return '#101013'
  return colors?.[String(index)] ?? '#444444'
}

/** Hex for an LED spec ({type, palette, paletteB, rgb}) in a given animation phase. */
export function ledHex(led, phase = 'a') {
  if (!led || led.type === 'off') return '#101013'
  if (led.type === 'rgb') {
    const [r, g, b] = led.rgb ?? [0, 0, 0]
    const to255 = (v) => Math.round((Math.min(127, Math.max(0, v)) / 127) * 255)
    return `rgb(${to255(r)}, ${to255(g)}, ${to255(b)})`
  }
  if (led.type === 'flash' && phase === 'b') return paletteHex(led.paletteB ?? 0)
  return paletteHex(led.palette ?? 0)
}

export const paletteIsUnverified = () => unverified

/** All 128 indices for pickers. */
export const paletteIndices = () => Array.from({ length: 128 }, (_, i) => i)
