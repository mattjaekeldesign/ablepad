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

MEASURED 2026-08-13 on Live 12.4.3 by installing three differently-named copies in
the three candidate locations and seeing which appeared in the dropdown. Exactly one
did.

1. Copy the `Ablepad/` folder to:

   ```
   C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\Ablepad\
   ```

2. Restart Live. It scans for scripts **only at startup**.
3. Preferences → **Link, Tempo & MIDI** → a free **Control Surface** slot → `Ablepad`.
4. Leave Input and Output as **None**. This script never sends or receives MIDI.

Verify: `C:\LiveRig\Logs\ableton-ready.json` appears within a few seconds of a set
opening, and names that set.

### Locations that do NOT work — do not retry these

Both are widely cited for Live and neither is listed by Live 12.4.3. Recorded so the
next person does not spend the same half hour:

| Path | Result |
|---|---|
| `%APPDATA%\Ableton\Live <ver>\Preferences\User Remote Scripts\` | not listed |
| `<User Library>\Remote Scripts\` | not listed |
| `<User Library>\MIDI Remote Scripts\` | not listed |

Live logs nothing while scanning — a control surface only appears in `Log.txt` once
it is SELECTED. So a script in the wrong place is completely silent, and the
Preferences dropdown is the only test.

### The cost of the working location

`Resources\` is inside the Live installation, so **a Live update will delete this
script**. There is no user-scoped alternative that Live 12.4.3 honours.

The rig degrades safely when that happens: with no signal, the boot gate waits out
`rig.boot_settle_s` exactly as it did before this existed, and `main.py` logs that
the signal never arrived. It is slower, not broken. **Reinstall this script after
every Live update**, and treat a boot that suddenly takes the full settle time as
the symptom.

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
