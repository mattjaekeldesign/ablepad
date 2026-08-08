# lab — Launchpad Config Lab

**Purpose.** A library of Launchpad configurations you can see, press, edit and save —
without touching code. Each config is one Launchpad "screen" (Boot, Set Browser,
Performance, System, Error…): what every pad looks like, what every pad does, and which
mode each press leads to. The saved JSON files in `<repo>/configs/` are the same files
the Python rig will load later — the Lab is the design surface, the rig is the player.

**Dependencies.** Node 18+, Vite (already installed for viz). Nothing else. **Not part of
the rig runtime.** The save API is a Vite dev-server middleware — `npm run build` produces
a read-only Lab; editing needs `npm run dev`.

---

## Run

```bash
npm run dev     # http://localhost:5178/lab/
```

## The three panes

```text
┌ Library ──────┬─ Mapper / Flow ───────────────┬─ Inspector ─────────┐
│ configs on    │ Mapper: 9×9 Launchpad,        │ nothing selected:   │
│ disk          │   LEDs live, flash/pulse      │   mode settings,    │
│ open · new    │   animated at hardware        │   background LED,   │
│ duplicate     │   free-run timing             │   transitions       │
│ delete        │                               │                     │
│ import/export │ Flow: n8n-style mode map —    │ pad selected:       │
│ save / revert │   nodes = configs, edges =    │   label, LED per    │
│               │   transitions + SWITCH_MODE   │   state, action +   │
│               │   pads                        │   params + hold     │
└───────────────┴───────────────────────────────┴─────────────────────┘
```

| Key | Action |
|---|---|
| `⌘S` | save the open config |
| `Space` | toggle Simulate mode |
| `1` / `2` | Mapper / Flow view |
| `Esc` | deselect pad (inspector shows mode settings) |

## Workflow

1. **Pick or create** a config in the Library.
2. **Click a pad** in the Mapper → the Inspector shows that pad. Set its label, its LED
   per state (`idle` / `pressed` / `active`), and its action from the dropdown — params
   and hold-to-confirm render automatically from the action catalogue in `schema.js`.
3. **Simulate** (Space): press pads like hardware. Pressed LEDs show, holds draw a
   progress ring, `SWITCH_MODE` actually follows the transition — so you can walk
   Boot → Set Browser → Performance exactly as the rig will.
4. **Flow view**: the whole mode tree as a node graph. Drag to arrange (positions save),
   double-click a node to open it in the Mapper.
5. **Save** (`⌘S`). The file lands in `configs/<id>.json`.

## Responsibilities

```text
viz/lab/
├── index.html     shell markup — topbar, three panes            │ composition
├── lab.js         boot order, view tabs, sim toggle, toasts     │ composition
├── lab.css        tokens (zinc dark) + layout, no pane chrome   │ composition
├── schema.js      THE config contract — shapes, enums, validate │ contract
├── store.js       state + events; panels never talk directly    │ state
├── api.js         the only file that fetches                    │ transport
├── palette.js     128-colour candidate palette, hex lookup      │ data
├── library.js/.css   left pane — list, CRUD, import/export      │ panel
├── grid.js/.css      centre — 9×9 Launchpad, LED sim, presses   │ panel
├── flow.js/.css      centre — n8n-style mode graph              │ panel
└── inspector.js/.css right pane — webflow-style property editor │ panel

vite.config.js     plugin `ablepad-config-api` — GET/PUT/DELETE /api/configs/:id,
                   files in <repo>/configs/, GET /api/palette from docs/
configs/           the saved configurations. THIS is the product.
```

Panels communicate only through `store.js` events. Adding an action = one entry in
`ACTIONS` in `schema.js`; the inspector grows the form fields, the sim narrates it,
no panel code changes.

## The schema, in one breath

```jsonc
{
  "schemaVersion": 1,
  "id": "set-browser", "name": "Set Browser", "kind": "mode",
  "background": { "type": "off" },
  "pads": {                       // sparse — only bound pads, programmer-mode ids 11–99
    "81": {
      "label": "Set 1",
      "led": {
        "idle":    { "type": "static", "palette": 45 },
        "pressed": { "type": "static", "palette": 13 },
        "active":  { "type": "pulse",  "palette": 21 }
      },
      "action": { "type": "LOAD_SET", "params": { "slot": 0 }, "hold_ms": 2000 }
    }
  },
  "transitions": [ { "on": "SET_LOADED", "to": "performance" } ],
  "meta": { "flowPos": { "x": 400, "y": 40 } }
}
```

LED types mirror the hardware's lighting SysEx (`03h`): `static`, `flash` (A/B, 1 beat),
`pulse` (2 beats), `rgb` (SysEx-only). The Lab animates at free-run 120 BPM timing —
flash 0.5 s, pulse 1 s — per `docs/launchpad-x-sysex.md` §6.

## Known limitations · failure modes

- **The palette is UNVERIFIED.** Swatches come from `docs/colour-palette-candidate.json`,
  sampled from the Launchpad Mini MK3 manual — a different device. 8 indices are confirmed
  for the X (0, 5, 13, 19, 21, 23, 37, 45). The starter configs use only those for
  load-bearing colours. Close out with `tools/led_color_tester.py`, then fix the JSON.
- **The CC frame is UNVERIFIED** (top row 91–98, right column 19–89, logo 99). The Lab
  assumes the standard programmer layout; Phase 1's `launchpad_note_tester.py` confirms it.
- **Saving needs the dev server.** The built (`npm run build`) Lab has no `/api` — it can
  browse but not save. By design: persistence is a dev-tool concern.
- **Sim ≠ execution.** Actions other than `SWITCH_MODE` only narrate what the rig would
  do. The Lab never sends MIDI and never launches anything.
- **Two writers, one file.** Hand-editing `configs/*.json` while the Lab has the same
  config open and dirty will end with one side losing. The Lab re-reads only on open.
- **Python loader does not exist yet** (Phase 2/3). Until then, `schema.js` is the only
  validator. When `launchpad/mappings.py` is written, port `validateConfig` — do not
  invent a second schema.

## Future work

- Edge editing in the Flow view (today: edges are derived; edit transitions in the
  inspector, SWITCH_MODE on the pad).
- `kind: "page"` configs for Set Browser pagination, and an overlay preview.
- Export straight to the future `rig.yaml` mapping section once Phase 2 defines it.
- A "diff vs disk" view for a dirty config.
