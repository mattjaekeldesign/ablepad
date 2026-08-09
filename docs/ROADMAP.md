# Beelink Headless Ableton Rig — Master Roadmap

**Status:** Design complete, implementation not started (0 lines of code)
**Last updated:** 2026-08-07 (was 2026-08-03 — Phase 1 assumptions revised, see §0)
**Purpose:** Single source of truth for build order. Work top to bottom. Do not skip phases.

---

## 0. Where the project actually stands

```text
PROJECT STATE
│
├── COMPLETE
│   ├── System blueprint (Start_DOCS, §1–56)   ← NOT IN THIS REPO, see below
│   ├── Launchpad X hardware reference
│   ├── Launchpad X Programmer's Reference Manual (obtained 2026-08-07)
│   └── Bome MIDI Translator evaluation
│
├── PARTIALLY COMPLETE
│   └── Nothing — documentation only
│
└── NOT STARTED
    ├── Repository scaffolding beyond docs
    ├── Every module
    ├── Every hardware verification
    └── Every Windows configuration step
```

> ⚠️ **`Start_DOCS` is not in this repo.** Every `§n` reference below and in the other docs
> points at that 4,073-line blueprint, which currently lives only in the claude.ai project
> knowledge. Get it committed here before treating any § citation as checkable.

The documentation is strong. The problem is that **large parts of it are built on assumptions
that have never been tested against real hardware.** Phase 1 exists purely to convert
assumptions into verified facts before any of it becomes load-bearing.

### Assumption ledger

Revised 2026-08-07 after obtaining the Programmer's Reference Manual. Details and citations in
`docs/launchpad-x-sysex.md`.

| Assumption | Lives in | Status | Breaks if wrong |
|---|---|---|---|
| Programmer Mode SysEx bytes | `launchpad/device.py` | ✅ **VERIFIED** p.7 | Launchpad never lights up at all |
| Launchpad exposes 2 MIDI ports on Windows | §30 routing | ✅ **VERIFIED** p.6 | Forces the Bome decision early |
| Release = note-on velocity 0 | Hold-to-confirm | ✅ **VERIFIED** p.6 | Hold logic silently never fires |
| Batch LED write in one SysEx | `launchpad/renderer.py` | ✅ **VERIFIED** — 81 pads/msg, p.15 | Animations stutter; Bome gets more attractive |
| Grid notes 11–88 | `launchpad/grid.py` | ⚠️ **Corners verified** p.14, interior inferred | Every pad mapping, every renderer |
| CC frame 91–98 / 19–89 / 99 | `launchpad/grid.py` | ❌ Unverified — page image | Pagination and System Mode access |
| Colour index values | `launchpad/colors.py` | ❌ Unverified — page image; 8 indices confirmed | All LED feedback and animations |
| Beelink Wi-Fi supports hosted hotspot | §32 | ❌ Unverified | Loses offline SSH lifeline |
| Ableton exe path | `rig.yaml` | ❌ Unverified | Nothing launches |

**What changed the plan:** batch LED writes work. `clear_grid()` is one SysEx, not 64 note-ons,
so Python-side animation is viable. That removes the *performance* argument for Bome — but not
the MIDI-input-exclusivity argument, which is the real one. Phase 8 still decides.

---

## 1. The one architectural decision to defer, deliberately

**Who owns the Launchpad MIDI input?** On Windows a MIDI input port is exclusive — exactly one
process can hold it.

```text
OPTION A — Python owns the port
├── Ableton cannot see the Launchpad
├── Performance pads must be forwarded through a virtual MIDI port
├── One language, one process, no licence cost
└── LED animations run on a Python thread

OPTION B — Bome owns the port
├── Bome fans out: system pads → Python, performance pads → Ableton
├── Native non-blocking timers and port-plugged-in triggers
├── ~€79, second always-on process, logic split across two tools
└── Python never touches MIDI
```

**Recommendation: defer this until Phase 8.**

Reasoning: Phases 1–7 do not need Ableton to see the Launchpad at all. During browsing, booting
and system control, the Rig Controller is the only consumer of pad presses. The exclusivity
problem only becomes real when performance pads need to reach Ableton *while* the rig controller
is still listening.

Two facts were meant to decide it. Both are now known:

1. ~~Does the Launchpad X expose separate MIDI and DAW input ports on Windows?~~ **Yes** — but
   two ports is not the same as two readers of one port. Ableton on the DAW port and Python on
   the MIDI port is a real topology; whether it gives the performance behaviour you want is a
   Phase 8 question, not a documentation question.
2. ~~Can multiple LEDs be set in a single SysEx write?~~ **Yes, 81 per message.** Python
   animation will not stutter. Argument for Bome weakened.

**Risk of deferring: Low.** Phases 1–7 are written against a thin `LaunchpadDevice` interface.
If Bome wins later, only that one adapter is replaced.

---

## 2. Phase map

```text
BUILD ORDER
│
├── Phase 0  Bench truth        — prove audio works before automating anything
├── Phase 1  Hardware truth     — replace every guess with a measured value
├── Phase 2  Skeleton           — config, logging, state machine, tests
├── Phase 3  Launchpad service  — driver, renderer, modes
├── Phase 4  Set browser        — scan, paginate, map to pads
├── Phase 5  Ableton launcher   — launch, supervise, recover
├── Phase 6  Lifeline           — hotspot + SSH  ← BEFORE going headless
├── Phase 7  Headless boot      — task scheduler, cold-boot test
├── Phase 8  Performance layer  — Bome decision lands here
└── Phase 9  Hardening          — rehearsal, failure injection, system image
```

> **Note on ordering vs the blueprint.** Start_DOCS §56 puts hotspot/SSH at step 11 and the
> headless test at step 14. That is backwards. SSH is the recovery path *for* headless
> operation — build it while a monitor is still attached, or your first headless failure means
> reassembling a desk.

---

## Phase 0 — Bench truth (no rig code)

Prove the musical instrument works before automating it. If latency is bad here, no amount of
Python fixes it.

```text
□ Windows account "LiveRig" created, auto-login enabled
□ Audient EVO 8 Windows driver installed (MANDATORY — not class-compliant on Windows)
□ EVO firmware updated WHILE STILL ONLINE; driver + firmware versions recorded
□ EVO Mixer tray app running; ASIO buffer + sample rate set THERE, not in Ableton
□ Beelink USB port chosen and recorded (USB-A = 2 phantom channels, USB-C @1.5A = 4)
□ ASIO confirmed in Ableton
□ Guitar → EVO 8 front DI → Ableton → mixer produces sound (DI overrides channel 1)
□ Buffer size and sample rate chosen and written down
□ Round-trip latency measured and judged playable
□ C:\LiveRig\ folder tree created (§8)
□ Python 3.12+, Git, VSCode installed
□ Repo initialised, .gitignore, venv, requirements.txt
□ Ableton executable path recorded verbatim
■ Launchpad X Programmer's Reference Guide downloaded to /docs   ← DONE 2026-08-07
```

**Risk: Low.** Manual work only.
**Exit test:** You can play guitar through Ableton for 30 minutes with no dropouts.

---

## Phase 1 — Hardware truth layer

The most important phase in the project. Output is not features — it is **verified constants**
that the rest of the codebase depends on.

```text
tools/
├── midi_port_inspector.py      → list every MIDI in/out name on Windows
├── launchpad_note_tester.py    → press every pad, record note/CC numbers
├── led_color_tester.py         → sweep 0–127, photograph the result
├── led_batch_tester.py         → confirm + time an 81-entry SysEx write
└── interface_name_inspector.py → what does Get-PnpDevice actually return?
```

```text
□ Launchpad hardware settings configured
│   □ LED feedback (external) ENABLED      — SysEx 0Ah, assert at boot
│   □ MSD Mode DISABLED (bootloader)       — PHYSICAL ONLY, no SysEx, do before deployment
│   □ Aftertouch DISABLED                  — SysEx 0Bh, assert at boot
│   □ Velocity sensitivity DISABLED        — SysEx 04h fixed curve, assert at boot
│   □ LED Sleep OFF                        — SysEx 09h, assert at boot
│   □ Brightness set for stage             — SysEx 08h from rig.yaml
■ Programmer Mode SysEx confirmed against the Reference Guide   ← DONE, bytes were correct
□ Programmer Mode entry verified in code
□ Full 9×9 note + CC map recorded → commit as launchpad/grid.py
│   └── 8×8 pad grid corners already verified from the manual; the CC frame is the real unknown
□ Colour index recorded → commit as launchpad/colors.py
│   └── compare against docs/colour-palette-candidate.json, record every difference
■ Release semantics confirmed (note-on vel 0)                   ← DONE, manual p.6
■ Batch LED write                                               ← DONE, 81 entries/msg, p.15
□ Port list recorded — exact Windows name strings for both interfaces
□ EVO 8 Get-PnpDevice friendly names recorded for EVERY endpoint
│   └── manual prints 'EVO 8 Main Output 1+2' and 'Loop-back 1+2' — confirm against PnP
□ Decided which endpoint means 'interface present' (Loop-back is not it)
□ Programmer→Live restore-on-crash proven (kill the process, check the Setup menu still opens)
```

**Risk: Medium.** Was High — the missing document was the reason. Now the remaining unknowns are
two page images and a set of Windows-specific strings, all of which a bench session settles.

**Exit test:** `grid.py` and `colors.py` contain measured values, with the date and method
recorded in a comment. No guesses left in either file.

---

## Phase 2 — Skeleton

No hardware features. Just the spine everything else hangs from.

```text
rig/
├── state.py          RigState enum
├── controller.py     tick loop, state transitions only
├── events.py         PadEvent, domain events
├── commands.py       command dispatcher interface
└── exceptions.py

storage/
├── config_loader.py  load + validate rig.yaml, fail loudly
└── runtime_state.py  atomic JSON write

config/rig.yaml
main.py               logging setup, entry point
tests/                state machine + config validation
```

```text
■ rig.yaml loads and validates; missing sections raise clearly   ← DONE 2026-08-09 (all problems reported at once, exit code 2)
■ Logging writes to file and console                             ← DONE 2026-08-09
■ State machine transitions logged, illegal transitions rejected ← DONE 2026-08-09
■ Controller runs a no-op tick loop without crashing             ← DONE 2026-08-09 (30 Hz, overrun re-anchor, 0 overruns observed)
■ Ctrl+C exits cleanly                                           ← DONE 2026-08-09 on macOS — RE-VERIFY on Windows console (CTRL_C_EVENT path)
■ Unit tests pass                                                ← DONE 2026-08-09 (46 tests, incl. _bench SysEx vs manual p.14–15 examples)
```

**Risk: Low.** Pure Python, fully testable with no hardware attached. This is the only phase that
can be developed entirely off the Beelink.

> Built off-rig 2026-08-09 while awaiting the Beelink (Phases 0–1 hardware-blocked, not
> skipped). The state transition table in `rig/state.py` is a DESIGN DECISION authored
> without Start_DOCS — review it when that document lands.

---

## Phase 3 — Launchpad service

```text
launchpad/
├── ports.py       port discovery, name matching
├── device.py      open/close, Programmer Mode, read_events, set_led
├── grid.py        VERIFIED from Phase 1
├── colors.py      VERIFIED from Phase 1
├── renderer.py    state → pad colours (pure function where possible)
├── animations.py  non-blocking, killable
├── mappings.py    note → named action, per mode
└── modes.py       LaunchpadMode enum
```

```text
□ Connects, and re-runs the full init sequence on every reconnect
□ Restores Live mode in a finally block — on exit, exception AND signal
□ Survives unplug/replug with no restart (ESD failure mode)
□ Pad press → named action, not a raw note number
□ Renderer is separate from device I/O
□ Renderer emits one batched SysEx, not per-pad messages
□ Folder-scanner animation runs without blocking the event loop
□ Animation can be cancelled mid-run
```

**Risk: Medium.** The reconnect + SysEx path is the single most common way this rig dies on
stage. Test it 20 times, not twice.

---

## Phase 4 — Set browser

```text
set_browser/
├── scanner.py     find .als, ignore backups/autosaves
├── models.py      LiveSet dataclass
├── metadata.py    merge sets.yaml over scanned files
├── pagination.py
└── service.py
```

```text
□ Finds .als files, ignores backup/autosave/project-info
□ sets.yaml metadata (name, colour, category) overrides defaults
□ Unknown files still appear, in a neutral colour
□ Pagination works past 48 sets
□ Empty folder shows an error state, does not crash
□ Rescan works without restarting the controller
```

**Risk: Low.**

---

## Phase 5 — Ableton launcher

```text
ableton/
├── launcher.py   start, stop, restart
├── process.py    psutil supervision
├── readiness.py  "running" vs "actually loaded"
└── recovery.py   attempt limits
```

```text
□ Refuses to launch if the EVO 8 is absent
□ Refuses to launch if the .als is missing
□ Hold-to-confirm (2s) gates every set load
□ Graceful close attempted before kill
□ Crash detected and one restart attempted
□ Restart attempts capped — no infinite loop
□ Stable/Candidate deployment folders in use, sets treated read-only
```

**Risk: High.** "Process exists" ≠ "set loaded". Until an Ableton Remote Script sends a READY
signal, readiness is a timing guess. Accept that for now; log it as known debt.

---

## Phase 6 — Lifeline (build before headless)

```text
windows/
├── hotspot.py
├── ssh.py
├── power.py
└── commands.py
```

```text
□ OpenSSH Server installed, key auth only, password auth disabled
□ Hotspot starts and stops from a Launchpad pad
□ iPhone joins the hotspot with no internet present
□ SSH from iPhone reaches the Beelink
□ rig-status, ableton-restart, collect-logs work over SSH
□ Reboot requires System Mode + 4s hold
□ Shutdown requires two pads + 6s hold
```

**Risk: Medium.** Windows Mobile Hotspot APIs are inconsistent across adapters. Verify the
Beelink's adapter supports it before committing to the design.

---

## Phase 7 — Headless boot

```text
□ Task Scheduler starts the controller at logon, restarts on failure
□ Power plan: no sleep, no hibernate, no USB selective suspend
□ Notifications, update reboots, startup apps disabled
□ Cold boot with monitor attached → rig reaches Set Browser unaided
□ Cold boot with NO monitor/keyboard/mouse → same result
□ Full boot completes in under 90 seconds
```

**Risk: Medium.** USB enumeration order and login timing are the usual culprits.

---

## Phase 8 — Performance layer (Bome decision)

Revisit §1 of this document using the Phase 1 findings.

```text
□ Decision made and written down, with the reasoning
□ Performance pads reach Ableton
□ System pads still reach the Rig Controller
□ Panic mute works from any mode
□ Guitar tones, effects, looper mapped
□ Mode switching is deliberate, not accidental
```

**Risk: High.** This is where the architecture could need rework. Everything before it should
already be reliable so this can fail safely.

---

## Phase 9 — Hardening

```text
□ Full rehearsal test (§51) passed
□ Launchpad unplugged mid-show → recovers
□ Rig Controller killed mid-show → Launchpad still returns to Live mode
□ EVO 8 unplugged mid-show → warns, does not thrash
□ EVO 8 ESD-wedged mid-show → rig says AUDIO FAULT on the Launchpad, not silence
□ Launchpad AND EVO both replugged → both recover without restarting Live
□ Ableton killed mid-show → recovers once, then errors cleanly
□ Ran continuously for 4+ hours
□ Emergency clean set loads from a cold rig
□ Backup audio path (DI or pedal) physically present in the gig bag
□ Full Windows system image captured
```

---

## 3. Live risk register

| Risk | Level | Note |
|---|---|---|
| ~~Programmer Mode SysEx unverified~~ | ~~High~~ | **Closed** 2026-08-07 — bytes confirmed |
| Programmer mode disables the Setup menu | **High** | A crashed controller leaves the front panel unreachable on a headless rig. Restore Live mode in `finally` |
| Ableton readiness is a guess | High | No signal until a Remote Script exists |
| MIDI input exclusivity | High | Deferred, not solved |
| Colour index guessed | Medium | Cosmetic until it isn't. Candidate table is from a *different device* |
| CC frame guessed | Medium | Pagination and System Mode depend on it |
| Windows hotspot support | Medium | Hardware-dependent |
| ESD resets the Launchpad | Medium | Needs physical replug; code can only recover after |
| USB power / brightness at enumeration | Medium | Manual warns low brightness may be required to power on at all |
| Plugin auth dialogs | Medium | Mitigate via plugin policy, not code |
| Windows update reboot | Medium | Policy problem, not engineering |

---

## 4. Session-start ritual

Each session, answer before writing code:

```text
1. Which phase am I in?
2. Is the previous phase's exit test actually passing?
3. What is the single next checkbox?
4. What assumption am I about to make load-bearing?
```

---

## 5. Known limitations (accepted, documented)

- Set switching will interrupt audio. Not solvable without two Live instances.
- The rig cannot recover from a dead PSU, failed SSD or frozen Windows. Keep a backup path.
- Ableton's internal audio-device selection may need manual setup for a genuinely different
  interface family. Detection ≠ configuration.
- No plugin can be trusted to stay silent forever. Archive installers and freeze versions.
- LED flash/pulse are beat-clock slaved, not wall-clock. Any timing-critical feedback must be
  host-driven or the rig must never send clock to the Launchpad.
