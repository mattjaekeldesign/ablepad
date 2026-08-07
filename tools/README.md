# tools/ — Phase 1 hardware truth scripts

**Layer: none.** These are not part of the application. They are throwaway bench instruments
whose only output is *verified constants* that get committed into `launchpad/grid.py` and
`launchpad/colors.py`. Nothing in `rig/`, `launchpad/` or `ableton/` may import from here.

They must run on the **Beelink, under Windows, with the hardware attached.** Running them on
anything else proves nothing.

| Script | Answers |
|---|---|
| `midi_port_inspector.py` | Exact Windows port-name strings for both Launchpad interfaces. `launchpad/ports.py` matches on these |
| `launchpad_note_tester.py` | The 9×9 map. Press every pad and button in Programmer Mode, record note vs CC and the number |
| `led_color_tester.py` | The 128-colour palette. Sweep 0–127, photograph, record. Diff against `docs/colour-palette-candidate.json` |
| `led_batch_tester.py` | Confirms and **times** an 81-entry LED SysEx. 81 is the documented ceiling, not a measured throughput |
| `interface_name_inspector.py` | What `Get-PnpDevice` actually returns for each Scarlett. Feeds `AudioInterfaceDetector` |

## Rules

1. Every script prints results in a form that can be pasted into a module as a literal.
2. Every recorded constant carries the date and the method in a comment. A value without a
   provenance comment is a guess wearing a costume.
3. `launchpad_note_tester.py` and `led_color_tester.py` must restore **Live mode** on exit,
   including on `Ctrl+C`. Selecting Programmer Mode by SysEx disables the Setup menu, and a
   script that dies without restoring leaves the panel unreachable. Use `try/finally`.
4. Record disagreements, do not silently resolve them. If a pad reports something other than
   `(row × 10) + column`, that is a finding.

## Exit test for Phase 1

`grid.py` and `colors.py` contain measured values with dates and methods. No guesses left in
either file. See `docs/ROADMAP.md` Phase 1.
