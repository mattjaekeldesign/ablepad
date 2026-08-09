"""AbletonSupervisor: crash -> budgeted restart -> give up loudly. All via fakes."""

from pathlib import Path

from ableton.launcher import AbletonLauncher
from ableton.recovery import RestartBudget
from ableton.supervisor import AbletonSupervisor
from rig.events import AbletonCrashed, AbletonGaveUp, AbletonRestarted, EventBus
from tests.test_ableton import FakeAudio, FakeProcesses, make_set


def build(tmp_path, max_attempts=1, audio_present=True):
    exe = tmp_path / "Ableton Live.exe"
    exe.write_text("stub", encoding="utf-8")
    processes = FakeProcesses()
    audio = FakeAudio(audio_present)
    launcher = AbletonLauncher(exe=exe, processes=processes, audio=audio)
    now = {"t": 0.0}
    budget = RestartBudget(max_attempts=max_attempts, stable_s=60.0, clock=lambda: now["t"])
    bus = EventBus()
    events = []
    for kind in (AbletonCrashed, AbletonRestarted, AbletonGaveUp):
        bus.subscribe(kind, events.append)
    supervisor = AbletonSupervisor(launcher=launcher, budget=budget, bus=bus)
    return supervisor, launcher, processes, audio, events, now


def test_healthy_run_publishes_nothing(tmp_path):
    supervisor, launcher, _p, _a, events, _now = build(tmp_path)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)
    for _ in range(10):
        supervisor.poll()
    assert events == []


def test_crash_restarts_once_then_gives_up(tmp_path):
    supervisor, launcher, processes, _a, events, _now = build(tmp_path, max_attempts=1)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)

    processes.crash()
    supervisor.poll()
    assert [type(e).__name__ for e in events] == ["AbletonCrashed", "AbletonRestarted"]
    assert launcher.is_running()  # relaunched

    processes.crash()
    supervisor.poll()
    assert [type(e).__name__ for e in events][-2:] == ["AbletonCrashed", "AbletonGaveUp"]

    events.clear()
    supervisor.poll()  # gave up: stays silent, does not thrash
    assert events == []


def test_stable_run_refills_budget(tmp_path):
    supervisor, launcher, processes, _a, events, now = build(tmp_path, max_attempts=1)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)

    processes.crash()
    supervisor.poll()  # restart #1 at t=0
    now["t"] = 120.0
    supervisor.poll()  # stable long enough — budget refills

    processes.crash()
    supervisor.poll()
    assert [type(e).__name__ for e in events][-1] == "AbletonRestarted"  # second life


def test_restart_refused_gives_up_immediately(tmp_path):
    supervisor, launcher, processes, audio, events, _now = build(tmp_path, max_attempts=3)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)

    audio.present = False  # the world changed: interface unplugged
    processes.crash()
    supervisor.poll()
    assert [type(e).__name__ for e in events] == ["AbletonCrashed", "AbletonGaveUp"]


def test_reset_rearms_after_give_up(tmp_path):
    supervisor, launcher, processes, _a, events, _now = build(tmp_path, max_attempts=0)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)
    processes.crash()
    supervisor.poll()
    assert [type(e).__name__ for e in events][-1] == "AbletonGaveUp"

    supervisor.reset()
    supervisor.poll()  # not watching anything — silent
    assert len(events) == 2
