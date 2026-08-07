# ablepad

Control software for a headless Ableton Live performance rig. A Beelink mini PC, a Novation
Launchpad X, and a Focusrite Scarlett in a box that behaves like a guitar pedal — no monitor,
no keyboard, no mouse, no internet.

**Status:** design documented, implementation not started. Phase 0/1 of 9.

## Read in this order

| Document | What it is |
|---|---|
| `CLAUDE.md` | How to work in this repo. Architecture rules, layer separation, review process |
| `docs/ROADMAP.md` | **Authoritative build order.** Nine phases, exit tests, live risk register |
| `docs/launchpad-x-sysex.md` | The MIDI/SysEx spec. Source of truth for `launchpad/` constants |
| `docs/launchpad-x-hardware.md` | Device settings, ESD, Live vs Programmer mode |
| `docs/bome-mt-pro-reference.md` | Bome MIDI Translator evaluation. **Not adopted** — Phase 8 decides |

## Target environment

Windows, `C:\LiveRig\`, Python 3.12+. This repo is checked out on macOS; nothing
hardware-touching runs here. Keep the device layer behind a thin interface so the state machine,
config and set scanner stay testable off-rig.

## Not in this repo

`Start_DOCS` — the 4,073-line master blueprint (§1–56). Every `§n` citation in these documents
points at it. It lives in the claude.ai project knowledge and needs committing here.
