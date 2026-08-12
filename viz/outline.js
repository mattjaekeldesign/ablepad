/**
 * viz/outline.js — the text view of a tree.
 *
 * Why it exists : a 131-node SVG behind a zoom control is a bad reading surface. The outline is
 *                 the same data as plain indented text: scrollable, searchable, selectable,
 *                 copy-pasteable, no zoom, no pan, no blur.
 * Layer it owns : rendering a parsed tree to DOM. It does not parse and it does not fetch.
 * Who calls it  : main.js, one instance per pane.
 * What it returns: a small controller — see the object at the bottom.
 */
import { walk } from './parse.js'

const GLYPH = {
  done: '✓',
  partial: '◐',
  todo: '○',
  verified: '✓',
  unverified: '✗',
  decision: '◆',
  branch: '·',
  riskhigh: '▲',
  next: '→',
}

export function createOutline(host, tree, treeName) {
  host.innerHTML = ''
  const sectionEls = new Map()

  for (const section of tree.sections) {
    const wrap = document.createElement('section')
    wrap.className = 'ol-section'
    wrap.id = `ol-${treeName}-${section.id}`

    const head = document.createElement('button')
    head.className = 'ol-head'
    head.innerHTML =
      `<span class="ol-caret">▾</span>` +
      `<span class="ol-head-title">${escape(section.title)}</span>` +
      `<span class="ol-head-count">${section.memberIds.length}</span>`
    head.addEventListener('click', () => wrap.classList.toggle('collapsed'))
    wrap.append(head)

    const body = document.createElement('div')
    body.className = 'ol-body'

    for (const { node, depth } of walk(section.roots)) {
      const [first, ...rest] = node.label.split('\n')
      const row = document.createElement('div')
      row.className = `ol-row st-${node.status ?? 'none'}`
      row.style.setProperty('--depth', String(depth))
      row.dataset.text = node.label.toLowerCase()
      row.innerHTML =
        `<span class="ol-rail"></span>` +
        `<span class="ol-dot" title="${node.status ?? ''}">${GLYPH[node.status] ?? '·'}</span>` +
        `<span class="ol-text"><span class="ol-first">${escape(first)}</span>` +
        rest.map((r) => `<span class="ol-cont">${escape(r)}</span>`).join('') +
        `</span>`
      body.append(row)
    }

    wrap.append(body)
    host.append(wrap)
    sectionEls.set(section.id, wrap)
  }

  return {
    /** Scroll a section to the top of the pane and flash it, mirroring diagram focus. */
    scrollToSection(id) {
      const el = sectionEls.get(id)
      if (!el) return false
      el.classList.remove('collapsed')
      el.scrollIntoView({ block: 'start', behavior: 'smooth' })
      host.querySelectorAll('.ol-section.active').forEach((s) => s.classList.remove('active'))
      el.classList.add('active')
      return true
    },

    /** Substring filter. Hides non-matching rows; a section with no match collapses out of the way. */
    filter(query) {
      const q = query.trim().toLowerCase()
      host.classList.toggle('filtering', q.length > 0)
      for (const [, wrap] of sectionEls) {
        let hits = 0
        wrap.querySelectorAll('.ol-row').forEach((row) => {
          const hit = !q || row.dataset.text.includes(q)
          row.classList.toggle('hidden', !hit)
          if (hit) hits++
        })
        const titleHit = q && wrap.querySelector('.ol-head-title').textContent.toLowerCase().includes(q)
        wrap.classList.toggle('hidden', !!q && hits === 0 && !titleHit)
        if (q && titleHit) wrap.querySelectorAll('.ol-row').forEach((r) => r.classList.remove('hidden'))
      }
      return host.querySelectorAll('.ol-row:not(.hidden)').length
    },

    setCollapsed(collapsed) {
      sectionEls.forEach((el) => el.classList.toggle('collapsed', collapsed))
    },

    get scrollTop() {
      return host.scrollTop
    },
    set scrollTop(v) {
      host.scrollTop = v
    },
  }
}

function escape(s) {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])
}
