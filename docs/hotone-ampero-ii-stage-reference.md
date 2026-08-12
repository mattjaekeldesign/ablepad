# Hotone Ampero II Stage — Hardware Reference for the Beelink Rig

**Purpose.** The Ampero II Stage joins the rig as the second MIDI controller and the primary
"rack" concept: guitar processing happens in the Ampero, the Launchpad remains the rig's
operating-system interface. This document is the authority for what the Ampero can send,
what it can receive, and how it connects — for Phase 0 detection, the MIDI layer, and the
Phase 8 performance-mapping decision.

**Sources.**

1. Hotone *Ampero II Stage Online Manual EN, Firmware V1.7.0*, 102 pp.
   Retrieved 2026-08-09 from Hotone's CDN:
   `https://res.hotoneaudio.com/prod/support/Ampero%20II%20Stage_Online%20Manual_EN_Firmware%20V1.7.0.pdf.1784702712242.pdf`
   Local copy: `docs/datasheets/hotone-ampero-ii-stage-manual-v1.7.0.pdf`
   (13,590,668 bytes, sha256 `7db0e05ef3e3ca9ba0f28a6d4643b4f4757036aa34d681c052f46b07c987c845`).
   Page citations below are **printed page numbers** in that PDF.

2. Hotone *Ampero II Stage MIDI Control Information List EN, Firmware V1.0.2*, 5 pp.
   Retrieved 2026-08-09 from Hotone's CDN:
   `https://res.hotoneaudio.com/prod/support/Ampero%20II%20Stage_MIDI%20Control%20Information%20List_EN_Firmware%20V1.0.2.1703146582227.pdf`
   Local copy: `docs/datasheets/hotone-ampero-ii-stage-midi-info-list-v1.0.2.pdf`
   (229,363 bytes, sha256 `bf099e183201d65badab77ecbfb852db977af237c128182e35687d87fec3341a`).

**⚠ Version gap.** The MIDI list is **firmware V1.0.2**; the manual is **V1.7.0**. Hotone has
not published a newer MIDI list (checked 2026-08-09). The CC map in §5 may be incomplete for
current firmware — treat additions beyond it as possible, removals as unlikely. Recheck when
Hotone updates the document.

---

## 1. What the Ampero changes architecturally

| | |
|---|---|
| **Second MIDI controller** | The MIDI layer's "the Launchpad is the only input device" assumption dies. Device layer must handle N controllers |
| **Send vocabulary is CC/PC only** | Footswitches cannot send Note messages. Any Ableton mapping fed by the Ampero maps CCs, not notes (§4) |
| **No native double-press** | A footswitch sends the *same* fixed messages every press. Double-press as a distinct command must be synthesized by whatever receives the MIDI (§4, §7) — this is new fuel for the Phase 8 Bome decision |
| **Bluetooth MIDI is a headless trap** | All Bluetooth switches are **off at every power-up** (manual p.82). On a screenless rig, BT MIDI is unusable. Wire it: USB or TRS |
| **Second USB audio device** | The Ampero is also a USB audio interface with its own Windows ASIO driver (manual p.69). Ableton binds one ASIO device — the EVO 8. Ampero audio must arrive analog (§6) |

---

## 2. Physical I/O relevant to the rig

From the rear-panel description (manual p.15) and Technical Specifications (p.98):

- **MIDI IN**: 1/8" (3.5 mm) TRS jack — receives MIDI or connects a controller.
- **MIDI OUT/THRU**: 1/8" (3.5 mm) TRS jack — sends/transfers MIDI.
- DIN connection needs a converter cable; the manual shows a wiring diagram **as an image**
  (p.15). Whether it is MIDI TRS **Type A or Type B is UNVERIFIED** — do not buy adapters
  until the diagram is read or tested.
- **USB**: USB 2.0 Type-C to the computer — audio **and** MIDI.
- **Bluetooth**: 4.2 dual-mode, BLE MIDI supported (p.98) — but off at power-up (p.82), see §1.
- Audio outs: 2× 1/4" TRS unbalanced stereo, 2× XLR balanced with ground-lift, phones,
  FX send (p.98). The XLR or TRS pair is the analog path into the EVO 8.
- 2× EXP/CTRL TRS jacks for expression pedals / momentary footswitches (p.98).

---

## 3. What the Ampero can SEND (controller role)

This is the entire send vocabulary. It is small, and that is load-bearing.

### Footswitch MIDI (manual pp.53–54)

- Each of FS1–FS7 can send **up to 3 MIDI messages** per press in Stomp Mode.
- Per message: Channel (`OFF / 1–16 / Omni`, default **OFF** — i.e. sends nothing until
  configured), Command (`CC 0–CC 127` or `PC`), Data (`0–127`).
- Footswitch MIDI is only active when the switch's pedal function is **Effect Slot, Scene,
  or OFF** (p.53). A switch assigned to Bank/Patch/Tap/Tuner/Looper/EXP does not send.
- **No Note messages. No release message documented. No double-press or hold-press send.**
  The manual's only hold behaviour is UI navigation on the touchscreen (pp.43–44, 54).

### Patch MIDI (manual p.55)

- Switching to a patch can send **up to 6 MIDI messages**, same Channel/Command/Data scheme.
- This is the "rack concept" hook: selecting an Ampero patch can simultaneously re-aim
  Ableton (scene select, track arm, etc.) with a burst of CCs/PCs.

### UNVERIFIED (send side)

- Whether footswitch MIDI transmits over **USB** as well as the TRS MIDI OUT jack. The manual
  says footswitch/patch MIDI go "via the MIDI OUT/THRU jack" (pp.53, 55) — it does not state
  USB MIDI OUT carries them. **If they are TRS-only, the Beelink needs a TRS-MIDI→USB
  interface or the EVO/other path, and this whole design changes.** Test first, on the bench,
  before anything else (§8).
- Whether a footswitch sends on press or on release, and message timing/jitter.
- Windows MIDI port name(s) for the USB connection.

---

## 4. Double-press commands — where they can live

Matt's intent: double-press on an Ampero footswitch = a different command than single press.

Hardware truth: the Ampero cannot do this (§3). Every press emits the same fixed messages.
Something downstream must watch timing and translate *press, press within Δt* into a distinct
action. The candidates:

| Where | How | Verdict |
|---|---|---|
| Ampero itself | — | **Impossible** on V1.7.0 firmware |
| Ableton MIDI map | Native mapping is stateless | **Impossible** natively; a Max for Live device could do it |
| Rig controller (Python) | MIDI service watches CC timing, emits synthetic commands | Possible, but makes the rig a performance-path dependency — against the cornerstone that **Ableton owns performance mapping** and the rig never sits in the performance path |
| Bome MT Pro | Timers + rules translating double-press into a second CC | **This is literally Bome's use case** (`docs/bome-mt-pro-reference.md`) |

This is a **new, independent argument for Bome** — the first one that is not about Launchpad
port exclusivity. It does not decide anything today: the decision stays parked at Phase 8
(`docs/ROADMAP.md`), but the Phase 8 inputs list grows by one.

---

## 5. What the Ampero can RECEIVE (CC map, firmware V1.0.2)

Full map from the MIDI Control Information List (see version gap warning above). Receive
channel defaults to Omni on all three sources (manual p.74). This matters later if the rig or
Ableton ever drives the Ampero (scene/patch changes from the Launchpad, the Tensor idea, etc.).

| CC# | Value | Function |
|---|---|---|
| 0 | 0–2 | Bank MSB (with PC: P01-1→P26-3 = bank 0, P26-4→P52-1 = bank 1, P52-2→P60-5 = bank 2) |
| 7 | 0–100 | Patch volume |
| 11 | 0–127 | Expression pedal (EXP 1/2) |
| 13 | 0–63 / 64–127 | EXP 1 / EXP 2 switch |
| 16–21 | 0–127 | Quick Access Para 1–3 set / step up-down |
| 22 / 23 | any | Bank − / Bank + |
| 24 | any | Pre-select menu |
| 25 | 1–5 | Scene 1–5 |
| 26 / 27 | any | Patch − / Patch + |
| 28 | 0–63 / 64–127 | Patch Mode / Stomp Mode |
| 29 | 0–63 / 64–127 | Main display mode 1 / 2 |
| 36–39 | — | Drum machine: menu, play/stop, rhythm 1–100, volume 0–100 |
| 48–53 | 0–63 / 64–127 | Slot A1–A6 off/on |
| 54–59 | 0–63 / 64–127 | Slot B1–B6 off/on |
| 60 | 0–63 / 64–127 | Tuner off/on |
| 62–72 | — | Looper: menu, rec/overdub, play/stop, ½-speed, reverse, undo/redo, clear, rec level, loop level, pre/post, A/B chain |
| 74 / 75 | 0–2 / 0–127 | Tempo MSB/LSB (40–300 BPM) |
| 76 | any | Tap tempo |
| 77 | 0–63 / 64–127 | Screen lock / unlock |
| 78 | 0 / 1 / 2 | Analog bypass / DSP bypass / engage |
| 79–85 | 0–127 | FS 1–7 effect-slot on/off |

Patch selection from outside: CC0 (bank MSB) + Program Change covers all 300 patches.

---

## 6. Audio path decision — Ampero is NOT the interface

The Ampero has USB audio (24-bit/44.1 kHz, p.98) and a Windows ASIO driver — the "HOTONE
GENERIC USB ASIO DRIVER", tray-configured, same pattern as the EVO (p.69). It could
technically replace the EVO 8. It should not:

- Ableton binds **one** ASIO device. EVO 8 is the rig's interface — mics, phantom, monitor
  path, all already designed and documented (`docs/audient-evo-8-reference.md`).
- Two vendor ASIO drivers on one Windows box is a driver-conflict surface with zero upside.

**Decision: Ampero audio enters analog** — unbalanced TRS or XLR out → EVO 8 line in. USB is
for MIDI (and firmware updates / editor) only. The Hotone ASIO driver is **not** installed on
the Beelink unless a bench test proves USB MIDI needs it (UNVERIFIED — class-compliant MIDI
is likely but not documented).

Corollary: the Ampero is a **third ESD-adjacent stage box**, but unlike the Launchpad and
EVO 8 the manual makes no ESD claim — no known replug-only failure mode. Its failure surface
is instead: it is a computer that boots (power-on state, p.62 `POWER-ON` option — behaviour
UNVERIFIED) and a USB device that must enumerate.

---

## 7. Boundary with the cornerstone rule

**Ableton owns performance mapping** — the rig never builds a performance layer. The Ampero
is a performance controller, so:

- Ampero CC → Ableton mappings live **in the Ableton set / Live's MIDI map**, not in rig code.
- The rig's only Ampero responsibilities: **detect it** (Phase 0/1), **log its traffic**
  (debuggability), and — pending Phase 8 — possibly host the translation layer (Bome or
  otherwise) that synthesizes double-press. Until Phase 8 lands, the rig does nothing with
  Ampero MIDI in the performance path.

---

## 8. Bench verification checklist (before any design hardens)

```text
□ Ampero connected USB-C to a computer — Windows MIDI port name recorded
□ USB MIDI works WITHOUT the Hotone ASIO driver installed (or record that it does not)
□ Footswitch MIDI arrives over USB (not just TRS OUT) ← KILLS OR CONFIRMS THE DESIGN
□ Footswitch sends on press (not release); double-press inter-message gap measured
□ Patch MIDI burst (6 messages) arrives intact and in order
□ TRS MIDI type (A/B) read from the p.15 wiring diagram or verified with a meter
□ Ampero analog out → EVO 8 line in produces audio in Ableton
□ Power-on patch behaviour recorded (POWER-ON option, manual p.62)
```

---

## 9. Parked — Red Panda Tensor

Matt may add the (red) Tensor pedal later and "manipulate the MIDI" around it. Nothing
designed, nothing verified, nothing blocking. Parked until the Ampero integration is real.

---

## Known limitations of this document

- CC map is firmware V1.0.2 against a V1.7.0 manual (see version gap, top).
- TRS MIDI wiring diagram and any page-image content are not extracted.
- Everything Windows-specific (port names, driver need) is UNVERIFIED until Beelink bench time.
