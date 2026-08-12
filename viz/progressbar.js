/**
 * viz/progressbar.js — the progress strip at the top of the dashboard.
 *
 * Why it exists : one number for "how far along is this rig", a delta so you can see whether
 *                 the last commit moved it, and the next actions without hunting for section F.
 * Layer it owns : rendering + the /api/progress fetch. Scoring is progress.js, and the rule
 *                 lives there so the browser and the git-history endpoint cannot disagree.
 * Who calls it  : main.js — once at boot, and again whenever the trees hot-swap.
 *
 * Degrades honestly: with no dev server (a static build) there is no git history, so the strip
 * shows the live score and says the history needs the dev server. It never fabricates a delta.
 */
import { scoreTree, nextSteps, fmt } from './progress.js'

const CHIP_ORDER = ['done', 'verified', 'partial', 'todo', 'unverified', 'decision', 'riskhigh']
const CHIP_LABEL = {
  done: 'done',
  verified: 'verified',
  partial: 'partial',
  todo: 'not started',
  unverified: 'unverified',
  decision: 'decision',
  riskhigh: 'high risk',
}

export function createProgressBar(host) {
  host.innerHTML = `
    <button class="pg-summary" id="pg-toggle" aria-expanded="false">
      <span class="pg-label">Build progress</span>
      <span class="pg-pct" id="pg-pct">—</span>
      <span class="pg-delta" id="pg-delta"></span>
      <span class="pg-track"><span class="pg-fill" id="pg-fill"></span></span>
      <span class="pg-meta" id="pg-meta"></span>
      <span class="pg-caret">▾</span>
    </button>
    <div class="pg-panel" id="pg-panel" hidden></div>`

  const toggle = host.querySelector('#pg-toggle')
  const panel = host.querySelector('#pg-panel')

  toggle.addEventListener('click', () => setOpen(panel.hidden))
  document.addEventListener('click', (e) => {
    if (!host.contains(e.target)) setOpen(false)
  })
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') setOpen(false)
  })

  function setOpen(open) {
    panel.hidden = !open
    toggle.setAttribute('aria-expanded', String(open))
    host.classList.toggle('open', open)
  }

  async function refresh(trees) {
    // Live score first — it is instant and always correct for the working tree.
    let data = { ok: true, git: false, current: scoreTree(trees.projected), history: [], delta: null }
    try {
      const res = await fetch('/api/progress', { cache: 'no-store' })
      if (res.ok) data = await res.json()
    } catch {
      // static build, or the dev server is gone. Keep the live score.
    }

    const { current, history, delta, head, dirty, git } = data
    host.querySelector('#pg-pct').textContent = fmt(current.pct)
    host.querySelector('#pg-fill').style.width = `${Math.max(current.pct, 0.8)}%`

    const deltaEl = host.querySelector('#pg-delta')
    if (delta === null || delta === undefined) {
      deltaEl.textContent = ''
      deltaEl.className = 'pg-delta'
    } else {
      const up = delta > 0.05
      const flat = Math.abs(delta) <= 0.05
      deltaEl.textContent = flat ? '±0.0 since last commit' : `${up ? '▲ +' : '▼ '}${delta.toFixed(1)} pts since last commit`
      deltaEl.className = `pg-delta ${flat ? 'flat' : up ? 'up' : 'down'}`
    }

    host.querySelector('#pg-meta').textContent = git
      ? `${current.weighted} / ${current.total} steps${dirty ? ' · uncommitted edits' : ''}`
      : `${current.weighted} / ${current.total} steps · history needs the dev server`

    panel.innerHTML = renderPanel({ current, history, head, dirty, git, steps: nextSteps(trees.master) })
    return data
  }

  return { refresh, setOpen }
}

function renderPanel({ current, history, head, dirty, git, steps }) {
  const chips = CHIP_ORDER.filter((k) => current.byStatus?.[k])
    .map((k) => `<span class="chip st-chip-${k}"><b>${current.byStatus[k]}</b> ${CHIP_LABEL[k]}</span>`)
    .join('')

  return `
    <div class="pg-grid">
      <section class="pg-block">
        <h4>Where the number comes from</h4>
        <p class="pg-note">
          Leaf steps of <code>projected.mmd</code> only — phase roots and group headers describe
          work, they are not checkboxes. <b>done</b> and <b>verified</b> score 1, <b>partial</b>
          scores ½, everything else 0. Branch arms of the Phase 8 fork are excluded.
        </p>
        <div class="chips pg-chips">${chips}</div>
      </section>

      <section class="pg-block">
        <h4>Per commit${dirty ? ' · working tree has uncommitted edits' : ''}</h4>
        ${git ? renderHistory(history, current, head, dirty) : `<p class="pg-note">No git history — run through <code>npm run dev</code> to see per-commit deltas.</p>`}
      </section>

      <section class="pg-block pg-next">
        <h4>Next steps · from the master tree, section F</h4>
        ${
          steps.length
            ? `<ol class="pg-steps">${steps
                .map(
                  (s) =>
                    `<li><span class="pg-step-n">${s.n}</span><span><b>${esc(s.head)}</b>${s.detail ? `<span class="pg-step-detail">${esc(s.detail)}</span>` : ''}</span></li>`,
                )
                .join('')}</ol>`
            : `<p class="pg-note">No <code>STEP n →</code> rows found in the master tree's F section.</p>`
        }
      </section>
    </div>`
}

/** Bar per commit, plus the working tree if it differs. Bars are relative to 100%, not to max —
 *  a chart scaled to its own maximum always looks like progress. */
function renderHistory(history, current, head, dirty) {
  if (!history.length) return `<p class="pg-note">No commit has touched the plan tree yet.</p>`

  const points = [...history]
  if (dirty) points.push({ sha: 'working', subject: 'uncommitted working tree', pct: current.pct, date: null })

  return `<ul class="pg-hist">${points
    .map((p, i) => {
      const prev = i > 0 ? points[i - 1].pct : null
      const d = prev === null ? null : p.pct - prev
      const tag = d === null ? 'baseline' : d > 0.05 ? `+${d.toFixed(1)}` : d < -0.05 ? d.toFixed(1) : '±0.0'
      const cls = d === null ? 'flat' : d > 0.05 ? 'up' : d < -0.05 ? 'down' : 'flat'
      return `<li class="${p.sha === 'working' ? 'is-working' : ''}">
        <code class="pg-sha">${p.sha}</code>
        <span class="pg-bar"><span style="width:${Math.max(p.pct, 0.8)}%"></span></span>
        <span class="pg-hist-pct">${p.pct.toFixed(1)}%</span>
        <span class="pg-hist-delta ${cls}">${tag}</span>
        <span class="pg-hist-subject">${esc(p.subject)}</span>
      </li>`
    })
    .join('')}</ul>
    <p class="pg-note">HEAD is <code>${esc(head?.sha ?? '?')}</code> — ${esc(head?.subject ?? '')}</p>`
}

const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c])
