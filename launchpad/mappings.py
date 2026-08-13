"""
Config Lab contract — the Python side of viz/lab/schema.js.

LAYER: Configuration for the Launchpad service. Pure data + validation; no I/O
beyond reading the JSON files it is pointed at, no MIDI.

THE CONTRACT (schema.js header, verbatim intent)
    The Lab refuses to SAVE what this module would refuse to LOAD, and vice
    versa. Same rules, both sides. Change the schema in schema.js and port the
    change HERE — never invent shape rules on this side only. schemaVersion
    pins the pairing.

WHO CALLS IT
    The Phase 3 mode system: modes are ModeConfig objects loaded from
    <repo>/configs/, animations from <repo>/animations/. The renderer reads
    pad LED specs; the controller maps pad presses to Action entries and hands
    them to the CommandDispatcher (rig/commands.py) by ACTION type name.

FAILURE POLICY — two different severities, deliberately
    Shape errors (bad LED spec, unknown action, invalid pad id) are HARD: the
    file does not load, all errors reported at once (ConfigError). Dangling
    REFERENCES (animation ref, SWITCH_MODE target, transition target) are
    WARNINGS: the Lab warns and renders on, the rig logs and skips — a missing
    ambient animation must not stop a gig. Same split as schema.js.

Pad addressing is PROGRAMMER-MODE numbering (docs/launchpad-x-sysex.md §5):
grid corners VERIFIED, CC frame and logo still UNVERIFIED — Phase 1 truth.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from launchpad.animations import GENERATOR_DEFAULTS, PAD_IDS
from rig.exceptions import ConfigError

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

LED_TYPES = ("off", "static", "flash", "pulse", "rgb")
FRAME_LED_TYPES = ("off", "static", "rgb")  # frames are snapshots; flash/pulse make no sense
PAD_STATES = ("idle", "pressed", "active")
ANIM_ENGINES = ("generator", "frames")
ANIM_SLOTS = ("intro", "during")
ANIM_LAYERS = ("under", "over")

# Action catalogue: type name -> default hold_ms (None = no hold gate). Mirrors
# schema.js ACTIONS; the hold defaults are the roadmap's confirm gates.
ACTION_HOLDS: dict[str, int | None] = {
    "NONE": None,
    "SWITCH_MODE": None,
    # 1000, not 2000. MEASURED by using it: two seconds is longer than it sounds
    # with a finger on a pad -- "it works but the hold down is too long". The hold
    # exists so a set cannot change from a brush, and the handover makes that risk
    # smaller than it looks: during a performance the surface belongs to Ableton, so
    # these pads are only live when Ableton is closed or the escape hatch was used.
    # A second is still unmistakably deliberate.
    "LOAD_SET": 1000,
    "PAGE_NEXT": None,
    "PAGE_PREV": None,
    "RESCAN_SETS": None,
    "ABLETON_RESTART": 2000,
    "PANIC_MUTE": None,
    "HOTSPOT_TOGGLE": None,
    "SYSTEM_REBOOT": 4000,
    "SYSTEM_SHUTDOWN": 6000,
    "SEND_MIDI": None,
}
ACTION_TYPES = tuple(ACTION_HOLDS)

# Generator param ranges for validation — mirrors schema.js GENERATORS. Defaults
# live in animations.GENERATOR_DEFAULTS; keeping ranges next to defaults in two
# tables in two files is the porting cost of "schema.js is the source of truth".
_NUM = "number"
_SEL = "select"
_COLOR_SEED = {
    "colorMode": (_SEL, ("random", "hue")),
    "hue": (_NUM, 0, 359),
    "seed": (_NUM, 0, 99999),
}
GENERATOR_PARAM_SPECS: dict[str, dict[str, tuple]] = {
    "RAIN": {"density": (_NUM, 1, 24), "speed": (_NUM, 1, 20), "tail": (_NUM, 1, 8), **_COLOR_SEED},
    "PULSE_WAVE": {
        "direction": (_SEL, ("random", "up", "down", "left", "right")),
        "period_ms": (_NUM, 300, 6000),
        "width": (_NUM, 1, 6),
        **_COLOR_SEED,
    },
    "SPIN_SQUARE": {
        "size": (_SEL, (4, 6, 8)),
        "period_ms": (_NUM, 400, 8000),
        "tail": (_NUM, 1, 16),
        **_COLOR_SEED,
    },
}
assert set(GENERATOR_PARAM_SPECS) == set(GENERATOR_DEFAULTS), "catalogues out of sync"

_PAD_ID_STRINGS = frozenset(str(i) for i in PAD_IDS)


def pad_kind(pad: int) -> str:
    """'grid' | 'cc-top' | 'cc-right' | 'logo' — drives rendering and permissions."""
    row, col = pad // 10, pad % 10
    if row == 9 and col == 9:
        return "logo"
    if row == 9:
        return "cc-top"
    if col == 9:
        return "cc-right"
    return "grid"


def pad_is_button(pad: int) -> bool:
    return pad_kind(pad) != "logo"


# ------------------------------------------------------------------- validation


def _is_palette(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 127


def _check_led(led: object, where: str, errors: list[str]) -> None:
    if not isinstance(led, dict):
        errors.append(f"{where}: not an object")
        return
    led_type = led.get("type")
    if led_type not in LED_TYPES:
        errors.append(f'{where}: unknown LED type "{led_type}"')
        return
    if led_type in ("static", "pulse", "flash") and not _is_palette(led.get("palette")):
        errors.append(f"{where}: palette must be 0-127, got {led.get('palette')}")
    if led_type == "flash" and not _is_palette(led.get("paletteB")):
        errors.append(f"{where}: paletteB must be 0-127, got {led.get('paletteB')}")
    if led_type == "rgb":
        rgb = led.get("rgb")
        if not (isinstance(rgb, list) and len(rgb) == 3 and all(_is_palette(v) for v in rgb)):
            errors.append(f"{where}: rgb must be [r,g,b] each 0-127")


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_config(config: object) -> list[str]:
    """Every shape problem in the config, or [] if loadable. Mirrors validateConfig."""
    if not isinstance(config, dict):
        return ["config is not an object"]
    errors: list[str] = []
    if config.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion {config.get('schemaVersion')} != {SCHEMA_VERSION}")
    if not _ID_RE.match(str(config.get("id") or "")):
        errors.append(f'bad id "{config.get("id")}"')
    if not config.get("name"):
        errors.append("name is empty")
    _check_led(config.get("background"), "background", errors)

    animations = config.get("animations")
    if animations is not None:
        if not isinstance(animations, dict):
            errors.append("animations: not an object")
        else:
            for slot, binding in animations.items():
                if slot not in ANIM_SLOTS:
                    errors.append(f'animations: unknown slot "{slot}"')
                    continue
                if binding is None:
                    continue
                if not isinstance(binding, dict) or not _ID_RE.match(str(binding.get("ref") or "")):
                    ref = binding.get("ref") if isinstance(binding, dict) else binding
                    errors.append(f'animations.{slot}: bad ref "{ref}"')
                elif binding.get("layer") is not None and binding["layer"] not in ANIM_LAYERS:
                    errors.append(f"animations.{slot}: layer must be under | over")

    for pad_id, pad in (config.get("pads") or {}).items():
        if str(pad_id) not in _PAD_ID_STRINGS:
            errors.append(f'pad "{pad_id}" is not a valid programmer-mode index')
            continue
        pad_num = int(pad_id)
        for state, led in (pad.get("led") or {}).items():
            if state not in PAD_STATES:
                errors.append(f'pad {pad_id}: unknown LED state "{state}"')
            else:
                _check_led(led, f"pad {pad_id}.led.{state}", errors)
        action = pad.get("action") or {"type": "NONE"}
        if action.get("type") not in ACTION_TYPES:
            errors.append(f'pad {pad_id}: unknown action "{action.get("type")}"')
        if action.get("type") != "NONE" and not pad_is_button(pad_num):
            errors.append(f"pad {pad_id} is the logo — light-only, no action")
        hold = action.get("hold_ms")
        if hold is not None and not (isinstance(hold, int) and not isinstance(hold, bool) and hold >= 0):
            errors.append(f"pad {pad_id}: hold_ms must be a non-negative integer")

    for i, transition in enumerate(config.get("transitions") or []):
        if not (
            isinstance(transition, dict)
            and isinstance(transition.get("on"), str)
            and isinstance(transition.get("to"), str)
        ):
            errors.append(f"transition {i}: needs {{ on: string, to: string }}")

    return errors


def validate_animation(anim: object) -> list[str]:
    """Every shape problem in the animation, or []. Mirrors validateAnimation."""
    if not isinstance(anim, dict):
        return ["animation is not an object"]
    errors: list[str] = []
    if anim.get("schemaVersion") != SCHEMA_VERSION:
        errors.append(f"schemaVersion {anim.get('schemaVersion')} != {SCHEMA_VERSION}")
    if not _ID_RE.match(str(anim.get("id") or "")):
        errors.append(f'bad id "{anim.get("id")}"')
    if not anim.get("name"):
        errors.append("name is empty")
    if anim.get("engine") not in ANIM_ENGINES:
        errors.append(f'unknown engine "{anim.get("engine")}"')
    if not isinstance(anim.get("loop"), bool):
        errors.append("loop must be true or false")
    duration = anim.get("duration_ms")
    if duration is not None and not (
        isinstance(duration, int) and not isinstance(duration, bool) and duration > 0
    ):
        errors.append(f"duration_ms must be a positive integer or null, got {duration}")

    if anim.get("engine") == "generator":
        generator = anim.get("generator") or {}
        gen_type = generator.get("type")
        spec = GENERATOR_PARAM_SPECS.get(gen_type)
        if spec is None:
            errors.append(f'unknown generator "{gen_type}"')
        else:
            for key, value in (generator.get("params") or {}).items():
                param = spec.get(key)
                if param is None:  # unknown/cleared params are dropped, not fatal
                    continue
                if param[0] == _NUM and not (_is_number(value) and param[1] <= value <= param[2]):
                    errors.append(f"generator.{key}: must be {param[1]}-{param[2]}, got {value}")
                if param[0] == _SEL and value not in param[1]:
                    errors.append(f'generator.{key}: "{value}" is not an option')

    if anim.get("engine") == "frames":
        frames = anim.get("frames")
        if not isinstance(frames, list) or not frames:
            errors.append("frames: needs at least one frame")
        else:
            for i, frame in enumerate(frames):
                duration = frame.get("duration_ms")
                if not (isinstance(duration, int) and not isinstance(duration, bool) and duration > 0):
                    errors.append(f"frame {i}: duration_ms must be a positive integer")
                for pad_id, led in (frame.get("pads") or {}).items():
                    if str(pad_id) not in _PAD_ID_STRINGS:
                        errors.append(f'frame {i}: pad "{pad_id}" is not a valid index')
                    elif not isinstance(led, dict) or led.get("type") not in FRAME_LED_TYPES:
                        errors.append(f"frame {i} pad {pad_id}: frames allow only off/static/rgb")
                    else:
                        _check_led(led, f"frame {i} pad {pad_id}", errors)

    return errors


# ------------------------------------------------------------------ typed model


@dataclass(frozen=True)
class Action:
    type: str
    params: dict
    hold_ms: int | None  # already defaulted from ACTION_HOLDS where the file was sparse


@dataclass(frozen=True)
class PadBinding:
    pad: int
    label: str
    led: dict[str, dict]  # state name -> LED spec; missing states fall back to idle
    action: Action

    def led_for(self, state: str) -> dict:
        return self.led.get(state) or self.led.get("idle") or {"type": "off"}


@dataclass(frozen=True)
class ModeConfig:
    id: str
    name: str
    kind: str
    background: dict
    pads: dict[int, PadBinding]
    animations: dict[str, dict]  # slot -> {ref, layer?}; only bound slots present
    transitions: tuple[tuple[str, str], ...]  # (on, to)


def _to_mode_config(raw: dict) -> ModeConfig:
    pads: dict[int, PadBinding] = {}
    for pad_id, pad in (raw.get("pads") or {}).items():
        action_raw = pad.get("action") or {"type": "NONE"}
        action_type = action_raw.get("type", "NONE")
        pads[int(pad_id)] = PadBinding(
            pad=int(pad_id),
            label=pad.get("label") or "",
            led=dict(pad.get("led") or {}),
            action=Action(
                type=action_type,
                params=dict(action_raw.get("params") or {}),
                hold_ms=action_raw.get("hold_ms", ACTION_HOLDS.get(action_type)),
            ),
        )
    animations = {
        slot: binding
        for slot, binding in (raw.get("animations") or {}).items()
        if binding is not None
    }
    return ModeConfig(
        id=raw["id"],
        name=raw["name"],
        kind=raw.get("kind", "mode"),
        background=raw.get("background") or {"type": "off"},
        pads=pads,
        animations=animations,
        transitions=tuple((t["on"], t["to"]) for t in raw.get("transitions") or []),
    )


# --------------------------------------------------------------------- library


@dataclass
class ConfigLibrary:
    modes: dict[str, ModeConfig] = field(default_factory=dict)
    animations: dict[str, dict] = field(default_factory=dict)

    def cross_check(self) -> list[str]:
        """Dangling references — WARNINGS by contract, never load failures."""
        warnings: list[str] = []
        for mode in self.modes.values():
            for slot, binding in mode.animations.items():
                if binding["ref"] not in self.animations:
                    warnings.append(
                        f"config '{mode.id}' {slot} animation '{binding['ref']}' does not exist"
                    )
            for on, to in mode.transitions:
                if to not in self.modes:
                    warnings.append(f"config '{mode.id}' transition on {on} -> missing config '{to}'")
            for pad in mode.pads.values():
                if pad.action.type == "SWITCH_MODE":
                    target = pad.action.params.get("target")
                    if target not in self.modes:
                        warnings.append(
                            f"config '{mode.id}' pad {pad.pad} SWITCH_MODE -> missing config '{target}'"
                        )
        return warnings


def _load_json(path: Path, problems: list[str]) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        problems.append(f"{path.name}: unreadable ({exc})")
        return None


def load_library(configs_dir: Path, animations_dir: Path) -> tuple[ConfigLibrary, list[str]]:
    """
    Load every config and animation. Shape errors are collected across ALL files
    and raised as one ConfigError; dangling references come back as warnings.
    """
    problems: list[str] = []
    library = ConfigLibrary()

    for path in sorted(configs_dir.glob("*.json")) if configs_dir.is_dir() else []:
        raw = _load_json(path, problems)
        if raw is None:
            continue
        errors = validate_config(raw)
        if errors:
            problems.extend(f"{path.name}: {e}" for e in errors)
            continue
        library.modes[raw["id"]] = _to_mode_config(raw)

    for path in sorted(animations_dir.glob("*.json")) if animations_dir.is_dir() else []:
        raw = _load_json(path, problems)
        if raw is None:
            continue
        errors = validate_animation(raw)
        if errors:
            problems.extend(f"{path.name}: {e}" for e in errors)
            continue
        library.animations[raw["id"]] = raw

    if problems:
        raise ConfigError(problems)

    warnings = library.cross_check()
    for warning in warnings:
        log.warning("library: %s", warning)
    log.info(
        "library loaded: %d config(s), %d animation(s), %d warning(s)",
        len(library.modes),
        len(library.animations),
        len(warnings),
    )
    return library, warnings
