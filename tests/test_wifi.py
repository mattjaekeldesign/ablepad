"""
The offline lifeline: auto-joining a phone hotspot.

The Beelink cannot be the access point -- MEASURED, the adapter reports
"Hosted network supported: No" -- so the phone makes the network and the rig joins.
"""

from windows.wifi import NetworkStatus, WindowsWifi

INTERFACES = """
There is 1 interface on the system:

    Name                   : Wi-Fi 2
    Description            : Intel(R) Wi-Fi 6 AX101
    GUID                   : abc
    Physical address       : 00:11:22:33:44:55
    State                  : connected
    SSID                   : Matt's iPhone
    BSSID                  : aa:bb:cc:dd:ee:ff
    Radio type             : 802.11ax
    Signal                 : 92%
"""

PROFILES = """
Profiles on interface Wi-Fi 2:

User profiles
-------------
    All User Profile     : Matt's iPhone
    All User Profile     : HomeNet 5G
    All User Profile     : Some: Cafe
"""


def wifi_with(monkeypatch, outputs):
    w = WindowsWifi()
    monkeypatch.setattr(w, "_netsh", lambda args: outputs.get(tuple(args)))
    return w


def test_it_reports_the_network_it_is_on(monkeypatch):
    w = wifi_with(monkeypatch, {
        ("wlan", "show", "interfaces"): INTERFACES,
        ("wlan", "show", "profiles"): PROFILES,
    })
    status = w.status()
    assert status.connected
    assert status.ssid == "Matt's iPhone"


def test_ssid_is_not_confused_with_bssid(monkeypatch):
    # "SSID" is a substring of "BSSID". A loose match reports the access point's MAC
    # address as the network name, which looks plausible and is useless.
    w = wifi_with(monkeypatch, {
        ("wlan", "show", "interfaces"): INTERFACES,
        ("wlan", "show", "profiles"): PROFILES,
    })
    assert w.status().ssid == "Matt's iPhone"
    assert ":" not in (w.status().ssid or "").replace("'", "")


def test_profile_names_containing_colons_survive(monkeypatch):
    # netsh prints "label : value" and the value may itself contain a colon.
    w = wifi_with(monkeypatch, {("wlan", "show", "profiles"): PROFILES})
    assert "Some: Cafe" in w.known_profiles()


def test_disconnected_reports_no_ssid(monkeypatch):
    w = wifi_with(monkeypatch, {
        ("wlan", "show", "interfaces"): INTERFACES.replace("connected", "disconnected"),
        ("wlan", "show", "profiles"): PROFILES,
    })
    status = w.status()
    assert not status.connected and status.ssid is None


def test_auto_connect_refuses_a_network_with_no_stored_profile(monkeypatch):
    # The password has to be entered once by a human. Silently "succeeding" here
    # would leave a rig that never joins anything and no clue why.
    w = wifi_with(monkeypatch, {("wlan", "show", "profiles"): PROFILES})
    assert w.set_auto_connect("Never Seen This") is False


def test_auto_connect_sets_connectionmode_for_a_known_profile(monkeypatch):
    calls = []
    w = WindowsWifi()

    def fake(args):
        calls.append(args)
        return PROFILES if args[:3] == ["wlan", "show", "profiles"] else "Ok."

    monkeypatch.setattr(w, "_netsh", fake)
    assert w.set_auto_connect("Matt's iPhone") is True
    assert ["wlan", "set", "profileparameter", "name=Matt's iPhone", "connectionmode=auto"] in calls


def test_a_missing_netsh_is_not_an_exception(monkeypatch):
    # Off-Windows, or a stripped image. The rig must not die because it cannot
    # inspect Wi-Fi.
    w = wifi_with(monkeypatch, {})
    assert w.status() == NetworkStatus(connected=False, ssid=None)
    assert w.known_profiles() == ()


DENIED = """
Network shell commands need location permission to access WLAN information.
Turn on Location services on the Location page in Privacy & security settings.

Function WlanQueryInterface returns error 5:
Access is denied.
"""


def test_profiles_still_load_when_the_ssid_cannot_be_read(monkeypatch):
    # THE bug this closes: the SSID read is gated behind Location Services, and
    # returning early on that failure hid the profile list -- the half that actually
    # matters, because auto-connect is configured from it.
    w = WindowsWifi()
    monkeypatch.setattr(w, "_ssid_without_location", staticmethod(lambda: None))
    monkeypatch.setattr(w, "_netsh", lambda args: {
        ("wlan", "show", "interfaces"): DENIED,
        ("wlan", "show", "profiles"): PROFILES,
    }.get(tuple(args)))
    status = w.status()
    assert "Matt's iPhone" in status.known, "a permission gap must not hide the profiles"


def test_the_location_refusal_is_not_parsed_as_a_network(monkeypatch):
    # netsh prints that refusal on STDOUT with exit code ZERO, so a returncode check
    # calls it success and then hunts for an SSID in a help message.
    w = WindowsWifi()
    monkeypatch.setattr(w, "_ssid_without_location", staticmethod(lambda: None))
    monkeypatch.setattr(w, "_netsh", lambda args: {
        ("wlan", "show", "interfaces"): DENIED,
        ("wlan", "show", "profiles"): PROFILES,
    }.get(tuple(args)))
    assert w.status().ssid is None


def test_it_falls_back_to_a_source_that_needs_no_location(monkeypatch):
    w = WindowsWifi()
    monkeypatch.setattr(w, "_ssid_without_location", staticmethod(lambda: "Matt's iPhone"))
    monkeypatch.setattr(w, "_netsh", lambda args: {
        ("wlan", "show", "interfaces"): DENIED,
        ("wlan", "show", "profiles"): PROFILES,
    }.get(tuple(args)))
    status = w.status()
    assert status.connected and status.ssid == "Matt's iPhone"


def test_the_fallback_name_is_not_assumed_to_equal_a_profile_name(monkeypatch):
    # MEASURED: Get-NetConnectionProfile said "Verizon_Monk 2" while the stored
    # profile is "Verizon_Monk" -- Windows suffixes a profile it has seen twice.
    # Code comparing the two for equality would decide the rig is on an unknown
    # network and, in a reconnect loop, act on it.
    w = WindowsWifi()
    monkeypatch.setattr(w, "_ssid_without_location", staticmethod(lambda: "Verizon_Monk 2"))
    monkeypatch.setattr(w, "_netsh", lambda args: {
        ("wlan", "show", "interfaces"): DENIED,
        ("wlan", "show", "profiles"): "    All User Profile     : Verizon_Monk",
    }.get(tuple(args)))
    status = w.status()
    assert status.ssid == "Verizon_Monk 2"
    assert status.known == ("Verizon_Monk",)
    assert status.ssid not in status.known  # the trap, documented
