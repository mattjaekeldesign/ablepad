"""
launchpad/ — the Launchpad X service (Phase 3).

LAYER: Drivers + Services for the one piece of hardware that is the whole UI.

    ports.py         name -> which USB interface. Pure, no mido.
    device.py        open, Programmer Mode, read presses, write LEDs, RESTORE.
    backend_mido.py  the only module that imports mido.
    grid.py          the 9x9 map. MEASURED on hardware 2026-08-12.
    colors.py        palette indices. The 8 in use are MEASURED.
    mappings.py      Config Lab schema contract, ported not reinvented.
    animations.py    deterministic frame engine, golden-verified against the Lab.
    player.py        intro/during playback policy.

    modes.py         which surface a RigState shows. A table, not string munging.
    renderer.py      state + animation + presses -> 81 LedSpecs. Pure.

Phase 3's modules are all present. What has never happened is any of it running
against the device: the exit test (connect, survive 20 replugs, a press arriving as
a named action) needs the Beelink.

The rule that shapes this package: nothing here may import from tools/. The bench
instruments proved the protocol against real hardware, and that knowledge is PORTED
into device.py rather than referenced, because tools/ is throwaway and this is not.
"""
