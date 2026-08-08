/**
 * viz/lab/lab.js — the Config Lab shell.
 *
 * Why it exists : something has to boot the store, mount the four panels and own the
 *                 chrome that belongs to no panel (view tabs, sim toggle, save, toasts).
 * Layer it owns : composition only. No schema knowledge, no rendering of pads/forms.
 * Who calls it  : viz/lab/index.html as the single module entry.
 * What it returns: nothing — it wires the DOM and hands control to the panels.
 *
 * Boot order matters: palette before any LED paint, library before any configRef
 * dropdown, then panels, then open the first config so every panel starts populated.
 */
import { store, loadLibrary, openConfig, saveConfig, selectPad, setSim } from './store.js'
import { loadPalette } from './palette.js'
import { initLibrary } from './library.js'
import { initGrid } from './grid.js'
import { initFlow } from './flow.js'
import { initInspector } from './inspector.js'

/* ══════════════════════════════════════════════════════════════════ view tabs */

const stages = {
  grid: document.getElementById('stage-grid'),
  flow: document.getElementById('stage-flow'),
}
let view = 'grid'

function setView(next) {
  view = next
  for (const [name, el] of Object.entries(stages)) el.classList.toggle('hidden', name !== view)
  document
    .querySelectorAll('.tabs .tab')
    .forEach((b) => b.classList.toggle('active', b.dataset.view === view))
  store.emit('view:changed', view)
}

document
  .querySelectorAll('.tabs .tab')
  .forEach((b) => b.addEventListener('click', () => setView(b.dataset.view)))

// Panels ask for a view switch (e.g. flow: double-click a node → jump to the mapper).
store.on('view:request', (v) => setView(v))

/* ══════════════════════════════════════════════════════════════ sim + save UI */

const simBtn = document.getElementById('sim-toggle')
simBtn.addEventListener('click', () => setSim(!store.state.sim))
store.on('sim:changed', (on) => {
  simBtn.classList.toggle('on', on)
  simBtn.textContent = on ? '■ Simulating' : '▶ Simulate'
})

const saveBtn = document.getElementById('save')
const dirtyFlag = document.getElementById('dirty-flag')
saveBtn.addEventListener('click', () => saveConfig())
store.on('dirty:changed', (dirty) => {
  dirtyFlag.hidden = !dirty
  saveBtn.disabled = !dirty
})
saveBtn.disabled = true

// Unsaved edits are working memory only — losing them to a stray ⌘W costs a session.
window.addEventListener('beforeunload', (e) => {
  if (store.state.dirty) e.preventDefault()
})

/* ═══════════════════════════════════════════════════════════════════ keyboard */

window.addEventListener('keydown', (e) => {
  const typing = /^(input|textarea|select)$/i.test(document.activeElement?.tagName ?? '')
  if ((e.metaKey || e.ctrlKey) && e.key === 's') {
    e.preventDefault() // browser save dialog is never what anyone wants here
    saveConfig()
    return
  }
  if (typing || e.metaKey || e.ctrlKey || e.altKey) return
  if (e.key === 'Escape') selectPad(null)
  else if (e.key === ' ') {
    e.preventDefault()
    setSim(!store.state.sim)
  } else if (e.key === '1') setView('grid')
  else if (e.key === '2') setView('flow')
})

/* ═══════════════════════════════════════════════════════════════════ toasts */

const toastsEl = document.getElementById('toasts')
store.on('toast', ({ kind, text }) => {
  const el = document.createElement('div')
  el.className = `toast ${kind}`
  el.textContent = text
  toastsEl.append(el)
  setTimeout(() => el.classList.add('bye'), 2600)
  setTimeout(() => el.remove(), 3000)
})

/* ══════════════════════════════════════════════════════════════════════ boot */

await loadPalette()
try {
  await loadLibrary()
} catch (err) {
  store.emit('toast', { kind: 'error', text: `library load failed: ${err.message}` })
}

initLibrary(document.getElementById('library'))
initGrid(stages.grid)
initFlow(stages.flow)
initInspector(document.getElementById('inspector'))

// Open something real on first load: boot mode if present, else the first config.
const first = store.state.library.find((c) => c.id === 'boot') ?? store.state.library[0]
if (first && first.kind !== 'broken') {
  try {
    await openConfig(first.id)
  } catch (err) {
    store.emit('toast', { kind: 'error', text: `could not open ${first.id}: ${err.message}` })
  }
}
setView('grid')
