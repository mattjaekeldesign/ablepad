---
name: launchpad-x-headless-trap
description: Selecting Programmer Mode by SysEx disables the Launchpad X Setup menu — a crashed controller leaves a headless rig unrecoverable
metadata: 
  node_type: memory
  type: project
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-07T23:57:15.235Z
---

On the Launchpad X, selecting Programmer Mode via SysEx **disables the Setup menu** (the
hold-Session gesture). Novation's Programmer's Reference states this for both the layout-select
(`00h`) and mode-toggle (`0Eh`) commands. The only ways back are another SysEx selecting a
non-Programmer layout, or a power cycle.

On a rig with no monitor, keyboard or mouse, that means: **any process that enters Programmer
Mode and exits without restoring Live mode leaves the front panel unreachable.** Restoring Live
mode (`F0 00 20 29 02 0C 0E 00 F7`) must live in a `finally`, and must cover exceptions and
signals, not just the happy path. Same requirement applies to the Phase 1 bench scripts in
`tools/`, and it is an open question for Bome if Bome is ever adopted.

Related: the device always powers on into Live Mode and forgets everything across a replug, so
the full init sequence must re-run on every reconnect. ESD-triggered replugs are an expected
live failure mode.

**Why:** this is the one failure in the project with no software recovery path, and it is easy to
write code that causes it without noticing, because it looks fine on a bench with a monitor.

**How to apply:** flag it in any review of `launchpad/device.py` or the `tools/` scripts. Full
spec and citations in the repo's `docs/launchpad-x-sysex.md`. See [[ablepad-project-state]].
