"""
tools/_bench.py pure logic, checked against the manual's OWN worked examples.

These tests need no hardware: they verify that the byte sequences our builders
produce match sequences the Programmer's Reference Manual prints in prose
(docs/launchpad-x-sysex.md §3, §6), and that port classification and
device-inquiry parsing behave. This is the off-rig verification tools/README.md
calls for.

Requires mido (import side effect of _bench). Skipped cleanly if absent.
"""

import pytest

mido = pytest.importorskip("mido", reason="_bench needs mido; install requirements")

from _bench import (  # noqa: E402  (import after skip guard)
    PortRole,
    clear_all,
    find_ports,
    led_batch,
    led_static,
    parse_device_inquiry,
    programmer_mode,
)

HEADER = (0x00, 0x20, 0x29, 0x02, 0x0C)  # manual p.6, mido convention (no F0/F7)


def test_programmer_mode_bytes_match_manual_p7():
    # Full frame per manual: F0 00 20 29 02 0C 0E 01 F7
    assert tuple(programmer_mode(True).data) == (*HEADER, 0x0E, 0x01)
    assert tuple(programmer_mode(False).data) == (*HEADER, 0x0E, 0x00)


def test_led_static_matches_manual_p15_worked_example():
    # Manual p.15: "F0h ... 03h 00h 0Bh 0Dh ..." = pad 11 static yellow (13).
    assert tuple(led_static(11, 13).data) == (*HEADER, 0x03, 0x00, 0x0B, 0x0D)


def test_led_batch_concatenates_colourspecs_like_manual_p15():
    # The static entries of the p.15 example, batched: type 0, index, colour each.
    message = led_batch([(11, 13), (13, 37)])
    assert tuple(message.data) == (*HEADER, 0x03, 0x00, 0x0B, 0x0D, 0x00, 0x0D, 0x25)


def test_clear_all_covers_all_81_leds_in_one_message():
    data = tuple(clear_all().data)
    assert data[:6] == (*HEADER, 0x03)
    specs = data[6:]
    assert len(specs) == 81 * 3  # type + index + colour per LED
    indices = specs[1::3]
    assert len(set(indices)) == 81
    assert set(specs[0::3]) == {0}  # all static
    assert set(specs[2::3]) == {0}  # all palette 0 = off (p.14), not grey


def test_all_data_bytes_are_valid_sysex_payload():
    # Every payload byte must be 7-bit; 0x80+ inside SysEx corrupts the stream.
    for message in (programmer_mode(True), led_static(99, 127), clear_all()):
        assert all(0 <= b <= 0x7F for b in message.data)


# --- port classification (manual p.6: DAW first interface, MIDI second) ---


def test_find_ports_classifies_by_name_when_names_say_so():
    ports = find_ports(["LPX DAW In", "LPX MIDI In", "EVO 8 MIDI"])
    roles = {p.name: (p.role, p.classified_by) for p in ports}
    assert roles["LPX DAW In"] == (PortRole.DAW, "name")
    assert roles["LPX MIDI In"] == (PortRole.MIDI, "name")
    assert "EVO 8 MIDI" not in roles  # not a Launchpad


def test_find_ports_falls_back_to_ordinal_and_says_so():
    ports = find_ports(["Launchpad X 0", "Launchpad X 1"])
    assert [(p.role, p.classified_by) for p in ports] == [
        (PortRole.DAW, "ordinal"),
        (PortRole.MIDI, "ordinal"),
    ]


def test_find_ports_ignores_non_launchpad_noise():
    assert find_ports(["Microsoft GS Wavetable Synth", "EVO 8"]) == []


# --- device inquiry parsing (manual p.6) ---


def test_inquiry_reply_application():
    reply = (0x7E, 0x00, 0x06, 0x02, 0x00, 0x20, 0x29, 0x13, 0x01, 0x00, 0x00, 3, 5, 1, 2)
    identity = parse_device_inquiry(reply)
    assert identity is not None
    assert identity.running_application is True
    assert identity.version == "3512"


def test_inquiry_reply_bootloader_flagged():
    reply = (0x7E, 0x00, 0x06, 0x02, 0x00, 0x20, 0x29, 0x13, 0x11, 0x00, 0x00, 1, 0, 0, 0)
    identity = parse_device_inquiry(reply)
    assert identity is not None
    assert identity.running_application is False


def test_inquiry_rejects_other_devices_and_junk():
    mini_mk3 = (0x7E, 0x00, 0x06, 0x02, 0x00, 0x20, 0x29, 0x14, 0x01, 0x00, 0x00, 1, 0, 0, 0)
    assert parse_device_inquiry(mini_mk3) is None
    assert parse_device_inquiry(()) is None
    assert parse_device_inquiry((0x7E, 0x00)) is None
