"""
Load and validate config/rig.yaml into typed sections.

LAYER: Configuration.

WHO CALLS IT
    main.py, once, at startup. The returned RigConfig is passed down by injection;
    no module reaches for a global config object.

HOW IT FAILS
    Loudly and completely: validation collects EVERY problem and raises one
    ConfigError listing all of them. A headless rig gets exactly one chance to
    say why it refused to start — "field 3 of 9 is wrong" nine reboots in a row
    is not acceptable on an appliance.

WHAT IT DOES NOT DO
    No defaults for hardware-truth values (port names, exe paths). A missing
    value must be filled from a measured survey result, not papered over here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from rig.exceptions import ConfigError


@dataclass(frozen=True)
class RigSection:
    name: str
    tick_hz: int
    #: How long the boot gate waits for every precondition before giving up and
    #: showing Error Mode. A rig stuck on the splash screen forever is
    #: indistinguishable, on a screenless machine, from one that has crashed.
    boot_timeout_s: float = 90.0
    #: How long after Ableton's process appears we ASSUME its set finished loading.
    #: A guess -- see ableton/readiness.py. Measure it on the Beelink with the real
    #: set and a stopwatch, then put the measured value here.
    boot_settle_s: float = 25.0
    #: The CEILING is boot_settle_s; this is the FLOOR. A Remote Script readiness
    #: signal is not honoured before this many seconds, because the hook that writes
    #: it is UNVERIFIED (remote_script/README.md) -- an over-eager signal would
    #: complete boot earlier than the timer it replaces, which is worse than the
    #: guess. Only lower this once the real gap has been measured.
    boot_floor_s: float = 5.0


@dataclass(frozen=True)
class LaunchpadSection:
    brightness: int  # 0-127, asserted at boot via SysEx 08h (manual p.25)
    port_contains: str  # substring both port names must carry, from rig_survey.py
    #: Hand the Launchpad to Ableton once a set is up, so it behaves as a normal
    #: Live controller. Requires "Launchpad X" enabled as a Control Surface in
    #: Live's Preferences -- a manual step the rig cannot verify or perform, which
    #: is why this is a switch and not an assumption. False keeps the rig on the
    #: surface at all times (every phase before this).
    handover_to_ableton: bool = True


@dataclass(frozen=True)
class AudioSection:
    match_any: tuple[str, ...]  # PnP FriendlyName substrings, from interface_name_inspector.py
    require_status: str


@dataclass(frozen=True)
class AbletonSection:
    exe: str  # verbatim path, from rig_survey.py — UNVERIFIED until then
    sets_dir: str
    #: The set launched at boot. Sets/Emergency/ exists for exactly this: one
    #: known-good file that always loads, so the rig reaches a usable state before
    #: anyone picks a real set. Empty means "do not launch Ableton at boot", which
    #: is honest but means boot can only complete if something else started it.
    boot_set: str = ""
    #: Automatic restarts allowed after a crash before the rig gives up and shows
    #: Error Mode. One, deliberately — see ableton/recovery.py.
    restart_attempts: int = 1
    #: How long a run must survive before that one restart is earned back.
    restart_stable_s: float = 120.0
    #: %APPDATA%\\Ableton -- the folder holding the versioned "Live 12.4.3" dirs.
    #: Empty disables the crash-journal sweep, and the recovery dialog becomes
    #: possible again. Not derived from the environment because the rig runs as a
    #: scheduled task, where %APPDATA% is whatever the task's user has.
    #: Where the Remote Script writes its readiness handshake. Empty disables the
    #: signal, and the rig falls back to the settle timer alone.
    ready_signal_path: str = ""
    appdata_dir: str = ""
    #: Where swept crash journals go. They are MOVED, never deleted, because this
    #: machine also builds sets and a journal can hold genuinely unsaved work.
    crash_quarantine_dir: str = ""



@dataclass(frozen=True)
class LoggingSection:
    dir: str
    level: str


@dataclass(frozen=True)
class RigConfig:
    rig: RigSection
    launchpad: LaunchpadSection
    audio_interface: AudioSection
    ableton: AbletonSection
    logging: LoggingSection


_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def load_config(path: Path) -> RigConfig:
    problems: list[str] = []

    if not path.exists():
        raise ConfigError([f"config file not found: {path}"])
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError([f"not valid YAML: {exc}"])
    if not isinstance(raw, dict):
        raise ConfigError([f"top level must be a mapping, got {type(raw).__name__}"])

    def section(name: str) -> dict:
        value = raw.get(name)
        if not isinstance(value, dict):
            problems.append(f"section {name!r} missing or not a mapping")
            return {}
        return value

    def want(sec: dict, sec_name: str, key: str, kind: type) -> object | None:
        value = sec.get(key)
        if value is None:
            problems.append(f"{sec_name}.{key} is missing")
            return None
        # bool is an int subclass; a YAML `true` must not pass as tick_hz.
        if kind is int and isinstance(value, bool) or not isinstance(value, kind):
            problems.append(
                f"{sec_name}.{key} must be {kind.__name__}, got {type(value).__name__}"
            )
            return None
        return value

    rig_raw = section("rig")
    name = want(rig_raw, "rig", "name", str)
    tick_hz = want(rig_raw, "rig", "tick_hz", int)
    # Optional: sane defaults so a config written before the boot gate still loads.
    boot_timeout_s = rig_raw.get("boot_timeout_s", 90.0)
    boot_settle_s = rig_raw.get("boot_settle_s", 25.0)
    boot_floor_s = rig_raw.get("boot_floor_s", 5.0)
    if isinstance(tick_hz, int) and not 1 <= tick_hz <= 200:
        problems.append(f"rig.tick_hz must be 1-200, got {tick_hz}")

    lp_raw = section("launchpad")
    brightness = want(lp_raw, "launchpad", "brightness", int)
    if isinstance(brightness, int) and not 0 <= brightness <= 127:
        problems.append(f"launchpad.brightness must be 0-127 (SysEx data byte), got {brightness}")
    port_contains = want(lp_raw, "launchpad", "port_contains", str)
    handover = lp_raw.get("handover_to_ableton", True)

    audio_raw = section("audio_interface")
    match_any = audio_raw.get("match_any")
    if not isinstance(match_any, list) or not match_any or not all(
        isinstance(m, str) and m for m in match_any
    ):
        problems.append("audio_interface.match_any must be a non-empty list of strings")
        match_any = []
    require_status = want(audio_raw, "audio_interface", "require_status", str)

    ableton_raw = section("ableton")
    exe = want(ableton_raw, "ableton", "exe", str)
    boot_set = ableton_raw.get("boot_set", "")
    restart_attempts = ableton_raw.get("restart_attempts", 1)
    restart_stable_s = ableton_raw.get("restart_stable_s", 120.0)
    sets_dir = want(ableton_raw, "ableton", "sets_dir", str)
    ready_signal_path = ableton_raw.get("ready_signal_path", "")
    appdata_dir = ableton_raw.get("appdata_dir", "")
    crash_quarantine_dir = ableton_raw.get("crash_quarantine_dir", "")

    log_raw = section("logging")
    log_dir = want(log_raw, "logging", "dir", str)
    level = want(log_raw, "logging", "level", str)
    if isinstance(level, str) and level not in _LEVELS:
        problems.append(f"logging.level must be one of {_LEVELS}, got {level!r}")

    if problems:
        raise ConfigError(problems)

    return RigConfig(
        rig=RigSection(
            name=str(name), tick_hz=int(tick_hz),
            boot_timeout_s=float(boot_timeout_s), boot_settle_s=float(boot_settle_s),
            boot_floor_s=float(boot_floor_s),
        ),  # type: ignore[arg-type]
        launchpad=LaunchpadSection(
            brightness=int(brightness), port_contains=str(port_contains),  # type: ignore[arg-type]
            handover_to_ableton=bool(handover),
        ),
        audio_interface=AudioSection(
            match_any=tuple(str(m) for m in match_any), require_status=str(require_status)
        ),
        ableton=AbletonSection(
            exe=str(exe), sets_dir=str(sets_dir), boot_set=str(boot_set),
            restart_attempts=int(restart_attempts), restart_stable_s=float(restart_stable_s),
            appdata_dir=str(appdata_dir), crash_quarantine_dir=str(crash_quarantine_dir),
            ready_signal_path=str(ready_signal_path),
        ),
        logging=LoggingSection(dir=str(log_dir), level=str(level)),
    )
