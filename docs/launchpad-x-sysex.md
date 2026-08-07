# Launchpad X — MIDI & SysEx Implementation

**Purpose.** Replace every guessed constant in the blueprint with a cited one. This document is
the authority for `launchpad/device.py`, `launchpad/grid.py` and `launchpad/colors.py`.

**Source.** Novation *Launchpad X Programmer's Reference Manual*, 29 pp.
Retrieved 2026-08-07 from Novation's own CDN:
`https://fael-downloads-prod.focusrite.com/customer/prod/s3fs-public/downloads/Launchpad%20X%20-%20Programmers%20Reference%20Manual.pdf`
Local copy: `docs/datasheets/novation-launchpad-x-programmers-reference.pdf`
(1,078,951 bytes, sha256 `eca1842544e184e200a2134053acac8b1acb77df0247f23ef488fd9c2897db7a`).

Page citations below refer to that PDF.

**Known limitation of this document.** Pages 10, 11, 12, 18 and 20 carry their content as
*images* — the Programmer-mode layout, the Custom-mode layouts, the colour palette table, the
Session layout and the Drum Rack layout. Text extraction cannot read them. Everything sourced
from those pages is marked `UNVERIFIED` and needs `tools/launchpad_note_tester.py` /
`tools/led_color_tester.py` to close out. Everything else here is quoted prose.

---

## 1. Answers to the four open questions

The old `launchpad info` doc ended with four blockers. Three are closed:

| # | Question | Answer | Cite |
|---|---|---|---|
| 1 | Exact Programmer Mode SysEx bytes | `F0 00 20 29 02 0C 0E 01 F7` — **the assumed value was correct** | p.7 |
| 2 | The 127-colour index | **Still open.** The table is a page image | p.12 |
| 3 | SysEx for flashing / pulsing | Yes — lighting types 1 and 2, plus RGB as type 3 | p.13, p.15 |
| 4 | Can one SysEx set multiple LEDs | **Yes — up to 81 `<colourspec>` entries, the whole surface in one write** | p.15 |

Question 4 is the important one. `clear_grid()` does **not** need 64 individual `note_on`
messages; it needs one SysEx. Python-side LED animation is viable.

---

## 2. USB interfaces

Two MIDI in/out pairs over USB (p.6):

| Interface | Name | Windows | Purpose |
|---|---|---|---|
| DAW | `LPX DAW In / Out` | **first** interface | DAW control of Session mode + DAW Faders |
| MIDI | `LPX MIDI In / Out` | **second** interface | Note/Custom mode MIDI, external note input, lighting in Lighting Custom Modes and **Programmer mode** |

The Rig Controller runs the device in Programmer mode, so it wants the **MIDI** interface —
the second one on Windows. Picking the wrong one is the most common integration mistake.

**Note-off convention (p.6):** the device *sends* Note On (`90h`–`9Fh`) with velocity 0 for note
offs. It *accepts* either a real Note Off (`80h`–`8Fh`) or Note On with velocity 0.

> This confirms the hold-to-confirm design. The release trigger is note-on velocity 0, not a
> note-off. Bome's hold-cancel translator incoming string is `90 pp 00`, as drafted.

**This does not solve MIDI input exclusivity.** Two ports exist, but on Windows each input port
is still openable by exactly one process. Two ports means Python and Ableton *can* hold one
each — it does not mean both can see the same pad press. That is the Phase 8 problem.

---

## 3. SysEx framing

Every message, both directions (p.6):

```text
F0h 00h 20h 29h 02h 0Ch      →   240 0 32 41 2 12
```

`00 20 29` is the Novation manufacturer ID. `02 0C` identifies the **Launchpad X**.

> ⚠️ `0Ch` is the Launchpad X. The Launchpad Mini MK3 is `0Dh`. Copying SysEx between the two
> device families silently does nothing.

A command byte follows the header.

**Readback:** send header + command + `F7h` with no data, and the device replies with the same
command and its current `<data>` (p.7). Supported on most commands — see §10.

```python
# launchpad/device.py — layer: driver
# Bytes only. No I/O, no mido import. Anything that opens a port lives elsewhere.

LPX_HEADER = [0x00, 0x20, 0x29, 0x02, 0x0C]   # F0/F7 framing added by mido

PROGRAMMER_MODE = LPX_HEADER + [0x0E, 0x01]   # VERIFIED p.7
LIVE_MODE       = LPX_HEADER + [0x0E, 0x00]   # VERIFIED p.7
DAW_MODE_ON     = LPX_HEADER + [0x10, 0x01]   # VERIFIED p.16
DAW_MODE_OFF    = LPX_HEADER + [0x10, 0x00]   # VERIFIED p.16
```

Note `mido.Message("sysex", data=...)` takes the payload **without** `F0`/`F7`; Bome's raw MIDI
strings take it **with**. Same bytes, two conventions — a real source of copy-paste bugs.

### Device inquiry (p.6)

```text
Host → LPX:  F0h 7Eh 7Fh 06h 01h F7h
LPX → Host:  F0h 7Eh 00h 06h 02h 00h 20h 29h 13h 01h 00h 00h <app_version>  F7h   (application)
LPX → Host:  F0h 7Eh 00h 06h 02h 00h 20h 29h 13h 11h 00h 00h <boot_version> F7h   (bootloader)
```

Byte 9 distinguishes state: `01h` = application, `11h` = bootloader. `<version>` is 4 bytes, one
decimal digit each (0–9).

**Use this as the boot-time presence check.** It is the only way for a headless host to confirm
the Launchpad enumerated *and* is running the application rather than sitting in the bootloader.
"A MIDI port with the right name exists" does not prove either.

---

## 4. Mode and layout control

### Select layout — `00h` (p.7)

```text
F0h 00h 20h 29h 02h 0Ch 00h <layout> F7h
```

| `<layout>` | Meaning |
|---|---|
| `00h` (0) | Session — **only selectable in DAW mode** |
| `01h` (1) | Note mode |
| `04h` (4) | Custom mode 1 (Drum Rack, factory default) |
| `05h` (5) | Custom mode 2 (Keys, factory default) |
| `06h` (6) | Custom mode 3 (Lighting mode, Drum Rack layout, factory default) |
| `07h` (7) | Custom mode 4 (Lighting mode, Session layout, factory default) |
| `0Dh` (13) | DAW Faders — **only selectable in DAW mode** |
| `7Fh` (127) | Programmer mode |

### Programmer / Live toggle — `0Eh` (p.7–8)

```text
F0h 00h 20h 29h 02h 0Ch 0Eh <mode> F7h      mode: 0 = Live, 1 = Programmer
```

Selecting Live drops the device into Session layout, or into Note mode if not in DAW mode.

> ### ⚠️ The failure mode that bricks a headless rig
>
> **Selecting Programmer mode by SysEx disables the Setup menu** (the hold-Session gesture).
> The manual states this for both `00h` and `0Eh`. The only way back is another SysEx selecting
> a non-Programmer layout — or a power cycle.
>
> On a rig with no monitor and no keyboard, a Rig Controller that enters Programmer mode and
> exits without restoring Live mode leaves the Launchpad's own UI unreachable. **The controller
> must restore Live mode on clean exit, on exception, and on SIGTERM.** Put it in a `finally`,
> not in a happy path. Add it to the Phase 9 failure-injection list.

**Programmer mode is not persistent.** The device always powers on into Live mode. Re-send the
SysEx on every connect *and* every reconnect — including after the ESD replug failure mode.

### DAW mode — `10h` (p.16)

```text
F0h 00h 20h 29h 02h 0Ch 10h <mode> F7h      mode: 0 = Standalone, 1 = DAW
```

Must be enabled before software can drive Session or Fader layouts. Entering DAW mode clears all
DAW state and lights the Session button. Novation's own instruction: **on exit, send `<mode>`=0**
so the unit stays usable standalone without a power cycle.

---

## 5. Surface addressing

### Programmer mode grid — `UNVERIFIED`, but corners are confirmed

The layout on p.10 is an image. The rule is believed to be:

```text
note = (row × 10) + column        rows 1–9 bottom-to-top, columns 1–9 left-to-right

91 92 93 94 95 96 97 98 99
81 82 83 84 85 86 87 88 89
71 72 73 74 75 76 77 78 79
61 62 63 64 65 66 67 68 69
51 52 53 54 55 56 57 58 59
41 42 43 44 45 46 47 48 49
31 32 33 34 35 36 37 38 39
21 22 23 24 25 26 27 28 29
11 12 13 14 15 16 17 18 19
```

**Three of the four corners are confirmed** by the manual's own worked examples on p.14, which
name pads in prose:

- `0Bh` (11) — "the lower left one in Programmer mode" ✅
- `51h` (81) — "the upper left one" ✅
- `12h` (18) — "the lower right one" ✅

Three corners pin the origin, the row stride and the column stride, so the 8×8 pad grid
(11–88) can be treated as solid. What is **not** confirmed by any prose:

- The top row of function buttons as **CC 91–98**
- The right-hand scene-launch column as **CC 19, 29, 39, 49, 59, 69, 79, 89**
- The logo LED as **CC 99**

These are the ones the Set Browser depends on for pagination and System Mode access. Verify with
`tools/launchpad_note_tester.py` before wiring mappings. This is exactly the Phase 1 exit test.

The manual does confirm (p.10) that **in Programmer mode every pad and button accepts either
Note or Control Change**. The Note/CC split is only what the device *sends* on press. So
`read_events()` must handle both, and `set_led()` may use either.

> **LED indices always follow Programmer-mode numbering** whenever the LED Lighting SysEx (`03h`)
> is used, regardless of the layout currently selected (p.15).

---

## 6. Lighting

### By MIDI channel (p.13)

| Channel | Note status | CC status | Effect |
|---|---|---|---|
| 1 | `90h` (144) | `B0h` (176) | **Static** colour |
| 2 | `91h` (145) | `B1h` (177) | **Flashing** colour |
| 3 | `92h` (146) | `B2h` (178) | **Pulsing** colour |

Note/CC number selects the pad; velocity/value selects the palette index.

- **Flashing** alternates between the static-or-pulsing colour already set (A) and the colour in
  the flashing message (B), 50% duty, one period = one beat.
- **Pulsing** ramps dark ↔ full intensity, one period = two beats.

Both are **slaved to MIDI beat clock**, falling back to 120 bpm or the last clock received.

> **Design consequence.** Open question 3 in the old doc asked whether the hardware could do the
> "set selected, awaiting hold confirmation" pulse natively rather than from a Python thread. It
> can — channel 3, one message. That removes a timer from the event loop entirely.
>
> But the period is **beat-locked, not wall-clock**. With no clock source it free-runs at 120 bpm,
> so one pulse period = 1 s. If Ableton later becomes clock master over USB, every LED animation
> silently retimes to the song tempo. Decide deliberately whether the rig ever sends clock to the
> Launchpad. For a 2 s hold-to-confirm you want wall-clock certainty — so either never send
> clock, or drive that particular animation from the host.

### LED Lighting SysEx — `03h` (p.15)

```text
F0h 00h 20h 29h 02h 0Ch 03h <colourspec> [<colourspec> …] F7h
```

Each `<colourspec>` = lighting type (1 byte) + LED index (1 byte) + lighting data (1–3 bytes):

| Type | Data | Meaning |
|---|---|---|
| 0 | 1 byte | Static, palette entry |
| 1 | 2 bytes | Flashing — Colour B, then Colour A |
| 2 | 1 byte | Pulsing, palette entry |
| 3 | 3 bytes | **RGB** — R, G, B, each 0–127 |

**Up to 81 entries per message — the entire surface in one transaction.**

Manual's example (p.15):
```text
F0h 00h 20h 29h 02h 0Ch 03h  00h 0Bh 0Dh  01h 0Ch 15h 17h  02h 0Dh 25h  F7h
```
→ pad 11 static yellow; pad 12 flashing between palette 21 and 23 (bright/dim green); pad 13
pulsing turquoise 37.

Type 3 is the only route to arbitrary RGB — the note/CC path is palette-only. Worth knowing
before anyone designs a colour scheme that the 128-entry palette cannot hit.

### Colour palette — `UNVERIFIED`

128 entries, 0–127. The table is an image on p.12 and did not extract.

**Eight indices are confirmed** from worked examples and prose:

| Index | Colour | Cite |
|---|---|---|
| 0 | blank / off | p.14 |
| 5 | Red | p.14 |
| 13 | Yellow | p.15 |
| 19 | Green | p.14 |
| 21 | bright Green | p.15 |
| 23 | dim Green | p.15 |
| 37 | Turquoise | p.15, p.23 |
| 45 | Blue | p.14 |

`docs/colour-palette-candidate.json` holds a full 128-entry table **sampled from the Launchpad
Mini MK3 manual, not this one.** All eight indices above agree with it, which is suggestive but
is not proof — it is a different device. Treat the file as a starting hypothesis for layout
mock-ups, and close it out with `tools/led_color_tester.py` (sweep 0–127, photograph, record).
Do not let it become load-bearing before then.

---

## 7. Text scrolling — `07h` (p.23)

```text
F0h 00h 20h 29h 02h 0Ch 07h [<loop> [<speed> [<colourspec> [<text>]]]] F7h
```

- `<loop>` — 0 no loop, 1 loop
- `<speed>` — pads/second. **If ≥ 40h it is negative** (`speed − 80h`), scrolling left→right
- `<colourspec>` — `00h <palette>` (2 bytes) or `01h <R> <G> <B>` (4 bytes, 0–127 each)
- `<text>` — ASCII

Empty message (`…07h F7h`) terminates any active scroll. Omitting `<text>` retunes the
*currently scrolling* text's loop/speed/colour. Turning loop off mid-scroll lets the current
pass finish, then stops.

Scroll covers the pads and right-side buttons only. The top row and logo are unaffected, and any
lighting underneath is **preserved and restored** afterwards. Works in DAW mode too, overlaying
without disturbing surface state.

Example — "Hello World", looping, 7 pads/sec, turquoise:
```text
F0h 00h 20h 29h 02h 0Ch 07h 01h 07h 00h 25h 48h 65h 6Ch 6Ch 6Fh 20h 57h 6Fh 72h 6Ch 64h F7h
```

> **This is the headless error display.** No monitor is attached at gig time. Error Mode
> currently plans to signal with pad colours; a scrolling string can name the actual fault —
> `NO ASIO`, `SET MISSING`, `LP LOST`. Cheaper and more specific than a colour code someone has
> to memorise. Worth designing into Error Mode from the start rather than bolting on.

---

## 8. Configuration — the settings the blueprint wanted set by hand

`launchpad info` §4 lists device settings to configure manually before deployment. **Most are
also settable by SysEx**, which means the Rig Controller can assert them at every boot instead
of trusting that nobody changed them.

| Setting | Cmd | Message | Cite |
|---|---|---|---|
| Brightness (0–127) | `08h` | `F0 00 20 29 02 0C 08 <brightness> F7` | p.25 |
| LED feedback | `0Ah` | `F0 00 20 29 02 0C 0A <internal> <external> F7` | p.25 |
| Velocity curve | `04h` | `F0 00 20 29 02 0C 04 <curve> <fixed> F7` | p.25 |
| Aftertouch | `0Bh` | `F0 00 20 29 02 0C 0B <type> <threshold> F7` | p.26 |
| Fader velocity | `0Dh` | `F0 00 20 29 02 0C 0D <mode> F7` | p.26 |
| LED sleep | `09h` | `F0 00 20 29 02 0C 09 <mode> F7` | p.24 |

Values:

- **LED feedback** — internal = light on local press; external = light on MIDI arriving at the
  MIDI interface. Each 0 = off, 1 = on. **External must be on** or the controller's LED writes
  silently do nothing. This is the documented silent-failure trap.
- **Velocity curve** — 0 Low, 1 Medium, 2 High, **3 Fixed**. `<fixed>` supplies the fixed value
  (default `7Fh`) and **is not settable from the Setup menu at all** — SysEx only. Pads here are
  buttons, not instruments, so `<curve>`=3 with `<fixed>`=127 gives constant velocity and
  simplifies `read_events()`.
- **Aftertouch** — 0 Polyphonic, 1 Channel, **2 Off**. Set 2. Aftertouch is a stream of junk
  messages the event loop would otherwise filter every frame.
- **LED sleep** — 0 = LEDs off, 1 = on. **Do not use.** A blanked surface is indistinguishable
  from a dead rig mid-show. Any interaction also wakes the device.
- **Brightness** — the manual notes **low brightness may be required for some hosts to power the
  device at all** (p.5). If the Launchpad fails to enumerate on the Beelink, suspect brightness
  and USB power before the cable.

Asserting all of these at boot is strictly better than a bench checklist, because it survives
someone poking the Setup menu at a gig. **Except MSD mode** — see below.

### Bootloader (p.5) — the one thing SysEx cannot fix

Entered by **holding Capture MIDI while plugging the device in**. Exposes: device ID 1–16 (top
two rows), Onboarding/MSD toggle (yellow pad, middle right), brightness (blue row), bootloader
and application version (green pads, bottom left), start application (green pad, bottom right).

**Disable MSD/Onboarding once, at bench setup.** Otherwise the Launchpad mounts as a USB mass
storage volume on every boot — a spurious drive and one more thing for Windows to enumerate on a
headless machine. There is no SysEx for this; it is physical, and it must happen before
deployment.

> Note for anyone who has read the Launchpad **Mini MK3** manual: that document's bootloader
> section also says "Capture MIDI", which is wrong for the Mini (it has no such button). For the
> **Launchpad X** it is correct — the X does have Capture MIDI.

---

## 9. DAW interface — deferred, not needed yet

Phases 1–7 run the device in Programmer mode on the MIDI interface. The DAW interface is only
relevant if Ableton drives the Launchpad directly, which is the Phase 8 question. Recorded here
so it is not re-researched later.

Channels on `LPX DAW In/Out` (p.16):

**Host → device:** ch 1 static / ch 2 flashing / ch 3 pulsing on Session layout; ch 5 (`B4h`)
fader position; ch 6 (`B5h`) fader colour; ch 9/10/11 (`98h`/`99h`/`9Ah`) static/flashing/pulsing
on DAW Drum Rack; ch 16 (`9Fh`) external note injection.

**Device → host:** ch 1 Session activity; ch 5 fader activity; ch 9 Drum Rack activity.
Aftertouch also arrives on ch 1 / ch 9 unless disabled.

DAW state persists across layout switches and applies whether or not the layout is visible. The
Session/Note/Custom buttons cannot be *controlled* by the DAW but still *send* their CCs, so the
host can observe user-driven layout changes.

Other DAW-only commands: DAW state clear `12h` (p.17), fader bank setup `01h` (p.19), Note/Drum
Rack select `0Fh` (p.20), Intelligent Drum Rack position `13h` (p.21), Session button colour
`14h` (p.22), Note mode active colour `17h` (p.22), Note mode config `15h`/`16h` (p.27).

Fader banks: up to 8 faders, shared orientation (0 vertical / 1 horizontal), each independently
unipolar or bipolar, each with a CC and a palette colour. **Colour 0 hides a fader.** Configure
the bank *before* switching to layout `0Dh`, or the previous bank flashes up during the
transition (p.19).

---

## 10. Command summary

| Function | Cmd | Readback | Cite |
|---|---|---|---|
| Select Layout | `00h` | Yes | p.7 |
| DAW Fader Setup | `01h` | Yes | p.19 |
| LED Lighting | `03h` | No | p.15 |
| Velocity Curve | `04h` | Yes | p.25 |
| Text Scrolling | `07h` | No | p.23 |
| Brightness | `08h` | Yes | p.25 |
| LED Sleep | `09h` | Yes | p.24 |
| LED Feedback | `0Ah` | Yes | p.25 |
| Aftertouch | `0Bh` | Yes | p.26 |
| Fader Velocity | `0Dh` | Yes | p.26 |
| Programmer/Live | `0Eh` | Yes | p.7 |
| Note/Drum Rack select | `0Fh` | Yes | p.20 |
| DAW / Standalone | `10h` | Yes | p.16 |
| Clear DAW state | `12h` | No | p.17 |
| Drum Rack position | `13h` | Yes | p.21 |
| Session Colour | `14h` | Yes | p.22 |
| Note Mode mode | `15h` | Yes | p.27 |
| Note Mode config | `16h` | Yes | p.27 |
| Note Mode colour | `17h` | Yes | p.22 |

---

## 11. Startup / shutdown contract

Consolidated from the above. This is the spec `launchpad/device.py` must satisfy.

**On connect, in order:**

1. Device inquiry → confirm application, not bootloader. Log the version.
2. `0Eh 01` — Programmer mode.
3. `0Ah 01 01` — LED feedback internal + external on.
4. `04h 03 7Fh` — fixed velocity.
5. `0Bh 02 01` — aftertouch off.
6. `08h <brightness>` — from `rig.yaml`, not hardcoded.
7. Short settle delay before the first LED write.
8. `03h` — paint the surface in one SysEx.

**On disconnect / exit / crash / signal — non-negotiable:**

1. `0Eh 00` — **restore Live mode.** In a `finally`. Without this the front panel is stuck.
2. `10h 00` — Standalone, if DAW mode was ever enabled.

**On reconnect:** the entire connect sequence again. The device forgets everything across a
replug, and ESD-triggered replugs are an expected live failure mode, not an edge case.

---

## 12. Open items

1. Verify the CC frame — top row 91–98, right column 19–89, logo 99. `tools/launchpad_note_tester.py`.
2. Verify the 128-colour palette. `tools/led_color_tester.py`. Compare against
   `docs/colour-palette-candidate.json` and record which entries differ.
3. Confirm on Windows that the Launchpad X enumerates as two distinct input ports, and record
   the exact port name strings. Name matching in `launchpad/ports.py` depends on them.
4. Measure the settle delay needed between Programmer-mode entry and the first accepted LED
   write. The 100 ms in the old draft is a guess.
5. Confirm whether one SysEx carrying all 81 entries is accepted in practice, and time it.
   81 entries is the documented ceiling, not a measured throughput.
