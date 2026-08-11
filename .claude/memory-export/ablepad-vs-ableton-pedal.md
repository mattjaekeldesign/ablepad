---
name: ablepad-vs-ableton-pedal
description: ablepad and the local ableton-pedal folder are two different builds with incompatible hardware — never cross-cite between them
metadata: 
  node_type: memory
  type: project
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-09T05:25:08.174Z
---

Two separate Ableton-rig projects exist on this machine and they are easy to confuse:

| | `~/Documents/code/ablepad` | `~/Documents/Projects/ableton-pedal` |
|---|---|---|
| Controller | Launchpad **X** (SysEx device ID `0x0C`) | Launchpad Mini **MK3** (device ID `0x0D`) |
| Audio | Audient EVO 8 (was Focusrite Scarlett until 2026-08-09) | MOTU M2 |
| Computer | Beelink, **Windows** | Beelink, OS undecided |
| Enclosure | not the focus | NANUK case, parametric FreeCAD |
| Focus | control software | hardware/CAD/BOM |
| Git | yes | no |

**Why:** the SysEx headers differ by one byte, so protocol copied between them silently does
nothing. The MK3 grid layouts, colour palette and physical dimensions are also not
interchangeable.

**How to apply:** never cite `ableton-pedal` dimensions, SysEx or datasheets as authority inside
ablepad. The one deliberate exception is
`ablepad/docs/colour-palette-candidate.json`, which was copied from the MK3 research and is
explicitly labelled unverified for the Launchpad X — it needs bench confirmation before anything
depends on it. See [[ablepad-project-state]].
