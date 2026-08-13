# Beelink Headless Ableton Rig — Master Roadmap

**Status:** Phases 2, 4 and 5 built and green. Phase 1's exit test is met on hardware.
Phase 3 is the real gap. ~2404 lines of rig code, 1364 lines of tests, 374 passing.
**Last updated:** 2026-08-12 — reconciled against the actual tree, see §0
**Purpose:** Single source of truth for build order. Work top to bottom. Do not skip phases.

---

## 0. Where the project actually stands

```text
PROJECT STATE — reconciled against the tree 2026-08-12
│
├── DONE, WITH CODE AND TESTS
│   ├── Phase 2  rig/ storage/ config/rig.yaml main.py       exit test MET
│   ├── Phase 4  set_browser/ scanner models metadata …      exit test MET
│   └── Phase 5  ableton/ launcher process readiness …       exit test MET
│
├── DONE, ON HARDWARE
│   ├── Phase 0  audio path proven, 256 @ 44.1k, 15 min clean (30 still owed)
│   └── Phase 1  grid.py + colors.py hold MEASURED constants  exit test MET
│
├── PARTIALLY DONE
│   ├── Phase 3  launchpad/ has grid colors animations mappings player
│   │            MISSING: ports.py  device.py  renderer.py  modes.py
│   │            — i.e. everything that actually opens the device
│   ├── Phase 6  SSH lifeline works (Tailscale + key auth). The windows/ package
│   │            does not exist: no hotspot.py ssh.py power.py commands.py
│   └── Phase 7  power plan, Defender exclusions, startup trimming applied BY HAND.
│                Nothing automated, no Task Scheduler entry, no cold-boot test
│
└── NOT STARTED
    ├── Phase 8  performance layer / the Bome decision
    └── Phase 9  hardening, rehearsal, system image
```

> ### Why this section was wrong, and how to keep it right
>
> Until 2026-08-12 this file said "implementation not started (0 lines of code)"
> while five phases of working code sat in the tree. It was taken at face value and
> a session started rebuilding Phase 2 from scratch before anyone ran the tests.
>
> **The tree is the truth; this file is only a claim about the tree.** Before
> trusting a status line here, run `pytest -q` and look at which modules exist.
> Update this section in the same commit as the code, or it drifts again.

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
| Batch LED write in one SysEx | `launchpad/renderer.py` | ✅ **MEASURED ON HARDWARE** 2026-08-12 — 81 pads, one message, whole surface | Animations stutter; Bome gets more attractive |
| Grid notes 11–88 | `launchpad/grid.py` | ⚠️ Corners p.14 + 7 interior notes measured 2026-08-12, all fit the rule | Every pad mapping, every renderer |
| CC frame 91–98 / 19–89 | `launchpad/grid.py` | ✅ **MEASURED 2026-08-12** — 16/16 exact, zero mismatches. Logo 99 lights but is NOT a button | Pagination and System Mode access |
| Colour index values | `launchpad/colors.py` | ✅ **8/8 IN USE VERIFIED** on hardware 2026-08-12. Other 120 unread (p.12 is an image) but nothing references them — `tools/palette_coverage.py` guards that | All LED feedback and animations |
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
├── Phase 8  Performance layer  — Bome decision + Ampero, both blocked on a
│                              TRS-to-USB MIDI interface (see hotone reference)
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
■ Audient EVO 8 Windows driver installed — CONFIRMED 2026-08-12
│   └── driver packages oem98.inf/oem99.inf v5.4.0.20404, ASIO registered,
│       tray app running
■ EVO 8 enumerating — CONFIRMED 2026-08-12 after a replug
│   └── device node 'Audient EVO8' (MEDIA), VID_2708&PID_0007, 13 audio endpoints
│   └── gate presence on the HARDWARE ID: friendly names differ from the manual
│       and two endpoints share one. tools/results/interface-names-evo8.txt
□ EVO firmware updated WHILE STILL ONLINE; driver + firmware versions recorded
■ EVO Mixer tray app running (pid 2480) — CONFIRMED 2026-08-12
■ Beelink USB port chosen and recorded — DONE 2026-08-13
│   └── EVO 8 is USB-C (device) to USB-A (host), DIRECT to the root hub, no hub between
│   └── CONSEQUENCE: 2 of 4 phantom channels only (EVO manual p.22). Fits the 2 XLR
│       cables on hand, but that is coincidence — a third condenser needs a port change
│   └── the box cable is USB-C to USB-C and cannot reach a USB-A host; the C-to-A cable
│       in use is load-bearing kit. Spare in the gig bag
■ ASIO confirmed in Ableton — DONE 2026-08-12, 'Audient USB Audio ASIO Driver'
■ Guitar → EVO 8 front DI → Ableton → NAM + IR produces sound — DONE 2026-08-12
■ Buffer size and sample rate written down — DONE 2026-08-12
│   └── **256 samples @ 44100 Hz**, no crackles. Set in the ASIO driver panel,
│       NOT in Ableton — Ableton's control is read-only for ASIO devices
│   └── GUI-ONLY: nothing persists these where a script can reach them, so they
│       must be frozen into the system image. EVO reference open item 6
│   └── tools/results/phase0-audio-settings.txt
■ Round-trip latency: 256 @ 44.1k holds cleanly under a heavy chain, 15 min.
│   └── derived estimate ~15 ms (was ~27 ms at 512)
│   └── STILL OWED: read Ableton's "Overall Latency" field and record the real
│       number. The estimate is arithmetic from the manual, not a measurement
□ C:\LiveRig\ folder tree created (§8)
□ Python 3.12+ installed — NOT PRESENT 2026-08-12 (WindowsApps python.exe is a
│   0-byte Store alias stub, and `py` is absent — there is no Python on the box)
■ Git installed — CONFIRMED 2026-08-12, C:\Program Files\Git\cmd\git.exe
□ VSCode installed — not present 2026-08-12
□ Repo initialised, .gitignore, venv, requirements.txt
■ Ableton executable path recorded — DONE 2026-08-12
│   └── C:\ProgramData\Ableton\Live 12 Suite\Program\Ableton Live 12 Suite.exe
│   └── Live 12 Suite 12.4.3. Note ProgramData, NOT Program Files — a guess would
│       have been wrong. tools/results/phase0-ableton-evo.txt
■ Launchpad X Programmer's Reference Guide downloaded to /docs   ← DONE 2026-08-07
```

**Risk: Low.** Manual work only.
**Exit test: PARTIAL — 15 of 30 minutes, 2026-08-12.** Heavy NAM + IR chain, no
crackles, CPU clock held at ~3.1 GHz with no throttling, EVO and Launchpad present
throughout. Stopped early by choice; a re-test is owed with the real set anyway.

NOT marked complete: thermal throttling on this N150 would typically appear at
15–25 minutes, so the run stopped exactly where the interesting failure begins.
See tools/results/phase0-endurance-notes.md.

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
■ Full 9×9 map recorded — DONE 2026-08-12 → committed as launchpad/grid.py
│   └── all 81 positions swept. 80 pressable, every one reporting a number
│       identical to the LED index that lit it. Zero unexplained mismatches
│   └── evidence: tools/results/grid-{frame,8x8,retest}.txt
│   └── the map is an EQUATION, (row*10)+col, not a lookup table
│   └── logo 99 lights but has NO button — nothing may bind to it
■ Colour indices in use recorded — DONE 2026-08-12, 8/8 confirmed by eye
│   └── 0 off · 5 red · 13 yellow · 19 green · 21 bright green · 23 dim green
│       · 37 cyan · 45 blue. All match the Mini MK3 candidate table
│   └── the other 120 stay candidates; palette_coverage.py fails the build if a
│       config ever starts depending on one of them
■ Release semantics confirmed (note-on vel 0)                   ← DONE, manual p.6
■ Batch LED write                                               ← DONE, 81 entries/msg, p.15
□ Port list recorded — exact Windows name strings for both interfaces
■ EVO 8 endpoint names recorded — DONE 2026-08-12, all 13 + the device node
│   └── manual's 'EVO 8 Main Output 1+2' and 'Loop-back 1+2' DO NOT EXIST
│   └── real: 'Main Output 1/2 (Audient EVO8)' — slash not plus, EVO8 not EVO 8
■ Presence signal decided: hardware id VID_2708&PID_0007, not a friendly name
│   └── two endpoints share the name 'Loop-back 1/2 (Audient EVO8)'
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

**STATUS: BUILT AND GREEN.** `rig/{state,controller,events,commands,exceptions}.py`,
`storage/{config_loader,runtime_state}.py`, `config/rig.yaml`, `main.py`. Covered by
`tests/test_{state,controller,events,commands,config_loader,runtime_state}.py`.
Exit test met: illegal transitions rejected, config fails loudly with every problem at
once, controller ticks without drifting, Ctrl+C exits clean.

**Risk: Low.** Pure Python, fully testable with no hardware attached.

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
■ Connects, and re-runs the full init on every reconnect — PASS 2026-08-13
│   └── 13 recorded cycles, all four forgotten settings re-asserted every time
■ Restores Live mode in a finally block — PROVEN on hardware 2026-08-12 through an
│   unhandled exception; the mode was read back off the device afterwards
■ Survives unplug/replug with no restart — PASS 2026-08-13, ~20 physical replugs
│   └── found a real bug: a lost device logged "COULD NOT RESTORE LIVE MODE" once
│       per unplug, false twice over. tools/results/phase3-replug-test.txt
◐ Pad press → named action — built (ActionRequested) and tested off-rig; NOT yet
│   observed end-to-end on hardware
■ Renderer is separate from device I/O — pure by construction, launchpad/renderer.py
■ Renderer emits one batched SysEx — 81 specs per frame, measured on hardware
□ Folder-scanner animation runs without blocking the event loop
□ Animation can be cancelled mid-run
```

**STATUS: BUILT AND WIRED. The rig boots and drives a surface.**

```text
ports.py         name -> USB interface. Pure.                    DONE 2026-08-12
device.py        open, Programmer Mode, IO, RESTORE              DONE 2026-08-12
backend_mido.py  the only module importing mido                  DONE 2026-08-12
renderer.py      state + animation + presses -> 81 LedSpecs      DONE 2026-08-12
modes.py         RigState -> which surface                       DONE 2026-08-12
service.py       owns the connection, survives losing it         DONE 2026-08-13
surface.py       the bridge: modes, animations, hold-to-confirm  DONE 2026-08-13
main.py          wired; controller gained on_tick hooks          DONE 2026-08-13
```

`python main.py` loads the library, refuses to start if any RigState lacks a surface,
arms the boot intro, and ticks at 30 Hz. With no device attached it logs the loss once
and keeps running — verified off-rig.

**PROVEN ON HARDWARE 2026-08-12:** connect, identify (firmware 0351), Programmer Mode,
a full-surface paint, and — through an unplanned crash — restore-to-Live-mode holding
after an unhandled exception, confirmed by reading the mode back off the device.

**PROVEN ON HARDWARE 2026-08-13:** the reconnect path. ~20 physical replugs, 13
recorded cycles, every one re-asserting all four settings. Still owed: a press
observed as a named action end-to-end, and an animation cancelled mid-run.

**Risk: Medium.** The reconnect + SysEx path is the single most common way this rig dies on
stage. Test it 20 times, not twice.

> Off-rig head start, 2026-08-09: `launchpad/animations.py` — the pure frame engine — is
> ported from `viz/lab/anim.js` and verified bit-for-bit against 240 golden frames dumped
> from the real Lab engine (`tools/dump_golden_frames.mjs`, `tests/test_animations_golden.py`).
> `launchpad/player.py` covers the two animation checkboxes' LOGIC: pull-model frame(now)
> per tick (non-blocking by construction), cancel mid-run, any-press intro skip, 15 s
> failsafe. `launchpad/mappings.py` ports the Config Lab contract (viz/lab/schema.js):
> the committed configs/ and animations/ load into typed ModeConfig objects — shape
> errors hard-fail listing every file, dangling refs warn and load, hold_ms defaults
> (2 s load / 4 s reboot / 6 s shutdown) fill from the catalogue. What remains hardware:
> everything touching a port, and the renderer that composites player frames under/over
> a mode screen. Regenerate goldens after any edit to the Lab engine; port any schema.js
> change into mappings.py — the pairing is pinned by schemaVersion.

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
■ Finds .als files, ignores backup/autosave/project-info         ← DONE 2026-08-09
■ sets.yaml metadata (name, colour, category) overrides defaults ← DONE 2026-08-09 (colour stays a NAME — palette indices are Phase 1 truth)
■ Unknown files still appear, in a neutral colour                ← DONE 2026-08-09
■ Pagination works past 48 sets                                  ← DONE 2026-08-09 (48/page is an UNVERIFIED design constant pending Start_DOCS)
■ Empty folder shows an error state, does not crash              ← LOGIC DONE 2026-08-09 (`is_empty` exposed; the Error Mode *display* is Phase 3)
■ Rescan works without restarting the controller                 ← DONE 2026-08-09 (same service object; preserves page, clamps when sets vanish)
```

**STATUS: BUILT AND GREEN.** `set_browser/{scanner,models,metadata,pagination,service}.py`,
covered by `tests/test_{scanner,metadata,pagination,set_browser_service}.py`.

**Risk: Low.**

> Built off-rig 2026-08-09, out of phase order because Phase 3 is hardware-blocked. The
> controller wiring (pads → page turns → selection) is Phase 3 work and remains open.

---

## Boot completion — the definition, and its limits

Specified 2026-08-13 by the person who has to play through it:

> "Boot complete means Ableton is up and running smoothly, connected to EVO sound,
> with no complications — otherwise the error screen on the Launchpad."

That is stricter than "the process exists", and it decomposes into checks of very
different confidence. `rig/boot.py` keeps that difference visible rather than
averaging it into a boolean.

| Check | Confidence | How |
|---|---|---|
| Launchpad connected | CERTAIN | the service says so |
| EVO 8 enumerated | CERTAIN | `VID_2708` on the USB bus |
| Ableton process alive | CERTAIN | psutil |
| Ableton bound to the EVO | **STRONG** | it has `audientusbaudioasio_x64.dll` loaded — it opened *that* driver, not another |
| Set finished loading | **GUESS** | a settle timer. `ableton/readiness.py` calls it `ASSUMED_READY` on purpose |

### What this gate can never prove

**That audio is reaching the mixer.** There is no software answer. An ESD-wedged EVO
enumerates perfectly, loads its driver, and outputs silence — its own manual says so
(`docs/audient-evo-8-reference.md` §6). Ableton looks healthy throughout.

So BOOT_COMPLETE means *"as ready as software can tell"*. The only real detector for
silence is a human with ears, or a loopback measurement nobody has built. There is a
test asserting no check claims otherwise, so this cannot be quietly "improved" into a
lie later.

**Failure names the check.** On a screenless rig, "EVO 8 missing" versus "Ableton not
running" is the difference between checking a cable and checking a set. A generic red
screen would waste the only minutes that matter.

**A timeout is mandatory.** A rig sitting on the splash screen forever is
indistinguishable, on a screenless machine, from one that has crashed.

### Still to wire

`rig/boot.py` is pure policy with injected probes, tested off-rig. The probes
themselves — psutil, PnP enumeration, module inspection — are Windows-specific and
belong with the Phase 6 `windows/` package, which does not exist yet.

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
◪ Refuses to launch if the EVO 8 is absent      ← LOGIC DONE 2026-08-09 against a fake detector; the REAL PnP detector needs Phase 1 names
◪ Refuses to launch if the .als is missing      ← LOGIC DONE 2026-08-09 (all failing preconditions reported together)
□ Hold-to-confirm (2s) gates every set load       (controller/mode wiring — Phase 3+)
◪ Graceful close attempted before kill          ← LOGIC DONE 2026-08-09; Windows terminate() behaviour UNVERIFIED until bench
◪ Crash detected and one restart attempted      ← LOGIC DONE 2026-08-09 (supervisor poll, events on the bus)
◪ Restart attempts capped — no infinite loop    ← LOGIC DONE 2026-08-09 (budget refills only after a stable_s run)
□ Stable/Candidate deployment folders in use, sets treated read-only
```

◪ = policy built+tested off-rig with fakes; the psutil adapter (`ableton/process.py`)
is the ONLY unverified seam and gets one bench session on the Beelink.

**STATUS: BUILT, TESTED, AND NOW WIRED.** `ableton/{launcher,process,readiness,recovery,supervisor}.py`,
covered by `tests/test_{ableton,supervisor}.py`.

Wired into `main.py` 2026-08-13: the boot sequence launches `ableton.boot_set` once,
the supervisor polls every tick, and `AbletonGaveUp` drives the rig into Error Mode.
`windows/audio.py` supplies the audio-presence precondition from the registry probe.

**Blocked on content, not code: `ableton.boot_set` is empty because no `.als` exists
yet.** `Sets/Emergency/` is the intended home — one known-good file that always
loads, so the rig reaches a usable state before anyone picks a real set. Until it
exists the rig declines to launch Ableton, says so once, and lets the boot gate fail
in its own words. That is the honest behaviour, and it is not the finished one.

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
■ OpenSSH Server installed — DONE 2026-08-12, key auth PROVEN from matts-mac-mini
│   └── Tailscale 100.70.171.124 (host 'rig'), user rigma, host key verified out-of-band
□ Password auth disabled (deferred until key login proven — it now is, so this is next)
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
■ Power plan — DONE 2026-08-12. High performance scheme, min AND max processor
│   state 100%, no sleep/hibernate/display/disk timeout, USB selective suspend off
│   └── was Balanced with min processor state 5% — cores downclocking between
│       audio buffers, the classic dropout cause on Intel N-series
│   └── scheme changes do NOT carry settings over; re-apply if the scheme changes
■ Defender exclusions + startup trimming — DONE 2026-08-12
│   └── excluded C:\LiveRig, C:\ProgramData\Ableton, VST3, and the Ableton process.
│       Real-time monitoring deliberately left ON everywhere else
│   └── PresentMonSharedService and IntelGraphicsSoftwareService disabled
│   └── Intel Graphics Run entry removed, backed up to
│       HKLM\SOFTWARE\ablepad-disabled-startup
│   └── tools/results/phase7-hardening.txt
■ OneDrive + Edge autolaunch disabled — DONE 2026-08-12. Run entries removed and
│   backed up, six OneDrive scheduled tasks disabled. HKCU Run key now empty.
│   Placeholder audit taken first: 1 of 329 files was cloud-only, and it was the
│   OneDrive welcome PDF — nothing was stranded
■ Documents un-redirected out of OneDrive — DONE 2026-08-12. Ableton, Max 9 and
│   namirs moved to C:\Users\rigma\Documents; shell folder repointed
│   └── Ableton's Library.cfg has <UserLibrary /> empty, i.e. default, which now
│       resolves to the new path — no re-pointing expected. Confirm on next launch
□ Desktop and Pictures are still redirected into OneDrive. Decide whether they
│   matter for a rig (nothing rig-critical lives in either today)
□ Confirm which namirs path the NAM/Gateway plugin actually loads from —
│   C:\LiveRig\namirs is the copy that should win
□ Notifications, update reboots, remaining startup apps disabled
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
- **The controller MUST run in the logged-on user's session.** RESOLVED 2026-08-13, and the
  single most expensive lesson of that session. A controller started over SSH runs in Windows
  **session 0**, the non-interactive services session, and every process it spawns inherits
  that. Ableton then runs with no desktop and no access to the user's audio endpoints: alive,
  `Responding: True`, ZERO top-level windows, Audient ASIO DLL never mapped, silent. The boot
  gate correctly failed to ERROR after 90 s, which is the gate working, not a bug.

  This is why the rig is launched by scheduled task `ablepad-rig`, registered `/it`
  (interactive only) `/rl highest`, running `C:\LiveRig\Controller\run-rig.bat`. Same shape
  Phase 7 needs anyway. **Never start the controller from an SSH shell** — it looks like it
  works, and produces a rig that makes no sound.

  Corrects an earlier entry that blamed a force-kill for the wedge: the zero-window symptom
  was session isolation, and a clean reboot reproduced it with no kill involved.

  `/rl highest` matters for a second reason: both elevated means the controller can post
  `WM_CLOSE` to Live. An unelevated process closing an elevated Live gets `Access is denied`
  (UIPI).

- **Live's recovery dialog will block a headless boot unless it is cleared.** RESOLVED
  2026-08-13. `%APPDATA%\Ableton\Live <ver>\Preferences\CrashRecoveryInfo.cfg` plus `Undo\`
  is the trigger; `Preferences\Crash\<stamp>_*` is only an ARCHIVE that Live copies out of
  the root at startup. Sweeping the archive alone changes nothing — verified the hard way.
  `ableton/crash_recovery.py` moves both aside before launch (moves, never deletes: the
  trigger is someone's unsaved session). After the fix: 5 entries swept, no dialog,
  `ableton_audio` bound in 4 s, boot complete. Before it: 90 s timeout, every time.

- **RESOLVED 2026-08-13 — the settle timer is no longer a guess.** `boot_settle_s`
  was a wall-clock guess covering the slowest imaginable set on every boot. The
  Ablepad Remote Script now writes a handshake when a set finishes loading, and the
  gate reads it: **boot went 25 s → 8.0 s**, and the log states which path it took.

  `boot_floor_s` (8 s) is what remains of the caution, and it is measured rather
  than felt: the signal fires at 4.61 s but Live's window does not exist until
  6.25 s, so the signal is optimistic by ~1.6 s and the floor covers the last
  objective marker plus margin. A floor below 6.25 s completes boot before Live has
  a UI, which 5 s was doing.

  Verified by ear: a note played the instant the Launchpad entered Set Browser spoke
  cleanly. That is the only test that proves it — every software marker is a proxy
  and none can distinguish silence from sound. `tools/measure_load.py` reproduces
  the timings.

- **The readiness Remote Script lives inside the Live installation, so Live updates
  delete it.** MEASURED 2026-08-13 on Live 12.4.3: only
  `C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\` is listed in
  the Control Surface dropdown. Both user-scoped locations that every guide
  recommends — `Preferences\User Remote Scripts\` and `<User Library>\Remote Scripts\`
  — are ignored, and Live logs NOTHING while scanning, so a misplaced script is
  completely silent. Established by installing three differently-named copies and
  seeing which appeared.

  Degrades safely: with no signal the boot gate waits out `boot_settle_s` exactly as
  before, and `main.py` logs that the signal never arrived. Slower, not broken.
  **Re-run `tools/install-remote-script.ps1` after every Live update.** The symptom
  is a boot that suddenly takes the full settle time again.

- **`psutil.terminate()` is not graceful on Windows.** It is `TerminateProcess`, the same
  syscall as `kill()`. `terminate_gracefully()` was therefore a hard kill wearing a polite
  name, and since `SetBrowserControl` stops Live before every set change, every ordinary set
  switch armed the recovery dialog for the next boot. Now posts `WM_CLOSE` via `taskkill`
  without `/F`. Remaining risk: a set with unsaved changes raises Live's "save changes?"
  prompt, which nothing headless can answer — that run burns the 10 s timeout and is then
  killed, i.e. no worse than before. Performance sets are not edited; timeouts in the log
  mean something is modifying sets at runtime, and that is the bug to chase.
