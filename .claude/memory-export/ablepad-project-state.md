---
name: ablepad-project-state
description: "What ablepad is, its hardware, and where the build actually stands as of 2026-08-07"
metadata: 
  node_type: memory
  type: project
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-09T07:09:45.945Z
---

ablepad is the control software for a headless Ableton Live performance rig — a Beelink mini PC
running Windows, a Novation **Launchpad X**, and an **Audient EVO 8** 4in/4out USB-C interface
(replaced the Focusrite Scarlett 2026-08-09; see [[evo-8-two-esd-devices]]). Goal: no monitor, no keyboard, no mouse, no internet. The Launchpad
is the entire user interface. Target install path is `C:\LiveRig\`.

As of 2026-08-09: **Phase 2 skeleton EXISTS and its exit tests pass** (46 unit tests) —
`rig/` (state machine + explicit transition table, EventBus, CommandDispatcher, 30 Hz tick
controller with injected clock), `storage/` (fail-loud config loader, atomic runtime state),
`main.py`, `config/rig.yaml` (hardware values still UNVERIFIED placeholders). The transition
table is a design decision authored without Start_DOCS — review when it lands. Phases 0/1
remain open, hardware-blocked. Ctrl+C clean-exit verified on macOS only; re-verify on Windows.

**The Beelink Windows machine is not here yet** (as of 2026-08-09) — Matt is building in
anticipation of getting it. Everything hardware-touching is pre-staged, not run: Phase 0/1
checkboxes cannot close until the machine arrives. `tools/rig_survey.py` (stdlib-only,
read-only, added 2026-08-09) is the first thing to run on it. Until then, the only
roadmap-sanctioned off-rig work is Phase 2 skeleton (pure Python, no hardware) and off-rig
tests of pure logic like `_bench.py` SysEx builders.

Web tooling exists (not rig runtime): `viz/` architecture-tree viewer, and `viz/lab/` — the
**Config Lab** (built 2026-08-07): a Vite app at `localhost:5178/lab/` for designing Launchpad
mode configurations — 9×9 grid mapper with LED simulation, webflow-style inspector, n8n-style
mode-flow graph, config library. Configs persist as JSON in `<repo>/configs/` via a Vite
middleware API; `viz/lab/schema.js` is the config contract the future Python loader
(`launchpad/mappings.py`) must port, not reinvent.

Animation system added 2026-08-08: animations are first-class assets in `<repo>/animations/`,
authored in the Lab's Anim view (view 3). Two engines — `generator` (procedural RAIN /
PULSE_WAVE / SPIN_SQUARE, seeded mulberry32 randomness, random-per-element colours by default)
and `frames` (hand-painted keyframes). Screens bind them via `animations: { intro, during }`
(intro plays once full-cover, any press skips, 15 s failsafe cap; during loops layer
'under'/'over' with bound pads). Key fact: the Launchpad X has NO native animation engine —
only static/flash/pulse. All effects are host-computed frames streamed as batch LED SysEx
(81 pads/msg, verified); `viz/lab/anim.js` is the deterministic frame engine. **PORTED
2026-08-09**: `launchpad/animations.py` matches it bit-for-bit against 240 golden frames
(`tools/dump_golden_frames.mjs` regenerates `tests/golden/`; rerun after any anim.js edit).
Also built+tested off-rig 2026-08-09: `launchpad/player.py` (pull-model animation player:
intro skip, 15 s failsafe, cancel), `launchpad/mappings.py` (Config Lab schema.js contract
ported — real configs/ + animations/ load into typed ModeConfig; schemaVersion pins the
pairing, port schema.js changes there), `set_browser/` (Phase 4 complete, colour kept as
semantic names), `ableton/` (Phase 5 policy: precondition-refusal launcher, ASSUMED_READY
readiness, restart budget, supervisor — psutil adapter is the one unverified seam).
374 tests green. Sustained 30 fps SysEx streaming on hardware is still UNVERIFIED.

Two decisions deliberately deferred to Phase 8, do not pre-empt them:
- Whether Bome MIDI Translator Pro (~€79) owns the Launchpad MIDI input instead of Python. The
  real driver is Windows MIDI input exclusivity, not performance.
- Ableton readiness detection — "process exists" ≠ "set loaded", and there is no signal until an
  Ableton Remote Script exists. Logged as known debt.

**Why this matters:** it's a live-performance appliance. A failure is a dead rig on stage, not a
stack trace. Reliability outranks features, and the roadmap's phase order is load-bearing.

**How to apply:** `docs/ROADMAP.md` in the repo is authoritative for build order — read it before
proposing work. See [[architect-process-required]], [[launchpad-x-headless-trap]],
[[ablepad-vs-ableton-pedal]], [[ablepad-start-docs-missing]].
