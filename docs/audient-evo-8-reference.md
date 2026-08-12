# Audient EVO 8 — Hardware Reference for the Beelink Rig

**Purpose.** The audio interface is now an Audient EVO 8, not a Focusrite Scarlett. This
document is the authority for `AudioInterfaceDetector`, the Phase 0 bench setup, and the
Phase 5 launcher guard.

**Source.** Audient *EVO 8 User Manual V1.0*, 24 pp.
Retrieved 2026-08-09 from Audient's own CDN:
`https://d9w4fhj63j193.cloudfront.net/EVO/EVO%208/Drivers/EVO%208%20Manual%20V1.0.pdf`
Local copy: `docs/datasheets/audient-evo-8-manual-v1.0.pdf`
(2,638,574 bytes, sha256 `f2151a788f5bcdb4b5593c67d81e0c178bfd58b0d6c6f9d014eaab731a96ac6d`).

Page citations refer to the **printed page numbers** in that PDF.

**Related kit, same change:** Samson over-ear stereo headphones (model not yet recorded — see
§8) and 2× XLR mic cables.

---

## 1. What changed, and why it is not just a rename

The Scarlett was documented as "temporary — a permanent interface replaces it later". This is
that replacement. Four things in the design were written against assumptions that the EVO 8
does not share:

| Assumption | Scarlett era | EVO 8 reality | Cite |
|---|---|---|---|
| Interface is class-compliant | assumed | **Windows needs a driver.** macOS does not | p.13 |
| ASIO settings live in Ableton | assumed | Buffer + sample rate are set in the **EVO tray app** | p.26 |
| One always-on audio process | assumed | **EVO Mixer is a second always-on process** | p.26 |
| Only the Launchpad dies to ESD | documented | **The EVO 8 dies to ESD too** | p.10 |

The last one is the one that matters on stage. See §6.

---

## 2. Identity on Windows

**The manual's device names are wrong on Windows.** p.14 shows "EVO 8 Main Output 1+2"
and p.36 shows "Loop-back 1+2". Neither string exists. MEASURED 2026-08-12 with the
interface attached, `Get-PnpDevice` reports 13 endpoints plus the device node:

```text
DEVICE NODE   'Audient EVO8'                             Class MEDIA
              InstanceId  TUSBAUDIO_ENUM\VID_2708&PID_0007&KS\...

OUTPUTS       'Main Output 1/2 (Audient EVO8)'
              'Line 3/4 (Audient EVO8)'
INPUTS        'Mic | Line | Instrument 1 (Audient EVO8)'
              'Mic | Line 2 (Audient EVO8)'   'Mic | Line 3 (Audient EVO8)'
              'Mic | Line 4 (Audient EVO8)'
              'Mic | Line 1/2 (Audient EVO8)' 'Mic | Line 3/4 (Audient EVO8)'
LOOP-BACK     'Loop-back 1 (Audient EVO8)'    'Loop-back 2 (Audient EVO8)'
              'Loop-back 1/2 (Audient EVO8)'  x2  <- SAME NAME, TWO ENDPOINTS
```

Three things differ from the manual, and all three matter:

1. **`EVO8`, closed up — not `EVO 8`.** A match on `'EVO 8'` never fires. This document
   previously recommended exactly that, and `interface_name_inspector.py` emitted it as a
   `rig.yaml` candidate. Both were wrong, and the tool found its own bug the first time it
   met the hardware.
2. **Slash, not plus** — `Main Output 1/2`, not `Main Output 1+2`.
3. **The device name is a parenthetical suffix**, so every endpoint ends in `(Audient EVO8)`.

**Gate presence on the hardware ID, not on a name:**

```yaml
# config/rig.yaml -- MEASURED 2026-08-12, tools/results/interface-names-evo8.txt
audio_interface:
  hardware_id: 'VID_2708&PID_0007'     # Audient EVO 8. Does not move.
  match_any:
    - 'Audient EVO8'                    # the Class MEDIA device node
  require_status: OK
```

> ⚠️ **Two endpoints share the friendly name `Loop-back 1/2 (Audient EVO8)`.** Matching on
> friendly names is therefore ambiguous *on this device today*, never mind across driver
> versions or locales. `VID_2708&PID_0007` is the only identifier that cannot drift.
>
> And Loop-back is the wrong thing to gate on regardless — it is virtual routing, present
> whether or not audio can reach a mixer.

**Windows driver is mandatory** (p.13): download from the EVO 8 downloads page, run the `.exe`,
reboot into it before the Launchpad work matters. macOS works with no driver at all (p.11) —
irrelevant to the rig, but it explains why a Mac test would not catch a missing Windows driver.

**Consequence for Phase 7:** a Windows driver is a thing Windows Update can replace or break.
Add the driver version to the system-image notes and to the health check.

---

## 3. The EVO Mixer tray app — a second always-on process

On Windows the EVO application lives in the system tray (p.26). It owns:

| Setting | Why the rig cares |
|---|---|
| **Set ASIO buffer size** | The latency figure Phase 0 measures and writes down |
| **Set Sample rate** | 44.1 / 48 / 88.2 / 96 kHz. Must match the Live set |
| Set Loop-back Source | Not needed for the rig; leave alone |
| Mic Pre controls (gain, +48V) | Remote gain + phantom, per channel — p.29 |
| Artist Mix | Independent mix to outputs 3+4 — p.30 |
| Check For Updates | **Needs internet.** The rig is offline by design — see §7 |

This is architecturally the same cost the Bome evaluation counts against Bome: a second
always-on process in the startup chain. It is not optional here, because it is where buffer
size and sample rate live.

```text
STARTUP CHAIN (revised)
│
├── 1. EVO driver loads, interface enumerates
├── 2. EVO Mixer tray app          ← owns ASIO buffer + sample rate
├── 3. (Bome, if Phase 8 chooses it)
├── 4. Rig Controller
└── 5. Ableton Live
```

**Add to §36 health monitoring:** is the EVO tray app running? Its absence does not stop audio
(the driver does that), but it means nobody can change buffer size without a screen.

---

## 4. Signal path for a guitar rig

```text
Guitar
  │  unbalanced TS jack, FRONT panel
  ▼
EVO 8 Instrument (DI) input          ← overrides Mic/Line on channel 1 when plugged, p.24
  │  58 dB gain range, +10 dBu max in, 1 MΩ unbalanced, p.38
  ▼
Input Channel 1 ──► USB ──► Ableton Live ──► USB ──► Outputs 1+2  ──► mixer
                                                └──► Outputs 3+4  ──► headphones (Artist Mix)
```

Facts worth having in one place:

- **4 mic preamps**, rear, Combi XLR/TRS. XLR = mic, ¼" TRS centre = line (line gets a −10 dB
  pad). Mic gain range 58 dB; max input +16 dBu. p.18, p.38
- **DI is front panel, TS, and hijacks channel 1.** Plugging a guitar in silences whatever is on
  channel 1's rear Combi. Not a fault — document it so nobody debugs a "dead mic" that is
  actually a plugged-in guitar. p.24
- **Two independent output pairs**, 1+2 and 3+4, each with its own volume button. Outputs 3+4
  double as the second headphone output. p.24
- **Artist Mix** sends a *different* mix to 3+4 (p.30). For this rig that is the obvious way to
  give the player a monitor mix that is not the front-of-house feed.
- **Stereo link** 1+2 or 3+4 by pressing both channel buttons together. p.22
- **Mute** by press-and-hold on any channel or output button. p.24
- **Smartgain** auto-sets mic gain (p.19–20). A bench convenience; do not build on it, it is a
  front-panel interaction and the rig is headless.
- **Loop-back** arrives on **input channels 5+6** (p.32). Unused by the rig. Worth knowing so
  the channel count in Live is not a surprise: 4 analogue in, but 6 inputs visible.

---

## 5. Power, USB, and the phantom-channel limit

```text
USB 2.0 High Speed, USB-C connector. Included cable: 1m USB-C to USB-C.  p.40
```

> **Phantom power is gated by the host port** (p.22, p.37):
> - **USB-A host → only 2 of the 4 channels can run +48 V at once**
> - **USB-C host supplying 1.5 A → all 4 channels**
>
> 48 V ±4 V @ 10 mA per channel.

**This makes the Beelink's port choice an audio decision, not a cabling detail.** With 2 XLR
cables the current kit needs at most 2 phantom channels, so USB-A is sufficient *today* — but
it silently caps the rig at two condensers forever. If the Beelink has a USB-C port that can
deliver 1.5 A, use it, and record which physical port was used. Add the port identity to the
Phase 0 record: USB enumeration order is already a suspect in Phase 7 boot problems.

The included cable is **USB-C to USB-C**. If the Beelink's chosen port is USB-A, that cable is
the wrong one and an adaptor becomes a load-bearing part of a touring rig. Buy a proper
USB-A-to-C cable rather than stacking a dongle.

---

## 6. ESD — the failure mode that now exists twice

Straight from the manual's conformity page (p.10):

> "Under an environment with electrostatic discharge, the device may cease to output sound
> (EUT could not operate properly). This requires the user reset the device by **unplugging &
> re-connecting to host computer**."

The Launchpad X User Guide says the same thing about the Launchpad. So:

```text
ESD FAILURE TREE  (both are physical-recovery-only)
│
├── Launchpad X ceases to respond   → unplug / replug USB
└── EVO 8 ceases to output sound    → unplug / replug USB
```

**Why this is worse than either alone.** A guitarist on a dry carpeted stage is an ESD source,
and the rig has no screen. If the EVO dies, the symptom is *silence* — indistinguishable from a
dead amp, a bad cable, or a crashed Live set. The Launchpad is the only diagnostic surface, and
it will still be lit and responsive, because it is a different device on a different port.

Design consequences, all of which are new work:

1. **The rig must be able to tell "no audio device" from "audio device present but silent".**
   Presence via `Get-PnpDevice` is not enough — an ESD-wedged EVO may still enumerate. Treat
   detection and health as two different questions.
2. **Error Mode needs an audio-fault state** distinct from the Launchpad-fault state, and it
   should say which one on the surface. The Launchpad X text-scroll SysEx exists for exactly
   this — `NO AUDIO` scrolling across the grid beats a colour nobody remembers.
3. **Add to the §51 rehearsal test:** unplug the EVO mid-show, confirm the rig detects it, says
   so on the Launchpad, and does not thrash; replug, confirm recovery without restarting Live.
4. **Physical mitigation beats code here.** Both USB cables should be strain-relieved and
   reachable without disassembly, because replugging is the only fix that exists.

---

## 7. Firmware updates need internet — the rig does not have any

Firmware updates go through the EVO app's "Check for Updates", which requires an internet
connection, and **the unit restarts several times during the update** (p.42).

The rig is specified to run with no internet. So:

- **Update firmware once, at bench setup**, before the machine goes offline and headless.
- **Record the firmware version** alongside the driver version in the Phase 0 notes and the
  system image.
- Never let an update run on a gig day. A device that restarts multiple times mid-update is not
  something to discover an hour before a set.

Same discipline as the Launchpad's MSD-mode toggle: a one-time bench action that must happen
before the enclosure closes.

---

## 8. Headphones and cables

**Samson over-ear stereo headphones — model not recorded.** Get the exact model number into
`docs/` and check it against the EVO 8's headphone amp before assuming it is fine.

EVO 8 headphone output (p.38):

| Load | Max level | Power |
|---|---|---|
| 30 Ω | +0.5 dBu | 45 mW |
| 60 Ω | +4.22 dBu | 52 mW |
| 600 Ω | +10.1 dBu | 20 mW |

Output impedance: **< 50 Ω**. Connector: ¼" jack, TIP left / RING right / SLEEVE shield.

> ⚠️ **UNVERIFIED, and worth one bench check.** `< 50 Ω` is a ceiling, not a measurement. Most
> Samson over-ears are around 32 Ω. If the real source impedance is near that 50 Ω ceiling,
> driving a 32 Ω headphone gives a damping factor below 1, which audibly colours the low end —
> the usual guideline is source impedance ≤ ⅛ of the load. This is a *listening* check, not a
> blocker, and it may well be a non-issue. Do not repeat the ceiling figure as if it were the
> real one.

**2× XLR mic cables.** Pinout confirmed p.38: **pin 2 hot, pin 3 cold, pin 1 shield** — standard,
no surprises. Two cables and the USB-A phantom limit of two channels happen to match; that is
coincidence, not design, and §5 is where it stops being true.

---

## 9. Latency figures — the manual's numbers, for comparison only

Published (p.39–40), all at a 32-sample buffer:

| | 44.1 kHz | 48 kHz | 88.2 kHz | 96 kHz |
|---|---|---|---|---|
| DSP mixer roundtrip (in→out) | 0.594 ms | 0.552 ms | 0.302 ms | 0.281 ms |
| DAW roundtrip software monitoring | 5 ms | — | — | 4.1 ms |
| DAW playback (software instrument) | ~2.5 ms | — | — | ~2 ms |

The manual's own caveat: "Performance may vary as stability at these low buffer sizes is
dependent on many factors including CPU load, operating system and performance of other
drivers."

**These are not the rig's numbers.** Phase 0 measures round-trip latency on the Beelink, with
the real Live set and real plugins loaded, and writes down what it actually got. Treat the table
above only as a sanity ceiling — if the bench measures dramatically worse, something is wrong
with the driver or the power plan, and that is a finding.

---

## 10. Physical

| | |
|---|---|
| Dimensions | 190 mm (w) × 70 mm (h) × 70 mm (d) |
| Weight | 475 g |
| Connector | USB-C, USB 2.0 High Speed |
| Included cable | 1 m USB-C to USB-C |

Registration (ARC) needs the serial number and a 4-digit PIN on the underside of the unit
(p.16). **Photograph the underside before the unit is mounted or cased** — that label becomes
unreachable, and it is also what a warranty claim needs.

---

## 11. Impact on the existing blueprint

| Blueprint section | Change |
|---|---|
| §5 Software Stack | Add the Audient EVO Windows driver and the EVO Mixer tray app. Both are versioned artefacts; freeze and record them. |
| §26 Focusrite Detection | Rename to audio-interface detection. Match `EVO 8`. Presence ≠ health — see §6. |
| §36 Health Monitoring | Add: EVO tray app running? Driver present? Interface enumerated *and* producing audio? |
| §38 Error Categories | Add "audio interface present but silent (suspect ESD)" as distinct from "absent". |
| §40 Startup | Chain is now: driver → EVO tray app → (Bome?) → Rig Controller → Ableton. |
| §42 Installation Tree | Add: install EVO Windows driver; update firmware while online; record driver + firmware versions; photograph the serial/PIN label. |
| §46 Failure Tree | Add EVO 8 ESD as a second physical-recovery-only cause, alongside the Launchpad's. |
| §51 Rehearsal Test | Add: unplug the EVO mid-show → rig reports an audio fault on the Launchpad, does not thrash, recovers on replug. |

---

## 12. Open items

1. Record the **exact `Get-PnpDevice` FriendlyName strings** for every EVO 8 endpoint.
   `tools/interface_name_inspector.py --label evo8`.
2. Decide **which endpoint means "the interface is present"** — there are several, and
   Loop-back is not the one.
3. Record the **Samson headphone model** and check its impedance against §8.
4. Decide the **Beelink USB port** — USB-A (2 phantom channels) or USB-C at 1.5 A (4). Record
   the physical port used.
5. Measure **real round-trip latency** on the Beelink and write down the buffer size and sample
   rate chosen. Phase 0 exit test.
6. Confirm whether **ASIO buffer/sample rate can be set without the tray app's UI** — if not,
   changing them on a headless rig requires SSH plus a remote desktop, and that is worth
   knowing before it is needed.
7. Update **firmware and driver at bench**, record both versions, then take the rig offline.
