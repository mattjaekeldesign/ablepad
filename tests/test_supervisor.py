"""AbletonSupervisor: crash -> budgeted restart -> give up loudly. All via fakes."""

from pathlib import Path

from ableton.launcher import AbletonLauncher
from ableton.recovery import RestartBudget
from ableton.supervisor import AbletonSupervisor
from rig.events import AbletonClosed, AbletonCrashed, AbletonGaveUp, AbletonRestarted, EventBus
from tests.test_ableton import FakeAudio, FakeProcesses, make_set


def build(tmp_path, max_attempts=1, audio_present=True, graceful_works=True):
    exe = tmp_path / "Ableton Live.exe"
    exe.write_text("stub", encoding="utf-8")
    processes = FakeProcesses(graceful_works)
    audio = FakeAudio(audio_present)
    launcher = AbletonLauncher(exe=exe, processes=processes, audio=audio)
    now = {"t": 0.0}
    budget = RestartBudget(max_attempts=max_attempts, stable_s=60.0, clock=lambda: now["t"])
    bus = EventBus()
    events = []
    for kind in (AbletonClosed, AbletonCrashed, AbletonRestarted, AbletonGaveUp):
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


# --- force_close(): the escape chord's hard-close -------------------------


def test_force_close_stops_gracefully_and_publishes_closed(tmp_path):
    supervisor, launcher, processes, _a, events, _now = build(tmp_path)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)

    supervisor.force_close("escape chord")
    assert not launcher.is_running()
    assert processes.log[-1] == "terminate"  # graceful path, no kill needed
    assert [type(e).__name__ for e in events] == ["AbletonClosed"]


def test_force_close_kills_when_graceful_close_will_not_go(tmp_path):
    # THE reason this exists: a stuck "Save changes to <set>?" dialog nothing
    # headless can answer. Graceful close times out, so it gets killed.
    supervisor, launcher, processes, _a, events, _now = build(tmp_path, graceful_works=False)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)

    supervisor.force_close("escape chord")
    assert not launcher.is_running()
    assert processes.log[-2:] == ["terminate", "kill"]
    assert [type(e).__name__ for e in events] == ["AbletonClosed"]


def test_force_close_does_not_look_like_a_crash_afterwards(tmp_path):
    # THE regression this guards against: force_close() must disarm watch() BEFORE
    # stopping the process. Stop first and the next poll() sees "not running, no
    # exit code" -- exactly what an adopted crash looks like -- reads the crash
    # journal a kill always leaves behind, calls it a crash, and spends the restart
    # budget relaunching a set nobody asked for again.
    supervisor, launcher, _p, _a, events, _now = build(tmp_path, max_attempts=1)
    live_set = make_set(tmp_path)
    launcher.launch(live_set)
    supervisor.watch(live_set)

    supervisor.force_close("escape chord")
    events.clear()
    for _ in range(5):
        supervisor.poll()
    assert events == []  # not watching anything anymore — silent, no auto-relaunch


def test_force_close_with_nothing_watched_is_a_noop(tmp_path):
    supervisor, launcher, _p, _a, events, _now = build(tmp_path)
    supervisor.force_close("escape chord")  # nothing running, nothing watched
    assert events == []
