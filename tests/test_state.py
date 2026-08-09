"""StateMachine: table enforcement, logging of reasons, event publication."""

import pytest

from rig.events import EventBus, StateChanged
from rig.exceptions import IllegalTransition
from rig.state import LEGAL_TRANSITIONS, RigState, StateMachine


def machine() -> StateMachine:
    return StateMachine(bus=EventBus())


def test_starts_in_boot():
    assert machine().state is RigState.BOOT


def test_legal_transition_moves_and_records():
    m = machine()
    m.transition(RigState.SET_BROWSER, "boot complete")
    assert m.state is RigState.SET_BROWSER
    assert m.history == [(RigState.BOOT, RigState.SET_BROWSER, "boot complete")]


def test_illegal_transition_rejected_and_state_unchanged():
    m = machine()
    with pytest.raises(IllegalTransition) as excinfo:
        m.transition(RigState.PERFORMANCE, "skipping the browser")
    assert m.state is RigState.BOOT
    # The error must be actionable: name both states and the allowed set.
    message = str(excinfo.value)
    assert "boot" in message and "performance" in message and "set_browser" in message


def test_transition_publishes_state_changed():
    bus = EventBus()
    seen: list[StateChanged] = []
    bus.subscribe(StateChanged, seen.append)
    m = StateMachine(bus=bus)
    m.transition(RigState.SET_BROWSER, "boot complete")
    assert seen == [StateChanged("boot", "set_browser", "boot complete")]


def test_shutdown_is_terminal():
    m = machine()
    m.transition(RigState.SET_BROWSER, "boot complete")
    m.transition(RigState.SHUTDOWN, "operator")
    for target in RigState:
        assert not m.can(target)


def test_error_reachable_from_every_live_state():
    for state in (RigState.BOOT, RigState.SET_BROWSER, RigState.PERFORMANCE, RigState.SYSTEM):
        assert RigState.ERROR in LEGAL_TRANSITIONS[state], state


def test_error_recovers_only_to_browser_or_shutdown():
    assert LEGAL_TRANSITIONS[RigState.ERROR] == {RigState.SET_BROWSER, RigState.SHUTDOWN}


def test_every_state_has_a_table_entry():
    assert set(LEGAL_TRANSITIONS) == set(RigState)


def test_nothing_returns_to_boot():
    for state, targets in LEGAL_TRANSITIONS.items():
        assert RigState.BOOT not in targets, f"{state} may not return to BOOT"
