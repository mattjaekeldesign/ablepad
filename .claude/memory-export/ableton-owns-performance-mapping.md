---
name: ableton-owns-performance-mapping
description: "Cornerstone: performance pad mappings live in Ableton itself and take precedence when in use; the Python rig never implements a performance layer"
metadata: 
  node_type: memory
  type: project
  originSessionId: c0e57cce-140d-44cd-8e85-382d5c9933ae
  modified: 2026-08-08T05:08:48.960Z
---

Decision by Matt, 2026-08-08: **the performance layer does not belong to the rig controller.**
Performance-time pad mappings (tones, effects, looper, clips) are done inside Ableton — its own
Launchpad X integration / MIDI mapping — and **Ableton's mappings take precedence whenever a set
is in use.** The Python rig owns everything around performance: boot, set browsing, system
controls, error display — never the playing itself.

**Why:** this is the cornerstone of screenless control. Ableton already knows how to map a
Launchpad; re-implementing that in Python duplicates a solved problem and adds a failure mode to
the exact moment (playing live) where failure costs most.

**How to apply:**
- Never propose building performance features (tone switching, looper control, clip launch) in
  the Python rig. Roadmap "Phase 8 — Performance layer" reduces to a *handover* problem: how the
  rig yields the Launchpad to Ableton and takes it back for system/browse modes.
- Natural topology: Ableton on the DAW port (native integration), Python on the MIDI port. This
  further weakens the Bome case, but the handover mechanics are still unverified — record the
  final decision in `docs/ROADMAP.md` Phase 8 when tested on hardware (not yet done there).
- `configs/performance.json` in the Config Lab is illustrative only — it mocks what Ableton will
  own, so the flow graph shows the full mode tree. Don't grow it into real functionality.

See [[ablepad-project-state]], [[launchpad-x-headless-trap]].
