import { defineConfig } from 'vite'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

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
const CONFIG_DIR = path.join(ROOT, 'configs')
const PALETTE_FILE = path.join(ROOT, 'docs', 'colour-palette-candidate.json')

/** Config ids are filenames. Lock them down so the API can never write outside configs/. */
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
 *   GET    /api/palette        → { unverified: true, colors: { "0": "#616161", … } }
 *   GET    /api/configs        → [{ id, name, kind, modified }]   (index)
 *   GET    /api/configs/:id    → the full config JSON
 *   PUT    /api/configs/:id    → save (body must be the full config; body.id must match)
 *   DELETE /api/configs/:id    → delete the file
 */
function configApiPlugin() {
  async function handle(req, res) {
    const url = new URL(req.url, 'http://x')
    const parts = url.pathname.split('/').filter(Boolean) // ['api', 'configs', id?]

    if (parts[1] === 'palette' && req.method === 'GET') {
      const colors = JSON.parse(fs.readFileSync(PALETTE_FILE, 'utf8'))
      return send(res, 200, {
        unverified: true,
        note: 'Sampled from the Launchpad Mini MK3 manual — a DIFFERENT device. 8 indices confirmed for the X. Close out with tools/led_color_tester.py.',
        colors,
      })
    }

    if (parts[1] !== 'configs') return send(res, 404, { error: 'unknown endpoint' })
    const id = parts[2]

    if (!id && req.method === 'GET') {
      if (!fs.existsSync(CONFIG_DIR)) return send(res, 200, [])
      const index = fs
        .readdirSync(CONFIG_DIR)
        .filter((f) => f.endsWith('.json') && !f.startsWith('_'))
        .map((f) => {
          const file = path.join(CONFIG_DIR, f)
          try {
            const c = JSON.parse(fs.readFileSync(file, 'utf8'))
            return { id: c.id, name: c.name, kind: c.kind, modified: fs.statSync(file).mtimeMs }
          } catch {
            // A hand-edited broken file must show up in the UI, not vanish silently.
            return { id: f.replace(/\.json$/, ''), name: `⚠ unparseable: ${f}`, kind: 'broken', modified: 0 }
          }
        })
        .sort((a, b) => a.name.localeCompare(b.name))
      return send(res, 200, index)
    }

    if (!id || !ID_RE.test(id)) return send(res, 400, { error: `bad config id: ${id}` })
    const file = path.join(CONFIG_DIR, `${id}.json`)

    if (req.method === 'GET') {
      if (!fs.existsSync(file)) return send(res, 404, { error: `no config: ${id}` })
      return send(res, 200, JSON.parse(fs.readFileSync(file, 'utf8')))
    }

    if (req.method === 'PUT') {
      const body = JSON.parse(await readBody(req))
      if (body.id !== id) return send(res, 400, { error: `body.id "${body.id}" ≠ url id "${id}"` })
      fs.mkdirSync(CONFIG_DIR, { recursive: true })
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
  plugins: [configApiPlugin()],
})
