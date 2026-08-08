/**
 * viz/lab/library.js — the left sidebar: the config library and its lifecycle buttons.
 *
 * Why it exists : someone must own the config lifecycle short of pad editing — browse,
 *                 create, duplicate, import, export, delete, save, revert. Keeping all
 *                 of it in one panel keeps the grid and inspector purely about the
 *                 currently OPEN config.
 * Layer it owns : presentation + user intent. Every mutation goes through store.js
 *                 actions; the only direct api.js use is import/export, which is file
 *                 transport, not state.
 * Who calls it  : lab.js, once at boot, after loadLibrary() has filled state.library.
 * What it returns: nothing — it owns the #library subtree and re-renders on store events.
 */
import * as api from './api.js'
import { validateConfig } from './schema.js'
import {
  store,
  toast,
  loadLibrary,
  openConfig,
  saveConfig,
  createConfig,
  duplicateConfig,
  deleteConfig,
  revertConfig,
} from './store.js'

/** Display order for the grouped list. Unknown kinds land in 'other'; 'broken' is last. */
const KIND_ORDER = ['mode', 'page', 'overlay']

/* ═══════════════════════════════════════════════════════════════════ helpers */

/** name → id: lowercase, spaces→dashes, strip anything outside [a-z0-9_-], no bad lead. */
function slugify(name) {
  return String(name ?? '')
    .toLowerCase()
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9_-]/g, '')
    .replace(/^[-_]+/, '')
}

/** Slug that is guaranteed not to collide with any library id (appends -2, -3, …). */
function uniqueSlug(base) {
  if (!base) return ''
  const taken = new Set(store.state.library.map((e) => e.id))
  if (!taken.has(base)) return base
  for (let n = 2; ; n++) if (!taken.has(`${base}-${n}`)) return `${base}-${n}`
}

/** Browser-side file download — export never touches the server beyond the GET. */
function download(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function el(tag, className, text) {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text
  return node
}

/* ═══════════════════════════════════════════════════════════════════ init */

export function initLibrary(rootEl) {
  rootEl.innerHTML = `
    <div class="lib-head">
      <span class="lib-title">Library <span class="lib-count"></span></span>
      <div class="lib-head-actions">
        <button type="button" class="lib-btn" data-lib="import" title="Import a config .json file">Import</button>
        <button type="button" class="lib-btn lib-btn-primary" data-lib="new" title="Create a new config">New</button>
      </div>
    </div>
    <form class="lib-new-form" hidden>
      <input class="lib-input" data-lib="new-name" type="text" placeholder="Name" autocomplete="off" spellcheck="false" />
      <select class="lib-select" data-lib="new-kind" title="Config kind">
        <option value="mode">mode</option>
        <option value="page">page</option>
        <option value="overlay">overlay</option>
      </select>
      <div class="lib-new-id"></div>
      <div class="lib-new-actions">
        <button type="submit" class="lib-btn lib-btn-primary" data-lib="new-create" disabled>Create</button>
        <button type="button" class="lib-btn" data-lib="new-cancel">Cancel</button>
      </div>
    </form>
    <div class="lib-list"></div>
    <div class="lib-foot">
      <button type="button" class="lib-btn lib-btn-primary" data-lib="save" title="Save the open config to disk" disabled>Save</button>
      <button type="button" class="lib-btn" data-lib="revert" title="Discard unsaved edits, reload from disk" disabled>Revert</button>
    </div>
    <input type="file" data-lib="file" accept=".json,application/json" hidden />
  `

  const $ = (name) => rootEl.querySelector(`[data-lib="${name}"]`)
  const countEl = rootEl.querySelector('.lib-count')
  const listEl = rootEl.querySelector('.lib-list')
  const newForm = rootEl.querySelector('.lib-new-form')
  const newIdEl = rootEl.querySelector('.lib-new-id')
  const nameInput = $('new-name')
  const kindSelect = $('new-kind')
  const createBtn = $('new-create')
  const saveBtn = $('save')
  const revertBtn = $('revert')
  const fileInput = $('file')

  /* ─────────────────────────────────────────────────────────── list rendering */

  function renderList() {
    const lib = store.state.library ?? []
    countEl.textContent = lib.length ? `(${lib.length})` : ''
    listEl.textContent = ''

    const groups = new Map()
    for (const entry of lib) {
      const kind =
        entry.kind === 'broken' ? 'broken' : KIND_ORDER.includes(entry.kind) ? entry.kind : 'other'
      if (!groups.has(kind)) groups.set(kind, [])
      groups.get(kind).push(entry)
    }

    for (const kind of [...KIND_ORDER, 'other', 'broken']) {
      const entries = groups.get(kind)
      if (!entries?.length) continue
      const group = el('div', 'lib-group')
      group.append(el('div', 'lib-group-title', kind === 'broken' ? 'broken files' : `${kind}s`))
      for (const entry of entries) group.append(buildRow(entry, kind === 'broken'))
      listEl.append(group)
    }

    if (!lib.length) listEl.append(el('div', 'lib-empty', 'No configs yet — create one with New.'))
  }

  function buildRow(entry, broken) {
    const isActive = store.state.config?.id === entry.id
    const row = el('div', 'lib-row')
    if (isActive) row.classList.add('lib-active')
    if (broken) row.classList.add('lib-broken')

    const main = el('div', 'lib-row-main')
    const nameEl = el('div', 'lib-name', entry.name || entry.id)
    if (isActive && store.state.dirty) nameEl.append(el('span', 'lib-dot', ' •'))
    main.append(nameEl, el('div', 'lib-id', entry.id))
    row.append(main)

    if (broken) {
      row.title = 'This file failed to parse — fix or remove it on disk.'
      return row
    }

    const actions = el('div', 'lib-row-actions')
    actions.append(
      iconBtn('⧉', `Duplicate "${entry.name}"`, () => onDuplicate(entry)),
      iconBtn('↧', `Export ${entry.id}.json`, () => onExport(entry)),
      iconBtn('✕', `Delete "${entry.name}"`, () => onDelete(entry)),
    )
    row.append(actions)
    row.addEventListener('click', () => onOpen(entry))
    return row
  }

  function iconBtn(glyph, title, onClick) {
    const btn = el('button', 'lib-icon-btn', glyph)
    btn.type = 'button'
    btn.title = title
    btn.addEventListener('click', (e) => {
      e.stopPropagation() // the row underneath opens the config; the icon must not
      onClick()
    })
    return btn
  }

  /* ─────────────────────────────────────────────────────────────── row actions */

  async function onOpen(entry) {
    const open = store.state.config
    if (open?.id === entry.id) return
    if (store.state.dirty && !confirm(`discard unsaved changes to ${open?.name ?? open?.id}?`)) return
    await openConfig(entry.id)
  }

  async function onDuplicate(entry) {
    const name = prompt(`Name for the copy of "${entry.name}"`, `${entry.name} copy`)
    if (!name) return
    const id = uniqueSlug(slugify(name))
    if (!id) return toast('error', 'that name produces an empty id')
    await duplicateConfig(entry.id, id, name.trim())
  }

  async function onExport(entry) {
    try {
      const config = await api.getConfig(entry.id)
      download(`${entry.id}.json`, JSON.stringify(config, null, 2))
    } catch (err) {
      toast('error', `export failed — ${err.message}`)
    }
  }

  async function onDelete(entry) {
    if (!confirm(`delete "${entry.name}" (${entry.id}.json)? This removes the file.`)) return
    await deleteConfig(entry.id)
  }

  /* ─────────────────────────────────────────────────────────────── new form */

  function newFormSlug() {
    return slugify(nameInput.value)
  }

  function refreshNewForm() {
    const slug = newFormSlug()
    const taken = store.state.library.some((e) => e.id === slug)
    createBtn.disabled = !slug || taken
    newIdEl.classList.toggle('lib-warn', taken)
    newIdEl.textContent = !slug ? '' : taken ? `id "${slug}" is taken` : `id: ${slug}`
  }

  function closeNewForm() {
    newForm.hidden = true
    newForm.reset()
    refreshNewForm()
  }

  $('new').addEventListener('click', () => {
    newForm.hidden = !newForm.hidden
    if (!newForm.hidden) nameInput.focus()
  })
  $('new-cancel').addEventListener('click', closeNewForm)
  nameInput.addEventListener('input', refreshNewForm)

  newForm.addEventListener('submit', async (e) => {
    e.preventDefault()
    const slug = newFormSlug()
    if (!slug || store.state.library.some((c) => c.id === slug)) return
    await createConfig(slug, nameInput.value.trim(), kindSelect.value)
    closeNewForm()
  })

  /* ─────────────────────────────────────────────────────────────── import */

  $('import').addEventListener('click', () => fileInput.click())

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0]
    fileInput.value = '' // re-selecting the same file must fire 'change' again
    if (!file) return

    let config
    try {
      config = JSON.parse(await file.text())
    } catch {
      return toast('error', `${file.name} is not valid JSON`)
    }

    const { ok, errors } = validateConfig(config)
    if (!ok) return toast('error', errors[0])

    const exists = store.state.library.some((e) => e.id === config.id)
    if (exists && !confirm(`"${config.id}" already exists — overwrite it?`)) return

    try {
      await api.putConfig(config)
      await loadLibrary()
      await openConfig(config.id)
      toast('ok', `imported ${config.id}.json`)
    } catch (err) {
      toast('error', `import failed — ${err.message}`)
    }
  })

  /* ─────────────────────────────────────────────────────────────── footer */

  function refreshFoot() {
    const canWrite = !!store.state.config && store.state.dirty
    saveBtn.disabled = !canWrite
    revertBtn.disabled = !canWrite
    // Quiet "saved" affordance: same button, calmer label, no toast from here.
    saveBtn.textContent = store.state.config && !store.state.dirty ? 'Saved' : 'Save'
  }

  saveBtn.addEventListener('click', () => saveConfig())
  revertBtn.addEventListener('click', () => {
    const open = store.state.config
    if (!open) return
    if (!confirm(`revert "${open.name}" to the saved file?`)) return
    revertConfig()
  })

  /* ─────────────────────────────────────────────────────── store subscriptions */

  store.on('library:changed', () => {
    renderList()
    refreshNewForm() // a rename/delete elsewhere can free or take the pending slug
  })
  store.on('config:loaded', () => {
    renderList()
    refreshFoot()
  })
  store.on('dirty:changed', () => {
    renderList() // the unsaved dot lives on the active row
    refreshFoot()
  })

  renderList()
  refreshFoot()
}
