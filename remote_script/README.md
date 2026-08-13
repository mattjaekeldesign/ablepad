# Ablepad readiness Remote Script

Runs **inside Ableton Live**, not in the rig. Its whole job is to write one file
when a set has finished loading, so the boot gate can stop guessing.

## Why

`boot_settle_s` was a wall-clock timer. MEASURED 2026-08-13: `ableton_audio` binds
~4 s after launch for both a 7 KB and a 15 KB set, which proves that check measures
Ableton's startup and says nothing about the set. A set with a NAM model and IRs
takes much longer, so the timer had to cover the slowest set on every boot — and was
still a guess for the set that turns out slower.

## Install

1. Copy the `Ablepad/` folder to:
   `%APPDATA%\Ableton\Live <version>\Preferences\User Remote Scripts\`
2. Restart Live.
3. Preferences → **Link/Tempo/MIDI** → a free **Control Surface** slot → `Ablepad`.
4. Leave Input and Output as **None**. This script never sends or receives MIDI.

Verify: `C:\LiveRig\Logs\ableton-ready.json` appears within a few seconds of a set
opening, and names that set.

## Contract

```json
{"schema": 1, "set": "C:\\LiveRig\\Sets\\...\\test.als",
 "loaded_at": 1755082561.4, "reason": "control_surface_init"}
```

`SIGNAL_PATH` here and `ableton.ready_signal.SIGNAL_FILENAME` are two constants in
two interpreters with no import between them. Change one, change the other.

## Known limitations

- **UNVERIFIED**: whether `create_instance` runs before or after the set's devices
  finish loading. If early, the signal is optimistic — which is why
  `ReadinessTracker.floor_s` refuses to honour it before a minimum time. Measure the
  real gap before lowering that floor.
- A Remote Script that raises is disabled by Live silently; the only evidence is a
  traceback in Live's `Log.txt`. Everything here is wrapped for that reason.
- Not a `_Framework.ControlSurface` subclass on purpose — that base class brings MIDI
  plumbing and a display model this needs none of, each an extra way to raise.
