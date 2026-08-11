---
name: ampero-ii-stage-controller
description: "Hotone Ampero II Stage added 2026-08-09 as guitar rack + second MIDI controller; CC/PC-only sender, no native double-press, BT MIDI off at boot, audio goes analog into EVO 8"
metadata: 
  node_type: memory
  type: project
  originSessionId: 98ef5d41-be86-44ae-aaff-57ce345c23b3
  modified: 2026-08-09T23:19:49.518Z
---

Matt added a **Hotone Ampero II Stage** to the rig (2026-08-09): it is the main guitar
"rack" concept and a second MIDI controller for Ableton, alongside the Launchpad (which
stays as the rig OS). Reference: `docs/hotone-ampero-ii-stage-reference.md`; manual V1.7.0
+ MIDI list V1.0.2 in `docs/datasheets/`.

Hardware truths that shape design:
- Footswitches send only CC/PC — max 3 fixed messages per press, 6 per patch switch. No
  Notes, no release events, **no native double-press**. Matt wants double-press commands →
  a downstream translator must synthesize them (new independent argument for Bome; decision
  still parked at Phase 8 per [[roadmap-is-the-todo-list]] and the cornerstone
  [[ableton-owns-performance-mapping]] — rig stays out of the performance path).
- Bluetooth MIDI resets to OFF at every power-up → unusable on headless rig. Wire USB/TRS.
- Whether footswitch MIDI transmits over USB (not just the 3.5mm TRS OUT) is UNVERIFIED
  and design-killing if false — first bench test.
- Ampero audio enters the EVO 8 analog; its Hotone ASIO driver is NOT installed (one ASIO
  device rule, see [[evo-8-two-esd-devices]]).

Parked idea: add the Red Panda Tensor pedal later and "manipulate the MIDI" — nothing
designed yet.
