/**
 * viz/progress.js — how "percent done" is defined.
 *
 * Why it exists : a progress number is only useful if the rule behind it is written down and
 *                 identical everywhere. This module is that rule, imported by BOTH the browser
 *                 (live score) and vite.config.js (score of an old commit). One definition,
 *                 two callers, no drift.
 * Layer it owns : scoring. It does not parse (parse.js) and does not render (progressbar.js).
 * What it returns: { pct, weighted, total, leaves, byStatus }
 *
 * THE RULE
 *
 *   1. Only LEAF nodes count. A phase root ("PHASE 3") or a group header ("3.A launchpad/")
 *      describes work; it is not a checkbox. Counting them would inflate the number.
 *   2. Nodes with no status class are ignored entirely.
 *   3. `branch` nodes are excluded — the arms of the Phase 8 Option A/B fork are descriptions
 *      of a choice, not tasks. Only one arm will ever be built, so both counted as work would
 *      permanently cap the total below 100%.
 *   4. Weights: done and verified are 1.0, partial is 0.5, everything else is 0. A `decision`
 *      still sits in the denominator — an unmade decision is outstanding work.
 *
 * Deliberately NOT weighted by effort. A weighting scheme nobody maintains is a lie with
 * decimal places; equal weight per checkbox is a crude truth.
 */
import { parseTree, walk } from './parse.js'

export const WEIGHTS = { done: 1, verified: 1, partial: 0.5 }
export const EXCLUDED = new Set(['branch'])

export function scoreTree(src) {
  const tree = parseTree(src ?? '')
  const byStatus = {}
  let weighted = 0
  let total = 0
  let leaves = 0

  for (const section of tree.sections) {
    for (const { node } of walk(section.roots)) {
      if (node.children.length) continue // structural, not a checkbox
      leaves++
      if (!node.status || EXCLUDED.has(node.status)) continue
      byStatus[node.status] = (byStatus[node.status] ?? 0) + 1
      weighted += WEIGHTS[node.status] ?? 0
      total++
    }
  }

  return {
    pct: total ? (weighted / total) * 100 : 0,
    weighted,
    total,
    leaves,
    byStatus,
  }
}

/** The ordered next actions, read from the master tree's "F — NEXT" section. */
export function nextSteps(masterSrc) {
  const tree = parseTree(masterSrc ?? '')
  const section = tree.sections.find((s) => /^F\b/.test(s.title))
  if (!section) return []
  const steps = []
  for (const { node } of walk(section.roots)) {
    if (!/^STEP\s+\d+/i.test(node.label)) continue // skip the section's own root node
    const [head, ...rest] = node.label.split('\n')
    steps.push({ head: head.replace(/^STEP\s+\d+\s*→\s*/i, '').trim(), n: Number(head.match(/\d+/)?.[0] ?? 0), detail: rest.join(' ') })
  }
  return steps
}

export const fmt = (n) => `${n.toFixed(1)}%`
