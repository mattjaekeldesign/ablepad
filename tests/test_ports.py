"""
launchpad/ports.py — checked against the EXACT strings the rig reported.

The values in test_windows_* are copied verbatim from
tools/results/midi-ports-launchpad-attached.txt, measured 2026-08-12. They are the
reason this module exists: a naive substring classifier passes every plausible-looking
unit test and then fails on the only naming scheme that matters.
"""

from launchpad.ports import (
    Classification,
    Port,
    PortError,
    PortRole,
    classify,
    select,
)

# Verbatim from the rig, 2026-08-12.
WIN_INPUTS = ["LPX MIDI 0", "MIDIIN2 (LPX MIDI) 1"]
WIN_OUTPUTS = ["Microsoft GS Wavetable Synth 0", "LPX MIDI 1", "MIDIOUT2 (LPX MIDI) 2"]


def test_windows_second_interface_is_the_midi_one():
    ports = classify(WIN_INPUTS)
    assert [(p.name, p.role, p.interface) for p in ports] == [
        ("LPX MIDI 0", PortRole.DAW, 1),
        ("MIDIIN2 (LPX MIDI) 1", PortRole.MIDI, 2),
    ]
    assert select(ports, PortRole.MIDI).name == "MIDIIN2 (LPX MIDI) 1"


def test_windows_outputs_ignore_the_gs_synth():
    ports = classify(WIN_OUTPUTS)
    assert len(ports) == 2
    assert select(ports, PortRole.MIDI).name == "MIDIOUT2 (LPX MIDI) 2"
    assert select(ports, PortRole.DAW).name == "LPX MIDI 1"


def test_windows_names_are_classified_by_interface_not_by_name():
    # Every Windows name contains "MIDI" and none contains "DAW". If this ever
    # reports BY_NAME, the classifier has regressed to substring matching.
    assert all(p.how is Classification.BY_INTERFACE for p in classify(WIN_INPUTS))


def test_explicit_names_still_win_on_macos_and_linux():
    ports = classify(["Launchpad X LPX DAW Out", "Launchpad X LPX MIDI Out"])
    assert [(p.role, p.how) for p in ports] == [
        (PortRole.DAW, Classification.BY_NAME),
        (PortRole.MIDI, Classification.BY_NAME),
    ]


def test_uninformative_names_fall_back_to_position_and_say_so():
    ports = classify(["Launchpad X 0", "Launchpad X 1"])
    assert [(p.role, p.how) for p in ports] == [
        (PortRole.DAW, Classification.BY_ORDINAL),
        (PortRole.MIDI, Classification.BY_ORDINAL),
    ]


def test_non_launchpad_devices_are_dropped():
    assert classify(["Microsoft GS Wavetable Synth 0", "Audient EVO8", "Realtek"]) == []


def test_missing_port_raises_with_something_actionable():
    try:
        select(classify([]), PortRole.MIDI)
    except PortError as exc:
        assert "plugged in" in str(exc)
    else:
        raise AssertionError("expected PortError")


def test_two_launchpads_refuses_to_guess():
    # A second unit, or a virtual port impersonating one. Picking the first would
    # silently drive the wrong device.
    ports = [
        Port("MIDIIN2 (LPX MIDI) 1", PortRole.MIDI, Classification.BY_INTERFACE, 2),
        Port("MIDIIN2 (LPX MIDI) 3", PortRole.MIDI, Classification.BY_INTERFACE, 2),
    ]
    try:
        select(ports, PortRole.MIDI)
    except PortError as exc:
        assert "Refusing to guess" in str(exc)
    else:
        raise AssertionError("expected PortError")


# --- the trailing index is POSITIONAL and moves when devices are added ---
#
# MEASURED 2026-08-12, the same rig an hour apart:
#
#   two devices   IN: 'LPX MIDI 0'                'MIDIIN2 (LPX MIDI) 1'
#   three devices IN: 'Ampero II Stage MIDI 0'    'LPX MIDI 1'   'MIDIIN2 (LPX MIDI) 2'
#
# Plugging in a Hotone Ampero renumbered the Launchpad's ports. Anything matching a
# full port name including that integer breaks the moment a MIDI device is added,
# removed, or enumerates in a different order after a reboot.

THREE_DEVICE_INPUTS = [
    "Ampero II Stage MIDI 0",
    "LPX MIDI 1",
    "MIDIIN2 (LPX MIDI) 2",
]
THREE_DEVICE_OUTPUTS = [
    "Microsoft GS Wavetable Synth 0",
    "Ampero II Stage MIDI 1",
    "LPX MIDI 2",
    "MIDIOUT2 (LPX MIDI) 3",
]


def test_a_second_midi_device_renumbers_the_launchpad_but_changes_nothing():
    ports = classify(THREE_DEVICE_INPUTS)
    assert [(p.name, p.role) for p in ports] == [
        ("LPX MIDI 1", PortRole.DAW),
        ("MIDIIN2 (LPX MIDI) 2", PortRole.MIDI),
    ]
    assert select(ports, PortRole.MIDI).name == "MIDIIN2 (LPX MIDI) 2"


def test_the_ampero_is_not_mistaken_for_a_launchpad():
    # It is a MIDI device with "MIDI" in its name sitting at index 0, exactly where
    # the Launchpad's DAW port used to be. Ordinal-based logic would grab it.
    assert all("Ampero" not in p.name for p in classify(THREE_DEVICE_INPUTS))
    assert all("Ampero" not in p.name for p in classify(THREE_DEVICE_OUTPUTS))


def test_outputs_survive_the_shift_too():
    ports = classify(THREE_DEVICE_OUTPUTS)
    assert select(ports, PortRole.MIDI).name == "MIDIOUT2 (LPX MIDI) 3"
    assert select(ports, PortRole.DAW).name == "LPX MIDI 2"
