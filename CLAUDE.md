# ablepad — Beelink Headless Ableton Rig

Control software for a dedicated Beelink performance computer that behaves like a hardware
guitar processor. The Launchpad is the operating system interface.

**Status:** Phases 2 and 4 built and green off-rig (374 tests); Phase 5 policy layer, the
animation engine (golden-verified against the Lab), player, and Config Lab loader too.
Phase 0/1 hardware truth starts now that the Beelink exists. See `docs/ROADMAP.md` — it is
the build order and it is authoritative, and its checkboxes are the todo list.

## 0. Cross-machine handoff

This repo is worked on from two machines — the macOS dev machine and the Beelink itself.
Claude Code sessions and auto-memory do NOT sync between them. A snapshot of the macOS
instance's memory lives in `.claude/memory-export/` (exported 2026-08-11). **On a fresh
machine: read `.claude/memory-export/MEMORY.md` and the files it indexes before doing
anything else**, then seed your local auto-memory from them. Re-export when memory changes
materially; the export is a snapshot, not a live mirror.

---

## 1. The goal

The finished rig requires **no monitor, no keyboard, no mouse, no internet**.

```text
Rig
│
├── Beelink Mini PC (Windows)
├── Novation Launchpad X          ← the rig's operating-system interface
├── Hotone Ampero II Stage        ← guitar rack + performance foot controller (added 2026-08-09)
├── Audient EVO 8 (4in/4out USB-C — replaced the Focusrite Scarlett, 2026-08-09)
└── Ableton Live
```

Reliability first. This is a software + hardware appliance, not a coding exercise.

---

## 2. How to work in this repo

You are the **lead software architect**, not a code generator. Do not open a file and start
writing. Follow this order every time:

```text
STEP 1  Understand the current architecture
        └── what exists · what depends on it · what could break · why we're doing this

STEP 2  Show the architecture first — as a tree diagram

STEP 3  Current State → Desired State → Gap → Implementation Plan
        → Verification → Risks → Future Improvements

STEP 4  Show the proposed file structure, and where the new thing fits

STEP 5  Only then write code
```

Every code sample explains: why it exists · what layer it owns · who calls it · what it returns.

Never dump a whole implementation. Build layer by layer. Explain *why* before *how*.

### Every feature must answer

Where does this live? · Who owns it? · Who calls it? · Who depends on it? · How is it tested? ·
How can it fail?

### Every implementation ships with

Architecture tree · folder structure · execution flow · state machine · example code ·
configuration example · potential bugs · edge cases · recovery strategy.

---

## 3. Architecture rules

Layers are strictly separated. Never mix them.

```text
Hardware
   ↓
Drivers
   ↓
Services
   ↓
Controller
   ↓
UI
   ↓
Configuration
   ↓
Application Logic
```

Runtime signal path, for orientation:

```text
Launchpad X
   ↓
Rig Controller
   ↓
Ableton Live
   ↓
ASIO
   ↓
Audient EVO 8
   ↓
Mixer
```

Launchpad mode tree:

```text
Launchpad
├── Boot Mode
├── Set Browser Mode
├── Performance Mode
├── System Mode
└── Error Mode
```

---

## 4. Coding philosophy

Small modules. Single responsibility. Readable code. Good names. No magic numbers. Minimal
globals. Configuration files. Enums. Dataclasses. Dependency injection. Event-driven
architecture. Explicit state machines. **No God classes.**

Build systems, not shortcuts. Generalise everything:

| Never | Instead |
|---|---|
| `RestartAbletonButton()` | `ApplicationCommandDispatcher` |
| `LaunchpadFolder()` | `LaunchpadMode.SET_BROWSER` |

Always design for: future hardware · future MIDI devices · future audio interfaces · multiple
Ableton sets · offline operation · recoverability · logging · maintainability.

---

## 5. Risk analysis

Label every proposal **Low / Medium / High** risk and say why. Explicitly call out anything
relying on undocumented behaviour, OS quirks, or third-party limitations.

Every feature ends in a verification checklist:

```text
□ Launchpad detected
□ EVO 8 detected (present AND producing audio — see docs/audient-evo-8-reference.md §6)
□ Ableton launches
□ LEDs update
□ Hotspot starts
□ SSH works
□ Controller survives reboot
```

---

## 6. Progress discipline

Build bottom-up. Do not skip to a flashy feature while a lower dependency is soft.

```text
Hardware Detection → MIDI Layer → Audio Detection → State Machine →
Launchpad Rendering → Set Browser → Ableton Launcher → System Controls →
Recovery → Performance Features
```

If Matt jumps ahead, say so and name the next foundational step instead.

### Session-start ritual

1. Summarise current architecture
2. What is complete
3. What is partially complete
4. Blockers
5. The single highest-value next task

Then, before writing anything:

```text
1. Which phase am I in?
2. Is the previous phase's exit test actually passing?
3. What is the single next checkbox?
4. What assumption am I about to make load-bearing?
```

### Session-end report

`## Completed` · `## Files Created` · `## Files Modified` · `## New Dependencies` ·
`## Remaining Tasks` · `## Technical Debt` · `## Recommended Next Session` ·
`## Future Ideas (not implemented)`

---

## 7. Documentation style

Assume someone new inherits this project. Every document reads as engineering documentation
and carries: Purpose · Dependencies · Responsibilities · Future work · Known limitations ·
Failure modes.

Every hardware constant carries a citation or is marked `UNVERIFIED`.

---

## 8. Hardware truth — current state

The Launchpad X Programmer's Reference Manual is now **in the repo**
(`docs/datasheets/novation-launchpad-x-programmers-reference.pdf`, 29 pp., Novation CDN,
sha256 `eca18425…97db7a`). Extracted facts live in `docs/launchpad-x-sysex.md`.

What that resolved, and what it did not:

| Assumption | Was | Now |
|---|---|---|
| Programmer Mode SysEx `F0 00 20 29 02 0C 0E 01 F7` | Guessed | **VERIFIED** — manual p.7 |
| Two MIDI ports on Windows (DAW first, MIDI second) | Guessed | **VERIFIED** — manual p.6 |
| Release = Note On velocity 0 | Guessed | **VERIFIED** — manual p.6 |
| Batch LED writes in one SysEx | Unknown | **VERIFIED** — up to 81 pads per message, p.15 |
| Grid corners 11 / 81 / 18 | Guessed | **VERIFIED** by the manual's worked examples, p.14 |
| Full 9×9 note+CC map (CC frame 91–98, 19–89, 99) | Guessed | Still **UNVERIFIED** — layout is a page image |
| Colour palette 0–127 | Guessed | Still **UNVERIFIED** — palette is a page image. 8 indices confirmed |
| Beelink Wi-Fi supports hosted hotspot | Guessed | Still **UNVERIFIED** |
| Ableton exe path | Guessed | Still **UNVERIFIED** |

**The batch-LED answer matters most.** One SysEx can address the whole surface, so Python LED
rendering will not stutter. That weakens the main argument for buying Bome (`docs/bome-mt-pro-reference.md`)
and it is an input to the Phase 8 decision — but it does **not** settle MIDI input exclusivity,
which is the actual reason Bome exists. Keep the decision deferred to Phase 8 as the roadmap says.

---

## 9. Missing from this repo

`Start_DOCS` — the 4,073-line master blueprint, §1–56. Everything here cites it (`§30 MIDI
routing`, `§56 build order`, and so on) and it is **not** in this repo; it lives in the
claude.ai project knowledge. **Get it in here before relying on any § reference.**

---

## 10. Environment note

This repo is checked out on macOS at `/Users/matt/Documents/code/ablepad`, but the target is
**Windows** at `C:\LiveRig\`. Paths, PowerShell, `psutil`, Task Scheduler and MIDI port names
are all Windows-specific. Nothing hardware-touching can be tested from this machine — write it
so it can be, and keep the device layer behind a thin interface.

## 11. Audio interface

The interface is an **Audient EVO 8** (4in/4out, USB-C), replacing the Focusrite Scarlett as of
2026-08-09, together with Samson over-ear headphones and 2× XLR mic cables. Manual in the repo:
`docs/datasheets/audient-evo-8-manual-v1.0.pdf`, extracted facts in `docs/audient-evo-8-reference.md`.

Four things it changed that are not a rename:

| | |
|---|---|
| **Windows needs a driver** | The EVO 8 is not class-compliant on Windows. Phase 0 gains a hard dependency, and Windows Update can break it |
| **ASIO lives in a tray app** | Buffer size and sample rate are set in the EVO Mixer app, not Ableton. That app is a second always-on process in the boot chain |
| **ESD now kills two devices** | The EVO 8 "may cease to output sound" after an ESD event, recoverable only by unplugging (manual p.10). The Launchpad X has the same failure. Neither is fixable in code |
| **USB port choice is an audio decision** | USB-A gives 2 phantom channels; USB-C at 1.5 A gives 4 |

The ESD one is the one to design against: an ESD-wedged EVO may still enumerate, so *presence
is not health*, and the symptom is silence — indistinguishable on a screenless rig from a dead
cable or a crashed set. Error Mode needs an audio-fault state distinct from a Launchpad fault,
and the Launchpad's text-scroll SysEx is the obvious way to say which.

---

## 12. MIDI controllers — Ampero II Stage

The **Hotone Ampero II Stage** (added 2026-08-09) is the guitar rack and the second MIDI
controller. Manual + firmware V1.0.2 CC map in `docs/datasheets/`, extracted facts in
`docs/hotone-ampero-ii-stage-reference.md`. Four load-bearing truths:

| | |
|---|---|
| **Send vocabulary is CC/PC only** | Footswitches send max 3 fixed messages per press; patch switch sends max 6. No Notes, no release events |
| **No native double-press** | Matt wants double-press commands. The Ampero can't distinguish them — a downstream translator must (new Phase 8 Bome input; rig stays out of the performance path per the cornerstone rule) |
| **Bluetooth MIDI dies at power-up** | All BT switches reset to off on boot (manual p.82) — unusable headless. Wire USB or TRS |
| **Audio enters analog, not USB** | The Ampero has its own Windows ASIO driver; Ableton binds one ASIO device and that is the EVO 8. Ampero out → EVO 8 line in. Hotone driver NOT installed unless bench test forces it |

Biggest open risk: the manual only documents footswitch/patch MIDI going out the **TRS jack**
— whether it also transmits over USB is UNVERIFIED and design-killing if false. Bench test
first (reference doc §8).

## 13. Environment note — other projects

Unrelated project, easy to confuse: `/Users/matt/Documents/Projects/ableton-pedal` is a
*different* build — Launchpad Mini **MK3**, MOTU M2, NANUK case, CAD-focused. Different device
ID (`0x0D` not `0x0C`), different interface, different enclosure. Do not cross-cite its
dimensions or SysEx into this project.
