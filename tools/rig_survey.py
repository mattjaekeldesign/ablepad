"""
One-shot, read-only survey of the Windows machine. Run this FIRST, before anything else.

LAYER: none. Bench instrument. Nothing in rig/, launchpad/ or ableton/ may import this.

ANSWERS
    Every roadmap unknown that can be collected without a human at the Launchpad:

        Phase 0   Ableton exe path, ASIO drivers, Python/Git toolchain,
                  C:\\LiveRig tree, auto-login state
        Phase 1   verbatim MIDI port names, EVO 8 PnP names + driver version
        Phase 4   where the .als files live
        Phase 6   Wi-Fi hotspot capability, OpenSSH server state
        Phase 7   power plan, sleep states, scheduled tasks

    What it CANNOT answer — and the interactive tools that do:
        the 9x9 note/CC map          -> launchpad_note_tester.py
        the colour palette           -> led_color_tester.py
        batch SysEx timing           -> led_batch_tester.py
        port open-ability/exclusivity-> midi_port_inspector.py

WHY IT IS STDLIB-ONLY
    This is the first thing run on a fresh machine — before the venv exists, before
    requirements.txt is installed. A survey tool that needs pip output to run cannot
    survey a machine that has never seen pip. Everything here is ctypes, winreg,
    subprocess and pathlib.

WHY IT IS READ-ONLY
    It never opens a MIDI port and never sends a byte to the Launchpad, so there is
    no Programmer-Mode restore contract to honour and no interference with whoever
    currently holds a port. MIDI names come from the WinMM device table (the same
    API python-rtmidi wraps, so the strings match what mido will later report).

    KNOWN LIMIT: WinMM truncates device names to 31 characters (MAXPNAMELEN).
    python-rtmidi reads through the same API, so the truncated string is still the
    string to match on — but it is truncated, and the report says so.

FAILURE POLICY
    Every section runs inside a guard. A section that fails records its error and
    the survey continues — a machine with no Wi-Fi adapter still reports its MIDI
    ports. An empty or failed section is a finding, not a crash.

RUN IT
    python tools\\rig_survey.py --label first-boot
    Re-run with a new --label after every driver install or hardware change.
"""

from __future__ import annotations

import argparse
import getpass
import os
import platform
import subprocess
import sys
import traceback
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Iterator

# ---------------------------------------------------------------------------
# Report plumbing (self-contained: _bench.Recorder needs mido, this must not)
# ---------------------------------------------------------------------------

RESULTS_DIR = Path(__file__).parent / "results"


@dataclass
class Section:
    """One titled block of findings, tagged with the roadmap item it feeds."""

    title: str
    roadmap: str  # which checkbox this answers, e.g. "Phase 0: Ableton exe path"
    lines: list[str] = field(default_factory=list)
    failed: bool = False

    def add(self, line: str = "") -> None:
        self.lines.append(line)


@dataclass
class Survey:
    label: str
    sections: list[Section] = field(default_factory=list)

    def run_section(self, title: str, roadmap: str, fn: Callable[[Section], None]) -> None:
        section = Section(title, roadmap)
        print(f"  [{title}] ...", flush=True)
        try:
            fn(section)
        except Exception:  # noqa: BLE001 -- a failed section is a finding
            section.failed = True
            section.add("!! SECTION FAILED — this is a finding, record it, do not hide it")
            for ln in traceback.format_exc(limit=3).splitlines():
                section.add(f"!!   {ln}")
        self.sections.append(section)

    def render(self) -> str:
        out = [
            "# Recorded by tools/rig_survey.py",
            f"# Date:     {date.today().isoformat()}",
            f"# Label:    {self.label}",
            f"# Machine:  {platform.node()} — {platform.platform()}",
            f"# User:     {getpass.getuser()}",
            f"# Python:   {sys.version.split()[0]} ({sys.executable})",
            "# Source:   read-only queries against the live machine",
            "#",
            "# Paste values into their target modules WITH this header. It is the provenance.",
            "",
        ]
        for s in self.sections:
            mark = "FAILED" if s.failed else "ok"
            out.append("=" * 74)
            out.append(f"== {s.title}   [{mark}]")
            out.append(f"== feeds: {s.roadmap}")
            out.append("=" * 74)
            out.extend(s.lines or ["(nothing found)"])
            out.append("")
        return "\n".join(out) + "\n"

    def save(self) -> Path:
        RESULTS_DIR.mkdir(exist_ok=True)
        path = RESULTS_DIR / f"rig-survey-{self.label}.txt"
        path.write_text(self.render(), encoding="utf-8")
        return path


# ---------------------------------------------------------------------------
# Shared query helpers
# ---------------------------------------------------------------------------


def run(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """Run a command, merge stderr in, never raise on non-zero exit."""
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
    except FileNotFoundError:
        return 127, f"(command not found: {cmd[0]})"
    except subprocess.TimeoutExpired:
        return 124, f"(timed out after {timeout}s)"
    output = completed.stdout
    if completed.returncode != 0 and completed.stderr:
        output += "\n" + completed.stderr
    return completed.returncode, output.strip()


def powershell(command: str, timeout: int = 60) -> tuple[int, str]:
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        timeout=timeout,
    )


def reg_values(hive_root: str, key_path: str) -> dict[str, object]:
    """All values under one registry key. Empty dict if the key is absent."""
    import winreg

    hive = getattr(winreg, hive_root)
    values: dict[str, object] = {}
    try:
        with winreg.OpenKey(hive, key_path) as key:
            index = 0
            while True:
                try:
                    name, value, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                values[name] = value
                index += 1
    except FileNotFoundError:
        pass
    return values


def reg_subkeys(hive_root: str, key_path: str) -> list[str]:
    import winreg

    hive = getattr(winreg, hive_root)
    names: list[str] = []
    try:
        with winreg.OpenKey(hive, key_path) as key:
            index = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    break
                index += 1
    except FileNotFoundError:
        pass
    return names


def grab(text: str, *needles: str) -> Iterator[str]:
    """Lines of text containing any needle, case-insensitive."""
    lowered = [n.lower() for n in needles]
    for line in text.splitlines():
        if any(n in line.lower() for n in lowered):
            yield line.rstrip()


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


def sec_system(s: Section) -> None:
    s.add(f"Computer name : {platform.node()}")
    s.add(f"OS            : {platform.platform()}")
    s.add(f"Logged-in user: {getpass.getuser()}")
    s.add(f"Python running: {sys.version.split()[0]} at {sys.executable}")
    code, out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-CimInstance Win32_OperatingSystem).LastBootUpTime"])
    if code == 0 and out:
        s.add(f"Last boot     : {out}")
    s.add()
    s.add("Roadmap wants the account to be 'LiveRig'. If the user above is not that,")
    s.add("the Phase 0 account step is not done yet.")


def sec_toolchain(s: Section) -> None:
    for cmd, label in (
        (["py", "-0p"], "Installed Pythons (py launcher)"),
        (["git", "--version"], "Git"),
        (["pip", "--version"], "pip on PATH"),
    ):
        code, out = run(cmd)
        s.add(f"{label}:")
        for ln in (out or "(no output)").splitlines():
            s.add(f"    {ln}")
    s.add()
    s.add("Phase 0 wants Python 3.12+ and Git present. Anything missing above blocks it.")


def sec_midi_ports(s: Section) -> None:
    import ctypes
    from ctypes import wintypes

    MAXPNAMELEN = 32

    class MIDIINCAPSW(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.UINT),
            ("szPname", ctypes.c_wchar * MAXPNAMELEN),
            ("dwSupport", wintypes.DWORD),
        ]

    class MIDIOUTCAPSW(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.UINT),
            ("szPname", ctypes.c_wchar * MAXPNAMELEN),
            ("wTechnology", wintypes.WORD),
            ("wVoices", wintypes.WORD),
            ("wNotes", wintypes.WORD),
            ("wChannelMask", wintypes.WORD),
            ("dwSupport", wintypes.DWORD),
        ]

    winmm = ctypes.WinDLL("winmm")

    def enumerate_ports(count_fn, caps_fn, caps_type) -> list[str]:
        names = []
        for i in range(count_fn()):
            caps = caps_type()
            if caps_fn(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                names.append(caps.szPname)
            else:
                names.append(f"(device {i}: caps query failed)")
        return names

    ins = enumerate_ports(winmm.midiInGetNumDevs, winmm.midiInGetDevCapsW, MIDIINCAPSW)
    outs = enumerate_ports(winmm.midiOutGetNumDevs, winmm.midiOutGetDevCapsW, MIDIOUTCAPSW)

    s.add(f"INPUT ports ({len(ins)}):")
    for i, name in enumerate(ins):
        tag = "   <-- Launchpad" if "launchpad" in name.lower() or "lpx" in name.lower() else ""
        s.add(f"    [{i}] {name!r}{tag}")
    s.add(f"OUTPUT ports ({len(outs)}):")
    for i, name in enumerate(outs):
        tag = "   <-- Launchpad" if "launchpad" in name.lower() or "lpx" in name.lower() else ""
        s.add(f"    [{i}] {name!r}{tag}")
    s.add()
    launchpad_ins = [n for n in ins if "launchpad" in n.lower() or "lpx" in n.lower()]
    if len(launchpad_ins) >= 2:
        s.add("Two Launchpad input interfaces present — matches the manual (p.6).")
    elif launchpad_ins:
        s.add(f"Only {len(launchpad_ins)} Launchpad input interface(s). Manual says two (p.6).")
        s.add("Record the discrepancy; do not work around it silently.")
    else:
        s.add("No Launchpad ports. Unplugged, or in MSD/bootloader mode?")
    s.add()
    s.add("NOTE: WinMM truncates names to 31 chars (MAXPNAMELEN). python-rtmidi reads")
    s.add("the same table, so these truncated strings ARE what mido will report — match")
    s.add("on them verbatim. For open-ability/exclusivity, run midi_port_inspector.py.")


def sec_audio_devices(s: Section) -> None:
    code, out = powershell(
        "Get-PnpDevice -PresentOnly "
        "| Where-Object { $_.Class -in @('MEDIA','AudioEndpoint','USB',"
        "'SoundVideoAndGameControllers') } "
        "| Select-Object Status, Class, FriendlyName, InstanceId "
        "| Format-List | Out-String -Width 300"
    )
    if code != 0:
        raise RuntimeError(out)
    interesting = ("evo", "audient", "launchpad", "usb audio", "loop-back", "loopback")
    hits = [b for b in out.split("\n\n") if any(t in b.lower() for t in interesting)]
    s.add(f"Audio/USB-class PnP devices matching {interesting}:")
    s.add()
    for block in hits or ["(none matched — full class dump follows)"]:
        for ln in block.splitlines():
            s.add(f"    {ln}")
        s.add()
    if not hits:
        for ln in out.splitlines():
            s.add(f"    {ln}")
        s.add()
        s.add("No EVO/Audient device present. Either unplugged or the Windows driver is")
        s.add("not installed — the EVO 8 is NOT class-compliant on Windows (manual p.13).")
    else:
        code, drv = powershell(
            "Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'EVO|Audient' } "
            "| ForEach-Object { $_.FriendlyName + '  driver=' + "
            "($_ | Get-PnpDeviceProperty -KeyName DEVPKEY_Device_DriverVersion)"
            ".Data }"
        )
        if code == 0 and drv:
            s.add("EVO driver versions (record these — Windows Update can replace them):")
            for ln in drv.splitlines():
                s.add(f"    {ln}")
    s.add()
    s.add("Presence is NOT health: an ESD-wedged EVO 8 still enumerates (manual p.10).")
    s.add("For the presence-endpoint decision, run interface_name_inspector.py.")


def sec_asio(s: Section) -> None:
    found = False
    for root in (r"SOFTWARE\ASIO", r"SOFTWARE\WOW6432Node\ASIO"):
        drivers = reg_subkeys("HKEY_LOCAL_MACHINE", root)
        if not drivers:
            continue
        found = True
        s.add(f"HKLM\\{root}:")
        for name in drivers:
            values = reg_values("HKEY_LOCAL_MACHINE", rf"{root}\{name}")
            desc = values.get("Description", "")
            s.add(f"    {name!r}  {('— ' + str(desc)) if desc else ''}")
    if not found:
        s.add("No ASIO drivers registered. The EVO 8 driver install is missing —")
        s.add("Phase 0 cannot pass without it.")
    s.add()
    s.add("Ableton must show the EVO ASIO driver by one of these names. Buffer size and")
    s.add("sample rate are set in the EVO Mixer tray app, not in Ableton.")


def sec_ableton(s: Section) -> None:
    patterns = [
        (Path(r"C:\ProgramData\Ableton"), "Live*/Program/Ableton Live*.exe"),
        (Path(r"C:\Program Files\Ableton"), "Live*/Program/Ableton Live*.exe"),
    ]
    exes: list[Path] = []
    for base, pattern in patterns:
        if base.exists():
            exes.extend(base.glob(pattern))
    s.add("Ableton executables found on disk:")
    for exe in exes or []:
        s.add(f"    {exe}")
    if not exes:
        s.add("    (none in the standard install locations)")
    s.add()
    s.add("Registry uninstall entries mentioning Ableton:")
    hits = 0
    for root in (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ):
        for sub in reg_subkeys("HKEY_LOCAL_MACHINE", root):
            values = reg_values("HKEY_LOCAL_MACHINE", rf"{root}\{sub}")
            name = str(values.get("DisplayName", ""))
            if "ableton" in name.lower():
                hits += 1
                s.add(f"    {name}  ->  {values.get('InstallLocation', '(no location)')}")
    if not hits:
        s.add("    (none)")
    s.add()
    if exes:
        s.add("PASTE INTO config/rig.yaml (verify the version you actually gig with):")
        s.add(f"    ableton_exe: '{exes[-1]}'")
    else:
        s.add("Roadmap Phase 0: 'Ableton executable path recorded verbatim' — still open.")


def sec_live_sets(s: Section) -> None:
    roots = [
        Path(r"C:\LiveRig"),
        Path.home() / "Documents",
    ]
    skip_tokens = ("backup", "autosave", "project-info", "recycle")
    total = 0
    for root in roots:
        if not root.exists():
            s.add(f"{root} — does not exist")
            continue
        s.add(f"{root}:")
        count = 0
        for als in root.rglob("*.als"):
            if any(t in str(als).lower() for t in skip_tokens):
                continue
            count += 1
            total += 1
            if count <= 40:
                s.add(f"    {als}")
        if count > 40:
            s.add(f"    ... and {count - 40} more")
        if count == 0:
            s.add("    (no .als files)")
    s.add()
    s.add(f"Total performable sets found: {total}. Phase 4's scanner will formalise the")
    s.add("skip rules; the tokens used here were: " + ", ".join(skip_tokens))


def sec_wifi(s: Section) -> None:
    code, drivers = run(["netsh", "wlan", "show", "drivers"])
    if code != 0:
        raise RuntimeError(drivers)
    s.add("netsh wlan show drivers — key lines:")
    for ln in grab(drivers, "interface name", "driver", "vendor", "hosted network"):
        s.add(f"    {ln.strip()}")
    s.add()
    code, caps = run(["netsh", "wlan", "show", "wirelesscapabilities"])
    if code == 0:
        s.add("Wi-Fi Direct capability (this, not 'hosted network', is what Windows 10+")
        s.add("Mobile Hotspot actually uses):")
        for ln in grab(caps, "wi-fi direct"):
            s.add(f"    {ln.strip()}")
    s.add()
    s.add("READ THIS CAREFULLY: 'Hosted network supported: No' does NOT kill the plan.")
    s.add("Modern Mobile Hotspot rides Wi-Fi Direct. If the Direct capabilities above say")
    s.add("Supported, the Phase 6 design survives — but the definitive test is manual:")
    s.add("Settings > Network > Mobile hotspot, switched on with NO internet present.")


def sec_ssh(s: Section) -> None:
    code, out = run(["sc", "query", "sshd"])
    s.add("sshd service:")
    if code == 0:
        for ln in grab(out, "state", "service_name"):
            s.add(f"    {ln.strip()}")
    else:
        s.add("    not installed (sc query found no sshd service)")
    s.add()
    for exe in (
        Path(r"C:\Windows\System32\OpenSSH\sshd.exe"),
        Path(r"C:\Windows\System32\OpenSSH\ssh.exe"),
    ):
        s.add(f"{'present ' if exe.exists() else 'MISSING '} {exe}")
    s.add()
    s.add("Phase 6 wants OpenSSH Server installed, key-auth only, passwords disabled.")
    s.add("If sshd is missing: Settings > Optional Features > OpenSSH Server.")


def sec_power(s: Section) -> None:
    code, out = run(["powercfg", "/getactivescheme"])
    s.add(f"Active scheme : {out if code == 0 else '(query failed)'}")
    s.add()
    code, out = run(["powercfg", "/a"])
    if code == 0:
        s.add("Available sleep states (Phase 7 wants sleep and hibernate OFF):")
        for ln in out.splitlines():
            s.add(f"    {ln.rstrip()}")
    s.add()
    # USB selective suspend: subgroup 2a737441, setting 48e6b7a6. Suspended USB is
    # a plausible cause of a Launchpad or EVO vanishing mid-show.
    code, out = run([
        "powercfg", "/query", "SCHEME_CURRENT",
        "2a737441-1930-4402-8d77-b2bebba308a3",
        "48e6b7a6-50f5-4782-a5d4-53bb8f07e226",
    ])
    if code == 0:
        s.add("USB selective suspend (0x0 = disabled, which is what the rig wants):")
        for ln in grab(out, "power setting index"):
            s.add(f"    {ln.strip()}")
    else:
        s.add("USB selective suspend query failed — check manually in the power plan.")


def sec_autologin(s: Section) -> None:
    values = reg_values(
        "HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    )
    for name in ("AutoAdminLogon", "DefaultUserName", "DefaultDomainName", "ForceAutoLogon"):
        s.add(f"{name:<17}: {values.get(name, '(not set)')}")
    s.add()
    auto = str(values.get("AutoAdminLogon", "0"))
    if auto == "1":
        s.add("Auto-login is ON — Phase 0 checkbox satisfied for this account.")
    else:
        s.add("Auto-login is OFF. Headless boot (Phase 7) cannot work: the rig would sit")
        s.add("at the login screen forever. Use Sysinternals Autologon or netplwiz.")


def sec_tasks(s: Section) -> None:
    code, out = run(["schtasks", "/query", "/fo", "csv", "/nh"], timeout=120)
    if code != 0:
        raise RuntimeError(out)
    hits = list(grab(out, "liverig", "ablepad", "ableton", "rig"))
    s.add("Scheduled tasks mentioning liverig/ablepad/ableton/rig:")
    for ln in hits or ["    (none — Phase 7's controller task does not exist yet, expected)"]:
        s.add(f"    {ln.strip()}")


def sec_liverig_tree(s: Section) -> None:
    root = Path(r"C:\LiveRig")
    if not root.exists():
        s.add(r"C:\LiveRig does not exist. Phase 0 checkbox 'folder tree created' open.")
        return
    s.add(f"{root} exists. Top two levels:")
    for child in sorted(root.iterdir()):
        s.add(f"    {child.name}{'/' if child.is_dir() else ''}")
        if child.is_dir():
            for grandchild in sorted(child.iterdir())[:20]:
                s.add(f"        {grandchild.name}{'/' if grandchild.is_dir() else ''}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

SECTIONS: list[tuple[str, str, Callable[[Section], None]]] = [
    ("system", "Phase 0: LiveRig account, machine identity", sec_system),
    ("toolchain", "Phase 0: Python 3.12+, Git installed", sec_toolchain),
    ("midi-ports", "Phase 1: port list recorded — exact Windows name strings", sec_midi_ports),
    ("audio-devices", "Phase 1: EVO 8 Get-PnpDevice names + driver version", sec_audio_devices),
    ("asio", "Phase 0: ASIO confirmed (driver installed and registered)", sec_asio),
    ("ableton", "Phase 0: Ableton executable path recorded verbatim", sec_ableton),
    ("live-sets", "Phase 4: where the .als files live", sec_live_sets),
    ("wifi-hotspot", "Phase 6: Beelink adapter hotspot capability", sec_wifi),
    ("ssh", "Phase 6: OpenSSH Server state", sec_ssh),
    ("power", "Phase 7: no sleep, no hibernate, no USB selective suspend", sec_power),
    ("auto-login", "Phase 0/7: auto-login enabled for headless boot", sec_autologin),
    ("scheduled-tasks", "Phase 7: Task Scheduler entries", sec_tasks),
    ("liverig-tree", "Phase 0: C:\\LiveRig folder tree", sec_liverig_tree),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="run", help="tag for the output filename")
    parser.add_argument(
        "--allow-non-windows",
        action="store_true",
        help="run anyway off-rig. Results are NOT valid for the build.",
    )
    args = parser.parse_args()

    print("\n=== Rig survey ===")
    print("Purpose: collect every machine-level roadmap unknown in one read-only pass")
    print("Answers: Phase 0/1/4/6/7 constants. Interactive Launchpad tools still needed.\n")

    if platform.system() != "Windows" and not args.allow_non_windows:
        print("  ! rig_survey.py is Windows-only and you are on " + platform.system())
        print("  ! The values it collects are Windows-specific. Run it on the Beelink.\n")
        return 1
    if platform.system() != "Windows":
        print("  ! --allow-non-windows: exercising error paths only, results meaningless.\n")

    survey = Survey(label=args.label)
    for title, roadmap, fn in SECTIONS:
        survey.run_section(title, roadmap, fn)

    path = survey.save()
    failed = [s.title for s in survey.sections if s.failed]

    print(f"\n  written: {path}")
    if failed:
        print(f"  sections failed (recorded, not fatal): {', '.join(failed)}")
    print("\n  Next: the four interactive tools, in the order tools/README.md gives.")
    print("  Commit the survey file — it is the evidence.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
