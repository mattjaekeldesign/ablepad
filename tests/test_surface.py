"""
launchpad/surface.py — rig state in, lit surface out, named actions back.

The tests that matter are the hold ones. LOAD_SET is a 2000 ms hold and
SYSTEM_SHUTDOWN is 6000 ms because the alternative is changing song, or powering the
rig off, because a foot brushed a pad between numbers.
"""

from pathlib import Path

from launchpad import colors, grid
from launchpad.holdfeedback import HOLD_RAMP
from launchpad.mappings import Action, ModeConfig, PadBinding, ConfigLibrary, load_library
from launchpad.service import LaunchpadService
from launchpad.surface import Surface
from rig.events import ActionArmed, ActionCancelled, ActionRequested, EventBus, PadEvent
from rig.state import RigState, StateMachine

REPO = Path(__file__).resolve().parent.parent


class FakeService(LaunchpadService):
    """A service that never touches a device: we drive its input by hand."""

    def __init__(self):
        self.pending: list[PadEvent] = []
        self.painted: list = []
        self.bus = None

    def tick(self, now, specs=None):
        if specs:
            self.painted.append(list(specs))
        out, self.pending = self.pending, []
        return out


def library_with(pads: dict[int, PadBinding]) -> ConfigLibrary:
    """A one-mode library so tests are not coupled to the real configs."""
    lib = ConfigLibrary()
    lib.modes["boot"] = ModeConfig(
        id="boot", name="Boot", kind="mode",
        background={"type": "off"}, pads=pads, animations={}, transitions=(),
    )
    return lib


def binding(pad, action_type, hold_ms, params=None):
    return PadBinding(
        pad=pad, label="", led={"idle": {"type": "static", "palette": colors.GREEN}},
        action=Action(type=action_type, params=params or {}, hold_ms=hold_ms),
    )


def build(pads):
    bus = EventBus()
    seen: list = []
    for kind in (ActionRequested, ActionArmed, ActionCancelled):
        bus.subscribe(kind, seen.append)
    machine = StateMachine(bus=bus)
    service = FakeService()
    surface = Surface(service=service, library=library_with(pads), machine=machine, bus=bus)
    return surface, service, seen


# --- painting ------------------------------------------------------------


def test_every_tick_paints_the_whole_surface():
    surface, service, _ = build({})
    surface.tick(now_ms=0)
    assert len(service.painted) == 1
    assert len(service.painted[0]) == 81


def test_a_missing_config_shows_nothing_rather_than_stopping():
    surface, service, _ = build({})
    surface.library.modes.clear()          # library changed underneath the rig
    surface.tick(now_ms=0)                 # must not raise
    assert all(s.colour == colors.OFF for s in service.painted[0])


# --- actions with no hold -----------------------------------------------


def test_a_no_hold_action_fires_on_press():
    surface, service, seen = build({11: binding(11, "PAGE_NEXT", None)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    assert [type(e).__name__ for e in seen] == ["ActionRequested"]
    assert seen[0].action == "PAGE_NEXT" and seen[0].pad == 11


def test_a_press_on_an_unbound_pad_does_nothing():
    surface, service, seen = build({})
    service.pending = [PadEvent(note=44, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    assert seen == []


def test_an_explicit_none_action_does_nothing():
    surface, service, seen = build({11: binding(11, "NONE", None)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    assert seen == []


# --- hold to confirm -----------------------------------------------------


def test_load_set_does_not_fire_on_a_tap():
    surface, service, seen = build({11: binding(11, "LOAD_SET", 2000)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    service.pending = [PadEvent(note=11, velocity=0, pressed=False)]
    surface.tick(now_ms=300)               # released well before 2000 ms
    kinds = [type(e).__name__ for e in seen]
    assert kinds == ["ActionArmed", "ActionCancelled"]
    assert not any(isinstance(e, ActionRequested) for e in seen)


def test_load_set_fires_once_the_hold_completes():
    surface, service, seen = build({11: binding(11, "LOAD_SET", 2000)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    for t in range(100, 2000, 100):        # still held, not yet due
        surface.tick(now_ms=t)
    assert not any(isinstance(e, ActionRequested) for e in seen)
    surface.tick(now_ms=2000)
    fired = [e for e in seen if isinstance(e, ActionRequested)]
    assert len(fired) == 1 and fired[0].action == "LOAD_SET"


def test_a_completed_hold_fires_exactly_once():
    surface, service, seen = build({11: binding(11, "LOAD_SET", 2000)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    for t in (2000, 2100, 2200, 5000):
        surface.tick(now_ms=t)
    assert len([e for e in seen if isinstance(e, ActionRequested)]) == 1


def test_releasing_after_the_hold_fired_does_not_cancel_anything():
    surface, service, seen = build({11: binding(11, "LOAD_SET", 2000)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    surface.tick(now_ms=2000)              # fires
    service.pending = [PadEvent(note=11, velocity=0, pressed=False)]
    surface.tick(now_ms=2500)
    assert not any(isinstance(e, ActionCancelled) for e in seen)


def test_shutdown_needs_six_seconds():
    surface, service, seen = build({11: binding(11, "SYSTEM_SHUTDOWN", 6000)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    surface.tick(now_ms=5999)
    assert not any(isinstance(e, ActionRequested) for e in seen)
    surface.tick(now_ms=6000)
    assert any(isinstance(e, ActionRequested) for e in seen)


def test_a_mode_change_abandons_a_hold_in_progress():
    # Otherwise a hold started in one mode completes in another, firing an action
    # against a surface that no longer shows it.
    surface, service, seen = build({11: binding(11, "LOAD_SET", 2000)})
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    surface.machine.transition(RigState.ERROR, "fault")
    surface.tick(now_ms=100)
    surface.tick(now_ms=5000)
    assert not any(isinstance(e, ActionRequested) for e in seen)
    assert surface.holding == {}


# --- held pads are visible ----------------------------------------------


def test_a_held_pad_shows_hold_progress_not_its_pressed_colour():
    # Supersedes an earlier assertion that a held pad paints its config `pressed`
    # colour. Same intent -- the player must see the hold happening -- but a flat
    # colour cannot say HOW FAR ALONG the hold is, and that is the information a
    # 2000 ms hold actually needs to convey. See launchpad/holdfeedback.py.
    pads = {11: PadBinding(
        pad=11, label="", action=Action("LOAD_SET", {}, 2000),
        led={"idle": {"type": "static", "palette": colors.GREEN},
             "pressed": {"type": "static", "palette": colors.RED}},
    )}
    surface, service, _ = build(pads)
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    surface.tick(now_ms=100)
    painted = {s.index: s for s in service.painted[-1]}
    assert painted[11].colour == HOLD_RAMP[0]
    assert painted[11].colour != colors.GREEN, "must differ from idle, or nothing happened"


def test_the_held_pad_climbs_the_ramp_as_the_hold_progresses():
    pads = {11: PadBinding(
        pad=11, label="", action=Action("LOAD_SET", {}, 3000),
        led={"idle": {"type": "static", "palette": colors.GREEN}},
    )}
    surface, service, _ = build(pads)
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    seen = []
    for now in (100, 1500, 2900):
        surface.tick(now_ms=now)
        seen.append({s.index: s for s in service.painted[-1]}[11].colour)
    assert seen == list(HOLD_RAMP), "a 6 s shutdown hold must not look static"


def test_releasing_a_hold_returns_the_pad_to_normal():
    pads = {11: PadBinding(
        pad=11, label="", action=Action("LOAD_SET", {}, 2000),
        led={"idle": {"type": "static", "palette": colors.GREEN}},
    )}
    surface, service, _ = build(pads)
    service.pending = [PadEvent(note=11, velocity=90, pressed=True)]
    surface.tick(now_ms=0)
    surface.tick(now_ms=100)
    service.pending = [PadEvent(note=11, velocity=0, pressed=False)]
    surface.tick(now_ms=200)
    surface.tick(now_ms=300)
    painted = {s.index: s for s in service.painted[-1]}
    assert painted[11].colour == colors.GREEN, "an abandoned hold must stop looking armed"


# --- against the real configs -------------------------------------------


def test_the_real_boot_config_renders_and_arms_its_intro():
    library, _ = load_library(REPO / "configs", REPO / "animations")
    bus = EventBus()
    service = FakeService()
    surface = Surface(service=service, library=library, machine=StateMachine(bus=bus), bus=bus)
    surface.tick(now_ms=0)
    assert surface.player.is_playing, "boot.json binds an intro; it should be running"
    assert len(service.painted[-1]) == 81


def test_the_frame_buttons_are_not_special_cased():
    """
    MEASURED 2026-08-14/15: Custom, Session and Note never reach the rig at all --
    pressing them logged nothing in either ownership state. An earlier version
    treated 95/96/97 as layout buttons and snapped the device back to Programmer
    Mode; that code could never fire, and it nearly broke System Mode, which binds
    95 to ABLETON_RESTART and 97 to SYSTEM_REBOOT.

    So a frame button is an ordinary pad here: bound means it acts, unbound means
    nothing happens.
    """
    pads = {95: binding(95, "ABLETON_RESTART", None)}
    surface, service, seen = build(pads)
    service.pending = [PadEvent(note=95, velocity=127, pressed=True)]
    surface.tick(now_ms=0)
    fired = [e for e in seen if isinstance(e, ActionRequested)]
    assert [e.action for e in fired] == ["ABLETON_RESTART"]


def test_an_unbound_frame_button_does_nothing():
    surface, service, seen = build({})
    service.pending = [PadEvent(note=97, velocity=127, pressed=True)]
    surface.tick(now_ms=0)
    assert seen == []
