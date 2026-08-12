import { defineConfig } from 'vite'
import fs from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { scoreTree } from './viz/progress.js'

/**
 * The rig itself is Python. This config exists only for the web tooling in viz/:
 *   /            — the architecture tree viewer
 *   /lab/        — the Launchpad Config Lab (grid mapper · mode flow · config library)
 *
 * Root is pinned to viz/ so no web tooling leaks into the application tree.
 *
 * The config API plugin below is the Lab's persistence layer. It reads and writes
 * JSON files in <repo>/configs/ — the same files the Python rig will load later, so
 * the Lab and the rig share one source of truth and one schema (viz/lab/schema.js).
 */

const ROOT = path.dirname(fileURLToPath(import.meta.url))
const PALETTE_FILE = path.join(ROOT, 'docs', 'colour-palette-candidate.json')

/**
 * The two saved-entity collections. Same REST shape, different directory — screens
 * in configs/, reusable animations in animations/. Both are what the rig loads later.
 */
const COLLECTIONS = {
  configs: path.join(ROOT, 'configs'),
  animations: path.join(ROOT, 'animations'),
}

/** Ids are filenames. Lock them down so the API can never write outside its directory. */
const ID_RE = /^[a-z0-9][a-z0-9_-]*$/

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = ''
    req.on('data', (c) => {
      data += c
      if (data.length > 2_000_000) reject(new Error('body too large'))
    })
    req.on('end', () => resolve(data))
    req.on('error', reject)
  })
}

function send(res, status, obj) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.end(JSON.stringify(obj, null, 2))
}

/**
 * Dev-server-only REST API. Deliberately dumb: files on disk, no database, no cache.
 *
 *   GET    /api/palette             → { unverified: true, colors: { "0": "#616161", … } }
 *   GET    /api/<collection>        → [{ id, name, kind?, engine?, modified }]   (index)
 *   GET    /api/<collection>/:id    → the full JSON
 *   PUT    /api/<collection>/:id    → save (body must be the full entity; body.id must match)
 *   DELETE /api/<collection>/:id    → delete the file
 *
 * <collection> is 'configs' or 'animations' — same handler, different directory.
 */
function configApiPlugin() {
  async function handle(req, res) {
    const url = new URL(req.url, 'http://x')
    const parts = url.pathname.split('/').filter(Boolean) // ['api', collection, id?]

    if (parts[1] === 'palette' && req.method === 'GET') {
      const colors = JSON.parse(fs.readFileSync(PALETTE_FILE, 'utf8'))
      return send(res, 200, {
        unverified: true,
        note: 'Sampled from the Launchpad Mini MK3 manual — a DIFFERENT device. 8 indices confirmed for the X. Close out with tools/led_color_tester.py.',
        colors,
      })
    }

    const dir = COLLECTIONS[parts[1]]
    if (!dir) return send(res, 404, { error: 'unknown endpoint' })
    const id = parts[2]

    if (!id && req.method === 'GET') {
      if (!fs.existsSync(dir)) return send(res, 200, [])
      const index = fs
        .readdirSync(dir)
        .filter((f) => f.endsWith('.json') && !f.startsWith('_'))
        .map((f) => {
          const file = path.join(dir, f)
          try {
            const c = JSON.parse(fs.readFileSync(file, 'utf8'))
            // kind (configs) / engine (animations): pass through whichever exists.
            return { id: c.id, name: c.name, kind: c.kind, engine: c.engine, modified: fs.statSync(file).mtimeMs }
          } catch {
            // A hand-edited broken file must show up in the UI, not vanish silently.
            return { id: f.replace(/\.json$/, ''), name: `⚠ unparseable: ${f}`, kind: 'broken', modified: 0 }
          }
        })
        .sort((a, b) => a.name.localeCompare(b.name))
      return send(res, 200, index)
    }

    if (!id || !ID_RE.test(id)) return send(res, 400, { error: `bad id: ${id}` })
    const file = path.join(dir, `${id}.json`)

    if (req.method === 'GET') {
      if (!fs.existsSync(file)) return send(res, 404, { error: `no ${parts[1].replace(/s$/, '')}: ${id}` })
      return send(res, 200, JSON.parse(fs.readFileSync(file, 'utf8')))
    }

    if (req.method === 'PUT') {
      const body = JSON.parse(await readBody(req))
      if (body.id !== id) return send(res, 400, { error: `body.id "${body.id}" ≠ url id "${id}"` })
      fs.mkdirSync(dir, { recursive: true })
      fs.writeFileSync(file, JSON.stringify(body, null, 2) + '\n')
      return send(res, 200, { ok: true, id })
    }

    if (req.method === 'DELETE') {
      if (fs.existsSync(file)) fs.unlinkSync(file)
      return send(res, 200, { ok: true, id })
    }

    return send(res, 405, { error: `method ${req.method} not supported` })
  }

  return {
    name: 'ablepad-config-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url.startsWith('/api/')) return next()
        handle(req, res).catch((err) => send(res, 500, { error: String(err?.message ?? err) }))
      })
    },
  }
}

/**
 * Dev-server-only progress API. Scores the PLAN tree (viz/trees/projected.mmd) at every commit
 * that touched it, plus the working tree, so the dashboard can show a total and a per-commit
 * delta. Scoring lives in viz/progress.js and is shared with the browser — one rule, not two.
 *
 *   GET /api/progress → { head, dirty, current, history: [{sha, date, subject, pct}], delta }
 *
 * Git is read-only here: log, show, status. It never writes.
 */
const TREE_FILE = 'viz/trees/projected.mmd'

function git(args) {
  return execFileSync('git', args, { cwd: ROOT, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 })
}

function progressApiPlugin() {
  let cache = null // { key, payload } — keyed on HEAD sha + working-tree mtime

  function build() {
    const workingSrc = fs.readFileSync(path.join(ROOT, TREE_FILE), 'utf8')
    const current = scoreTree(workingSrc)

    let head = null
    let dirty = false
    const history = []

    try {
      const [sha, date, subject] = git(['log', '-1', '--format=%H%x1f%aI%x1f%s']).trim().split('\x1f')
      head = { sha: sha.slice(0, 7), date, subject }
      dirty = git(['status', '--porcelain', '--', TREE_FILE]).trim().length > 0

      const log = git(['log', '--reverse', '--format=%H%x1f%aI%x1f%s', '--', TREE_FILE]).trim()
      for (const line of log ? log.split('\n') : []) {
        const [full, at, subj] = line.split('\x1f')
        let src
        try {
          src = git(['show', `${full}:${TREE_FILE}`])
        } catch {
          continue // the file did not exist at that commit
        }
        const score = scoreTree(src)
        // A commit where the file parsed to zero checkboxes is not a 0% milestone — it is a
        // file that was not this tree yet. Plotting it would invent a cliff that never happened.
        if (!score.total) continue
        history.push({ sha: full.slice(0, 7), date: at, subject: subj, ...pick(score) })
      }
    } catch (err) {
      // Not a git repo, or git is missing. The live score still works; history just stays empty.
      return { ok: true, git: false, reason: String(err?.message ?? err), current: pick(current), history: [], head, dirty, delta: null }
    }

    const last = history[history.length - 1]
    return {
      ok: true,
      git: true,
      head,
      dirty,
      current: pick(current),
      history,
      delta: last ? current.pct - last.pct : null,
    }
  }

  const pick = (s) => ({ pct: s.pct, weighted: s.weighted, total: s.total, byStatus: s.byStatus })

  return {
    name: 'ablepad-progress-api',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url.startsWith('/api/progress')) return next()
        try {
          const key = fs.statSync(path.join(ROOT, TREE_FILE)).mtimeMs + ':' + git(['rev-parse', 'HEAD']).trim()
          if (!cache || cache.key !== key) cache = { key, payload: build() }
          send(res, 200, cache.payload)
        } catch (err) {
          send(res, 500, { ok: false, error: String(err?.message ?? err) })
        }
      })
    },
  }
}

export default defineConfig({
  root: 'viz',
  // host: true → bind 0.0.0.0 so other machines on the LAN (laptop, the Beelink at the
  // bench) can open the Lab at http://<this-mac's-ip>:5178/lab/, not just localhost.
  server: { host: true, port: 5178, open: true },
  build: {
    outDir: '../dist-viz',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        trees: path.join(ROOT, 'viz/index.html'),
        lab: path.join(ROOT, 'viz/lab/index.html'),
      },
    },
  },
  // .mmd is not a known text extension to Vite — declare it so ?raw imports work.
  assetsInclude: ['**/*.mmd'],
  // Order matters: the config API claims every /api/ path, so the progress middleware must be
  // registered ahead of it or its requests get answered with "unknown endpoint".
  plugins: [progressApiPlugin(), configApiPlugin()],
})
