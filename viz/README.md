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

## Reading it

```text
1  Pick a view      Plan · Truth · Compare          keys 1 2 3
2  Pick a section   sidebar list, derived from the .mmd subgraphs
3  Walk in order    footer arrows                   keys J / K
4  Edit content     viz/trees/*.mmd → page reloads on save
```

Clicking a section zooms that pane to it and dims the rest. The **other pane stays where it
was** — comparing one zoomed side against the other is the whole point.

| Key | Action |
|---|---|
| `1` `2` `3` | Plan only · Truth only · Compare |
| `J` / `K` | next / previous section |
| `+` / `−` | zoom the visible pane(s) |
| `F` | fit the whole tree — clamped by the zoom floor, so expect to pan |
| `0` | reset to the zoom floor |
| `L` | Tall / Wide layout |
| `S` | toggle sidebar |

Scroll = zoom about the cursor. Drag = pan. **Double-click any box** to fill the pane with it.
Each pane has its own transform and its own zoom readout in its header.

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
├── main.js      mermaid init · section parser · pan/zoom — owns behaviour only
├── style.css    shadcn-style zinc-dark tokens            — owns chrome colour
└── trees/
    ├── projected.mmd   PLAN  — 10 sections, phases 0-9, every step numbered
    └── master.mmd      TRUTH — 6 sections, A-F, only what exists
```

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
