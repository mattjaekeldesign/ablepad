"""
launchpad/device.py driven entirely through a fake backend — no mido, no hardware.

The point of the backend Protocol is that the parts that can strand a headless rig
are testable off-rig. The most important test in this file is the one asserting that
Live Mode is restored when connect() raises partway through.
"""

import pytest

from launchpad import colors, grid
from launchpad.device import (
    CMD_AFTERTOUCH,
    CMD_LED_FEEDBACK,
    CMD_LED_LIGHTING,
    CMD_PROGRAMMER_LIVE,
    CMD_VELOCITY_CURVE,
    HEADER,
    MAX_COLOURSPECS,
    DeviceError,
    LaunchpadDevice,
    LedSpec,
    Lighting,
    parse_device_inquiry,
)
from launchpad.ports import PortError

# Verbatim from the rig, 2026-08-12.
WIN_INPUTS = ["LPX MIDI 0", "MIDIIN2 (LPX MIDI) 1"]
WIN_OUTPUTS = ["Microsoft GS Wavetable Synth 0", "LPX MIDI 1", "MIDIOUT2 (LPX MIDI) 2"]

# The reply the device actually sends. Note family byte 0x03, where the manual says 0x13.
REAL_INQUIRY = (0x7E, 0, 6, 2, 0, 0x20, 0x29, 0x03, 0x01, 0, 0, 0, 3, 5, 1)


class FakeMessage:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class FakeIn:
    def __init__(self):
        self.queue = []
        self.closed = False
        self.sysex_delivered = False

    def iter_pending(self):
        out, self.queue = self.queue, []
        return iter(out)

    def close(self):
        self.closed = True


class FakeOut:
    def __init__(self):
        self.sent = []
        self.closed = False
        self.explode_on = None

    def send(self, message):
        if self.explode_on is not None and len(self.sent) >= self.explode_on:
            raise OSError("cable yanked")
        self.sent.append(tuple(message.data))

    def close(self):
        self.closed = True


class FakeBackend:
    def __init__(self, inputs=WIN_INPUTS, outputs=WIN_OUTPUTS, reply=REAL_INQUIRY):
        self.inputs, self.outputs, self.reply = inputs, outputs, reply
        self.inport, self.outport = FakeIn(), FakeOut()

    def input_names(self):
        return list(self.inputs)

    def output_names(self):
        return list(self.outputs)

    def open_input(self, name):
        self.opened_in = name
        return self.inport

    def open_output(self, name):
        self.opened_out = name
        return self.outport

    def sysex(self, payload):
        # The inquiry is answered immediately so connect() need not really wait.
        if tuple(payload) == (0x7E, 0x7F, 0x06, 0x01) and self.reply:
            self.inport.queue.append(FakeMessage("sysex", data=self.reply))
        return FakeMessage("sysex", data=tuple(payload))

    def deliver_sysex(self, port):
        port.sysex_delivered = True


def device(backend, **kw):
    """
    A device with the real-time waits removed.

    settle_s is a hardware settling delay and the inquiry timeout is a real timeout;
    neither teaches us anything in a fake-backend test, and paying them ~20 times
    turned a 0.2 s suite into 2.4 s. The controller contract is that tests run a
    thousand ticks in milliseconds — the driver should not be the thing that breaks it.
    """
    kw.setdefault("settle_s", 0)
    return LaunchpadDevice(backend, **kw)


def commands(out):
    """Command byte of every Novation-addressed message sent."""
    return [m[len(HEADER)] for m in out.sent if m[: len(HEADER)] == HEADER]


# --- the safety contract -------------------------------------------------


def test_close_restores_live_mode():
    backend = FakeBackend()
    with device(backend) as dev:
        assert dev.connected
    assert (*HEADER, CMD_PROGRAMMER_LIVE, 0) in backend.outport.sent


def test_live_mode_restored_even_if_the_body_raises():
    backend = FakeBackend()
    with pytest.raises(RuntimeError, match="boom"):
        with device(backend):
            raise RuntimeError("boom")
    assert (*HEADER, CMD_PROGRAMMER_LIVE, 0) in backend.outport.sent, (
        "Programmer Mode disables the Setup menu; failing to restore on an "
        "exception strands a headless rig"
    )


def test_close_is_idempotent():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    dev.close()
    before = len(backend.outport.sent)
    dev.close()
    assert len(backend.outport.sent) == before


def test_close_never_raises_even_if_the_cable_is_gone():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.outport.explode_on = len(backend.outport.sent)  # every further send fails
    dev.close()  # must not raise: close() runs in finally blocks
    assert backend.outport.closed


# --- connect sequence ----------------------------------------------------


def test_connect_opens_the_second_interface_not_the_first():
    backend = FakeBackend()
    device(backend).connect()
    assert backend.opened_in == "MIDIIN2 (LPX MIDI) 1"
    assert backend.opened_out == "MIDIOUT2 (LPX MIDI) 2"


def test_connect_asserts_the_settings_that_flood_the_event_loop():
    backend = FakeBackend()
    device(backend).connect()
    sent = commands(backend.outport)
    assert CMD_PROGRAMMER_LIVE in sent
    assert CMD_AFTERTOUCH in sent      # measured ON out of the box: 130 msgs / 10 presses
    assert CMD_VELOCITY_CURVE in sent  # measured ON: velocities ranged 21-127
    assert CMD_LED_FEEDBACK in sent    # off = LED writes silently do nothing


def test_connect_clears_rtmidis_sysex_ignore():
    backend = FakeBackend()
    device(backend).connect()
    assert backend.inport.sysex_delivered, (
        "without this the inquiry reply is discarded and a live device reports 'no reply'"
    )


def test_bootloader_is_refused():
    boot = (0x7E, 0, 6, 2, 0, 0x20, 0x29, 0x03, 0x11, 0, 0, 0, 3, 5, 1)
    with pytest.raises(DeviceError, match="BOOTLOADER"):
        device(FakeBackend(reply=boot)).connect()


def test_missing_device_raises_before_anything_is_opened():
    with pytest.raises(PortError):
        device(FakeBackend(inputs=[], outputs=[])).connect()


def test_silent_device_is_a_warning_not_a_crash():
    # A port can exist while nothing answers. That is worth logging, not dying over.
    dev = device(FakeBackend(reply=None), identify_timeout_s=0.05)
    assert dev.connect() is None
    assert dev.connected


# --- inquiry parsing -----------------------------------------------------


def test_real_reply_parses_despite_the_manual_being_wrong():
    identity = parse_device_inquiry(REAL_INQUIRY)
    assert identity is not None and identity.running_application
    assert identity.version == "0351"


def test_manual_shaped_reply_also_parses():
    doc = (0x7E, 0, 6, 2, 0, 0x20, 0x29, 0x13, 0x01, 0, 0, 3, 5, 1, 2)
    assert parse_device_inquiry(doc).version == "3512"


def test_a_mini_mk3_is_not_a_launchpad_x():
    mini = (0x7E, 0, 6, 2, 0, 0x20, 0x29, 0x14, 0x01, 0, 0, 1, 0, 0, 0)
    assert parse_device_inquiry(mini) is None


def test_junk_is_rejected():
    assert parse_device_inquiry(()) is None
    assert parse_device_inquiry((0x7E, 0)) is None


# --- output --------------------------------------------------------------


def test_clear_blanks_all_81_leds_in_one_message():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.outport.sent.clear()
    dev.clear()
    assert len(backend.outport.sent) == 1
    body = backend.outport.sent[0][len(HEADER) :]
    assert body[0] == CMD_LED_LIGHTING
    assert len(body[1:]) == 81 * 3
    assert set(body[3::3]) == {colors.OFF}


def test_set_leds_chunks_at_the_documented_ceiling():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.outport.sent.clear()
    dev.set_leds([LedSpec(index=i, colour=colors.RED) for i in grid.ALL_INDICES] * 2)
    assert len(backend.outport.sent) == 2  # 162 specs -> 81 + 81
    for message in backend.outport.sent:
        assert len(message[len(HEADER) + 1 :]) <= MAX_COLOURSPECS * 3


def test_flashing_spec_carries_both_colours():
    spec = LedSpec(index=11, colour=colors.RED, lighting=Lighting.FLASHING, colour_b=colors.BLUE)
    assert spec.payload() == (1, 11, colors.RED, colors.BLUE)


# --- input ---------------------------------------------------------------


def test_release_is_note_on_velocity_zero_not_note_off():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.inport.queue = [
        FakeMessage("note_on", note=11, velocity=87),
        FakeMessage("note_on", note=11, velocity=0),
    ]
    events = dev.read_events()
    assert [(e.note, e.pressed) for e in events] == [(11, True), (11, False)]


def test_cc_frame_is_read_as_well_as_the_note_grid():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.inport.queue = [FakeMessage("control_change", control=91, value=127)]
    assert [(e.note, e.pressed) for e in dev.read_events()] == [(91, True)]


def test_aftertouch_and_clock_are_ignored():
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.inport.queue = [
        FakeMessage("polytouch", note=27, value=64),
        FakeMessage("clock"),
        FakeMessage("note_on", note=27, velocity=30),
    ]
    assert len(dev.read_events()) == 1


def test_the_logo_is_never_reported_as_a_press():
    # LED 99 lights but has no button under it — confirmed on hardware.
    backend = FakeBackend()
    dev = device(backend)
    dev.connect()
    backend.inport.queue = [FakeMessage("control_change", control=99, value=127)]
    assert dev.read_events() == []
