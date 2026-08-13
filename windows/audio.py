"""
The audio-interface presence adapter.

LAYER: Drivers. Implements ableton.launcher.AudioInterfacePresence against the
registry probe, so the launcher never learns what Windows is.

PRESENCE IS NOT HEALTH, and the launcher's own docstring says so. An ESD-wedged
EVO 8 still enumerates and still reports present here, while outputting silence
(docs/audient-evo-8-reference.md §6). This answers "is it worth trying", never
"will it make sound".
"""

from __future__ import annotations

from dataclasses import dataclass

from windows import probes

__all__ = ["EvoPresence"]


@dataclass
class EvoPresence:
    """VERIFIED 2026-08-13: goes False when the cable is pulled. See probes."""

    vid_pid: str = probes.EVO8_VID_PID
    service: str = probes.AUDIENT_SERVICE

    def is_present(self) -> bool:
        return probes.usb_device_bound(self.vid_pid, self.service)
