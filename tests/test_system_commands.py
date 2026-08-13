"""
System Mode's pads: restart Live, reboot, shut down.

These are the troubleshooting options one step from the Set Browser -- which is
where the rig lands when Ableton closes or something has gone wrong.
"""

from pathlib import Path

import pytest

from rig.commands import CommandDispatcher
from rig.exceptions import UnknownCommand
from rig.system_commands import Reboot, RestartAbleton, Shutdown


class FakePower:
    def __init__(self):
        self.calls = []

    def reboot(self):
        self.calls.append("reboot")

    def shutdown(self):
        self.calls.append("shutdown")


class FakeLauncher:
    def __init__(self, refuse=False):
        self.stops = 0
        self.launched = []
        self.refuse = refuse

    def stop(self):
        self.stops += 1

    def launch(self, path):
        if self.refuse:
            from ableton.launcher import LaunchRefused

            raise LaunchRefused(["audio interface not present"])
        self.launched.append(path)


# --- restart -------------------------------------------------------------


def test_restart_stops_then_launches_the_same_set():
    launcher = FakeLauncher()
    cmd = RestartAbleton(launcher=launcher, current_set=lambda: Path("/sets/test.als"))
    cmd.execute({})
    assert launcher.stops == 1
    assert launcher.launched == [Path("/sets/test.als")]


def test_restart_reads_the_set_at_press_time_not_wiring_time():
    # The loaded set changes every time someone loads one; a captured Path would
    # restart whatever happened to be playing when the rig booted.
    current = {"set": Path("/sets/first.als")}
    launcher = FakeLauncher()
    cmd = RestartAbleton(launcher=launcher, current_set=lambda: current["set"])
    current["set"] = Path("/sets/second.als")
    cmd.execute({})
    assert launcher.launched == [Path("/sets/second.als")]


def test_restart_with_nothing_loaded_does_nothing():
    launcher = FakeLauncher()
    RestartAbleton(launcher=launcher, current_set=lambda: None).execute({})
    assert launcher.stops == 0
    assert launcher.launched == []


def test_a_refused_restart_is_reported_not_raised():
    # Raising would take down a rig whose only problem is that it cannot start a set.
    launcher = FakeLauncher(refuse=True)
    RestartAbleton(launcher=launcher, current_set=lambda: Path("/s.als")).execute({})
    assert launcher.stops == 1


# --- power ---------------------------------------------------------------


def test_reboot_and_shutdown_reach_the_power_controller():
    power = FakePower()
    Reboot(power=power).execute({})
    Shutdown(power=power).execute({})
    assert power.calls == ["reboot", "shutdown"]


def test_power_commands_take_nothing_from_the_pad():
    # The context is available and deliberately unused: nothing a config can say
    # should be able to influence what shutdown does.
    power = FakePower()
    Shutdown(power=power).execute({"params": {"force": True}, "pad": 98})
    assert power.calls == ["shutdown"]


def test_shutdown_is_never_built_from_configuration():
    # The whole attack surface of "the rig can turn the machine off" is two literals.
    from windows.power import _REBOOT, _SHUTDOWN

    for argv in (_REBOOT, _SHUTDOWN):
        assert argv[0] == "shutdown"
        assert all(isinstance(a, str) for a in argv)
    assert "/r" in _REBOOT and "/s" in _SHUTDOWN


def test_windows_power_dry_run_does_not_run_anything(monkeypatch):
    from windows import power as power_module

    def boom(*a, **k):
        raise AssertionError("dry run must not execute shutdown")

    monkeypatch.setattr(power_module.subprocess, "run", boom)
    power_module.WindowsPower(dry_run=True).shutdown()


# --- dispatcher ----------------------------------------------------------


def test_the_dispatcher_can_say_what_it_does_not_own():
    # ActionRequested carries every named action the surface resolves, most owned by
    # other subscribers. Dispatching blindly would raise on the first LOAD_SET.
    d = CommandDispatcher()
    d.register(Reboot(power=FakePower()))
    assert d.knows("SYSTEM_REBOOT")
    assert not d.knows("LOAD_SET")


def test_dispatching_an_unowned_name_still_raises():
    # knows() is for filtering; a pad wired to a missing command is a bug that must
    # surface at the bench rather than silently do nothing at a gig.
    with pytest.raises(UnknownCommand):
        CommandDispatcher().dispatch("SYSTEM_REBOOT", {})


def test_every_system_config_action_has_a_command_or_an_owner():
    # The guard against the Config Lab designing a pad nobody implements -- which is
    # exactly how SWITCH_MODE, LOAD_SET and these three all began.
    import json

    ROOT = Path(__file__).resolve().parent.parent
    actions = {
        b["action"]["type"]
        for b in json.load(open(ROOT / "configs" / "system.json"))["pads"].values()
        if b.get("action", {}).get("type") not in (None, "NONE")
    }
    implemented = {"SYSTEM_REBOOT", "SYSTEM_SHUTDOWN", "ABLETON_RESTART"}
    owned_elsewhere = {"SWITCH_MODE"}
    known_gap = {"HOTSPOT_TOGGLE"}  # Phase 6: adapter has no hosted-network support
    assert actions <= implemented | owned_elsewhere | known_gap, (
        f"system.json has unimplemented actions: {actions - implemented - owned_elsewhere - known_gap}"
    )
