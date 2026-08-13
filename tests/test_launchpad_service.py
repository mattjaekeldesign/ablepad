"""
launchpad/service.py — the connection lifecycle, especially losing one.

The roadmap calls the reconnect path the single most common way this rig dies on
stage, so these tests are mostly about failure: a yanked cable, a device that never
appears, a device that comes back. The rule under all of them is that none of it may
raise into the tick loop, because a rig with no user interface still has a show to
finish.
"""


from launchpad import colors, grid
from launchpad.device import HEADER, CMD_PROGRAMMER_LIVE, LedSpec
from launchpad.service import LaunchpadService
from rig.events import EventBus, PadEvent

WIN_INPUTS = ["LPX MIDI 0", "MIDIIN2 (LPX MIDI) 1"]
WIN_OUTPUTS = ["Microsoft GS Wavetable Synth 0", "LPX MIDI 1", "MIDIOUT2 (LPX MIDI) 2"]
REAL_INQUIRY = (0x7E, 0, 6, 2, 0, 0x20, 0x29, 0x03, 0x01, 0, 0, 0, 3, 5, 1)


class FakeMessage:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class FakeIn:
    def __init__(self):
        self.queue, self.closed, self.fail = [], False, False

    def iter_pending(self):
        if self.fail:
            raise OSError("device disappeared")
        out, self.queue = self.queue, []
        return iter(out)

    def close(self):
        self.closed = True


class FakeOut:
    def __init__(self):
        self.sent, self.closed, self.fail = [], False, False

    def send(self, message):
        if self.fail:
            raise OSError("device disappeared")
        self.sent.append(tuple(message.data))

    def close(self):
        self.closed = True


class FakeBackend:
    """A backend whose device can be made to vanish and come back."""

    def __init__(self, present=True):
        self.present = present
        self.inport, self.outport = FakeIn(), FakeOut()
        self.opens = 0

    # the cable
    def unplug(self):
        self.present = False
        self.inport.fail = self.outport.fail = True

    def replug(self):
        self.present = True
        self.inport, self.outport = FakeIn(), FakeOut()

    def input_names(self):
        return list(WIN_INPUTS) if self.present else []

    def output_names(self):
        return list(WIN_OUTPUTS) if self.present else []

    def open_input(self, name):
        self.opens += 1
        return self.inport

    def open_output(self, name):
        return self.outport

    def sysex(self, payload):
        if tuple(payload) == (0x7E, 0x7F, 0x06, 0x01) and self.present:
            self.inport.queue.append(FakeMessage("sysex", data=REAL_INQUIRY))
        return FakeMessage("sysex", data=tuple(payload))

    def deliver_sysex(self, port):
        pass


def service(backend, **kw):
    # Real waits teach nothing against a fake backend, and twenty reconnects paid
    # twenty settle delays -- 3 s for a suite that should be milliseconds.
    kw.setdefault("retry_interval_s", 2.0)
    kw.setdefault("settle_s", 0)
    kw.setdefault("identify_timeout_s", 0.05)
    svc = LaunchpadService(backend, **kw)
    return svc


def commands(out):
    return [m[len(HEADER)] for m in out.sent if m[: len(HEADER)] == HEADER]


# --- the happy path ------------------------------------------------------


def test_connects_and_reports_it():
    backend = FakeBackend()
    svc = service(backend)
    assert svc.ensure_connected(now=0.0) is True
    assert svc.connected
    assert svc.stats["connects"] == 1


def test_poll_publishes_presses_to_the_bus():
    backend = FakeBackend()
    bus = EventBus()
    seen: list[PadEvent] = []
    bus.subscribe(PadEvent, seen.append)
    svc = service(backend, bus=bus)
    svc.ensure_connected(0.0)
    backend.inport.queue = [FakeMessage("note_on", note=11, velocity=90)]
    events = svc.poll()
    assert [e.note for e in events] == [11]
    assert [e.note for e in seen] == [11]


# --- losing the device ---------------------------------------------------


def test_a_yanked_cable_does_not_raise_into_the_tick_loop():
    backend = FakeBackend()
    svc = service(backend)
    svc.ensure_connected(0.0)
    backend.unplug()
    assert svc.poll() == []          # must not raise
    assert svc.paint([LedSpec(11, colors.RED)]) is False
    assert not svc.connected
    assert svc.stats["losses"] >= 1


def test_absent_device_is_survivable_forever():
    svc = service(FakeBackend(present=False))
    now = 0.0
    for _ in range(50):
        now += 2.5
        assert svc.tick(now, [LedSpec(11, colors.RED)]) == []
    assert not svc.connected


def test_retries_are_rate_limited():
    # A 30 Hz loop must not attempt a reconnect 30 times a second.
    backend = FakeBackend(present=False)
    svc = service(backend, retry_interval_s=2.0)
    for i in range(60):                       # two seconds of ticks at 30 Hz
        svc.ensure_connected(now=i / 30.0)
    assert backend.opens == 0                 # nothing to open, but also…
    svc2 = service(FakeBackend(), retry_interval_s=2.0)
    b2 = svc2.backend
    svc2.ensure_connected(0.0)
    b2.unplug()
    svc2.poll()                               # notices the loss
    for i in range(60):
        svc2.ensure_connected(now=i / 30.0)   # all inside one retry window
    assert b2.opens == 1                      # the original connect only


# --- coming back ---------------------------------------------------------


def test_replug_reconnects_and_reruns_the_full_init():
    backend = FakeBackend()
    svc = service(backend, retry_interval_s=1.0)
    svc.ensure_connected(0.0)
    backend.unplug()
    svc.poll()
    assert not svc.connected

    backend.replug()
    assert svc.ensure_connected(now=10.0) is True
    assert svc.connected
    assert svc.stats["connects"] == 2

    # The device forgets everything across a replug (manual p.18). A reconnect that
    # only reopened the port would leave aftertouch on and the surface in Live mode.
    sent = commands(backend.outport)
    from launchpad.device import CMD_AFTERTOUCH, CMD_LED_FEEDBACK, CMD_VELOCITY_CURVE

    assert CMD_PROGRAMMER_LIVE in sent
    assert CMD_AFTERTOUCH in sent
    assert CMD_VELOCITY_CURVE in sent
    assert CMD_LED_FEEDBACK in sent


def test_surviving_twenty_replugs():
    # The roadmap says test this 20 times, not twice.
    backend = FakeBackend()
    svc = service(backend, retry_interval_s=0.0)
    now = 0.0
    for cycle in range(20):
        now += 1.0
        assert svc.ensure_connected(now), f"failed to connect on cycle {cycle}"
        backend.unplug()
        svc.poll()
        assert not svc.connected
        backend.replug()
    assert svc.stats["connects"] == 20
    assert svc.stats["losses"] == 20


# --- painting ------------------------------------------------------------


def test_paint_reaches_the_device_when_connected():
    backend = FakeBackend()
    svc = service(backend)
    svc.ensure_connected(0.0)
    backend.outport.sent.clear()
    assert svc.paint([LedSpec(i, colors.GREEN) for i in grid.PAD_INDICES]) is True
    assert len(backend.outport.sent) == 1


def test_paint_is_a_no_op_rather_than_an_error_when_disconnected():
    svc = service(FakeBackend(present=False))
    assert svc.paint([LedSpec(11, colors.RED)]) is False


def test_close_restores_live_mode():
    backend = FakeBackend()
    svc = service(backend)
    svc.ensure_connected(0.0)
    svc.close()
    assert (*HEADER, CMD_PROGRAMMER_LIVE, 0) in backend.outport.sent
    svc.close()  # idempotent


def test_tick_reads_before_it_paints():
    # A press arriving this tick should come back from this tick, not the next one.
    backend = FakeBackend()
    svc = service(backend)
    svc.ensure_connected(0.0)
    backend.inport.queue = [FakeMessage("control_change", control=91, value=127)]
    events = svc.tick(now=1.0, specs=[LedSpec(11, colors.RED)])
    assert [e.note for e in events] == [91]


# --- a device that has GONE must not be "restored" -----------------------
#
# MEASURED 2026-08-13: a twelve-cycle replug test on real hardware logged
#   "COULD NOT RESTORE LIVE MODE ... the Setup menu stays disabled"
# twelve times. Every one was false. The device was already unplugged, and a
# Launchpad powers on into Live Mode by itself (manual p.18), so there was nothing
# to restore and nothing wrong. At a gig that message is the worst possible thing to
# read while hunting the real fault.


def test_losing_the_device_does_not_attempt_a_futile_restore(caplog):
    import logging

    backend = FakeBackend()
    svc = service(backend)
    svc.ensure_connected(0.0)
    backend.unplug()
    with caplog.at_level(logging.ERROR):
        svc.poll()
    assert "COULD NOT RESTORE" not in caplog.text, (
        "the device is gone; claiming the Setup menu is stranded is false and alarming"
    )


def test_a_clean_close_still_restores():
    backend = FakeBackend()
    svc = service(backend)
    svc.ensure_connected(0.0)
    svc.close()
    assert (*HEADER, CMD_PROGRAMMER_LIVE, 0) in backend.outport.sent


def test_twenty_replugs_produce_no_false_alarms(caplog):
    import logging

    backend = FakeBackend()
    svc = service(backend, retry_interval_s=0.0)
    now = 0.0
    with caplog.at_level(logging.ERROR):
        for _ in range(20):
            now += 1.0
            svc.ensure_connected(now)
            backend.unplug()
            svc.poll()
            backend.replug()
    assert svc.stats["connects"] == 20
    assert "COULD NOT RESTORE" not in caplog.text
