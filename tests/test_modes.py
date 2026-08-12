"""launchpad/modes.py — the state -> surface binding, and its startup check."""

import pytest

from pathlib import Path

from launchpad.mappings import ConfigLibrary, load_library
from launchpad.modes import (
    LaunchpadMode,
    ModeError,
    config_id_for,
    missing_configs,
    mode_for,
    resolve,
)
from rig.state import RigState


REPO = Path(__file__).resolve().parent.parent


def test_set_browser_is_hyphenated_not_underscored():
    # The whole reason modes.py is a table. RigState.SET_BROWSER is "set_browser";
    # the file on disk is set-browser.json. Deriving one from the other breaks here
    # and only here, which is what makes it dangerous.
    assert RigState.SET_BROWSER.value == "set_browser"
    assert config_id_for(RigState.SET_BROWSER) == "set-browser"


def test_every_rig_state_is_mapped():
    # An unmapped state would leave the surface showing whatever the last mode
    # painted, which on stage looks like the rig ignoring you.
    for state in RigState:
        mode_for(state)  # must not raise


def test_shutdown_has_no_surface():
    assert mode_for(RigState.SHUTDOWN) is None
    assert config_id_for(RigState.SHUTDOWN) is None


def test_missing_configs_reports_what_is_absent():
    empty = ConfigLibrary()
    assert missing_configs(empty) == sorted(m.value for m in LaunchpadMode)


def test_the_real_configs_on_disk_satisfy_every_mode():
    # Guards against someone renaming a config file and finding out mid-set.
    library, problems = load_library(REPO / "configs", REPO / "animations")
    assert problems == [], problems
    assert missing_configs(library) == []


def test_resolve_returns_the_config_for_a_state():
    library, _ = load_library(REPO / "configs", REPO / "animations")
    config = resolve(RigState.SET_BROWSER, library)
    assert config is not None and config.id == "set-browser"


def test_resolve_raises_if_the_library_lost_a_config():
    library = ConfigLibrary()
    with pytest.raises(ModeError, match="set-browser"):
        resolve(RigState.SET_BROWSER, library)
