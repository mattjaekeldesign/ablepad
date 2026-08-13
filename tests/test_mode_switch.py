"""
SWITCH_MODE turns a pad into a state change -- or refuses, without dying.
"""

import pytest

from launchpad.modes import ModeError, config_id_for, state_for
from rig.events import ActionRequested, EventBus
from rig.mode_switch import ModeSwitch
from rig.state import RigState, StateMachine


def build(state=RigState.PERFORMANCE):
    bus = EventBus()
    machine = StateMachine(bus=bus)
    if state is not RigState.BOOT:
        machine.transition(RigState.SET_BROWSER, "setup")
        if state is not RigState.SET_BROWSER:
            machine.transition(state, "setup")
    ModeSwitch(bus=bus, machine=machine)
    return bus, machine


def test_the_browse_pad_reaches_the_set_browser():
    bus, machine = build(RigState.PERFORMANCE)
    bus.publish(ActionRequested(action="SWITCH_MODE", params={"target": "set-browser"}, pad=98))
    assert machine.state is RigState.SET_BROWSER


def test_an_unreachable_mode_is_ignored_not_raised():
    # 'Browse' pressed during boot. A mistimed press must not take the tick loop down.
    bus, machine = build(RigState.BOOT)
    bus.publish(ActionRequested(action="SWITCH_MODE", params={"target": "performance"}, pad=98))
    assert machine.state is RigState.BOOT


def test_switching_to_the_current_mode_is_a_no_op():
    bus, machine = build(RigState.PERFORMANCE)
    before = len(machine.history)
    bus.publish(ActionRequested(action="SWITCH_MODE", params={"target": "performance"}, pad=98))
    assert len(machine.history) == before


def test_a_bogus_target_is_ignored():
    bus, machine = build(RigState.PERFORMANCE)
    bus.publish(ActionRequested(action="SWITCH_MODE", params={"target": "nonsense"}, pad=98))
    bus.publish(ActionRequested(action="SWITCH_MODE", params={}, pad=98))
    assert machine.state is RigState.PERFORMANCE


def test_other_actions_are_left_alone():
    bus, machine = build(RigState.PERFORMANCE)
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert machine.state is RigState.PERFORMANCE


# --- the inverse table --------------------------------------------------


@pytest.mark.parametrize(
    "state",
    [s for s in RigState if config_id_for(s) is not None],
)
def test_every_state_with_a_surface_round_trips(state):
    # The guard against the two tables drifting apart: a mode you can switch TO must
    # be the same mode the surface then PAINTS.
    assert state_for(config_id_for(state)) is state


def test_an_unknown_config_id_raises_rather_than_guessing():
    with pytest.raises(ModeError):
        state_for("set_browser")  # underscore -- the classic trap, and not a mode
