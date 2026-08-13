"""RigController: pacing with a fake clock, tick events, stop, overrun re-anchor."""

from rig.controller import RigController
from rig.events import EventBus, Tick
from rig.state import StateMachine


class FakeTime:
    """Deterministic clock: sleep() advances it; tick work can add extra cost."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        assert seconds >= 0
        self.sleeps.append(seconds)
        self.now += seconds


def build(tick_hz=30):
    fake = FakeTime()
    bus = EventBus()
    controller = RigController(
        machine=StateMachine(bus=bus),
        bus=bus,
        tick_hz=tick_hz,
        clock=fake.clock,
        sleep=fake.sleep,
    )
    return controller, bus, fake


def test_runs_exactly_max_ticks():
    controller, _bus, _fake = build()
    assert controller.run(max_ticks=100) == 100
    assert controller.ticks == 100


def test_publishes_tick_events_with_counts():
    controller, bus, _fake = build()
    seen = []
    bus.subscribe(Tick, seen.append)
    controller.run(max_ticks=3)
    assert seen == [Tick(1), Tick(2), Tick(3)]


def test_paces_at_the_configured_rate():
    controller, _bus, fake = build(tick_hz=10)
    controller.run(max_ticks=50)
    # Instant ticks + 100 ms period => total sleep ~= 50 * 0.1 s.
    assert abs(sum(fake.sleeps) - 5.0) < 0.01
    assert controller.overruns == 0


def test_stop_from_a_subscriber_ends_the_loop():
    controller, bus, _fake = build()

    def stop_at_five(event):
        if event.count == 5:
            controller.stop("test")

    bus.subscribe(Tick, stop_at_five)
    assert controller.run(max_ticks=1000) == 5


def test_overrun_reanchors_instead_of_bursting():
    controller, bus, fake = build(tick_hz=10)

    def slow_tick(_event):
        fake.now += 0.25  # every tick costs 2.5 periods

    bus.subscribe(Tick, slow_tick)
    controller.run(max_ticks=4)
    assert controller.overruns == 4
    assert fake.sleeps == []  # never slept, but also never went negative


# --- tick hooks (Phase 3 wiring) -----------------------------------------


def test_on_tick_hooks_run_every_tick_in_order():
    from rig.controller import RigController
    from rig.events import EventBus
    from rig.state import StateMachine

    calls: list[str] = []
    controller = RigController(
        machine=StateMachine(bus=EventBus()),
        bus=EventBus(),
        tick_hz=1000,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
        on_tick=[lambda: calls.append("a"), lambda: calls.append("b")],
    )
    controller.run(max_ticks=3)
    assert calls == ["a", "b", "a", "b", "a", "b"]


def test_a_throwing_hook_does_not_take_the_rig_down():
    # A dead Launchpad service must not stop a show that Ableton is still driving.
    from rig.controller import RigController
    from rig.events import EventBus
    from rig.state import StateMachine

    survived: list[int] = []

    def explode():
        raise RuntimeError("device on fire")

    controller = RigController(
        machine=StateMachine(bus=EventBus()),
        bus=EventBus(),
        tick_hz=1000,
        clock=lambda: 0.0,
        sleep=lambda _s: None,
        on_tick=[explode, lambda: survived.append(1)],
    )
    ticks = controller.run(max_ticks=5)
    assert ticks == 5
    assert controller.hook_errors == 5
    # Each hook is isolated. A dead Launchpad must not stop the set browser or the
    # Ableton supervisor from ticking -- they are independent subsystems that happen
    # to share a clock.
    assert survived == [1, 1, 1, 1, 1]
