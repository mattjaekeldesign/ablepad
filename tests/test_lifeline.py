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


def lifeline(wifi, now, ssid="Trailmix", grace_s=0.0):
    # grace_s=0 by default HERE so these tests exercise the knock/interval mechanics
    # directly. The grace period is the safety property and gets its own test --
    # burying it in a shared helper is how it would get weakened by accident.
    return WifiLifeline(
        wifi=wifi, ssid=ssid, clock=lambda: now[0], retry_interval_s=20.0, grace_s=grace_s
    )


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
    now[0] = 40.0  # first interval doubled to 40 after the first attempt
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
    now[0] += 40  # knocks are backed off
    line.poll()
    assert line.attempts == 2
    wifi.status_value = NetworkStatus(connected=True, ssid="Trailmix")
    now[0] += 20  # status is checked on the FIXED interval, not the backed-off one
    line.poll()
    assert line.attempts == 0, "a restored connection must be noticed promptly"


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


# --- not making things worse ---------------------------------------------


def test_it_waits_out_the_grace_period_before_the_first_knock():
    # THE fix. A connect attempt at an absent SSID occupies the radio, and Windows
    # reassociating with a network it knows must not be interrupted -- a watchdog
    # that knocks immediately can stop the recovery it exists to help.
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = WifiLifeline(wifi=wifi, ssid="Trailmix", clock=lambda: now[0],
                        retry_interval_s=20.0, grace_s=60.0)
    for _ in range(3):
        line.poll()
        now[0] += 20
    assert wifi.connects == [], "must let Windows try on its own first"
    now[0] += 20  # past the grace period
    line.poll()
    assert wifi.connects == ["Trailmix"]


def test_it_backs_off_rather_than_knocking_forever():
    # The target may be a hotspot in a bag two towns away.
    now = [100.0]
    wifi = FakeWifi(connected=False)
    line = WifiLifeline(wifi=wifi, ssid="Trailmix", clock=lambda: now[0],
                        retry_interval_s=20.0, max_interval_s=160.0, grace_s=0.0)
    gaps = []
    last = now[0]
    for _ in range(6):
        before = len(wifi.connects)
        while len(wifi.connects) == before:
            now[0] += 1
            line.poll()
        gaps.append(now[0] - last)
        last = now[0]
    assert gaps[0] < gaps[1] < gaps[2], f"intervals must widen, got {gaps}"
    assert max(gaps) <= 161, f"must cap at max_interval_s, got {gaps}"


def test_reconnecting_resets_the_backoff():
    # An hour away from the hotspot must not leave the rig slow to notice the NEXT
    # time it appears.
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = WifiLifeline(wifi=wifi, ssid="Trailmix", clock=lambda: now[0],
                        retry_interval_s=20.0, grace_s=0.0)
    for _ in range(40):
        now[0] += 20
        line.poll()
    wifi.status_value = NetworkStatus(connected=True, ssid="Trailmix")
    now[0] += 400
    line.poll()
    wifi.status_value = NetworkStatus(connected=False, ssid=None)
    wifi.connects.clear()
    now[0] += 1
    line.poll()          # goes down again; grace is 0 here
    now[0] += 20
    line.poll()
    assert wifi.connects, "backoff must reset after a successful connection"



def test_a_restored_connection_is_noticed_without_waiting_out_the_backoff():
    # Knocks back off because they cost radio time; a status read does not. Sharing
    # one clock meant a rig away for an hour would not notice it was back for
    # another five minutes.
    now = [0.0]
    wifi = FakeWifi(connected=False)
    line = WifiLifeline(wifi=wifi, ssid="Trailmix", clock=lambda: now[0],
                        retry_interval_s=20.0, max_interval_s=300.0, grace_s=0.0)
    for _ in range(20):
        now[0] += 20
        line.poll()
    assert line.attempts > 1
    wifi.status_value = NetworkStatus(connected=True, ssid="Trailmix")
    now[0] += 20
    line.poll()
    assert line.attempts == 0
