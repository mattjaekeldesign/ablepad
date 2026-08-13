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


@dataclass(frozen=True)
class LaunchpadSection:
    brightness: int  # 0-127, asserted at boot via SysEx 08h (manual p.25)
    port_contains: str  # substring both port names must carry, from rig_survey.py


@dataclass(frozen=True)
class AudioSection:
    match_any: tuple[str, ...]  # PnP FriendlyName substrings, from interface_name_inspector.py
    require_status: str


@dataclass(frozen=True)
class AbletonSection:
    exe: str  # verbatim path, from rig_survey.py — UNVERIFIED until then
    sets_dir: str


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
    if isinstance(tick_hz, int) and not 1 <= tick_hz <= 200:
        problems.append(f"rig.tick_hz must be 1-200, got {tick_hz}")

    lp_raw = section("launchpad")
    brightness = want(lp_raw, "launchpad", "brightness", int)
    if isinstance(brightness, int) and not 0 <= brightness <= 127:
        problems.append(f"launchpad.brightness must be 0-127 (SysEx data byte), got {brightness}")
    port_contains = want(lp_raw, "launchpad", "port_contains", str)

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
    sets_dir = want(ableton_raw, "ableton", "sets_dir", str)

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
        ),  # type: ignore[arg-type]
        launchpad=LaunchpadSection(
            brightness=int(brightness), port_contains=str(port_contains)  # type: ignore[arg-type]
        ),
        audio_interface=AudioSection(
            match_any=tuple(str(m) for m in match_any), require_status=str(require_status)
        ),
        ableton=AbletonSection(exe=str(exe), sets_dir=str(sets_dir)),
        logging=LoggingSection(dir=str(log_dir), level=str(level)),
    )
