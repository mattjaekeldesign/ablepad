"""
Who drives the Launchpad: the rig, or Ableton.

The rule is not "which mode are we in" but "is Ableton up", because Live's control
surface does not wait to be handed anything -- it drives the device from the moment
Live starts, and would knock it out of Programmer Mode underneath the rig.
"""

import pytest

from rig.state import RigState
from rig.surface_owner import Owner, SurfaceOwner


@pytest.fixture
def owner():
    return SurfaceOwner(enabled=True)


# --- the normal arc ------------------------------------------------------


def test_the_rig_owns_the_surface_during_boot(owner):
    # Nothing is loaded; the rig is the only UI there is.
    assert owner.owner(RigState.BOOT, ableton_ready=False) == Owner.RIG
    assert owner.owner(RigState.BOOT, ableton_ready=True) == Owner.RIG


def test_ableton_takes_over_once_a_set_is_up(owner):
    assert owner.owner(RigState.PERFORMANCE, ableton_ready=True) == Owner.ABLETON


def test_the_rig_takes_it_back_when_ableton_goes(owner):
    owner.owner(RigState.PERFORMANCE, ableton_ready=True)
    assert owner.owner(RigState.SET_BROWSER, ableton_ready=False) == Owner.RIG


def test_the_browser_is_the_rigs_while_ableton_is_down(owner):
    # Which is the only way the browser is reachable at all -- see the module docs.
    assert owner.owner(RigState.SET_BROWSER, ableton_ready=False) == Owner.RIG


# --- the overrides that matter -------------------------------------------


def test_error_mode_always_steals_the_surface_back(owner):
    # An ESD-wedged EVO enumerates perfectly and outputs silence. A Launchpad still
    # showing Ableton's session view while the rig makes no sound is the worst thing
    # this surface can do on stage.
    assert owner.owner(RigState.ERROR, ableton_ready=True) == Owner.RIG


def test_system_mode_is_the_rigs_own_screen(owner):
    assert owner.owner(RigState.SYSTEM, ableton_ready=True) == Owner.RIG


def test_nothing_is_handed_to_an_ableton_that_is_not_running(owner):
    # Handing over to a process that is not there leaves a dark, unresponsive
    # surface with nothing driving it: a rig that looks dead while working.
    for state in RigState:
        assert owner.owner(state, ableton_ready=False) == Owner.RIG


def test_handover_can_be_switched_off_entirely():
    # Handover depends on Launchpad X being enabled in Live's Preferences -- a manual
    # step the rig cannot verify or perform. Off means every earlier phase's behaviour.
    off = SurfaceOwner(enabled=False)
    for state in RigState:
        assert off.owner(state, ableton_ready=True) == Owner.RIG


def test_every_state_has_an_explicit_decision(owner):
    # No state may fall through to a default. Adding one should force a choice.
    from rig.surface_owner import _HANDS_OVER

    assert set(_HANDS_OVER) == set(RigState)


# --- the service side ----------------------------------------------------


def test_released_is_not_the_same_as_disconnected():
    # Released is working as intended: no retries, no warnings, no reconnect.
    from launchpad.service import LaunchpadService

    class Backend:
        def open_input(self, *a, **k):
            raise AssertionError("must not touch the device while released")

        def open_output(self, *a, **k):
            raise AssertionError("must not touch the device while released")

        def input_names(self):
            return []

        def output_names(self):
            return []

    service = LaunchpadService(backend=Backend())
    service.release()
    assert service.released
    assert service.ensure_connected(now=0.0) is False
    assert service.tick(now=999.0, specs=[]) == []


def test_acquiring_does_not_make_the_operator_wait_out_a_retry_window():
    from launchpad.service import LaunchpadService

    service = LaunchpadService(backend=object())
    service._next_retry_at = 1e9
    service.release()
    service.acquire()
    assert not service.released
    assert service._next_retry_at == 0.0
