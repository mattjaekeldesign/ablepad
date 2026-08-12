# tools/results — recorded evidence

Raw output from the Phase 1 bench tools, run against the real hardware. These files
are the provenance behind `launchpad/grid.py` and `launchpad/colors.py`. Committed on
purpose: a constant whose evidence nobody can re-read is a guess with better manners.

All from Beelink `RIG`, Launchpad X firmware **0.3.5.1**, driven over SSH.

| File | Date | What it records |
|---|---|---|
| `midi-ports-launchpad-attached.txt` | 2026-08-12 | Verbatim Windows MIDI port names, and that both interfaces open |
| `grid-frame.txt` | 2026-08-12 | 17 outer positions. CC 91–98 and 19–89, 16/16 exact. Logo 99 lights but has no button |
| `grid-8x8.txt` | 2026-08-12 | 64 interior pads. **Contains two bad rows — see below** |
| `grid-retest.txt` | 2026-08-12 | Pads 11, 12, 13 re-run. **Supersedes those rows in `grid-8x8.txt`** |

## The two bad rows, and why they are still here

`grid-8x8.txt` records `LED 12 -> note 11` and `LED 13 -> note 12`. Those are not device
behaviour — the operator pressed one pad to the left at the start of the sweep and
corrected by position 14. `grid-retest.txt` re-ran exactly those positions and got
11→11, 12→12, 13→13.

The bad file is kept rather than deleted or edited. Silently correcting recorded
evidence is how a lab notebook becomes fiction; the honest version is both files and
this note. Anything reading these must let `grid-retest.txt` win.

Two changes came out of it, in `launchpad_note_tester.py`:

- presses are now filtered from releases (the device sends note-on velocity 0 for a
  release, p.6, so "any note_on" was never the same thing as "a press")
- the input queue is drained fully between positions rather than one message swallowed
  — with aftertouch on, one press is a dozen messages

Neither caused this particular error. Both were real ambiguities the error made visible.

## Still missing

- **Colour palette**: 8 of 128 verified — the eight the rig actually uses. Everything
  else is a candidate sampled from a *different device*. `tools/palette_coverage.py`
  fails if a config starts depending on an unverified index.
- **EVO 8 endpoint names**: `interface_name_inspector.py` has not run with the
  interface attached.
