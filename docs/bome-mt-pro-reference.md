# Bome MIDI Translator Pro — Reference for the Beelink Rig

**Status: evaluation only. Not purchased, not adopted.** The decision lands in Phase 8. Read
`ROADMAP.md` §1 before acting on anything here.

Source: *Bome MIDI Translator Pro User Manual*, rev. 2025-12-19 (Bome Software GmbH & Co. KG),
chapters 1–9.11 read directly. Chapters 10 (Rules & Variables), 11 (Settings), 13.7 (Performance
Optimization) and 16.3 (Command Line Switches) did not extract — details below marked
**[UNVERIFIED]** came from Bome's published version history and forum, not the manual. Confirm
them in the PDF before building on them.

Version assumed: **MT Pro 1.9.2 or later** (Perform Action, Timer parameters, Variable Storage
all require 1.9.1/1.9.2+).

---

## 1. The single most important fact for this rig

> **On Windows, a MIDI INPUT port can only be opened by one program at a time.**

The manual states this indirectly, via the *MIDI Port Open Error* incoming action: it fires when
a port exists and is plugged in but MT Pro cannot open it, and the main cause on Windows is that
another program already holds that MIDI INPUT.

**Consequence for §30 of the blueprint:** if the Rig Controller (Python/mido) opens the Launchpad
input, Ableton cannot. If Ableton opens it, Python cannot.

Strategy A ("separate MIDI ports") requires the Launchpad X to expose two independent input ports
on Windows. **It does** — `LPX DAW In` and `LPX MIDI In`, confirmed in the Programmer's Reference
(see `launchpad-x-sysex.md` §2). So Strategy A is not dead on arrival the way this document
originally assumed. What it still cannot do is let both programs observe the *same* pad press.

Bome resolves that properly. It becomes the **single owner of the Launchpad's MIDI input**, and
fans messages out from there:

```text
Launchpad X (hardware)
   │  USB MIDI IN  ← opened by Bome ONLY
   ▼
Bome MIDI Translator
   │
   ├── System pads      → Execute File / Perform → Rig Controller scripts
   ├── Performance pads → Bome Virtual Port 1 → Ableton
   └── LED feedback     → Launchpad MIDI OUT
```

This is Strategy B from §30, but without writing a router in Python. It is the main reason to
introduce Bome at all.

---

## 2. What Bome should own vs. what stays in Python

Bome is not a replacement for the Rig Controller. It is bad at exactly the things Python is good
at, and vice versa. Split it this way:

| Concern | Owner | Why |
|---|---|---|
| Launchpad MIDI in/out, routing | **Bome** | Solves the port-exclusivity problem; near-realtime engine |
| Programmer Mode SysEx on connect/reconnect | **Bome** | Has a native "port plugged in" trigger; no polling |
| Mode switching (Boot / Browser / Performance / System) | **Bome** | Presets map 1:1 onto modes |
| Hold-to-confirm timing | **Bome** | Timers are non-blocking and killable |
| LED animations | **Contested** | See note below — batch SysEx changed this |
| Keystrokes / mouse into Ableton | **Bome** | Windows-only injection targets a window without focusing it |
| **Focusrite detection** | **Python** | Bome only sees MIDI devices. The Scarlett is a MEDIA-class audio device — invisible to Bome |
| Ableton process supervision & crash recovery | **Python** | `psutil`, restart limits, state machine |
| `.als` folder scanning | **Python** | Bome cannot enumerate a directory |
| Hotspot, SSH, reboot/shutdown | **Python** | PowerShell wrappers already designed |
| Logging, health metrics | **Python** | Bome's Log Window is a live-performance CPU risk (see §9) |

> **LED animations — revised 2026-08-07.** This document originally gave animations to Bome
> because 64 individual note-ons from Python would stutter. The Programmer's Reference confirms
> one SysEx can light all 81 LEDs at once. Python animation is now viable and keeps rendering in
> the layer that owns application state. Do not hand this to Bome by default.

The bridge in both directions is described in §8.

---

## 3. Core object model

Three levels, and the mapping onto the rig is almost exact:

```text
Project (.bmtp)            → the whole rig control surface, one file
├── Default MIDI in/out ports and aliases
├── MIDI Router (thru connections)
└── Presets                → ONE PRESET PER LAUNCHPAD MODE
    ├── "00 Always Active" → panic mute, mode-exit combo
    ├── "10 Boot"
    ├── "20 Set Browser"
    ├── "30 Performance"
    ├── "40 System"
    └── "50 Error"
        └── Translators    → one incoming trigger → optional rules → one outgoing action
```

Key behaviours:

- An incoming event is offered to every translator in every **active** preset, in list order.
- A translator with **Stop Processing** set halts that event's journey once it fires. Essential
  for first-match-wins, and the documented way to keep large projects fast.
- A translator has exactly **one** incoming and **one** outgoing action. To fan one pad press out
  to several actions, use a Perform Action (§6).
- Presets can be activated/deactivated by outgoing actions, and there is a *"deactivate all other
  presets (except always active)"* checkbox — precisely the mode-switch primitive §14 needs.
- Mark the panic/system preset **Always Active** so it is skipped by next/previous cycling and
  never accidentally switched off.

Numbering the presets (`00`, `10`, `20`…) matters because "Preset By Number" is zero-indexed and
you will want stable indices if you drive mode changes from a variable.

---

## 4. Ports and aliases — set these up first

Never reference a raw Windows device name. Create aliases and point translators at those, so the
project survives a USB re-enumeration or a Launchpad swap:

```text
ALIASES TO CREATE
├── LP_IN        → Launchpad X MIDI (input)      ← the SECOND interface, not the DAW one
├── LP_OUT       → Launchpad X MIDI (output)
└── TO_ABLETON   → Bome Virtual Port 1 (output)
```

Set MIDI ports at **Preset level**, not per-translator — the manual recommends this explicitly
and it saves a lot of editing later.

**Virtual ports:** installed as an option during setup (choose Custom install). They are
*unidirectional*, and one end must always be MT Pro — you cannot use a Bome virtual port to
connect two other applications to each other. Bome's port passes through the Windows API once
rather than twice, which is why they claim lower latency/jitter than loopback drivers.

In Ableton, `TO_ABLETON` becomes a control-surface or MIDI input. Ableton never touches the real
Launchpad port at all — which is what you want, since the Launchpad is in Programmer Mode and is
not speaking Live's control-surface protocol anyway.

**Dynamic reassignment:** the outgoing MIDI Port action can assign/unassign an alias at runtime,
or restart a port (close + reopen after a few seconds). The manual notes port restart as a
workaround for wedged devices/drivers — worth wiring to a System Mode pad given the ESD failure
mode.

---

## 5. Hardware detection — MIDI only

The incoming **MIDI Port** action has five types:

| Type | Fires when |
|---|---|
| Plugged In | Device appears / virtual port created |
| Unplugged | Device removed / virtual port destroyed |
| Opened | MT Pro successfully opened it (only if it's used in the project) |
| Got Closed | No longer used in the project, or unplugged |
| Open Error | Present and plugged in, but MT Pro could not open it — usually another app holds it |

This gives Launchpad reconnect handling for free, including the mandatory SysEx re-send:

```text
Translator: "Launchpad opened → Programmer Mode"
  Incoming:  MIDI Port — LP_IN — Port is Opened
  Outgoing:  MIDI (raw)  F0 00 20 29 02 0C 0E 01 F7
  Delay:     100 ms
```

**These bytes are now VERIFIED** against the Programmer's Reference (p.7). Note the raw hex
includes the `F0`/`F7` framing, unlike mido's `data=` list.

The 100 ms delay is still a guess — see `launchpad-x-sysex.md` §12 item 4.

```text
Translator: "Launchpad unplugged → tell the Rig Controller"
  Incoming:  MIDI Port — LP_IN — Port is Unplugged
  Outgoing:  Execute File  C:\LiveRig\Controller\commands\lp-lost.cmd
```

**A pending port — used in the project but not currently plugged in — does not fire "Opened".**
So boot ordering is safe: Bome can start before the Launchpad is enumerated and still catch it.

**The Focusrite is invisible here.** It is an audio device, not a MIDI device. Keep
`AudioInterfaceDetector` and its `Get-PnpDevice` PowerShell query in Python exactly as designed.

> **Unresolved, and it matters.** If Bome owns the port and Bome crashes, nothing restores Live
> mode on the Launchpad — the Setup menu stays disabled and the panel is unreachable on a
> headless rig. Python at least has `finally`. Whatever Bome's shutdown story is, verify it
> before Phase 8, because this is the one failure that has no physical recovery short of a
> power cycle.

---

## 6. Timers and Perform — the two mechanisms you'll use most

### Timer = hold-to-confirm, without blocking

Blueprint §23 requires a 2-second hold that does not block the event loop. Bome does this
natively:

```text
Translator 1: "Set pad DOWN — arm hold"
  Incoming:  MIDI  90 pp 7F           // note on, any pad, full velocity
  Rules:     gs=pp                    // remember which pad
  Outgoing:  Timer "ConfirmLoad" — Activate, Once, Initial Duration 2000 ms

Translator 2: "Set pad UP — cancel hold"
  Incoming:  MIDI  90 pp 00           // VERIFIED: LP X sends note-on vel 0 on release
  Outgoing:  Timer "ConfirmLoad" — Kill

Translator 3: "Hold completed — load the set"
  Incoming:  Timer "ConfirmLoad"
  Rules:     gn=gs-80                 // top row 81..88 → 1..8; verify the note map first
  Outgoing:  Execute File  C:\LiveRig\Controller\commands\load-set.cmd
             Parameters:  "%d gn%"
```

Two rules that matter here:

- **Timers are always retriggering.** Starting a running timer resets its wait and its counter.
- **Do not use the outgoing-action Delay field for this.** A delayed action cannot be cancelled
  once triggered, and a delayed *timer* does not exist yet — so you cannot kill it during the
  delay window. Always put the wait in the timer's Initial Duration instead. The manual is
  explicit about this.

Note the velocity in translator 1: `90 pp 7F` only matches full velocity. If velocity curve is
left on a sensitive setting, a soft press sends something else and the translator never fires.
Set fixed velocity by SysEx (`launchpad-x-sysex.md` §8) or match `90 pp vv` with a rule.

### Timer = LED animation

A repeating timer with a counter variable drives the §22 folder-scanner animation:

```text
Translator: "Start scanner"
  Incoming:  Perform "EnterBrowser"
  Outgoing:  Timer "Scan" — Activate, Multiple Times,
             Repeat Count 16, Initial Duration 0, Repeat Duration 70 ms

Translator: "Scanner frame"
  Incoming:  Timer "Scan", Counter variable → qq
  Rules:     [compute active column from qq]     // operator set UNVERIFIED, see §10 of manual
  Outgoing:  MIDI (raw) — concatenated note-on messages for the column
```

Timers take up to **10 parameters** (comma-separated variables or numbers) passed to the incoming
trigger, plus the counter variable. Parameters are evaluated **once**, when the timer starts — a
global that changes mid-run still reports its original value to every invocation.

### Perform = named internal event, immediate

Perform is the modern replacement for the old 0 ms one-shot timer trick. One outgoing Perform
triggers every translator listening for that name, immediately, with up to 10 parameters passed
by value. Unlike timers it never retriggers — one call, one event.

This is how you get multiple actions from a single pad press, given the one-outgoing-action
limit:

```text
Translator A:  Incoming: MIDI (browser pad)      Outgoing: Perform "EnterBrowser"
Translator B:  Incoming: Perform "EnterBrowser"  Outgoing: Preset — activate "20 Set Browser",
                                                  deactivate all others except always-active
Translator C:  Incoming: Perform "EnterBrowser"  Outgoing: Timer "Scan" — Activate
Translator D:  Incoming: Perform "EnterBrowser"  Outgoing: Execute File → log-mode-change.cmd
```

**Beware infinite loops.** If a Perform-triggered translator emits the same Perform name, the
engine will spin forever — the manual states it does not detect this.

---

## 7. Controlling Ableton and Windows

### Execute File — launching sets

Starts a program with parameters, or opens a document with its associated app. Variables embed
via a `printf`-like scheme: `%pp%` or `%d pp%` decimal, `%x pp%`/`%X pp%` hex, `%c pp%` as an
ASCII character, with width/zero-padding (`%02d g0%` → `07`).

Two viable designs for set loading:

**Option A — strict numeric filenames, Bome resolves the path directly.**

```text
File to Execute:  C:\LiveRig\Sets\Stable\%02d gn%.als
Parameters:       (empty — Windows opens it with Ableton)
```

Simple, but loses human-readable names and gives Python no say in whether the launch is safe.

**Option B — recommended — hand off to a script.**

```text
File to Execute:  C:\LiveRig\Controller\commands\load-set.cmd
Parameters:       "%d gn%"
```

`load-set.cmd` resolves `01*.als`, checks the Focusrite is present, closes the running instance
cleanly, logs, then launches. This keeps every safety rule from §24/§28 in Python where it
belongs. **Prefer Option B.**

Relative paths are resolved against the project file's folder, which is handy for keeping the
whole control layer under `C:\LiveRig\Controller\`.

Note: a `.bmtp` filename in this field loads that project into the *running* MT Pro instance
rather than starting a second one — a clean way to swap entire control surfaces (e.g. a
stripped-down "emergency" project).

### Keystroke and mouse injection (Windows only)

Normal emulated keystrokes go to whatever window has focus, and are suppressed entirely while MT
Pro itself is focused. On a headless rig with no user driving focus, that is fragile.

**Injection** targets a specific window or sub-window directly, without activating it. You pick
the target with a capture tool that outlines windows as you hover. The manual's own worked
example is injecting a click onto Ableton Live's TAP button — so this is a documented, intended
use.

Caveats it states plainly:
- It does not work with every program. Test against your Ableton build.
- Application windows are layered; you may need to experiment to find the right sub-window.
- For injected **mouse** events, X/Y are relative to the **target window**, not the screen, and
  injected mouse events cannot be aimed at a specific monitor.

Use injection for anything that must survive a stray focus change. Where you genuinely need real
focus, the **Application Focus** action exists in both directions.
**[Details of §9.13 unverified — not extracted.]**

`Emulate keystrokes slowly` adds 20 ms (or 50 ms, or a custom/variable delay) between every raw
key event including modifiers. Ableton sometimes needs this. The manual warns: enable it for the
whole project or none of it, because slow keystrokes are queued and scheduled while fast ones
fire immediately and will interleave badly.

---

## 8. The bridge between Bome and the Rig Controller

**Python/PowerShell → Bome** (used by SSH maintenance commands and by the state machine):

```text
/triggerPerform "Reset"                 # trigger a named Perform, up to 10 params
/triggerPerform "LoadSet,3"
-setVar <var> <value>                   # [UNVERIFIED] set a global; decimal, 0x hex, or a var
-triggerTimer <timerName>               # [UNVERIFIED] fire a timer once, immediately
```

`/triggerPerform` is confirmed in the manual (§9.6.3); note that **local variables cannot be used
as command-line parameters**. `-setVar` and `-triggerTimer` come from Bome's published version
history — confirm exact syntax and whether they apply to a running instance in §16.3 before
relying on them.

This gives the Python controller a clean way to push state onto the Launchpad without owning the
MIDI port. Example: Focusrite detected → `-setVar ga 1` → a Bome translator turns the interface
status pad green.

**Bome → Python**: Execute File, calling small `.cmd`/`.ps1` wrappers under
`C:\LiveRig\Controller\commands\`. These already exist in the blueprint (§33).

---

## 9. Live-performance hygiene

- **Turn off the Log Window during shows.** The manual warns that rendering many log lines eats
  CPU and degrades realtime engine performance. Enable it only while developing rules.
- Use **Stop Processing** aggressively. It is the documented optimisation for large projects.
- **There is no Undo** in the editor. Edits apply immediately. Back up the `.bmtp` before changes.
- MT Pro is a second always-on process alongside Ableton and the Rig Controller. Add it to §36
  health monitoring and to the §40 startup task chain.
- Startup behaviour (auto-launch, start minimised/hidden) lives in Settings → Startup Options,
  §11.1. **[Not extracted — read before configuring the headless boot.]** There is also a
  `-noshow` style parameter referenced in the version history for running without the UI.
- The **Panic / Stop** button (Shift+Esc) resets MIDI out and toggles Disable Processing. The
  outgoing **Project** action does the same programmatically — and translators whose *outgoing*
  action is of type Project keep running even while processing is disabled, which is the only way
  to re-enable from within the project. That is the true panic pad: kill all translation, keep
  one escape hatch alive.

---

## 10. Variables

| Kind | Names | Lifetime |
|---|---|---|
| Local | `oo` … `xx` (10 total) | One translator execution |
| Global | `ga`–`gz`, `g0`–`g9`, then `h`…`z` series — ~710 total **[UNVERIFIED count]** | As long as MT Pro runs |

Locals are private to one incoming event, so simultaneous matching messages don't collide — the
manual recommends them for capturing values out of incoming raw MIDI strings. Globals carry state
between translators and presets (current mode, selected set, hold flags).

Raw MIDI strings accept embedded variables at any byte position. In an **incoming** string a
variable matches any value and captures it; in an **outgoing** string it is substituted and left
unchanged:

| Raw string | Meaning |
|---|---|
| `90 pp 7F` | Note on, ch 1, any note (captured into `pp`), velocity 127 |
| `B0 xx pp` | CC on ch 1, any controller, any value — captures both |
| `F0 00 20 29 02 0C 0E 01 F7` | Launchpad X Programmer Mode SysEx (VERIFIED) |

Concatenating multiple messages in one raw string is supported on the incoming side; the manual
implies the same for outgoing.

> **Superseded.** This document previously flagged outgoing concatenation as the way to batch LED
> writes, and called it the deciding test for where LED rendering lives. The Programmer's
> Reference answers it directly: **the LED Lighting SysEx `03h` takes up to 81 entries in one
> message.** Both Bome and Python can batch. The question is settled and it no longer favours
> Bome.

Rule syntax (assignments, `if/then`, `Goto`, labels, `Log "text %pp%"`) is chapter 10.
**[Not extracted — confirm the operator set, especially modulo, before writing animation maths.]**

**Variable Storage** (§9.14, 1.9.2+) persists selected globals to a file and reloads them after a
restart. This is blueprint §44 runtime-state persistence, natively. **[Details unverified.]**
Decide deliberately whether last-active-set lives here or in the Python `state.json` — not both.

---

## 11. Impact on the existing blueprint

Applies **only if Bome is adopted at Phase 8.**

| Blueprint section | Change |
|---|---|
| §5 Software Stack | Add Bome MIDI Translator Pro (~€79, licensed per install). Add `.bmtp` to backups. |
| §6 Architecture | Launchpad Service shrinks: Bome owns MIDI I/O. Python keeps the state machine, Ableton service, audio service, health, logging. |
| §14 Launchpad Modes | Implement modes as Bome **presets** + "deactivate all others except always-active". |
| §16 Launchpad Device Class | Largely superseded. Python no longer opens the Launchpad port. |
| §23 Set Selection | Hold-to-confirm becomes a Bome timer (Activate on press / Kill on release). Never use the outgoing Delay field. |
| §24 Ableton Launcher | Keep in Python. Bome's Execute File calls `load-set.cmd`. |
| §25 Unsaved-Changes Prompts | Injected mouse/keystroke events give a *backup* way to dismiss a stray dialog — read-only Stable sets remain the primary defence. |
| §26 Focusrite Detection | Unchanged. Bome cannot see audio devices. |
| §30 MIDI Routing | Two input ports do exist, so Strategy A is possible — but it cannot give both programs the same pad press. Choose deliberately at Phase 8. |
| §36 Health Monitoring | Add: is MT Pro running? Did any MIDI Port Open Error fire? |
| §38 Error Categories | Add "MIDI port open error (port held by another process)". |
| §40 Startup | Task Scheduler must start MT Pro *before* the Rig Controller, and Ableton last. |
| §42 Installation Tree | Add: install MT Pro (Custom install → include virtual MIDI ports), load `.bmtp`, configure Startup Options, verify Programmer Mode SysEx fires on reconnect. |
| §44 Runtime State | Choose one owner: Bome Variable Storage or Python `state.json`. |
| §51 Full Rehearsal Test | Add: unplug Launchpad mid-show → confirm Bome re-opens the port *and* re-sends Programmer Mode SysEx with no restart. Also: kill MT Pro → confirm the Launchpad still returns to Live mode. |
| §56 Build Order | Insert between Step 4 and Step 5: build the Bome project skeleton (aliases, virtual port, five mode presets, Programmer Mode on connect). |

---

## 12. Open questions — read these manual sections before building

1. **§10.2 Rule Types** — full operator set. Modulo, bit ops, and comparison syntax needed for
   animation maths and pad→slot mapping.
2. **§16.3 Command Line Switches** — exact syntax for `-setVar`, `-triggerTimer`, `-noshow`, and
   whether they address a *running* instance or spawn a new one. The Python↔Bome bridge depends
   on this entirely.
3. **§11.1 Startup Options** — auto-start, start hidden/minimised, which project file loads on
   launch. Required for headless boot.
4. **§9.14 Variable Storage** — file location, whether the path can be set dynamically, save/load
   granularity.
5. **§9.13 Application Focus** — how a window is identified, and how reliably it works against
   Ableton's window hierarchy.
6. **Crash behaviour** — does MT Pro restore Live mode on the Launchpad when it exits or dies?
   If not, adopting Bome introduces a headless failure with no software recovery path.

~~7. Outgoing raw MIDI with concatenated messages~~ — **closed.** SysEx `03h` batches 81 LEDs.
~~8. Launchpad X release semantics~~ — **closed.** Note-on velocity 0, confirmed p.6.
