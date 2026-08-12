# viz — architecture tree viewer

**Purpose.** Render the plan and reality side by side, in labelled sections, so the gap between
them is visible at a glance instead of buried in `docs/ROADMAP.md`.

> The same dev server also hosts the **Launchpad Config Lab** at `http://localhost:5178/lab/`
> — grid mapper, LED simulation, mode flow, config library. See `viz/lab/README.md`.

**Dependencies.** Node 18+, `mermaid` (render), `vite` (dev server + HMR). Nothing else. **Not
part of the rig runtime** — the rig is Python and never imports any of this.

---

## Run

```bash
npm install     # once
npm run dev     # http://localhost:5178
```

## Two reading modes

**Outline** is the default and the one to use for reading.

| | Outline | Diagram |
|---|---|---|
| Surface | indented text, ordinary scrolling | mermaid SVG |
| Good at | reading, searching, copying, skimming a phase | seeing branch shape, e.g. the Phase 8 fork |
| Zoom | none needed | 25–100%, pan, double-click to frame |
| Text | selectable, always sharp | rasterised vectors |

`M` switches. Search (`/`) is outline-only and switches mode for you.

```text
1  Pick a view      Plan · Truth · Compare          keys 1 2 3
2  Pick a mode      Outline · Diagram               key  M
3  Pick a section   sidebar list, derived from the .mmd subgraphs
4  Walk in order    footer arrows                   keys J / K
5  Edit content     viz/trees/*.mmd → hot-swaps, no reload, position kept
```

| Key | Action |
|---|---|
| `1` `2` `3` | Plan only · Truth only · Compare |
| `M` | outline ⇄ diagram |
| `J` / `K` | next / previous section |
| `/` | focus search · `Esc` clears |
| `C` | collapse / expand all sections (outline) |
| `+` `−` `F` `0` | zoom · fit · 100% (diagram) |
| `L` | Tall / Wide layout (diagram) |
| `S` | toggle sidebar |

In diagram mode: scroll = zoom about the cursor, drag = pan, **double-click any box** to frame
it. Each pane has its own transform and zoom readout. Clicking a section focuses only that
pane — comparing one zoomed side against the other is the point.

## Progress tracker

The strip under the header shows one number for the whole build, the change since the last
commit, and — in the dropdown — the ordered next actions.

```text
BUILD PROGRESS   12.0%   ▲ +2.9 pts since last commit   [██░░░░░░░░]  15 / 125 steps  ▾
                                                                       └ dropdown ┘
                   ├── where the number comes from + status chips
                   ├── per-commit history, each row with its own delta
                   └── next steps, read live from master.mmd section F
```

**The rule** (`viz/progress.js`, imported by both the browser and the git endpoint so the two
cannot disagree):

- Only **leaf** steps of `projected.mmd` count. A phase root or a group header describes work;
  it is not a checkbox.
- `done` and `verified` score **1**, `partial` scores **½**, everything else **0**.
- `branch` nodes are excluded — only one arm of the Phase 8 fork will ever be built, so counting
  both would cap the total below 100% forever.
- A `decision` still sits in the denominator. An unmade decision is outstanding work.
- No effort weighting. A weighting scheme nobody maintains is a lie with decimal places.

**History** comes from `GET /api/progress` (dev server only, `vite.config.js`). It runs
`git log` for `viz/trees/projected.mmd`, re-scores the file at every commit that touched it via
`git show <sha>:<file>`, and appends the working tree as an extra row when it is dirty. Git is
read-only there — `log`, `show`, `status`, nothing else. Commits where the file scored zero
checkboxes are skipped: that is a file that was not this tree yet, not a 0% milestone.

In a static build there is no API, so the strip shows the live score and says the history needs
the dev server. It never fabricates a delta.

**To move the number, edit a status class in `projected.mmd`** — the strip updates on the same
hot-swap as the trees, with no reload.

## Position memory

View, mode, layout, section cursor, search text, per-pane zoom/pan and outline scroll are
written to `sessionStorage` on every change and restored on load. If the page does reload — an
edit to `main.js`, a Vite restart — you land back where you were.

### Tall vs Wide

`main.js` rewrites each section's `direction LR` to `direction TB` in Tall mode. Layout is a
view concern, so it never touches the `.mmd` files.

- **Tall** (default) — sections become narrow vertical columns. Readable; the doc stacks.
- **Wide** — the file's own `direction LR`. One section is one long row: good for an overview,
  unreadable without zooming.

### Zoom

Range is **25%–100%** (`MIN_K` / `MAX_K` in `main.js`). 100% is the SVG's intrinsic size and is
already readable, because zoom sets the element's layout size rather than CSS-scaling it — see
`apply()` in `main.js`. Never reintroduce `will-change: transform` on `.canvas`: it promotes the
canvas to a cached layer, the SVG rasterises once and gets bitmap-stretched, and everything goes
blurry.

`Fit` frames the whole tree, clamped at the 25% floor. `0` returns to 100%.

## Responsibilities

```text
viz/
├── index.html   shell · tabs · sidebar cards · stepper   — owns layout
├── main.js      controller: modes, sections, pan/zoom, position memory
├── trees.js     the .mmd sources + the ONLY HMR hook      — owns content loading
├── parse.js     .mmd → { sections, nodes, counts }        — owns text→data
├── outline.js   parsed tree → text DOM                    — owns the text view
├── progress.js  the scoring rule — shared with vite.config.js, never duplicated
├── progressbar.js  the progress strip + next-steps dropdown
├── style.css    shadcn-style zinc-dark tokens             — owns chrome colour
└── trees/
    ├── projected.mmd   PLAN  — 10 sections, phases 0-9, every step numbered
    └── master.mmd      TRUTH — 6 sections, A-F, only what exists
```

`parse.js` is the single parser: the outline rows, the sidebar sections and the header status
chips all come from it. It understands only the mermaid subset we author, and ignores anything
it cannot classify — a half-parsed outline beats a blank pane, and the diagram is the authority
if the two ever disagree.

### Why trees.js exists

A `?raw` import is a string, and Vite cannot hot-update a string module — so editing a tree
used to force a **full page reload**, throwing away your section, scroll and zoom. `trees.js`
self-accepts and notifies subscribers instead, so a `.mmd` edit swaps the text in place. Do not
move the glob back into `main.js`; the reload comes straight back.

**Edit `trees/*.mmd`. Never edit `main.js` to change content.** Two things are derived from the
source files at load:

- **Sections** — every `subgraph ID["Title"]` becomes a sidebar entry, in file order.
- **Status chips** — the counts in each pane header come from counting `:::class` suffixes.

Add a `subgraph`, get a nav entry. No JS change.

## Status vocabulary

Every node ends in exactly one class, and carries a glyph so colour is never the only signal.

| Class | Glyph | Meaning |
|---|---|---|
| `:::done` | ✓ | exit test passed |
| `:::partial` | ◐ | started, not proven |
| `:::todo` | ○ | not started |
| `:::verified` | ✓ | measured or cited against hardware / the manual |
| `:::unverified` | ✗ | a guess that something already depends on |
| `:::decision` | ◆ | deliberate branch point, not yet chosen |
| `:::branch` | | one arm of an undecided branch |
| `:::riskhigh` | ▲ | High on the roadmap risk register |
| `:::next` | → | the next action (master tree only) |

Adding a class means adding a `classDef` to **both** `.mmd` files, a `.b-*` rule in `style.css`,
and an entry to `STATUS_LABEL` in `main.js`.

## The rule that keeps this honest

`master.mmd` moves a node to `:::done` **only when the roadmap's exit test for it actually
passes.** Anything aspirational belongs in `projected.mmd`. If the two trees ever agree
completely, the project is finished — or someone lied to the master tree.

## Known limitations

- Status is hand-maintained; nothing parses `docs/ROADMAP.md`. The trees can drift. Reconcile at
  session end — `master.mmd` carries a `Last reconciled` date at the top.
- Section focus finds the cluster by `id` suffix (`<diagramId>-<subgraphId>`, verified against
  mermaid 11) and falls back to matching the title text. A mermaid major upgrade could break the
  primary path; the fallback would still work.
- Mermaid's dagre layout is not stable across edits — node positions can shift after a change.
- Dark theme only. Node colours live in the `.mmd` classDefs, so a light theme would need a
  second palette in both files.
- A syntax error in one `.mmd` shows a red error block in that pane; the other pane still works.
