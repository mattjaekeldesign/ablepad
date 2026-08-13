"""
A few seconds to pick a set before the rig picks one for you.

OBSERVED on the first cold boot 2026-08-13: the rig launched boot_set instantly and
by the time a human was looking the surface already belonged to Ableton. The Set
Browser existed at boot and was unreachable at boot.
"""

from rig.boot_choice import BootChoice
from rig.events import ActionRequested, EventBus
from rig.state import RigState, StateMachine


def build(seconds=8.0, now=None):
    now = now if now is not None else [0.0]
    bus = EventBus()
    machine = StateMachine(bus=bus)
    choice = BootChoice(seconds=seconds, clock=lambda: now[0], machine=machine, bus=bus)
    return choice, machine, bus, now


def test_it_shows_the_browser_so_the_sets_are_visible():
    choice, machine, _, now = build()
    assert choice.waiting(now[0]) is True
    assert machine.state is RigState.SET_BROWSER


def test_it_gives_up_on_its_own_so_an_unattended_rig_still_starts():
    # A prompt nobody answers is a rig that never starts. This is a courtesy, not a
    # gate: powering up in a van with nobody there must still reach a playable state.
    choice, _, _, now = build(seconds=8.0)
    choice.waiting(now[0])
    now[0] = 7.9
    assert choice.waiting(now[0]) is True
    now[0] = 8.0
    assert choice.waiting(now[0]) is False


def test_choosing_a_set_cancels_the_window_immediately():
    # The press IS the choice. Counting down afterwards would either load two sets
    # or ignore the one that was asked for.
    choice, _, bus, now = build()
    choice.waiting(now[0])
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert choice.waiting(now[0]) is False
    assert choice.chosen is True


def test_other_actions_do_not_cancel_it():
    choice, _, bus, now = build()
    choice.waiting(now[0])
    bus.publish(ActionRequested(action="PAGE_NEXT", params={}, pad=92))
    assert choice.waiting(now[0]) is True


def test_zero_seconds_restores_the_old_behaviour_exactly():
    choice, machine, _, now = build(seconds=0.0)
    assert choice.waiting(now[0]) is False
    assert machine.state is RigState.BOOT, "must not even show the browser"


def test_it_never_reopens():
    choice, _, _, now = build(seconds=8.0)
    choice.waiting(now[0])
    now[0] = 100.0
    assert choice.waiting(now[0]) is False
    now[0] = 101.0
    assert choice.waiting(now[0]) is False


def test_it_does_not_stall_boot_if_the_browser_cannot_be_shown():
    # Reached if the state machine has moved on underneath it. Loading the default
    # late is recoverable; never loading anything is not.
    # SHUTDOWN is terminal, so SET_BROWSER is genuinely unreachable from it.
    choice, machine, _, now = build()
    machine.transition(RigState.SET_BROWSER, "setup")
    machine.transition(RigState.SHUTDOWN, "setup")
    assert choice.waiting(now[0]) is False


def test_require_choice_waits_forever_rather_than_loading_the_default():
    # "live launched auto which is a big no... i must be able to choose the set i
    # want to boot into". Launching the WRONG set is worse than launching nothing.
    now = [0.0]
    bus = EventBus()
    machine = StateMachine(bus=bus)
    choice = BootChoice(seconds=8.0, clock=lambda: now[0], machine=machine, bus=bus,
                        require_choice=True)
    choice.waiting(now[0])
    for t in (8.0, 60.0, 3600.0):
        now[0] = t
        assert choice.waiting(now[0]) is True, f"must still be waiting at {t}s"


def test_require_choice_still_ends_the_moment_a_set_is_chosen():
    now = [0.0]
    bus = EventBus()
    machine = StateMachine(bus=bus)
    choice = BootChoice(seconds=8.0, clock=lambda: now[0], machine=machine, bus=bus,
                        require_choice=True)
    choice.waiting(now[0])
    now[0] = 500.0
    assert choice.waiting(now[0]) is True
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert choice.waiting(now[0]) is False
    assert choice.chosen is True


def test_the_bank_is_not_shown_until_the_rig_could_act_on_it():
    # OBSERVED: the bank appeared before the Launchpad and interface were confirmed,
    # so pressing a pad did nothing. A surface offering choices it cannot honour is
    # worse than one that plainly says "not yet" -- which is what Boot Mode's
    # animation is for.
    now = [0.0]
    bus = EventBus()
    machine = StateMachine(bus=bus)
    ready = {"v": False}
    choice = BootChoice(seconds=8.0, clock=lambda: now[0], machine=machine, bus=bus,
                        ready=lambda: ready["v"])

    for _ in range(5):
        now[0] += 1
        assert choice.waiting(now[0]) is True
        assert machine.state is RigState.BOOT, "must still be showing Boot Mode"

    ready["v"] = True
    assert choice.waiting(now[0]) is True
    assert machine.state is RigState.SET_BROWSER, "bank appears once it can be acted on"


def test_the_choice_window_starts_when_the_bank_appears_not_at_power_on():
    # Otherwise a slow-to-enumerate interface eats the window, and the default loads
    # before anyone has seen a pad light up.
    now = [0.0]
    bus = EventBus()
    machine = StateMachine(bus=bus)
    ready = {"v": False}
    choice = BootChoice(seconds=8.0, clock=lambda: now[0], machine=machine, bus=bus,
                        ready=lambda: ready["v"])
    now[0] = 30.0
    choice.waiting(now[0])          # still not ready; clock has run on
    ready["v"] = True
    choice.waiting(now[0])          # bank appears now
    now[0] = 37.9
    assert choice.waiting(now[0]) is True, "8s window counts from the bank, not boot"
    now[0] = 38.1
    assert choice.waiting(now[0]) is False


def test_a_broken_readiness_probe_does_not_strand_boot():
    now = [0.0]
    bus = EventBus()
    machine = StateMachine(bus=bus)

    def boom():
        raise OSError("registry unavailable")

    choice = BootChoice(seconds=8.0, clock=lambda: now[0], machine=machine, bus=bus,
                        ready=boom)
    assert choice.waiting(now[0]) is True
    assert machine.state is RigState.SET_BROWSER, "fall through rather than stall"
