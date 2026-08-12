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

STILL ABSENT: renderer.py (rig state -> a frame) and modes.py (LaunchpadMode).
Those are the next layer up; the driver beneath them now exists and is tested.

The rule that shapes this package: nothing here may import from tools/. The bench
instruments proved the protocol against real hardware, and that knowledge is PORTED
into device.py rather than referenced, because tools/ is throwaway and this is not.
"""
