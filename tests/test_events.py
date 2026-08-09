"""EventBus: routing, isolation of failing handlers, unsubscribe."""

from rig.events import EventBus, PadEvent, Tick


def test_routes_by_event_type():
    bus = EventBus()
    pads, ticks = [], []
    bus.subscribe(PadEvent, pads.append)
    bus.subscribe(Tick, ticks.append)
    bus.publish(PadEvent(note=11, velocity=127, pressed=True))
    bus.publish(Tick(1))
    assert pads == [PadEvent(11, 127, True)]
    assert ticks == [Tick(1)]


def test_failing_handler_does_not_block_later_handlers(caplog):
    bus = EventBus()
    seen = []

    def bad(_event):
        raise RuntimeError("subscriber bug")

    bus.subscribe(Tick, bad)
    bus.subscribe(Tick, seen.append)
    with caplog.at_level("ERROR"):
        bus.publish(Tick(1))
    assert seen == [Tick(1)]  # the show goes on
    assert any("continuing" in r.message for r in caplog.records)


def test_unsubscribe():
    bus = EventBus()
    seen = []
    unsubscribe = bus.subscribe(Tick, seen.append)
    bus.publish(Tick(1))
    unsubscribe()
    bus.publish(Tick(2))
    assert seen == [Tick(1)]


def test_publish_with_no_subscribers_is_fine():
    EventBus().publish(Tick(1))
