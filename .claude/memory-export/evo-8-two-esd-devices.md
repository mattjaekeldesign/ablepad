---
name: evo-8-two-esd-devices
description: "The rig now has TWO devices that die to ESD and recover only by physical replug — Launchpad X and Audient EVO 8, and the EVO fails silently"
metadata: 
  node_type: memory
  type: project
  originSessionId: f9ffc384-1dc9-4600-984a-d311be787bc2
  modified: 2026-08-09T05:00:12.921Z
---

The audio interface is an **Audient EVO 8** (4in/4out USB-C), from 2026-08-09, replacing the
Focusrite Scarlett. With it: Samson over-ear headphones (model not yet recorded) and 2× XLR mic
cables. Manual is in the repo at `docs/datasheets/audient-evo-8-manual-v1.0.pdf`; extracted
facts in `docs/audient-evo-8-reference.md`.

The EVO 8 manual (p.10) says an electrostatic discharge can make the unit "cease to output
sound", recoverable only by unplugging and re-connecting to the host. The Launchpad X User Guide
says the same about the Launchpad. **Two devices, same failure, neither fixable in code.**

The EVO's version is worse than the Launchpad's because it fails *silently* and may still
enumerate — so `Get-PnpDevice` presence is not health, and on a screenless rig the symptom is
indistinguishable from a dead cable or a crashed Live set.

Three other EVO 8 facts that changed the design, not just a name:
- **Windows needs a driver** — it is not class-compliant there (macOS is). Phase 0 hard dependency.
- **ASIO buffer + sample rate live in the EVO Mixer tray app**, not Ableton — a second
  always-on process in the boot chain.
- **USB port choice is an audio decision**: USB-A gives 2 phantom channels, USB-C at 1.5 A gives 4.

**Why:** it is a live-performance appliance with no screen. Silence with no diagnosis is the
worst failure mode it has, and it now has two independent causes.

**How to apply:** treat detection and health as separate questions in any audio-interface work.
Error Mode needs an audio-fault state distinct from a Launchpad fault — the Launchpad's
text-scroll SysEx can name which. See [[ablepad-project-state]], [[launchpad-x-headless-trap]].
