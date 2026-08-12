"""
Which of the Launchpad's USB interfaces is which.

LAYER: drivers. PURE — takes a list of port names, returns classified ports. It does
not import mido and never opens anything, so the whole thing is testable off-rig
against the exact strings the hardware reported.

WHY THIS IS NOT A ONE-LINE SUBSTRING MATCH
    The Launchpad X exposes two USB MIDI interfaces (manual p.6). Programmer Mode --
    the only mode the rig uses -- lives on the SECOND one. Picking the first gets you
    a port that opens cleanly, accepts writes, and does nothing.

    On Windows the names do not say which is which. MEASURED on the rig 2026-08-12:

        interface 1 (DAW) : 'LPX MIDI 0'            'LPX MIDI 1'
        interface 2 (MIDI): 'MIDIIN2 (LPX MIDI) 1'  'MIDIOUT2 (LPX MIDI) 2'

    Every one contains "LPX". Every one contains "MIDI". The word "DAW" -- which the
    manual promises -- appears nowhere. Windows applies its own multi-port convention
    instead: the first interface takes the bare device name, later ones get a
    MIDIIN<n>/MIDIOUT<n> prefix.

    A classifier keying on "daw"/"midi" therefore labels all four identically. That is
    not hypothetical: tools/_bench.py did exactly that and every bench tool aborted the
    first time it met real hardware.

    macOS and Linux DO name them ('LPX DAW Out', 'LPX MIDI Out'), so both worlds have
    to work. Explicit names win where they exist; interface number decides where they
    do not.

WHO CALLS IT
    launchpad/device.py, to pick which pair to open. Nothing else needs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

__all__ = ["PortRole", "Port", "Classification", "classify", "select", "PortError"]


class PortRole(Enum):
    """Which USB interface a port belongs to."""

    DAW = "daw"  # interface 1: Session mode + DAW Faders. The rig does not use it.
    MIDI = "midi"  # interface 2: Note/Custom modes AND Programmer mode. The rig's port.
    UNKNOWN = "unknown"


class Classification(Enum):
    """How confident we are, so callers can log the weak cases."""

    BY_NAME = "name"  # the name said so outright ('LPX DAW Out')
    BY_INTERFACE = "interface"  # Windows multi-port prefix gave the interface number
    BY_ORDINAL = "ordinal"  # nothing but position. The manual's p.6 rule. Weakest.


@dataclass(frozen=True)
class Port:
    name: str  # verbatim, exactly as the backend reported it
    role: PortRole
    how: Classification
    interface: int | None  # 1-based USB interface, where it could be determined


class PortError(RuntimeError):
    """No usable port, or too many. Always actionable."""


# Windows multi-port naming: 'MIDIIN2 (LPX MIDI)', 'MIDIOUT3 (Some Device)'.
# The digit is the 1-based interface index, starting at 2 for the second.
_WINDOWS_MULTIPORT = re.compile(r"\bMIDI(?:IN|OUT)(\d+)\s*\(", re.IGNORECASE)

# What a Launchpad X calls itself. 'LPX' is the Windows short form, 'Launchpad'
# the long one that macOS and Linux use.
_LAUNCHPAD_TOKENS = ("launchpad", "lpx")


def _is_launchpad(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in _LAUNCHPAD_TOKENS)


def _interface_number(name: str) -> int:
    """1 for a bare device name, n for a MIDIIN<n>/MIDIOUT<n> prefixed one."""
    match = _WINDOWS_MULTIPORT.search(name)
    return int(match.group(1)) if match else 1


def classify(names: list[str] | tuple[str, ...]) -> list[Port]:
    """
    Label every Launchpad port in `names`. Non-Launchpad names are dropped.

    Order of evidence, strongest first:
      1. the name says "daw"                       -> DAW,  BY_NAME
      2. a sibling carries a MIDIIN<n> prefix      -> role from interface number
      3. the name says "midi" (macOS/Linux)        -> MIDI, BY_NAME
      4. nothing at all                            -> position, BY_ORDINAL

    Step 2 is gated on a SIBLING carrying the prefix, not on this name having one:
    on Windows the first interface has no prefix, so it is only identifiable as
    "interface 1" once we know we are looking at Windows-style naming at all.
    """
    candidates = [n for n in names if _is_launchpad(n)]
    windows_style = any(_WINDOWS_MULTIPORT.search(n) for n in candidates)

    ports: list[Port] = []
    for ordinal, name in enumerate(candidates):
        lowered = name.lower()

        if "daw" in lowered:
            ports.append(Port(name, PortRole.DAW, Classification.BY_NAME, _interface_number(name)))
        elif windows_style:
            iface = _interface_number(name)
            role = {1: PortRole.DAW, 2: PortRole.MIDI}.get(iface, PortRole.UNKNOWN)
            ports.append(Port(name, role, Classification.BY_INTERFACE, iface))
        elif "midi" in lowered:
            ports.append(Port(name, PortRole.MIDI, Classification.BY_NAME, _interface_number(name)))
        else:
            role = {0: PortRole.DAW, 1: PortRole.MIDI}.get(ordinal, PortRole.UNKNOWN)
            ports.append(Port(name, role, Classification.BY_ORDINAL, ordinal + 1))
    return ports


def select(ports: list[Port], role: PortRole) -> Port:
    """
    The one port with this role.

    Raises rather than guessing. Two ports claiming the same role means either a
    second Launchpad is attached or a virtual port is impersonating one, and
    silently taking the first would put the rig on the wrong device.
    """
    matches = [p for p in ports if p.role is role]
    if not matches:
        seen = [p.name for p in ports] or ["nothing that looks like a Launchpad"]
        raise PortError(
            f"no Launchpad {role.value.upper()} port. Saw: {seen}. "
            "Is it plugged in, and out of MSD mode?"
        )
    if len(matches) > 1:
        raise PortError(
            f"{len(matches)} ports claim to be {role.value.upper()}: "
            f"{[m.name for m in matches]}. Two Launchpads, or a stale virtual port. "
            "Refusing to guess which one the rig should drive."
        )
    return matches[0]
