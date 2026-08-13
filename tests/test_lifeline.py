"""
Keep asking for the hotspot while disconnected -- and never touch a working link.

OBSERVED 2026-08-13: the profile was set to auto-connect and first in preference
order, the rig was disconnected, the hotspot came back, and Windows did not rejoin.
Passive auto-join is the wrong mechanism: Windows rescans on its own schedule, and
iOS sleeps Personal Hotspot until something tries to associate.
"""

from windows.wifi import NetworkStatus
from rig.lifeline import WifiLifeline


class FakeWifi:
    def __init__(self, connected=False, ssid=None):
        self.status_value = NetworkStatus(connected=connected, ssid=ssid)
        self.connects = []

    def status(self):
        return self.status_value

    def connect(self, ssid):
        self.connects.append(ssid)
        return True


def lifeline(wifi, now, ssid="Trailmix"):
    return WifiLifeline(wifi=wifi, ssid=ssid, clock=lambda: now[0], retry_interval_s=20.0)


def test_it_knocks_while_disconnected():
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = lifeline(wifi, now)
    line.poll()
    assert wifi.connects == ["Trailmix"]


def test_it_leaves_a_working_connection_completely_alone():
    # Matt joining a venue wifi by hand must not be undone by a watchdog, and a rig
    # that hops networks mid-set to satisfy a policy is worse than one that stays.
    now = [0.0]
    wifi = FakeWifi(connected=True, ssid="Some Venue Wifi")
    line = lifeline(wifi, now)
    for _ in range(5):
        now[0] += 60
        line.poll()
    assert wifi.connects == []


def test_it_respects_the_retry_interval():
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = lifeline(wifi, now)
    line.poll()
    now[0] = 19.0
    line.poll()
    assert len(wifi.connects) == 1
    now[0] = 20.0
    line.poll()
    assert len(wifi.connects) == 2


def test_polling_every_tick_is_cheap():
    # It is called from a 30 Hz loop; status() must not be hit 30 times a second.
    now = [0.0]
    wifi = FakeWifi(connected=False)
    calls = []
    wifi.status = lambda: (calls.append(1), NetworkStatus(False, None))[1]
    line = lifeline(wifi, now)
    for _ in range(100):
        line.poll()
    assert len(calls) == 1


def test_no_ssid_configured_disables_it_entirely():
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = lifeline(wifi, now, ssid="")
    line.poll()
    assert wifi.connects == []


def test_it_recovers_and_resets_its_count():
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = lifeline(wifi, now)
    line.poll()
    now[0] += 20
    line.poll()
    assert line.attempts == 2
    wifi.status_value = NetworkStatus(connected=True, ssid="Trailmix")
    now[0] += 20
    line.poll()
    assert line.attempts == 0


def test_a_radio_that_raises_does_not_break_the_loop():
    # No netsh, no adapter, off-Windows. The rig keeps running.
    now = [0.0]

    class Broken:
        def status(self):
            raise OSError("no wlan service")

        def connect(self, ssid):
            raise OSError("no wlan service")

    line = lifeline(Broken(), now)
    line.poll()  # must not raise
