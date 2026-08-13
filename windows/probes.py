"""
Cheap answers to "is that thing actually there?" on the Beelink.

LAYER: Drivers. Windows-only. Everything here is measured, because these run inside
a 30 Hz tick and a slow probe would eat the loop it is meant to protect.

MEASURED ON THE RIG, 2026-08-13
    registry service Enum read              0.03 ms   free
    psutil scan of ALL processes for a dll  1696 ms   unusable, never do this
    memory_maps of the Ableton process only 12.7 ms   38% of a 33 ms tick

    So: registry probes run every tick; anything touching process memory maps is
    cached behind a TTL. The numbers are the reason the design looks like this.

WHY THE REGISTRY AND NOT Get-PnpDevice
    Get-PnpDevice is the readable way to ask what is attached and takes about a
    second per call. A service's Enum key lists the device instances CURRENTLY BOUND
    to that driver, which is the same question, answered from a registry read.
"""

from __future__ import annotations

import logging
import time
import winreg
from dataclasses import dataclass, field
from typing import Callable

import psutil

log = logging.getLogger(__name__)

__all__ = [
    "EVO8_VID_PID",
    "AUDIENT_SERVICE",
    "ABLETON_PROCESS_HINT",
    "usb_device_bound",
    "process_running",
    "process_has_module",
    "cached",
]

#: Audient EVO 8. MEASURED from the bus 2026-08-12; see tools/results/usb-topology.txt.
EVO8_VID_PID = "VID_2708&PID_0007"

#: The kernel service the EVO's driver registers. Its Enum key lists bound devices.
AUDIENT_SERVICE = "audientusbaudio"

#: Ableton's process name varies by edition ("Ableton Live 12 Suite.exe"), so match
#: on a substring rather than pinning a version that changes on every upgrade.
ABLETON_PROCESS_HINT = "ableton live"

#: The Audient ASIO driver DLL. If a process has this mapped, it opened THAT device.
AUDIENT_ASIO_MODULE = "audientusbaudioasio"


def usb_device_bound(vid_pid: str = EVO8_VID_PID, service: str = AUDIENT_SERVICE) -> bool:
    """
    Is a device with this VID/PID currently bound to this driver service?

    Reads HKLM\\SYSTEM\\CurrentControlSet\\Services\\<service>\\Enum, which holds one
    entry per attached instance plus a Count. 0.03 ms.

    > ASSUMPTION, not yet verified by unplugging: that Count drops to 0 when the
    > device is removed. It is how the key is documented to behave and it matched
    > observation while the EVO was attached (Count=1, instance
    > 'USB\\VID_2708&PID_0007\\5&114e2b25&0&4'), but nobody has watched it go to
    > zero. Verify before this gates anything on stage.
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, rf"SYSTEM\CurrentControlSet\Services\{service}\Enum"
        ) as key:
            count, _ = winreg.QueryValueEx(key, "Count")
            for index in range(int(count)):
                instance, _ = winreg.QueryValueEx(key, str(index))
                if vid_pid.lower() in str(instance).lower():
                    return True
    except OSError:
        # Key absent means the driver has never bound anything — same answer as absent.
        return False
    return False


def process_running(name_hint: str = ABLETON_PROCESS_HINT) -> psutil.Process | None:
    """The first process whose name contains `name_hint`, or None. Case-insensitive."""
    hint = name_hint.lower()
    for proc in psutil.process_iter(["name"]):
        name = proc.info.get("name") or ""
        if hint in name.lower():
            return proc
    return None


def process_has_module(proc: psutil.Process, module_hint: str) -> bool:
    """
    Does this process have a DLL matching `module_hint` mapped?

    EXPENSIVE — 12.7 ms on the rig. Always call through `cached`. Scanning every
    process instead of one takes 1.7 SECONDS; do not be tempted.
    """
    try:
        return any(module_hint in (m.path or "").lower() for m in proc.memory_maps())
    except (psutil.AccessDenied, psutil.NoSuchProcess, OSError) as exc:
        log.debug("cannot inspect modules of pid %s: %s", getattr(proc, "pid", "?"), exc)
        return False


@dataclass
class cached:  # noqa: N801 — used as a decorator-ish wrapper, reads better lowercase
    """
    Call `fn` at most once per `ttl_s`, reusing the last answer in between.

    For probes whose cost matters at 30 Hz. The staleness is deliberate and bounded:
    a boot check that is up to a second out of date is fine, and a tick loop that
    spends 40% of its budget asking the same question thirty times a second is not.
    """

    fn: Callable[[], object]
    ttl_s: float = 1.0
    clock: Callable[[], float] = time.monotonic

    _value: object = field(default=None, init=False)
    _fetched_at: float | None = field(default=None, init=False)

    def __call__(self) -> object:
        now = self.clock()
        if self._fetched_at is None or now - self._fetched_at >= self.ttl_s:
            self._value = self.fn()
            self._fetched_at = now
        return self._value

    def invalidate(self) -> None:
        self._fetched_at = None
