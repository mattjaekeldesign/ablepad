"""ableton/: preconditions, graceful-then-kill, readiness honesty, restart budget."""

from pathlib import Path

import pytest

from ableton.launcher import AbletonLauncher, LaunchRefused
from ableton.process import ProcessHandle
from ableton.readiness import Readiness, ReadinessTracker
from ableton.recovery import RestartBudget


class FakeProcesses:
    """ProcessController fake with scriptable liveness and graceful-close result."""

    def __init__(self, graceful_works=True):
        self.graceful_works = graceful_works
        self.running: set[int] = set()
        self.log: list[str] = []
        self._next_pid = 100

    def start(self, exe, argument):
        self._next_pid += 1
        self.running.add(self._next_pid)
        self.log.append(f"start:{Path(argument).name}")
        return ProcessHandle(pid=self._next_pid, exe=str(exe))

    def is_running(self, handle):
        return handle.pid in self.running

    def terminate_gracefully(self, handle, timeout_s):
        self.log.append("terminate")
        if self.graceful_works:
            self.running.discard(handle.pid)
            return True
        return False

    def kill(self, handle):
        self.log.append("kill")
        self.running.discard(handle.pid)

    def crash(self):
        self.running.clear()


class FakeAudio:
    def __init__(self, present=True):
        self.present = present

    def is_present(self):
        return self.present


def make_launcher(tmp_path, audio_present=True, graceful_works=True):
    exe = tmp_path / "Ableton Live.exe"
    exe.write_text("stub", encoding="utf-8")
    processes = FakeProcesses(graceful_works)
    launcher = AbletonLauncher(exe=exe, processes=processes, audio=FakeAudio(audio_present))
    return launcher, processes


def make_set(tmp_path, name="show.als"):
    live_set = tmp_path / name
    live_set.write_text("stub", encoding="utf-8")
    return live_set


# --- preconditions -------------------------------------------------------


def test_launches_when_all_preconditions_pass(tmp_path):
    launcher, processes = make_launcher(tmp_path)
    handle = launcher.launch(make_set(tmp_path))
    assert launcher.is_running()
    assert processes.log == ["start:show.als"]
    assert handle.pid in processes.running


def test_refuses_missing_interface_AND_missing_set_together(tmp_path):
    launcher, _ = make_launcher(tmp_path, audio_present=False)
    with pytest.raises(LaunchRefused) as excinfo:
        launcher.launch(tmp_path / "ghost.als")
    reasons = excinfo.value.reasons
    assert len(reasons) == 2  # both named at once, not first-failure-wins
    assert any("ghost.als" in r for r in reasons)
    assert any("interface" in r for r in reasons)


def test_refuses_missing_exe(tmp_path):
    launcher, _ = make_launcher(tmp_path)
    launcher.exe.unlink()
    with pytest.raises(LaunchRefused, match="exe not found"):
        launcher.launch(make_set(tmp_path))


def test_refuses_double_launch(tmp_path):
    launcher, _ = make_launcher(tmp_path)
    launcher.launch(make_set(tmp_path))
    with pytest.raises(LaunchRefused, match="already running"):
        launcher.launch(make_set(tmp_path))


# --- stop: graceful first, kill second ----------------------------------


def test_stop_graceful(tmp_path):
    launcher, processes = make_launcher(tmp_path)
    launcher.launch(make_set(tmp_path))
    launcher.stop()
    assert processes.log == ["start:show.als", "terminate"]
    assert not launcher.is_running()


def test_stop_kills_when_graceful_times_out(tmp_path):
    launcher, processes = make_launcher(tmp_path, graceful_works=False)
    launcher.launch(make_set(tmp_path))
    launcher.stop()
    assert processes.log == ["start:show.als", "terminate", "kill"]


def test_stop_when_never_started_is_a_noop(tmp_path):
    launcher, processes = make_launcher(tmp_path)
    launcher.stop()
    assert processes.log == []


# --- readiness: the guess is named as one -------------------------------


def test_readiness_progression():
    now = {"t": 0.0}
    tracker = ReadinessTracker(settle_s=20.0, clock=lambda: now["t"])
    assert tracker.state(process_running=False) is Readiness.NOT_STARTED
    tracker.mark_started()
    assert tracker.state(True) is Readiness.STARTING
    now["t"] = 19.9
    assert tracker.state(True) is Readiness.STARTING
    now["t"] = 20.0
    assert tracker.state(True) is Readiness.ASSUMED_READY  # a guess, and named as one
    tracker.mark_confirmed_ready()
    assert tracker.state(True) is Readiness.CONFIRMED_READY


def test_readiness_gone_when_process_dies():
    tracker = ReadinessTracker(settle_s=5.0, clock=lambda: 100.0)
    tracker.mark_started()
    assert tracker.state(process_running=False) is Readiness.GONE


# --- restart budget ------------------------------------------------------


def test_budget_allows_then_refuses():
    budget = RestartBudget(max_attempts=1, stable_s=60.0, clock=lambda: 0.0)
    assert budget.allow_restart() is True
    assert budget.allow_restart() is False  # capped — no infinite loop


def test_budget_refills_after_stable_run():
    now = {"t": 0.0}
    budget = RestartBudget(max_attempts=1, stable_s=60.0, clock=lambda: now["t"])
    assert budget.allow_restart()
    now["t"] = 59.0
    budget.note_stable_if_due()
    assert budget.allow_restart() is False  # not stable long enough yet
    now["t"] = 130.0  # 59->130: the restart at t=0 has now survived 130 s... but the
    # SECOND allow_restart at 59 already failed without consuming; last restart is t=0
    budget.note_stable_if_due()
    assert budget.allow_restart() is True  # refilled after the stable window


def test_budget_does_not_refill_while_crashing_fast():
    now = {"t": 0.0}
    budget = RestartBudget(max_attempts=2, stable_s=60.0, clock=lambda: now["t"])
    assert budget.allow_restart()
    now["t"] = 10.0  # crashed again within the stable window
    budget.note_stable_if_due()
    assert budget.allow_restart()
    now["t"] = 20.0
    budget.note_stable_if_due()
    assert budget.allow_restart() is False
