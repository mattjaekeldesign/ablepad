"""
Reboot and shutdown. The only module allowed to end this machine's session.

LAYER: Drivers (OS). Windows-specific by definition; everything above it is
written against the Protocol so the rig stays testable off-rig.

WHY shutdown.exe AND NOT A WINDOWS API
    `shutdown /r /t 0` is documented, present on every Windows since forever, needs
    no extra dependency, and does exactly one thing. The WinRT and Win32 routes need
    privilege juggling that buys nothing here: the rig already runs elevated
    (scheduled task /rl highest, for reasons in docs/ROADMAP.md §5).

THE THING TO BE CAREFUL ABOUT
    These are the only rig actions that cannot be undone, cannot be verified
    afterwards, and cannot be recovered from without physical access. A shutdown
    triggered by a scuffed pad means a dead rig on stage and a walk to the machine.

    Defence in depth, none of it in this module:
      * SYSTEM_SHUTDOWN carries a 6000 ms hold and SYSTEM_REBOOT 4000 ms
        (configs/system.json), so neither can fire from a brush.
      * hold progress is now visible on the pad (launchpad/holdfeedback.py), so a
        hold in progress can be seen and abandoned.
      * both live in System Mode, which is two deliberate mode switches away from
        anywhere a performer's feet are.

    This module's own contribution is smaller and duller: refuse to run anything it
    did not construct itself, and never take an argument from configuration.

DRY RUN
    `dry_run=True` logs what it would do and returns. Used by the bench tools and by
    anyone who wants to exercise System Mode without losing the machine.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

log = logging.getLogger(__name__)

__all__ = ["PowerController", "WindowsPower"]

#: Fixed argument lists. NOT built from configuration, NOT string-formatted, and
#: not reachable from a pad's params -- a pad says SYSTEM_REBOOT and nothing more.
#: The whole attack surface of "the rig can turn the machine off" is these two
#: literals.
_REBOOT = ["shutdown", "/r", "/t", "0", "/c", "ablepad rig reboot"]
_SHUTDOWN = ["shutdown", "/s", "/t", "0", "/c", "ablepad rig shutdown"]


class PowerController:
    """The seam. Implemented below on Windows, faked in tests."""

    def reboot(self) -> None: ...

    def shutdown(self) -> None: ...


@dataclass
class WindowsPower:
    dry_run: bool = False

    def reboot(self) -> None:
        self._run(_REBOOT, "reboot")

    def shutdown(self) -> None:
        self._run(_SHUTDOWN, "shutdown")

    # -- internals --------------------------------------------------------

    def _run(self, argv: list[str], what: str) -> None:
        if self.dry_run:
            log.warning("DRY RUN: would %s (%s)", what, " ".join(argv))
            return
        log.warning("%s requested — the rig is going down now", what)
        try:
            result = subprocess.run(argv, capture_output=True, timeout=15)
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
            # Worth a loud log and nothing else. Raising would take down a rig that
            # is, by definition, still working -- the machine did not go anywhere.
            log.error("could not %s: %s", what, exc)
            return
        if result.returncode != 0:
            log.error(
                "%s refused (rc=%d): %s",
                what, result.returncode, result.stderr.decode(errors="replace").strip(),
            )
