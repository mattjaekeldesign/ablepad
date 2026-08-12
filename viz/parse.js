/**
 * viz/parse.js — turn a .mmd flowchart into a real tree structure.
 *
 * Why it exists : the outline view needs nodes, nesting and status as data, not as an SVG.
 *                 The sidebar and the status chips read the same output, so there is exactly
 *                 one parser in the app.
 * Layer it owns : text → data. No DOM, no mermaid, no rendering.
 * Who calls it  : main.js (sections, chips) and outline.js (rows).
 * What it returns: { sections: [{ id, title, roots: [Node], nodes: Map }], counts: {status: n} }
 *
 * It understands only the subset we author. Anything it cannot classify is ignored rather than
 * thrown, because a half-parsed outline still beats a blank pane — the diagram view is the
 * authority if the two ever disagree.
 */

/** Node shapes we use: A["x"] A(["x"]) A{"x"} A{{"x"}} A("x") — captured generically. */
const NODE_RE = /^([A-Za-z0-9_]+)\s*(?:(\(\[|\{\{|\[|\{|\()\s*"([^"]*)"\s*(?:\]\)|\}\}|\]|\}|\))\s*)?(?::::([a-z]+))?$/
const EDGE_SPLIT = /\s(?:-->|==>|-\.->|---|===)\s/

const clean = (s) =>
  s
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?[a-z]+>/gi, '')
    .trim()

/** Strip an inline edge label — `-->|"gates"|` — before splitting on the arrow. */
const stripEdgeLabels = (line) => line.replace(/\|[^|]*\|/g, ' ')

function upsert(map, id) {
  let n = map.get(id)
  if (!n) {
    n = { id, label: id, status: null, children: [], parents: [] }
    map.set(id, n)
  }
  return n
}

export function parseTree(src) {
  const sections = []
  const nodes = new Map() // id → node, across the whole file
  const owner = new Map() // id → section index it was first defined in
  const edges = [] // [fromId, toId]
  let current = null

  for (const rawLine of src.split('\n')) {
    const line = rawLine.trim()
    if (!line || line.startsWith('%%')) continue
    if (/^(flowchart|graph|direction|classDef|class |style |linkStyle)/.test(line)) continue

    const sub = line.match(/^subgraph\s+([A-Za-z0-9_]+)\s*\[\s*"([^"]+)"\s*\]/)
    if (sub) {
      current = { id: sub[1], title: sub[2], roots: [], memberIds: [] }
      sections.push(current)
      continue
    }
    if (line === 'end') {
      current = null
      continue
    }

    // One line can define several hops: A --> B --> C
    const parts = stripEdgeLabels(line)
      .split(EDGE_SPLIT)
      .map((p) => p.trim())
      .filter(Boolean)

    let prevId = null
    for (const part of parts) {
      const m = part.match(NODE_RE)
      if (!m) {
        prevId = null
        continue
      }
      const [, id, , label, status] = m
      const node = upsert(nodes, id)
      if (label !== undefined) node.label = clean(label)
      if (status) node.status = status

      // A node belongs to the section it is first mentioned in.
      if (current && !owner.has(id)) {
        owner.set(id, sections.length - 1)
        current.memberIds.push(id)
      }
      if (prevId) edges.push([prevId, id])
      prevId = id
    }
  }

  // Nest only WITHIN a section. Cross-section edges (P0 ==> P1) are phase ordering, not
  // parenthood — treating them as nesting would bury every phase inside Phase 0.
  for (const [from, to] of edges) {
    if (owner.get(from) !== owner.get(to)) continue
    const parent = nodes.get(from)
    const child = nodes.get(to)
    if (!parent || !child || parent === child) continue
    if (child.parents.includes(parent.id)) continue
    child.parents.push(parent.id)
    parent.children.push(child)
  }

  for (const s of sections) {
    s.roots = s.memberIds.map((id) => nodes.get(id)).filter((n) => n && n.parents.length === 0)
  }

  return { sections, nodes, counts: countStatuses(src) }
}

/** Status totals for the pane header chips. Counted from the source, not the tree, so a node
 *  that failed to parse still shows up in the totals. */
export function countStatuses(src) {
  const counts = {}
  for (const m of src.matchAll(/:::([a-z]+)/g)) counts[m[1]] = (counts[m[1]] ?? 0) + 1
  return counts
}

/** Depth-first walk of a section, yielding { node, depth, last } for flat rendering. */
export function* walk(roots, depth = 0, seen = new Set()) {
  for (let i = 0; i < roots.length; i++) {
    const node = roots[i]
    if (seen.has(node.id)) continue // cycles are a content bug; do not hang on them
    seen.add(node.id)
    yield { node, depth, last: i === roots.length - 1 }
    if (node.children.length) yield* walk(node.children, depth + 1, seen)
  }
}
