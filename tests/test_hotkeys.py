"""
The key strip: hold one of three keys, something happens.

Exists because the Launchpad cannot carry system controls during a performance --
only grid pads reach the rig, their note map belongs to whichever Custom layout is
loaded, and it moved under us on a firmware update.
"""

from rig.hotkeys import Hotkey, HotkeyControl


class FakeReader:
    def __init__(self):
        self.down: set[int] = set()

    def pressed(self, vk: int) -> bool:
        return vk in self.down


def build(hold_ms=1000, vk=0x7C):
    now = [0.0]
    reader = FakeReader()
    fired = []
    keys = (Hotkey(vk=vk, name="F13", hold_ms=hold_ms, action=lambda: fired.append("go")),)
    control = HotkeyControl(reader=reader, keys=keys, clock=lambda: now[0])
    return control, reader, fired, now


def test_a_completed_hold_fires():
    control, reader, fired, now = build(hold_ms=1000)
    reader.down.add(0x7C)
    control.poll()
    now[0] = 1.0
    control.poll()
    assert fired == ["go"]


def test_a_tap_does_nothing():
    # THE reason every key is hold-gated: this strip sits where hands and feet are,
    # and the cost of a knock is the audio stopping mid-song.
    control, reader, fired, now = build(hold_ms=1000)
    reader.down.add(0x7C)
    control.poll()
    now[0] = 0.2
    reader.down.clear()
    control.poll()
    now[0] = 5.0
    control.poll()
    assert fired == []


def test_it_fires_once_per_hold_not_once_per_tick():
    control, reader, fired, now = build(hold_ms=1000)
    reader.down.add(0x7C)
    control.poll()
    for t in (1.0, 1.1, 1.2, 9.0):
        now[0] = t
        control.poll()
    assert fired == ["go"]


def test_releasing_and_holding_again_fires_again():
    control, reader, fired, now = build(hold_ms=1000)
    reader.down.add(0x7C)
    control.poll()
    now[0] = 1.0
    control.poll()
    now[0] = 1.5
    reader.down.clear()
    control.poll()
    now[0] = 2.0
    reader.down.add(0x7C)
    control.poll()
    now[0] = 3.0
    control.poll()
    assert fired == ["go", "go"]


def test_the_clock_starts_when_the_key_goes_down():
    # Not when polling began -- otherwise a key already held at startup fires
    # immediately, which on the reboot key is a machine that restarts itself.
    control, reader, fired, now = build(hold_ms=1000)
    now[0] = 100.0
    reader.down.add(0x7C)
    control.poll()
    now[0] = 100.5
    control.poll()
    assert fired == []
    now[0] = 101.0
    control.poll()
    assert fired == ["go"]


def test_each_key_holds_independently():
    now = [0.0]
    reader = FakeReader()
    fired = []
    keys = (
        Hotkey(vk=0x7C, name="F13", hold_ms=1000, action=lambda: fired.append("browser")),
        Hotkey(vk=0x7D, name="F14", hold_ms=4000, action=lambda: fired.append("reboot")),
        Hotkey(vk=0x7E, name="F15", hold_ms=2000, action=lambda: fired.append("restart")),
    )
    control = HotkeyControl(reader=reader, keys=keys, clock=lambda: now[0])

    reader.down.update({0x7C, 0x7D, 0x7E})
    control.poll()
    now[0] = 1.0
    control.poll()
    assert fired == ["browser"], "only the 1 s key is due"
    now[0] = 2.0
    control.poll()
    assert fired == ["browser", "restart"]
    now[0] = 4.0
    control.poll()
    assert fired == ["browser", "restart", "reboot"]


def test_the_longest_hold_belongs_to_the_most_destructive_action():
    # Reboot costs a walk to the machine; the browser costs a moment of silence.
    from rig.hotkeys import Hotkey as H

    browser = H(vk=0x7C, name="F13", hold_ms=1000, action=lambda: None)
    restart = H(vk=0x7E, name="F15", hold_ms=2000, action=lambda: None)
    reboot = H(vk=0x7D, name="F14", hold_ms=4000, action=lambda: None)
    assert browser.hold_ms < restart.hold_ms < reboot.hold_ms


def test_a_failing_action_does_not_stop_the_loop():
    now = [0.0]
    reader = FakeReader()

    def boom():
        raise RuntimeError("command exploded")

    control = HotkeyControl(
        reader=reader,
        keys=(Hotkey(vk=0x7C, name="F13", hold_ms=1000, action=boom),),
        clock=lambda: now[0],
    )
    reader.down.add(0x7C)
    control.poll()
    now[0] = 1.0
    control.poll()  # must not raise


def test_a_dead_reader_does_not_stop_the_loop():
    now = [0.0]

    class Broken:
        def pressed(self, vk):
            raise OSError("no user32")

    control = HotkeyControl(
        reader=Broken(),
        keys=(Hotkey(vk=0x7C, name="F13", hold_ms=1000, action=lambda: None),),
        clock=lambda: now[0],
    )
    control.poll()  # must not raise


def test_no_keys_configured_is_inert():
    now = [0.0]
    reader = FakeReader()
    reader.down.add(0x7C)
    control = HotkeyControl(reader=reader, keys=(), clock=lambda: now[0])
    control.poll()
    assert control.held == {}
