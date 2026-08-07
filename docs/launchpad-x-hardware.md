# Launchpad X — Hardware Reference for the Beelink Rig

**Purpose.** Device behaviour and physical settings that are *not* MIDI protocol. For SysEx,
grid addressing, colours and the startup contract, see `launchpad-x-sysex.md` — that document
supersedes anything here that they disagree on, because it is sourced from the Programmer's
Reference rather than the User Guide.

Source: Novation *Launchpad X User Guide* (Focusrite Audio Engineering, 2019).
Companion, now obtained: *Launchpad X Programmer's Reference Manual* —
`docs/datasheets/novation-launchpad-x-programmers-reference.pdf`.

---

## 1. The single most important fact for a headless rig

> **Launchpad X always powers on into Live Mode.**

There is no persistent "boot into Programmer Mode" setting. Every time the Beelink powers on —
or the Launchpad is unplugged and replugged — the device comes up in Live Mode, where it expects
to talk to Ableton's control surface script, **not** to the Rig Controller.

**Consequence:** `LaunchpadDevice.connect()` must send the Programmer Mode SysEx immediately
after opening the output port, and again on every reconnect. This is not optional.

The full connect/disconnect contract is `launchpad-x-sysex.md` §11.

---

## 2. Live Mode vs Programmer Mode

| | Live Mode | Programmer Mode |
|---|---|---|
| Session / Note / Custom modes | Available | Disabled |
| Addressable surface | 8x8 grid only (in Custom modes) | Full 9x9 — pads **and** buttons |
| Logo LED | No | Yes, addressable |
| Top row & right column | Mode buttons | Send CC messages |
| Surface at entry | Lit per mode | Entirely unlit |

Manual entry (for bench testing without code): hold **Session** briefly to open Settings, then
press the **orange** Scene Launch button. Green returns to Live Mode.

> ⚠️ **That gesture stops working once software selects Programmer Mode by SysEx.** The
> Programmer's Reference states the Setup entry is disabled in that case. On a headless rig the
> only recovery is another SysEx or a power cycle. See `launchpad-x-sysex.md` §4.

---

## 3. Grid note numbering

Programmer Mode covers the **full 9x9 grid**, so the top row and right-hand column are
addressable. Those arrive as **CC messages**, not notes — `read_events()` must handle
`control_change` by falling back to `message.control`.

The 8x8 pad grid (11–88) is verified from the Programmer's Reference worked examples. The CC
frame is not. Details and the exact open items: `launchpad-x-sysex.md` §5.

**Custom Mode 4** uses "note values matching Programmer Mode, but for the 8x8 grid only." A
fallback if Programmer Mode causes problems, but it loses the side buttons — which the Set
Browser layout uses for pagination and system access. Prefer Programmer Mode.

---

## 4. Settings that must be configured before deployment

These live in the device's own settings menu (hold **Session**) or the bootloader menu, and they
persist on the hardware.

| Setting | Where | Required value | Why |
|---|---|---|---|
| **LED feedback (external)** | Settings → LED (1st scene button) | **Enabled** (default) | If disabled, MIDI sent from the Rig Controller will not light pads in Programmer Mode. Silent failure — LEDs just do nothing. |
| **MSD Mode** | Bootloader (hold *Capture MIDI* while plugging in) | **Disabled** | Otherwise the Launchpad mounts as a USB mass storage drive on every boot. Pointless on a headless rig and one more thing for Windows to enumerate. |
| **LED brightness** | Settings → LED, or bootloader | Set for stage lighting | 8 levels from the menu, 0–127 by SysEx. Dark venues need less than you think. Also: low brightness may be **required** for some hosts to power the device at all. |
| **Velocity sensitivity** | Settings → VEL (2nd scene button) | **Disabled** | Pads here are buttons, not instruments. Fixed velocity gives consistent values and simplifies `read_events()`. |
| **Aftertouch** | Settings → AFT (3rd scene button) | **Disabled** | Aftertouch generates a stream of extra MIDI messages the event loop must filter. |
| **Device ID** | Bootloader | Leave default | Only relevant with multiple units. |

> **Most of these are also settable by SysEx** — see `launchpad-x-sysex.md` §8. Prefer asserting
> them at every boot over trusting a bench checklist, because SysEx survives someone poking the
> Setup menu at a gig.
>
> **MSD Mode is the exception.** It is bootloader-only, physical, and must be done before
> deployment. There is no SysEx for it.

**Do not use LED Sleep** (Settings → LED). It blanks the surface until a pad is pressed —
indistinguishable from a dead rig mid-show.

---

## 5. Ghost Mode

Press **Note** then **Custom** in quick succession to un-light the function buttons around the
edge, leaving only the 8x8 grid lit. Press any edge button to restore.

Relevant only in Custom modes, not Programmer Mode. Mentioned here so it isn't mistaken for a
fault if someone triggers it accidentally.

---

## 6. Electrostatic discharge

The manual states plainly: a strong ESD event can disrupt normal operation, and the fix is to
unplug and replug the USB cable.

**This is a live-performance failure mode.** A guitarist walking across a carpeted stage in dry
air is an ESD source.

- Recovery requires a **physical** unplug/replug — code alone cannot reset the device.
- The reconnect loop in `ensure_launchpad()` handles the software side, and must re-run the
  *entire* init sequence, not just reopen the port. The device forgets Programmer Mode, LED
  feedback, velocity curve and aftertouch settings across a replug.
- Add to the §46 failure tree as a distinct Launchpad failure cause.
- Add to the §51 Full Rehearsal Test: unplug mid-performance, replug, confirm the controller
  reconnects and restores full device state without a restart.

---

## 7. Impact on the existing blueprint

| Blueprint section | Change |
|---|---|
| §16 Launchpad Device Class | Add `enter_programmer_mode()`, called from `connect()` and every reconnect. Add a `finally`-guarded `restore_live_mode()`. |
| §17 LED Color System | Palette still unverified — see `launchpad-x-sysex.md` §6 and `colour-palette-candidate.json`. |
| §22 Animations | Batch via one LED Lighting SysEx (81 entries), not per-pad note-ons. |
| §30 MIDI Routing | Two input ports confirmed on Windows. Still does not let two programs read the same port. Phase 8 decides. |
| §42 Installation Tree | Add: configure Launchpad hardware settings (MSD off via bootloader) before headless deployment. |
| §46 Failure Tree | Add ESD reset as a Launchpad failure cause. Add "controller crashed while in Programmer Mode" as a separate, worse one. |
| §56 First Build Order — Step 4 | Record the note map *while in Programmer Mode*; Live Mode sends different values. |

---

## 8. Open questions

All four original open questions are answered — see `launchpad-x-sysex.md` §1. Three closed
outright; the colour palette remains open because the manual renders it as an image. Remaining
work is bench verification, tracked in `launchpad-x-sysex.md` §12 and `ROADMAP.md` Phase 1.
