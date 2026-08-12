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
import { validateConfig, validateAnimation, ANIM_ENGINES } from './schema.js'
import {
  store,
  toast,
  loadLibrary,
  loadAnimLibrary,
  openConfig,
  saveAll,
  anyDirty,
  createConfig,
  duplicateConfig,
  deleteConfig,
  revertConfig,
  openAnimation,
  createAnimation,
  duplicateAnimation,
  deleteAnimation,
  revertAnimation,
} from './store.js'

/** Display order for the grouped list. Unknown kinds land in 'other'; 'broken' is last. */
const KIND_ORDER = ['mode', 'page', 'overlay']

/** The New form creates either entity; anim kinds carry their engine in the value. */
const NEW_KINDS = [
  { value: 'mode', label: 'screen · mode' },
  { value: 'page', label: 'screen · page' },
  { value: 'overlay', label: 'screen · overlay' },
  { value: 'anim:generator', label: 'animation · generator' },
  { value: 'anim:frames', label: 'animation · frames' },
]

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

/** Slug that collides with NEITHER library — configs and animations share the id space
    for sanity's sake, even though they live in different directories. */
function uniqueSlug(base) {
  if (!base) return ''
  const taken = new Set([...store.state.library, ...store.state.animLibrary].map((e) => e.id))
  if (!taken.has(base)) return base
  for (let n = 2; ; n++) if (!taken.has(`${base}-${n}`)) return `${base}-${n}`
}
const slugTaken = (slug) =>
  store.state.library.some((e) => e.id === slug) || store.state.animLibrary.some((e) => e.id === slug)

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
      <select class="lib-select" data-lib="new-kind" title="What to create">
        ${NEW_KINDS.map((k) => `<option value="${k.value}">${k.label}</option>`).join('')}
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

    // Animations — the second entity family, one flat group under the screens.
    const anims = store.state.animLibrary ?? []
    if (anims.length) {
      const group = el('div', 'lib-group')
      group.append(el('div', 'lib-group-title', 'animations'))
      for (const entry of anims) group.append(buildAnimRow(entry))
      listEl.append(group)
    }
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

  function buildAnimRow(entry) {
    const isActive = store.state.anim?.id === entry.id
    const row = el('div', 'lib-row')
    if (isActive) row.classList.add('lib-active')

    const main = el('div', 'lib-row-main')
    const nameEl = el('div', 'lib-name', entry.name || entry.id)
    if (isActive && store.state.animDirty) nameEl.append(el('span', 'lib-dot', ' •'))
    main.append(nameEl, el('div', 'lib-id', `${entry.id} · ${entry.engine ?? '?'}`))
    row.append(main)

    const actions = el('div', 'lib-row-actions')
    actions.append(
      iconBtn('⧉', `Duplicate "${entry.name}"`, () => onDuplicateAnim(entry)),
      iconBtn('↧', `Export ${entry.id}.json`, () => onExportAnim(entry)),
      iconBtn('✕', `Delete "${entry.name}"`, () => onDeleteAnim(entry)),
    )
    row.append(actions)
    row.addEventListener('click', () => onOpenAnim(entry))
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

  /* ─────────────────────────────────────────────────────── animation row actions */

  async function onOpenAnim(entry) {
    if (store.state.anim?.id === entry.id) {
      store.emit('view:request', 'anim')
      return
    }
    if (store.state.animDirty && !confirm(`discard unsaved changes to ${store.state.anim?.name}?`)) return
    await openAnimation(entry.id)
    store.emit('view:request', 'anim') // opening an animation means editing it
  }

  async function onDuplicateAnim(entry) {
    const name = prompt(`Name for the copy of "${entry.name}"`, `${entry.name} copy`)
    if (!name) return
    const id = uniqueSlug(slugify(name))
    if (!id) return toast('error', 'that name produces an empty id')
    await duplicateAnimation(entry.id, id, name.trim())
    store.emit('view:request', 'anim')
  }

  async function onExportAnim(entry) {
    try {
      const anim = await api.getAnimation(entry.id)
      download(`${entry.id}.json`, JSON.stringify(anim, null, 2))
    } catch (err) {
      toast('error', `export failed — ${err.message}`)
    }
  }

  async function onDeleteAnim(entry) {
    // Deleting a referenced animation is allowed — configs keep the ref, the renderer
    // skips it, the inspector flags it. Name the consequence at the moment of choice.
    const refs = usedBy(entry.id)
    const warning = refs.length ? `\n\nStill referenced by: ${refs.join(', ')} — those screens will warn.` : ''
    if (!confirm(`delete "${entry.name}" (${entry.id}.json)? This removes the file.${warning}`)) return
    await deleteAnimation(entry.id)
  }

  /** Which OPEN-able configs reference this animation (index has no slots — best effort
      from the open config only; the inspector does the authoritative dangling check). */
  function usedBy(animId) {
    const open = store.state.config
    if (!open?.animations) return []
    return Object.entries(open.animations)
      .filter(([, b]) => b?.ref === animId)
      .map(([slot]) => `${open.id}.${slot}`)
  }

  /* ─────────────────────────────────────────────────────────────── new form */

  function newFormSlug() {
    return slugify(nameInput.value)
  }

  function refreshNewForm() {
    const slug = newFormSlug()
    const taken = slugTaken(slug)
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
    if (!slug || slugTaken(slug)) return
    const kind = kindSelect.value
    if (kind.startsWith('anim:')) {
      await createAnimation(slug, nameInput.value.trim(), kind.slice('anim:'.length))
      store.emit('view:request', 'anim') // straight into the editor — that's why it was made
    } else {
      await createConfig(slug, nameInput.value.trim(), kind)
    }
    closeNewForm()
  })

  /* ─────────────────────────────────────────────────────────────── import */

  $('import').addEventListener('click', () => fileInput.click())

  fileInput.addEventListener('change', async () => {
    const file = fileInput.files?.[0]
    fileInput.value = '' // re-selecting the same file must fire 'change' again
    if (!file) return

    let data
    try {
      data = JSON.parse(await file.text())
    } catch {
      return toast('error', `${file.name} is not valid JSON`)
    }

    // One Import button, two entity types: the `engine` field is the discriminator —
    // configs never have one, animations always do.
    const isAnim = ANIM_ENGINES.includes(data.engine)
    const { ok, errors } = isAnim ? validateAnimation(data) : validateConfig(data)
    if (!ok) return toast('error', errors[0])

    const pool = isAnim ? store.state.animLibrary : store.state.library
    if (pool.some((e) => e.id === data.id) && !confirm(`"${data.id}" already exists — overwrite it?`)) return

    try {
      if (isAnim) {
        await api.putAnimation(data)
        await loadAnimLibrary()
        await openAnimation(data.id)
        store.emit('view:request', 'anim')
      } else {
        await api.putConfig(data)
        await loadLibrary()
        await openConfig(data.id)
      }
      toast('ok', `imported ${data.id}.json`)
    } catch (err) {
      toast('error', `import failed — ${err.message}`)
    }
  })

  /* ─────────────────────────────────────────────────────────────── footer */

  function refreshFoot() {
    saveBtn.disabled = !anyDirty()
    revertBtn.disabled = !anyDirty()
    // Quiet "saved" affordance: same button, calmer label, no toast from here.
    const anythingOpen = store.state.config || store.state.anim
    saveBtn.textContent = anythingOpen && !anyDirty() ? 'Saved' : 'Save'
  }

  saveBtn.addEventListener('click', () => saveAll())
  revertBtn.addEventListener('click', () => {
    const names = [
      store.state.dirty ? `"${store.state.config?.name}"` : null,
      store.state.animDirty ? `"${store.state.anim?.name}"` : null,
    ].filter(Boolean)
    if (!names.length) return
    if (!confirm(`revert ${names.join(' and ')} to the saved file${names.length > 1 ? 's' : ''}?`)) return
    if (store.state.dirty) revertConfig()
    if (store.state.animDirty) revertAnimation()
  })

  /* ─────────────────────────────────────────────────────── store subscriptions */

  store.on('library:changed', () => {
    renderList()
    refreshNewForm() // a rename/delete elsewhere can free or take the pending slug
  })
  store.on('animlib:changed', () => {
    renderList()
    refreshNewForm()
  })
  store.on('config:loaded', () => {
    renderList()
    refreshFoot()
  })
  store.on('anim:loaded', () => {
    renderList()
    refreshFoot()
  })
  store.on('dirty:changed', () => {
    renderList() // the unsaved dot lives on the active row
    refreshFoot()
  })
  store.on('animdirty:changed', () => {
    renderList()
    refreshFoot()
  })

  renderList()
  refreshFoot()
}
