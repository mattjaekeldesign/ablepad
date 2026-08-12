"""
Which surface the Launchpad shows for a given rig state.

LAYER: services. Pure — a lookup table and its validation. No IO, no device.

WHY THIS IS A TABLE AND NOT STRING MANIPULATION
    It is tempting to derive the config id from the state name. It even works, for
    four of the five:

        RigState.BOOT         "boot"        -> configs/boot.json         ok
        RigState.PERFORMANCE  "performance" -> configs/performance.json  ok
        RigState.SYSTEM       "system"      -> configs/system.json       ok
        RigState.ERROR        "error"       -> configs/error.json        ok
        RigState.SET_BROWSER  "set_browser" -> configs/set_browser.json  MISSING

    The file is `set-browser.json`. Underscore in the enum, hyphen in the id, because
    one is a Python identifier and the other is a filename the Config Lab writes.
    A `.replace("_", "-")` would paper over it until someone adds a state where that
    rule does not hold, and then the rig would fail to find a surface at the moment
    it switched to that mode -- on stage, with no screen.

    So: an explicit table, and a startup check that every entry resolves.

WHO CALLS IT
    The controller, to know which ModeConfig to hand the renderer when the state
    machine moves. Nothing else.
"""

from __future__ import annotations

from enum import Enum

from launchpad.mappings import ConfigLibrary, ModeConfig
from rig.state import RigState

__all__ = ["LaunchpadMode", "mode_for", "config_id_for", "resolve", "missing_configs", "ModeError"]


class LaunchpadMode(Enum):
    """
    A surface the Launchpad can show. The value IS the config id on disk.

    Deliberately not the same enum as RigState: the rig has states with no surface
    (SHUTDOWN), and a surface is a UI concept while a state is a domain one. They are
    bound by the table below, not by being the same type.
    """

    BOOT = "boot"
    SET_BROWSER = "set-browser"
    PERFORMANCE = "performance"
    SYSTEM = "system"
    ERROR = "error"


class ModeError(RuntimeError):
    """A state has no surface, or its surface is not on disk."""


#: The binding. SHUTDOWN is deliberately absent: the rig is going down and the
#: surface should go dark, not show a mode. Handled by mode_for() returning None
#: rather than by inventing a "shutdown" config nobody would ever design.
_MODE_FOR_STATE: dict[RigState, LaunchpadMode | None] = {
    RigState.BOOT: LaunchpadMode.BOOT,
    RigState.SET_BROWSER: LaunchpadMode.SET_BROWSER,
    RigState.PERFORMANCE: LaunchpadMode.PERFORMANCE,
    RigState.SYSTEM: LaunchpadMode.SYSTEM,
    RigState.ERROR: LaunchpadMode.ERROR,
    RigState.SHUTDOWN: None,
}


def mode_for(state: RigState) -> LaunchpadMode | None:
    """The surface for a state, or None where the surface should be blank."""
    if state not in _MODE_FOR_STATE:
        raise ModeError(
            f"{state} has no entry in the mode table. Every RigState needs one, even "
            "if it is None — an unmapped state would leave the surface showing "
            "whatever the last mode painted."
        )
    return _MODE_FOR_STATE[state]


def config_id_for(state: RigState) -> str | None:
    mode = mode_for(state)
    return mode.value if mode else None


def missing_configs(library: ConfigLibrary) -> list[str]:
    """
    Which required configs are absent. Empty means every state can be rendered.

    Call this ONCE AT STARTUP, not when a mode is entered. A missing config
    discovered at switch time is a black surface halfway through a set; the same
    fact discovered at boot is a message on a screen that is still attached.
    """
    return sorted(
        mode.value for mode in LaunchpadMode if mode.value not in library.modes
    )


def resolve(state: RigState, library: ConfigLibrary) -> ModeConfig | None:
    """
    The ModeConfig for a state, or None where the surface should be blank.

    Raises if the config is genuinely missing, because by the time this is called the
    startup check should already have caught it. Reaching here with a missing config
    means the library changed underneath the rig.
    """
    mode = mode_for(state)
    if mode is None:
        return None
    config = library.modes.get(mode.value)
    if config is None:
        raise ModeError(
            f"no config {mode.value!r} for {state}. Present: {sorted(library.modes)}. "
            "missing_configs() at startup exists to catch this before a set does."
        )
    return config
