# tools/ — Phase 1 hardware truth scripts

**Layer: none.** These are not part of the application. They are bench instruments whose only
output is *verified constants* that get committed into `launchpad/grid.py`, `launchpad/colors.py`,
`launchpad/ports.py` and `config/rig.yaml`. Nothing in `rig/`, `launchpad/` or `ableton/` may
import from here.

They must run on the **Beelink, under Windows, with the hardware attached.** Running them
anywhere else proves nothing, and the two that would produce misleading results off-rig refuse
to start.

## Layout

```text
tools/
├── _bench.py                     shared: SysEx vocabulary, ports, session lifecycle
├── midi_port_inspector.py        port names + open-ability probe
├── launchpad_note_tester.py      the 9x9 map
├── led_color_tester.py           the 128-colour palette
├── led_batch_tester.py           81-entry SysEx: accepted? how fast?
├── interface_name_inspector.py   Get-PnpDevice → Scarlett names
└── results/                      dated findings. Committed — they are the evidence
```

### Why `_bench.py` exists

Every tool that opens the Launchpad must restore Live Mode on the way out. Programmer Mode
entered by SysEx **disables the device's Setup menu** (manual p.7), so a script that exits
without restoring leaves the front panel unreachable with no software recovery path. That
contract is worth one implementation, not five.

`_bench.bench()` is the only sanctioned way to connect. It covers clean exit, exceptions,
`Ctrl+C` and `SIGTERM`. It cannot cover a hard kill (`taskkill /F`, power loss, a backend
segfault) — nothing in Python can. Recovery there is physical: unplug and replug the USB. Every
tool prints this before it starts.

`_bench.py` also holds the SysEx constants, each carrying its page citation. Byte sequences are
in **mido convention — no `F0`/`F7` framing**, since mido adds it on send. Bome's raw-MIDI
strings include the framing. Same bytes, two conventions.

## Run order

Each step depends on the one above it.

| # | Tool | Produces | Notes |
|---|---|---|---|
| 1 | `midi_port_inspector.py` | `launchpad/ports.py` names | Run twice: `--label ableton-closed`, then `--label ableton-open`, and diff. A port that reads OK in one and HELD in the other is MIDI input exclusivity made visible |
| 2 | `launchpad_note_tester.py --frame` | the CC frame | ~2 min, and it is the actual unknown. Do this before the full sweep |
| 3 | `launchpad_note_tester.py` | `launchpad/grid.py` | Full 81-position guided sweep |
| 4 | `led_batch_tester.py` | `renderer.py` design | Also measures the real Programmer-Mode settle time, replacing the guess in `_bench.py` |
| 5 | `led_color_tester.py` | `launchpad/colors.py` | Photograph both pages. **Commit the photographs** — a palette reading nobody can re-check is barely better than a guess |
| 6 | `interface_name_inspector.py` | `config/rig.yaml` | Once per Scarlett. `--label` keeps them apart |

## How the note tester works, and why

It does not just log presses. It lights LED index *i*, asks for the pad that just lit, and
records what pressing it sends. One pass yields a verified pairing:

```text
LED index  <->  physical position  <->  input message
```

without assuming either numbering is correct. A plain capture loop tells you which numbers
exist; it cannot tell you which number belongs to which position without the human reporting
that separately, which is where transcription errors come from. It also means that if LED
indices and input numbers ever disagree — contradicting p.15 — this is the tool that shows it.

## Rules

1. Every script prints results in a form that can be pasted into a module as a literal.
2. Every recorded constant carries the date and the method. `Recorder` does this automatically;
   **paste the header along with the values.** A value without provenance is a guess wearing a
   costume.
3. Anything touching the Launchpad connects through `_bench.bench()`. Never open a port directly.
4. Record disagreements, do not silently resolve them. If a pad reports something other than
   `(row × 10) + column`, that is a finding, and the tools are written to surface it rather than
   normalise it away.
5. `docs/colour-palette-candidate.json` is from a **different device**. It is printed alongside
   observations so differences stand out. Agreement with it is not verification.

## Exit test for Phase 1

`grid.py` and `colors.py` contain measured values with dates and methods. No guesses left in
either file. See `docs/ROADMAP.md` Phase 1.

## Off-rig

`_bench.py`'s pure logic — SysEx construction, port classification, device-inquiry parsing — has
no hardware dependency and is worth checking after any edit. The SysEx builders are verifiable
against the manual's own worked examples on p.14–15.
