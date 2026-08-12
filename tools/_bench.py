"""
Shared bench-instrument support for the Phase 1 tools.

LAYER: none. This is not application code.

WHY IT EXISTS
    All five Phase 1 tools open the Launchpad, put it in Programmer Mode, and must
    restore Live Mode on the way out. Selecting Programmer Mode by SysEx disables the
    device's Setup menu (Programmer's Reference p.7), so a tool that exits without
    restoring leaves the front panel unreachable with no software recovery path.

    That contract is worth exactly one implementation, not five.

WHO CALLS IT
    Only the sibling scripts in tools/. Nothing in rig/, launchpad/ or ableton/ may
    import from here — these are throwaway instruments, and their findings reach the
    application as committed literals, never as a dependency.

WHAT IT PROVIDES
    find_ports()      port discovery + classification, honest about ambiguity
    LaunchpadBench    context manager owning the connect/restore lifecycle
    Recorder          writes dated, provenance-stamped result files

ALL SYSEX BYTES ARE CITED
    Source: Novation Launchpad X Programmer's Reference Manual, 29pp.
    docs/datasheets/novation-launchpad-x-programmers-reference.pdf
    Page numbers appear against each constant.
"""

from __future__ import annotations

import atexit
import json
import platform
import re
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Iterator, Sequence

try:
    import mido
except ImportError:  # pragma: no cover - environment problem, not a logic path
    sys.exit(
        "mido is not installed.\n"
        "    python -m venv .venv\n"
        "    .venv\\Scripts\\activate      (Windows)\n"
        "    pip install -r requirements.txt"
    )


# ---------------------------------------------------------------------------
# SysEx vocabulary
# ---------------------------------------------------------------------------

# mido carries SysEx payloads WITHOUT the F0/F7 framing; it adds them on send.
# Bome's raw-MIDI strings include the framing. Same bytes, two conventions --
# a documented source of copy-paste bugs. Everything here is mido convention.

NOVATION_ID = (0x00, 0x20, 0x29)
DEVICE_LAUNCHPAD_X = (0x02, 0x0C)  # p.6. The Mini MK3 is 0x02 0x0D -- not this device.

HEADER = (*NOVATION_ID, *DEVICE_LAUNCHPAD_X)


class Cmd(Enum):
    """SysEx command bytes. Table on p.29."""

    SELECT_LAYOUT = 0x00
    LED_LIGHTING = 0x03
    VELOCITY_CURVE = 0x04
    TEXT_SCROLL = 0x07
    BRIGHTNESS = 0x08
    LED_SLEEP = 0x09
    LED_FEEDBACK = 0x0A
    AFTERTOUCH = 0x0B
    PROGRAMMER_LIVE = 0x0E
    DAW_MODE = 0x10


class LightingType(Enum):
    """LED Lighting <colourspec> types. p.15."""

    STATIC = 0  # + 1 byte palette entry
    FLASHING = 1  # + 2 bytes: colour B, colour A
    PULSING = 2  # + 1 byte palette entry
    RGB = 3  # + 3 bytes: R, G, B (0-127)


# Universal Device Inquiry -- not Novation-specific, no header. p.6
DEVICE_INQUIRY = (0x7E, 0x7F, 0x06, 0x01)

# Programmer mode covers the full 9x9: note = (row * 10) + column,
# rows 1-9 bottom-to-top, columns 1-9 left-to-right. p.10 renders this as an
# image, so it is INFERRED. Three corners are confirmed in prose on p.14:
#   11 = lower left, 81 = upper left, 18 = lower right.
# launchpad_note_tester.py exists to settle the rest.
ALL_LED_INDICES: tuple[int, ...] = tuple(
    row * 10 + col for row in range(1, 10) for col in range(1, 10)
)
PAD_GRID_INDICES: tuple[int, ...] = tuple(
    row * 10 + col for row in range(1, 9) for col in range(1, 9)
)

MAX_COLOURSPECS_PER_MESSAGE = 81  # p.15, documented ceiling. Not a measured throughput.
PALETTE_SIZE = 128  # p.12, indices 0-127

# Settle time between entering Programmer Mode and the first accepted LED write.
# UNVERIFIED -- inherited from an early draft. led_batch_tester.py measures the
# real figure; until then this is a guess and is labelled as one.
PROGRAMMER_MODE_SETTLE_S = 0.1


def _sysex(*payload: int) -> "mido.Message":
    """Build a Novation-addressed SysEx message. Framing is mido's job."""
    return mido.Message("sysex", data=[*HEADER, *payload])


def programmer_mode(enabled: bool) -> "mido.Message":
    """p.7. mode: 0 = Live, 1 = Programmer."""
    return _sysex(Cmd.PROGRAMMER_LIVE.value, 1 if enabled else 0)


def led_static(index: int, colour: int) -> "mido.Message":
    """Single static LED via the lighting SysEx. p.15."""
    return _sysex(Cmd.LED_LIGHTING.value, LightingType.STATIC.value, index, colour)


def led_batch(pairs: Sequence[tuple[int, int]]) -> "mido.Message":
    """
    Many LEDs in one message. p.15 allows up to 81 <colourspec> entries.

    Deliberately does NOT clamp to 81 -- led_batch_tester.py needs to send an
    over-length message to observe what the device actually does with it.
    """
    payload: list[int] = [Cmd.LED_LIGHTING.value]
    for index, colour in pairs:
        payload += [LightingType.STATIC.value, index, colour]
    return _sysex(*payload)


def clear_all() -> "mido.Message":
    """Blank the whole surface in one write. Palette 0 is off, not grey. p.14."""
    return led_batch([(i, 0) for i in ALL_LED_INDICES])


# ---------------------------------------------------------------------------
# Port discovery
# ---------------------------------------------------------------------------


class PortRole(Enum):
    DAW = "daw"
    MIDI = "midi"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Port:
    name: str
    role: PortRole
    ordinal: int  # position among Launchpad ports, in the order the backend reported
    classified_by: str  # "name" | "windows-multiport" -- how the role was decided
    interface: int | None = None  # 1-based USB interface, where it could be determined


# Windows names multi-port USB MIDI devices by its own convention, NOT the vendor's:
# the first interface takes the bare device name, and every later one is prefixed
# MIDIIN<n> / MIDIOUT<n>, n starting at 2. Measured on the rig 2026-08-12:
#
#     inputs :  'LPX MIDI 0'   'MIDIIN2 (LPX MIDI) 1'
#     outputs:  'LPX MIDI 1'   'MIDIOUT2 (LPX MIDI) 2'
#
# The manual's names ("LPX DAW In/Out", "LPX MIDI In/Out", p.6) appear NOWHERE.
# Naive substring matching on "daw"/"midi" therefore labels all four as MIDI, which
# is how the first version of this file crashed the moment real hardware appeared.
_WINDOWS_MULTIPORT = re.compile(r"\bMIDI(?:IN|OUT)(\d+)\s*\(", re.IGNORECASE)

# Trailing integer that mido/rtmidi appends to disambiguate duplicate names.
_RTMIDI_SUFFIX = re.compile(r"\s+\d+$")


def _looks_like_launchpad(name: str) -> bool:
    lowered = name.lower()
    return "launchpad" in lowered or "lpx" in lowered


def _interface_number(name: str) -> int:
    """1 for the bare device name, n for a MIDIIN<n>/MIDIOUT<n> prefixed name."""
    match = _WINDOWS_MULTIPORT.search(name)
    return int(match.group(1)) if match else 1


def find_ports(names: Sequence[str]) -> list[Port]:
    """
    Pick the Launchpad ports out of a backend port list and label each one.

    Two naming worlds, and the difference is not cosmetic:

      macOS / Linux   names say which is which -- 'LPX DAW Out', 'LPX MIDI Out'.
      Windows         names say nothing. Every port reads 'LPX MIDI'; the second
                      interface is distinguished only by a MIDIIN2/MIDIOUT2 prefix.

    So: trust an explicit 'daw' in the name when one exists. Otherwise, if any
    sibling port carries the Windows multi-port prefix, we are in the Windows world
    and interface number decides the role, per the manual's ordinal rule (p.6):
    first interface = DAW, second = MIDI.

    > That ordinal rule is the MANUAL'S CLAIM, not a measurement. It has not been
    > confirmed against this hardware. Programmer Mode only works on the MIDI
    > interface, so the cheapest proof is: enter Programmer Mode on the candidate
    > output, press a pad, see whether the matching input reports it.
    """
    candidates = [n for n in names if _looks_like_launchpad(n)]
    windows_style = any(_WINDOWS_MULTIPORT.search(n) for n in candidates)

    ports: list[Port] = []
    for ordinal, name in enumerate(candidates):
        lowered = name.lower()

        if "daw" in lowered:  # explicit, unambiguous -- believe it
            ports.append(Port(name, PortRole.DAW, ordinal, "name", _interface_number(name)))
            continue

        if windows_style:
            iface = _interface_number(name)
            role = {1: PortRole.DAW, 2: PortRole.MIDI}.get(iface, PortRole.UNKNOWN)
            ports.append(Port(name, role, ordinal, "windows-multiport", iface))
            continue

        if "midi" in lowered:  # explicit on macOS/Linux, meaningless on Windows
            ports.append(Port(name, PortRole.MIDI, ordinal, "name", _interface_number(name)))
            continue

        ports.append(Port(name, PortRole.UNKNOWN, ordinal, "name", None))
    return ports


def select_port(ports: Sequence[Port], role: PortRole) -> Port:
    matches = [p for p in ports if p.role is role]
    if not matches:
        raise BenchError(
            f"No Launchpad {role.value.upper()} port found.\n"
            f"Saw: {[p.name for p in ports] or 'nothing that looks like a Launchpad'}\n"
            "Run midi_port_inspector.py first."
        )
    if len(matches) > 1:
        raise BenchError(
            f"Ambiguous: {len(matches)} ports classified as {role.value.upper()}: "
            f"{[m.name for m in matches]}\n"
            "Two Launchpads attached, or a stale virtual port. Record this and resolve "
            "it before trusting any result."
        )
    return matches[0]


class BenchError(RuntimeError):
    """A bench precondition failed. Always actionable, never a stack trace at the user."""


def _deliver_sysex(inport: "mido.ports.BaseInput") -> None:
    """
    Stop python-rtmidi from throwing our SysEx replies away.

    RtMidiIn defaults to ignoreTypes(sysex=True, timing=True, active_sense=True), and
    mido does not clear it. MEASURED consequence on the rig 2026-08-12: the Universal
    Device Inquiry reply never arrived, so the boot-time presence check reported "no
    reply" from a device that was sitting there working perfectly. Notes and CCs were
    unaffected, which is what made it look like a hardware problem rather than a
    default.

    Anything that expects a SysEx *reply* -- device inquiry, and every readback
    command in the p.29 table -- is broken without this.
    """
    rt = getattr(inport, "_rt", None) or getattr(inport, "_port", None)
    if rt is None:
        return
    try:
        rt.ignore_types(sysex=False, timing=False, active_sense=False)
    except Exception:  # noqa: BLE001 -- best effort; a different backend may not have it
        pass


# ---------------------------------------------------------------------------
# Device identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceIdentity:
    """Parsed Universal Device Inquiry reply. p.6."""

    running_application: bool  # False => sitting in the bootloader
    version: str
    raw: tuple[int, ...]

    def __str__(self) -> str:
        state = "application" if self.running_application else "BOOTLOADER"
        return f"Launchpad X, {state}, version {self.version}"


_INQUIRY_HEAD = (0x7E,)  # data[1] is the device ID and varies
_INQUIRY_SUBID = (0x06, 0x02)  # data[2:4]
_NOVATION = (0x00, 0x20, 0x29)  # data[4:7]
_STATE_APPLICATION = 0x01
_STATE_BOOTLOADER = 0x11


def parse_device_inquiry(data: Sequence[int]) -> DeviceIdentity | None:
    """
    Reply shape per the manual (p.6), mido convention so F0/F7 are stripped:
        7E 00 06 02 00 20 29 13 <state> 00 00 <4 version bytes>

    MEASURED on the rig 2026-08-12, the actual reply was:
        7E 00 06 02 00 20 29 03 01 00 00 00 03 05
                              ^^
    Byte 7 is 0x03, NOT the 0x13 the manual prints, and the whole message is one
    byte shorter than the manual's layout implies. The state byte that follows it
    is 0x01 = application, which does match.

    So byte 7 is NOT validated here -- the first version of this function required
    0x13 and silently returned None against real hardware, which is how the boot-time
    presence check "worked" in tests and failed on the bench. What is validated is
    the part the MIDI spec guarantees: the 7E .. 06 02 sub-ID and the Novation
    manufacturer ID. Everything after is reported, not asserted.
    """
    if len(data) < 9:
        return None
    if tuple(data[:1]) != _INQUIRY_HEAD:
        return None
    if tuple(data[2:4]) != _INQUIRY_SUBID or tuple(data[4:7]) != _NOVATION:
        return None
    state = data[8]
    if state not in (_STATE_APPLICATION, _STATE_BOOTLOADER):
        return None
    version = ".".join(str(b) for b in data[11:]) or "unknown"
    return DeviceIdentity(state == _STATE_APPLICATION, version, tuple(data))


# ---------------------------------------------------------------------------
# The session lifecycle -- the safety-critical part
# ---------------------------------------------------------------------------


@dataclass
class LaunchpadBench:
    """
    Owns a Launchpad connection for the duration of a bench script.

    THE CONTRACT
        On the way in:  identify the device, then enter Programmer Mode.
        On the way out: blank the surface, then restore Live Mode -- on clean exit,
                        on exception, on Ctrl+C, and on SIGTERM.

    WHY THE EXIT PATH MATTERS MORE THAN THE ENTRY PATH
        Programmer Mode entered by SysEx disables the Setup menu (p.7). If this
        object is garbage-collected without restoring, the Launchpad's own UI is
        gone until someone sends more SysEx or pulls the USB cable. On a sealed
        headless rig neither is convenient, and during a gig neither is possible.

    KNOWN LIMIT -- state it, do not paper over it
        A hard kill (taskkill /F, power loss, a Python segfault in the backend)
        runs no Python at all. Nothing here can help. Recovery is physical: unplug
        and replug the Launchpad. Every tool prints this before it starts.
    """

    role: PortRole = PortRole.MIDI  # Programmer Mode lives on the MIDI interface, p.6
    settle_s: float = PROGRAMMER_MODE_SETTLE_S

    inport: "mido.ports.BaseInput | None" = field(default=None, init=False)
    outport: "mido.ports.BaseOutput | None" = field(default=None, init=False)
    identity: DeviceIdentity | None = field(default=None, init=False)
    _restored: bool = field(default=False, init=False)

    # -- entry ------------------------------------------------------------

    def open(self) -> "LaunchpadBench":
        in_ports = find_ports(mido.get_input_names())
        out_ports = find_ports(mido.get_output_names())

        chosen_in = select_port(in_ports, self.role)
        chosen_out = select_port(out_ports, self.role)

        for port in (chosen_in, chosen_out):
            if port.classified_by == "ordinal":
                print(
                    f"  ! '{port.name}' was classified as {port.role.value.upper()} by "
                    "POSITION, not by name. Verify against the manual's ordinal rule "
                    "(p.6) before trusting anything this run produces."
                )

        self.inport = mido.open_input(chosen_in.name)
        self.outport = mido.open_output(chosen_out.name)
        _deliver_sysex(self.inport)
        print(f"  in : {chosen_in.name}")
        print(f"  out: {chosen_out.name}")

        # Restore is armed BEFORE Programmer Mode is entered, so an exception
        # anywhere below still unwinds through it.
        self._arm_restore()

        self.identity = self._identify()
        if self.identity is None:
            print(
                "  ! Device inquiry got no reply. The port opened, but nothing "
                "answered. Do not treat 'a port exists' as 'the device is alive'."
            )
        else:
            print(f"  {self.identity}")
            if not self.identity.running_application:
                raise BenchError(
                    "The Launchpad is in its BOOTLOADER, not the application.\n"
                    "Unplug it, replug WITHOUT holding Capture MIDI, and try again."
                )

        self.outport.send(programmer_mode(True))
        time.sleep(self.settle_s)
        print(f"  Programmer Mode entered (settled {self.settle_s * 1000:.0f} ms)")
        return self

    def _identify(self, timeout_s: float = 1.0) -> DeviceIdentity | None:
        assert self.inport and self.outport
        self._drain()
        self.outport.send(mido.Message("sysex", data=list(DEVICE_INQUIRY)))
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for message in self.inport.iter_pending():
                if message.type == "sysex":
                    identity = parse_device_inquiry(message.data)
                    if identity is not None:
                        return identity
            time.sleep(0.01)
        return None

    # -- exit -------------------------------------------------------------

    def _arm_restore(self) -> None:
        """Cover every exit route Python can observe."""
        atexit.register(self.restore)
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError, AttributeError):
                # Not the main thread, or the platform lacks it. atexit and the
                # context manager's finally still cover the common cases.
                pass

    def _on_signal(self, signum: int, _frame: object) -> None:
        # Raising SystemExit unwinds the stack, so `finally` blocks run and atexit
        # fires. Calling restore() directly from a handler would not unwind, and the
        # ports would stay open.
        print(f"\n  signal {signum} -- restoring Live Mode before exit")
        raise SystemExit(128 + signum)

    def restore(self) -> None:
        """Idempotent. Called from finally, from atexit, and possibly from both."""
        if self._restored:
            return
        self._restored = True
        if self.outport is not None:
            try:
                self.outport.send(clear_all())
                self.outport.send(programmer_mode(False))
                print("  Live Mode restored, surface cleared")
            except Exception as exc:  # noqa: BLE001 -- last line of defence
                print(
                    f"\n  !! COULD NOT RESTORE LIVE MODE: {exc}\n"
                    "  !! The Setup menu is disabled until you unplug and replug "
                    "the Launchpad. Do that now.\n"
                )
        for port in (self.inport, self.outport):
            try:
                if port is not None:
                    port.close()
            except Exception:  # noqa: BLE001
                pass

    def _drain(self) -> None:
        if self.inport is not None:
            for _ in self.inport.iter_pending():
                pass

    # -- context manager --------------------------------------------------

    def __enter__(self) -> "LaunchpadBench":
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.restore()

    # -- convenience ------------------------------------------------------

    def send(self, message: "mido.Message") -> None:
        assert self.outport is not None
        self.outport.send(message)

    def wait_for_event(
        self, timeout_s: float | None = None, presses_only: bool = False
    ) -> "mido.Message | None":
        """
        Block for one note/CC message. Returns None on timeout.

        presses_only skips releases. The device signals a release as note_on with
        velocity 0 (p.6), so "any note_on" and "a press" are NOT the same thing --
        a release still in the queue reads as a press on the next position. That
        never bit us in the 2026-08-12 sweep (the two mismatches there were a
        misplaced finger), but the ambiguity is real and one-line to remove.
        """
        assert self.inport is not None
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while deadline is None or time.monotonic() < deadline:
            for message in self.inport.iter_pending():
                if message.type not in ("note_on", "note_off", "control_change"):
                    continue
                if presses_only:
                    if message.type == "note_off":
                        continue
                    value = getattr(message, "velocity", None)
                    if value is None:
                        value = getattr(message, "value", 0)
                    if not value:
                        continue
                return message
            time.sleep(0.005)
        return None

    def drain(self) -> None:
        """Discard everything queued. Aftertouch makes one press many messages."""
        self._drain()


# ---------------------------------------------------------------------------
# Result recording
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class Recorder:
    """
    Writes a findings file with its provenance attached.

    A constant without a date and a method is a guess wearing a costume. Every
    result file this produces carries both in its header, so that when it is
    pasted into launchpad/grid.py the comment travels with it.
    """

    tool: str
    lines: list[str] = field(default_factory=list)

    def add(self, line: str = "") -> None:
        self.lines.append(line)
        print(line)

    def header(self) -> list[str]:
        return [
            f"# Recorded by tools/{self.tool}",
            f"# Date:     {date.today().isoformat()}",
            f"# Machine:  {platform.system()} {platform.release()}",
            f"# Backend:  {mido.backend.name if mido.backend else 'unknown'}",
            "# Source:   physical measurement against the hardware",
            "#",
            "# Paste into the target module WITH this header. It is the provenance.",
            "",
        ]

    def save(self, filename: str) -> Path:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / filename
        path.write_text("\n".join([*self.header(), *self.lines, ""]), encoding="utf-8")
        print(f"\n  written: {path}")
        return path


def load_candidate_palette() -> dict[int, str]:
    """
    The 128-entry table copied from Launchpad Mini MK3 research.

    NOT AUTHORITATIVE. Different device. Every index the Launchpad X manual names
    in prose happens to agree with it, which is suggestive and nothing more.
    led_color_tester.py exists to replace it.
    """
    path = Path(__file__).parent.parent / "docs" / "colour-palette-candidate.json"
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text()).items()}


# ---------------------------------------------------------------------------
# Presentation
# ---------------------------------------------------------------------------

WARNING = """
  ------------------------------------------------------------------
  This puts the Launchpad into Programmer Mode, which DISABLES its
  Setup menu until Live Mode is restored (manual p.7).

  Exit with Ctrl+C or let the script finish -- both restore it.
  If you kill this process hard, or it dies with the machine, nothing
  restores it. Recovery is then physical: unplug and replug the USB.
  ------------------------------------------------------------------
"""


def banner(title: str, purpose: str, answers: str) -> None:
    print(f"\n=== {title} ===")
    print(f"Purpose: {purpose}")
    print(f"Answers: {answers}")
    print(WARNING)


def require_windows(tool: str) -> None:
    if platform.system() != "Windows":
        print(
            f"\n  ! {tool} is Windows-only and you are on {platform.system()}.\n"
            "  ! The values it collects are Windows-specific. Running it elsewhere\n"
            "  ! proves nothing. Run it on the Beelink.\n"
        )
        sys.exit(1)


def prompt(message: str, default: str = "", wait_s: float = 0.0) -> str:
    """
    Ask the operator something, and cope with there being no operator terminal.

    These tools are driven over SSH from another machine, where stdin is at EOF
    immediately. The first version raised SystemExit on EOF, which meant a bare
    "Ready? press Enter" line aborted the whole run before it started -- observed
    2026-08-12 on the first attempt at the frame sweep.

    With no tty we announce the default and continue. Where the prompt exists to
    give a human TIME rather than to collect an answer -- "photograph this now" --
    pass wait_s and the pause happens anyway. The Launchpad's own lit pad is the
    real prompt in the guided sweeps, so nothing is lost.
    """
    if not sys.stdin.isatty():
        note = f" [no tty, continuing{f', waiting {wait_s:.0f}s' if wait_s else ''}]"
        print(f"{message}{note}", flush=True)
        if wait_s:
            time.sleep(wait_s)
        return default
    try:
        return input(message)
    except (EOFError, KeyboardInterrupt):
        raise SystemExit(130)


@contextmanager
def bench(role: PortRole = PortRole.MIDI) -> Iterator[LaunchpadBench]:
    """Open a session, guaranteeing restore. The only way tools should connect."""
    session = LaunchpadBench(role=role)
    try:
        with session:
            yield session
    except BenchError as exc:
        print(f"\n  STOPPED: {exc}\n")
        raise SystemExit(1)
