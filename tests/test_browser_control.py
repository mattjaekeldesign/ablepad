"""
rig/browser_control.py — pads to sets, and a held pad to a loaded set.

The pad->slot indirection is the thing to protect: configs/set-browser.json decides
which pad is which slot, and moving a set to a different pad must never mean editing
Python.
"""

from pathlib import Path

from launchpad import colors
from launchpad.mappings import Action, ModeConfig, PadBinding
from rig.browser_control import SetBrowserControl
from rig.events import ActionRequested, EventBus
from rig.state import RigState, StateMachine
from set_browser.models import LiveSet


class FakeBrowser:
    def __init__(self, sets):
        self._sets = list(sets)
        self.rescans = 0
        self.page_calls = []

    def current_page(self):
        class P:
            items = tuple(self._sets)
            index = 0
            page_count = 1
        return P()

    def set_at(self, position):
        return self._sets[position] if 0 <= position < len(self._sets) else None

    def rescan(self):
        self.rescans += 1
        return len(self._sets)

    def next_page(self):
        self.page_calls.append("next")
        return self.current_page()

    def prev_page(self):
        self.page_calls.append("prev")
        return self.current_page()

    @property
    def is_empty(self):
        return not self._sets


class FakeLauncher:
    def __init__(self, refuse=False):
        self.launched = []
        self.stops = 0
        self.refuse = refuse

    def stop(self):
        self.stops += 1

    def launch(self, path):
        if self.refuse:
            from ableton.launcher import LaunchRefused
            raise LaunchRefused(["audio interface not present"])
        self.launched.append(path)


def config_with_slots(n=4):
    pads = {}
    for slot in range(n):
        pads[81 + slot] = PadBinding(
            pad=81 + slot, label=f"Set {slot+1}", led={"idle": {"type": "off"}},
            action=Action("LOAD_SET", {"slot": slot}, 2000),
        )
    return ModeConfig(id="set-browser", name="Set Browser", kind="mode",
                      background={"type": "off"}, pads=pads, animations={}, transitions=())


def live(name, colour="white"):
    return LiveSet(path=Path(f"/sets/{name}.als"), display_name=name, color=colour)


def build(sets, refuse=False):
    bus = EventBus()
    machine = StateMachine(bus=bus)
    launcher = FakeLauncher(refuse=refuse)
    control = SetBrowserControl(
        browser=FakeBrowser(sets), config=config_with_slots(), bus=bus,
        machine=machine, launcher=launcher,
    )
    return control, launcher, bus, machine


# --- painting ------------------------------------------------------------


def test_slots_with_a_set_are_lit_and_empty_slots_are_dark():
    control, _, _, _ = build([live("test"), live("emergency")])
    o = control.led_overrides()
    assert o[81]["type"] == "static"   # slot 0
    assert o[82]["type"] == "static"   # slot 1
    assert o[83] == {"type": "off"}    # slot 2, no set
    assert o[84] == {"type": "off"}


def test_a_lit_pad_is_a_promise_so_unknown_colours_still_light():
    # "white" is NOT one of the eight verified indices. Rendering it as OFF would
    # lose a selectable set because of a metadata typo -- worse than a wrong hue.
    control, _, _, _ = build([live("test", "white")])
    assert control.led_overrides()[81]["palette"] == colors.UNKNOWN_COLOR


def test_known_colour_names_resolve_to_verified_indices():
    control, _, _, _ = build([live("a", "red"), live("b", "cyan")])
    o = control.led_overrides()
    assert o[81]["palette"] == colors.RED
    assert o[82]["palette"] == colors.CYAN


# --- loading -------------------------------------------------------------


def test_holding_slot_zero_loads_the_first_set():
    control, launcher, bus, machine = build([live("test"), live("emergency")])
    machine.transition(RigState.SET_BROWSER, "test setup")  # where loads happen from
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert launcher.launched == [Path("/sets/test.als")]
    assert machine.state is RigState.PERFORMANCE


def test_loading_stops_the_running_set_first():
    # One Ableton owns the ASIO device. Two would fight over it, and the loser looks
    # like a broken interface rather than a mistake.
    control, launcher, bus, machine = build([live("test")])
    machine.transition(RigState.SET_BROWSER, "test setup")
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert launcher.stops == 1


def test_pressing_an_empty_slot_does_nothing_and_is_not_an_error():
    control, launcher, bus, machine = build([live("test")])
    machine.transition(RigState.SET_BROWSER, "test setup")
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 3}, pad=84))
    assert launcher.launched == []
    assert machine.state is RigState.SET_BROWSER


def test_reloading_the_already_loaded_set_is_a_no_op():
    # Otherwise re-pressing the boot set's pad stops and restarts a set that is
    # already up -- a pointless silence mid-show.
    control, launcher, bus, machine = build([live("test")])
    machine.transition(RigState.SET_BROWSER, "test setup")
    control.mark_loaded(Path("/sets/test.als"))
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert launcher.launched == []
    assert launcher.stops == 0


def test_a_refused_launch_goes_to_error_mode():
    control, launcher, bus, machine = build([live("test")], refuse=True)
    machine.transition(RigState.SET_BROWSER, "test setup")
    bus.publish(ActionRequested(action="LOAD_SET", params={"slot": 0}, pad=81))
    assert machine.state is RigState.ERROR


# --- pages and rescan ----------------------------------------------------


def test_page_actions_reach_the_browser():
    control, _, bus, _ = build([live("a")])
    bus.publish(ActionRequested(action="PAGE_NEXT", params={}, pad=92))
    bus.publish(ActionRequested(action="PAGE_PREV", params={}, pad=91))
    assert control.browser.page_calls == ["next", "prev"]


def test_rescan_finding_nothing_is_an_error_state():
    control, _, bus, machine = build([])
    bus.publish(ActionRequested(action="RESCAN_SETS", params={}, pad=19))
    assert control.browser.rescans == 1
    assert machine.state is RigState.ERROR
