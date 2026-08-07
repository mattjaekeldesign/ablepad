# ablepad — Beelink Headless Ableton Rig

Control software for a dedicated Beelink performance computer that behaves like a hardware
guitar processor. The Launchpad is the operating system interface.

**Status:** Phase 0/1. Zero lines of application code. Design is documented; hardware truth is
mostly unverified. See `docs/ROADMAP.md` — it is the build order and it is authoritative.

---

## 1. The goal

The finished rig requires **no monitor, no keyboard, no mouse, no internet**.

```text
Rig
│
├── Beelink Mini PC (Windows)
├── Novation Launchpad X          ← the entire user interface
├── Focusrite Scarlett (temporary — a permanent interface replaces it later)
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
Focusrite Scarlett
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
□ Scarlett detected
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

Unrelated project, easy to confuse: `/Users/matt/Documents/Projects/ableton-pedal` is a
*different* build — Launchpad Mini **MK3**, MOTU M2, NANUK case, CAD-focused. Different device
ID (`0x0D` not `0x0C`), different interface, different enclosure. Do not cross-cite its
dimensions or SysEx into this project.
