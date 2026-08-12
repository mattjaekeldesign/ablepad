# Phase 0 endurance run — 2026-08-12

**Stopped at 15 minutes of a planned 30, by choice.** No crackles, with a heavy
NAM + IR chain loaded. A fuller test is owed once the real set exists, so a second
run was going to happen regardless.

Raw samples: `phase0-endurance.csv`, 41 rows at 20 s intervals.

## What the 15 minutes showed

| | |
|---|---|
| Ableton CPU | avg **23.7%**, peak **31.1%** of 4 cores |
| System CPU | avg 41%, peak 86% |
| CPU clock | avg **3069 MHz**, min 2900 (nominal 800) |
| Clock, first third → last third | **3085 → 3057 MHz** — held |
| Ableton RAM | 896 → 1205 MB |
| EVO 8 on the bus | present in all 41 samples |
| Launchpad on the bus | present in all 41 samples |
| Audible dropouts | **none reported** |

**Load roughly doubled** versus the earlier idle-ish measurement (9.2% avg), which
is the heavy chain doing its job. Still clean at 256 samples.

**No throttling in this window.** The clock sat near 3.1 GHz throughout and the
last third was within 1% of the first. That is the High-performance plan and
min-processor-state 100% holding.

## What this run does NOT establish

**The exit test is 30 minutes and this was 15.** Not marked complete.

Thermal throttling on a passively-or-barely-cooled N150 typically appears at
15–25 minutes of sustained load, not at 5. Stopping at 15 lands right at the
edge of where the interesting failure starts. The clock held for the window
measured — that is a real result, and it is not the same as "it will hold for a
set".

**The temperature column is worthless.** All 41 samples read exactly 27.9 °C.
A sensor that never moves under a doubling of CPU load is not measuring the CPU;
`MSAcpi_ThermalZoneTemperature` on this board is reporting a fixed or ambient
zone. Ignore the column. If thermals ever need answering properly it needs a
tool that reads package temperature directly, not ACPI.

**RAM grew ~300 MB.** Almost certainly the chain loading rather than a leak, but
15 minutes is too short to distinguish the two. Worth a glance on the longer run.

## For the re-test

- Run the **full 30**, ideally 45, with the actual performance set
- Watch the clock in the last third — that is where throttling shows
- Note the minute mark of any audible artefact so it can be lined up against
  the clock curve
