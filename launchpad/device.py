"""
The Launchpad X driver: open it, put it in Programmer Mode, read presses, write LEDs,
and — the part that matters most — always put it back.

LAYER: drivers. The ONLY module in the application that talks MIDI. Everything above
(renderer, modes, controller) deals in frames and events and never sees a byte.

WHY THE EXIT PATH MATTERS MORE THAN THE ENTRY PATH
    Selecting Programmer Mode by SysEx DISABLES the Launchpad's own Setup menu
    (Programmer's Reference p.7). The only ways back are another SysEx or a power
    cycle. On a rig with no monitor and no keyboard, a controller that enters
    Programmer Mode and exits without restoring leaves the front panel unreachable.

    So `close()` is not cleanup, it is a safety contract, and it runs on clean exit,
    on exception, and on signal. Verified against real hardware 2026-08-12: the Setup
    menu still opened after every run, including the runs that failed.

    What it CANNOT survive: a hard kill, power loss, or a crash inside the backend.
    Nothing in Python can. Recovery there is physical — unplug and replug.

WHY A BACKEND PROTOCOL
    CLAUDE.md §10: "keep the device layer behind a thin interface" so the rig can be
    developed off the target. `MidiBackend` is that interface. `MidoBackend` is the
    real one; tests inject a fake and exercise the whole lifecycle — including the
    restore contract — with no hardware and no mido.

PORTED, NOT IMPORTED
    tools/_bench.py proved every byte sequence here against the device. It is a bench
    instrument and application code may not depend on it (tools/README.md), so this is
    that knowledge rewritten, not referenced. Where they disagree, THIS file is what
    ships and docs/launchpad-x-sysex.md is the citation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterator, Protocol, Sequence, runtime_checkable

from launchpad import colors, grid
from launchpad.ports import Port, PortRole, classify, select
from rig.events import PadEvent

log = logging.getLogger(__name__)

__all__ = [
    "MidiBackend",
    "LaunchpadDevice",
    "DeviceIdentity",
    "DeviceError",
    "LedSpec",
    "Lighting",
]


# ---------------------------------------------------------------------------
# SysEx vocabulary — every byte cited to the Programmer's Reference
# ---------------------------------------------------------------------------

# mido carries SysEx payloads WITHOUT F0/F7; it frames them on send. Bome's raw
# strings include the framing. Same bytes, two conventions, and a known source of
# copy-paste bugs — see docs/launchpad-x-sysex.md §3.
NOVATION_ID = (0x00, 0x20, 0x29)
DEVICE_LAUNCHPAD_X = (0x02, 0x0C)  # p.6. The Mini MK3 is 0x02 0x0D — a DIFFERENT device.
HEADER = (*NOVATION_ID, *DEVICE_LAUNCHPAD_X)

CMD_LED_LIGHTING = 0x03  # p.15
CMD_VELOCITY_CURVE = 0x04  # p.25
CMD_LED_SLEEP = 0x09  # p.24
CMD_LED_FEEDBACK = 0x0A  # p.25
CMD_AFTERTOUCH = 0x0B  # p.26
CMD_PROGRAMMER_LIVE = 0x0E  # p.7
CMD_BRIGHTNESS = 0x08  # p.25

MAX_COLOURSPECS = 81  # p.15. The whole surface in one message — MEASURED, it works.

DEVICE_INQUIRY = (0x7E, 0x7F, 0x06, 0x01)  # universal, not Novation-specific. p.6

# data[7] identifies the device family. Two values are legitimate for a Launchpad X:
#   0x13  what the manual prints (p.6)
#   0x03  what the hardware actually sends — MEASURED 2026-08-12, firmware 0351
# This stays a whitelist. Accepting anything would let a Mini MK3 parse as a
# Launchpad X, which is a silent wrong-device failure.
KNOWN_FAMILY_BYTES = frozenset({0x03, 0x13})
_STATE_APPLICATION = 0x01
_STATE_BOOTLOADER = 0x11

# Settle time between entering Programmer Mode and the first accepted LED write.
# Still UNVERIFIED — inherited as a guess and never measured. led_batch_tester.py
# exists to replace it; until it runs, this is deliberately generous.
PROGRAMMER_MODE_SETTLE_S = 0.1


def _clamp7(value: int) -> int:
    """Into 0-127. Anything above corrupts the SysEx stream, not just the colour."""
    return max(0, min(127, int(value)))


class Lighting(Enum):
    """LED Lighting <colourspec> types. p.15."""

    STATIC = 0  # + 1 byte palette entry
    FLASHING = 1  # + 2 bytes: colour B then colour A
    PULSING = 2  # + 1 byte palette entry
    RGB = 3  # + 3 bytes R,G,B each 0-127. The only route to arbitrary colour.


@dataclass(frozen=True)
class LedSpec:
    """One LED's desired appearance. The renderer speaks in these; nothing above sees bytes."""

    index: int
    colour: int = colors.OFF
    lighting: Lighting = Lighting.STATIC
    colour_b: int | None = None  # FLASHING only: the colour it alternates with
    rgb: tuple[int, int, int] | None = None  # RGB only: 0-127 per channel (p.15)

    def payload(self) -> tuple[int, ...]:
        """The <colourspec> bytes for this LED. p.15: type, index, then 1-3 data bytes."""
        if self.lighting is Lighting.RGB:
            r, g, b = self.rgb or (0, 0, 0)
            # 7-bit clamp is not cosmetic: a byte >= 0x80 inside a SysEx payload
            # terminates the message early and corrupts everything after it.
            return (self.lighting.value, self.index, _clamp7(r), _clamp7(g), _clamp7(b))
        if self.lighting is Lighting.FLASHING:
            return (self.lighting.value, self.index, self.colour, self.colour_b or colors.OFF)
        return (self.lighting.value, self.index, self.colour)


@dataclass(frozen=True)
class DeviceIdentity:
    """Parsed Universal Device Inquiry reply. p.6."""

    running_application: bool  # False means it is sitting in the bootloader
    version: str
    raw: tuple[int, ...]

    def __str__(self) -> str:
        where = "application" if self.running_application else "BOOTLOADER"
        return f"Launchpad X, {where}, firmware {self.version}"


class DeviceError(RuntimeError):
    """Something about the device is wrong, stated so a human can act on it."""


# ---------------------------------------------------------------------------
# The thin interface
# ---------------------------------------------------------------------------


@runtime_checkable
class MidiPort(Protocol):
    def close(self) -> None: ...


class MidiInput(MidiPort, Protocol):
    def iter_pending(self) -> Iterator[object]: ...


class MidiOutput(MidiPort, Protocol):
    def send(self, message: object) -> None: ...


@runtime_checkable
class MidiBackend(Protocol):
    """
    Everything this driver needs from the outside world. Implement it with mido for
    the rig, or with a fake for tests. Nothing else in launchpad/ may import mido.
    """

    def input_names(self) -> list[str]: ...
    def output_names(self) -> list[str]: ...
    def open_input(self, name: str) -> MidiInput: ...
    def open_output(self, name: str) -> MidiOutput: ...
    def sysex(self, payload: Sequence[int]) -> object: ...
    def deliver_sysex(self, port: MidiInput) -> None: ...


def parse_device_inquiry(data: Sequence[int]) -> DeviceIdentity | None:
    """
    Reply shape (p.6), F0/F7 already stripped:
        7E <dev> 06 02 00 20 29 <family> <state> 00 00 <4 version bytes>

    MEASURED reply, 2026-08-12:
        7E 00 06 02 00 20 29 03 01 00 00 00 03 05 01
                              ^^ manual prints 0x13 here

    Validates the manufacturer ID and a whitelist of family bytes. Requiring only
    0x13 rejects the real device; requiring nothing accepts a Mini MK3. Both fail
    silently, in opposite directions.
    """
    if len(data) < 9:
        return None
    if data[0] != 0x7E or tuple(data[2:4]) != (0x06, 0x02) or tuple(data[4:7]) != NOVATION_ID:
        return None
    if data[7] not in KNOWN_FAMILY_BYTES:
        return None
    state = data[8]
    if state not in (_STATE_APPLICATION, _STATE_BOOTLOADER):
        return None
    version = "".join(str(b) for b in data[11:15]) or "unknown"
    return DeviceIdentity(state == _STATE_APPLICATION, version, tuple(data))


# ---------------------------------------------------------------------------
# The device
# ---------------------------------------------------------------------------


@dataclass
class LaunchpadDevice:
    """
    Owns the connection for as long as the rig runs.

    Use it as a context manager, or call close() from a finally. Either way the
    Launchpad goes back to Live Mode.
    """

    backend: MidiBackend
    brightness: int = 40
    settle_s: float = PROGRAMMER_MODE_SETTLE_S
    identify_timeout_s: float = 1.0  # injectable so tests do not pay a real timeout

    identity: DeviceIdentity | None = field(default=None, init=False)
    _in: MidiInput | None = field(default=None, init=False)
    _out: MidiOutput | None = field(default=None, init=False)
    _restored: bool = field(default=False, init=False)
    _ports: list[Port] = field(default_factory=list, init=False)

    # -- lifecycle --------------------------------------------------------

    def connect(self) -> DeviceIdentity | None:
        """
        Open the MIDI interface and assert every setting the rig depends on.

        Asserting rather than trusting is deliberate. MEASURED out of the box
        2026-08-12: aftertouch ON (about ten presses produced 130 messages, mostly
        polytouch) and velocity sensitivity ON. Both flood the event loop. The device
        also forgets all of it across a replug, and ESD-triggered replugs are an
        expected live failure, not an edge case.
        """
        self._ports = classify(self.backend.input_names())
        chosen_in = select(self._ports, PortRole.MIDI)
        chosen_out = select(classify(self.backend.output_names()), PortRole.MIDI)
        for port in (chosen_in, chosen_out):
            if port.how.value == "ordinal":
                log.warning(
                    "port %r classified by POSITION only, not by name — verify it is "
                    "really the second USB interface", port.name
                )

        self._in = self.backend.open_input(chosen_in.name)
        self._out = self.backend.open_output(chosen_out.name)
        log.info("launchpad in=%r out=%r", chosen_in.name, chosen_out.name)

        # rtmidi discards SysEx by default and mido does not clear it. Without this
        # the device inquiry reply never arrives and a healthy device reports "no
        # reply" — MEASURED 2026-08-12, and it looked exactly like a hardware fault.
        self.backend.deliver_sysex(self._in)

        self._restored = False
        self.identity = self._identify(self.identify_timeout_s)
        if self.identity is None:
            log.warning("no device inquiry reply — a port existing is not a live device")
        else:
            log.info("%s", self.identity)
            if not self.identity.running_application:
                raise DeviceError(
                    "Launchpad is in its BOOTLOADER, not the application. Unplug it, "
                    "replug WITHOUT holding Capture MIDI, and retry."
                )

        self._send(CMD_PROGRAMMER_LIVE, 1)  # p.7
        time.sleep(self.settle_s)
        self._send(CMD_LED_FEEDBACK, 1, 1)  # p.25 — external feedback ON or LEDs do nothing
        self._send(CMD_VELOCITY_CURVE, 3, 127)  # p.25 — fixed velocity: pads are buttons
        self._send(CMD_AFTERTOUCH, 2, 1)  # p.26 — type 2 = OFF. Stops the polytouch flood
        self._send(CMD_LED_SLEEP, 1)  # p.24 — never blank; a dark surface reads as a dead rig
        self._send(CMD_BRIGHTNESS, max(0, min(127, self.brightness)))  # p.25
        self.clear()
        log.info("programmer mode entered, device settings asserted")
        return self.identity

    def hand_over(self) -> None:
        """
        Blank the surface and return the device to Live Mode WITHOUT closing.

        For handing the Launchpad to Ableton while keeping the input port open, so
        the rig can still hear the escape gesture that takes it back
        (rig/escape_hatch.py). Closing would work too and would be deaf.

        Blanking first matters: Live's script paints what it wants to paint, and
        whatever the rig left lit would otherwise sit there underneath until Live
        happened to overwrite that pad.
        """
        try:
            self.clear()
            self._send(CMD_PROGRAMMER_LIVE, 0)  # p.7 — back to Live Mode
            log.info("handed the surface to Live Mode (input stays open)")
        except Exception as exc:  # noqa: BLE001 -- a failed handover must not raise
            log.warning("could not hand over cleanly: %s", exc)

    def reassert(self) -> None:
        """
        Take the surface back: Programmer Mode and every device setting, again.

        Ableton has been driving the device into DAW mode and its own layout, so
        NOTHING about its state can be assumed -- velocity curve, aftertouch, LED
        feedback and brightness are all Live's now. This re-runs the same sequence
        connect() does, which is why it is worth having in one place.
        """
        self._send(CMD_PROGRAMMER_LIVE, 1)
        time.sleep(self.settle_s)
        self._send(CMD_LED_FEEDBACK, 1, 1)
        self._send(CMD_VELOCITY_CURVE, 3, 127)
        self._send(CMD_AFTERTOUCH, 2, 1)
        self._send(CMD_LED_SLEEP, 1)
        self._send(CMD_BRIGHTNESS, max(0, min(127, self.brightness)))
        self.clear()
        log.info("programmer mode re-asserted after Ableton had the surface")

    def close(self, restore: bool = True) -> None:
        """
        Let go of the device. Idempotent — safe from a finally block and an atexit
        handler on the same run.

        `restore=True` (the default) blanks the surface and returns the device to
        Live Mode. That is the safety contract: Programmer Mode disables the
        Launchpad's Setup menu, so a controller that exits without restoring strands
        a headless rig.

        `restore=False` is for a device that has ALREADY GONE — a yanked cable, an
        ESD reset. Two reasons, and the second is the important one:

          1. It cannot work. Every write fails; there is nothing on the other end.
          2. It is not needed. The Launchpad powers on into Live Mode (manual p.18),
             so a device that was unplugged is already back in Live Mode when it
             returns. There is nothing to put right.

        MEASURED 2026-08-13: without this distinction, a twelve-cycle replug test
        logged "COULD NOT RESTORE LIVE MODE — the Setup menu stays disabled" twelve
        times. Every one of those was false, and at a gig it is exactly the wrong
        thing to read while looking for the real fault.
        """
        if self._restored:
            return
        self._restored = True
        if restore and self._out is not None:
            try:
                self.clear()
                self._send(CMD_PROGRAMMER_LIVE, 0)  # p.7 — THE line that matters
                log.info("live mode restored")
            except Exception as exc:  # noqa: BLE001 — last line of defence, never re-raise
                log.error(
                    "COULD NOT RESTORE LIVE MODE (%s). The Setup menu stays disabled "
                    "until the Launchpad is unplugged and replugged.", exc
                )
        elif not restore:
            log.debug("device already gone; skipping restore (it powers up in Live Mode)")
        for port in (self._in, self._out):
            try:
                if port is not None:
                    port.close()
            except Exception:  # noqa: BLE001
                pass
        self._in = self._out = None

    def __enter__(self) -> "LaunchpadDevice":
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def connected(self) -> bool:
        return self._in is not None and self._out is not None

    # -- output -----------------------------------------------------------

    def set_leds(self, specs: Sequence[LedSpec]) -> None:
        """
        Paint LEDs. Chunked at the documented 81-entry ceiling (p.15).

        Chunking rather than trusting: 81 is what the manual allows and what was
        MEASURED to light the whole surface, but a caller passing 90 must not
        silently lose the tail — or, worse, have the device reject the lot.
        """
        if not specs:
            return
        for start in range(0, len(specs), MAX_COLOURSPECS):
            chunk = specs[start : start + MAX_COLOURSPECS]
            payload: list[int] = [CMD_LED_LIGHTING]
            for spec in chunk:
                payload.extend(spec.payload())
            self._send(*payload)

    def clear(self) -> None:
        """Blank all 81 LEDs in one message. Palette 0 is off, not grey (p.14)."""
        self.set_leds([LedSpec(index=i, colour=colors.OFF) for i in grid.ALL_INDICES])

    # -- input ------------------------------------------------------------

    def read_events(self) -> list[PadEvent]:
        """
        Drain everything waiting and return it as domain events.

        Two things the manual makes non-obvious:
          * a RELEASE is note_on with velocity 0 (p.6), not note_off. Treating "any
            note_on" as a press means every release counts as one.
          * the 8x8 grid sends NOTE, the surrounding frame sends CC (p.10, MEASURED
            across all 80 pressable controls). Both must be read.
        """
        if self._in is None:
            return []
        events: list[PadEvent] = []
        for message in self._in.iter_pending():
            kind = getattr(message, "type", None)
            if kind == "control_change":
                number, value = message.control, message.value
            elif kind in ("note_on", "note_off"):
                number, value = message.note, message.velocity
            else:
                continue  # polytouch, clock, active sense — not ours
            pressed = kind != "note_off" and value > 0
            if not grid.is_pressable(number):
                log.debug("ignoring %s %s — not a pressable control", kind, number)
                continue
            events.append(PadEvent(note=number, velocity=value, pressed=pressed))
        return events

    # -- internals --------------------------------------------------------

    def _send(self, *payload: int) -> None:
        if self._out is None:
            raise DeviceError("not connected")
        self._out.send(self.backend.sysex((*HEADER, *payload)))

    def _identify(self, timeout_s: float = 1.0) -> DeviceIdentity | None:
        assert self._in is not None and self._out is not None
        for _ in self._in.iter_pending():
            pass
        self._out.send(self.backend.sysex(DEVICE_INQUIRY))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for message in self._in.iter_pending():
                if getattr(message, "type", None) == "sysex":
                    identity = parse_device_inquiry(tuple(message.data))
                    if identity is not None:
                        return identity
            time.sleep(0.005)
        return None
