"""
The readiness handshake, and the staleness problem that is the whole difficulty.

A signal file from the previous boot looks exactly like one from this boot. Reading
a stale one confirms readiness for a set that is not loaded -- the precise failure
this exists to prevent, wearing success as a disguise.
"""

import json
from pathlib import Path

import pytest

from ableton.readiness import Readiness, ReadinessTracker
from ableton.ready_signal import ReadySignal


@pytest.fixture
def signal(tmp_path):
    return ReadySignal(tmp_path / "ableton-ready.json")


def write(signal, set_path="C:/LiveRig/Sets/test.als", **extra):
    payload = {"schema": 1, "set": set_path, "loaded_at": 1.0}
    payload.update(extra)
    signal.path.write_text(json.dumps(payload), encoding="utf-8")


# --- the happy path ------------------------------------------------------


def test_a_signal_for_the_expected_set_is_ready(signal):
    write(signal, "C:/LiveRig/Sets/test.als")
    assert signal.is_ready(Path("C:/LiveRig/Sets/test.als"))


def test_no_file_means_not_ready_rather_than_an_error(signal):
    # The overwhelmingly common case: the set is still loading.
    assert signal.read() is None
    assert not signal.is_ready()


# --- staleness -----------------------------------------------------------


def test_a_signal_naming_a_different_set_is_refused(signal):
    # The stale-file case. Honouring this would confirm a set that is not loaded.
    write(signal, "C:/LiveRig/Sets/emergency.als")
    assert not signal.is_ready(Path("C:/LiveRig/Sets/test.als"))


def test_clearing_removes_a_previous_run_s_signal(signal):
    write(signal)
    signal.clear()
    assert not signal.path.exists()
    assert not signal.is_ready()


def test_clearing_a_file_that_is_not_there_is_fine(signal):
    signal.clear()  # must not raise -- first boot on a fresh machine


def test_paths_are_matched_on_filename_not_string_equality(signal):
    # Live reports the path it opened, which can differ in drive-letter case or
    # separators from the one passed on the command line. A false mismatch would
    # stall boot until the timeout with a baffling message.
    write(signal, "c:\\liverig\\sets\\candidate\\TEST.ALS")
    assert signal.is_ready(Path("C:/LiveRig/Sets/Candidate/test.als"))


def test_a_signal_making_no_claim_about_its_set_is_trusted(signal):
    # Then clear() is the only defence -- which is where the rig was before any of
    # this existed, so it is not a regression.
    signal.path.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    assert signal.is_ready(Path("C:/LiveRig/Sets/test.als"))


# --- malformed input -----------------------------------------------------


def test_a_half_written_file_is_not_ready_yet(signal):
    # The rig polls at 30 Hz, so it will land mid-write eventually.
    signal.path.write_text('{"schema": 1, "set": "C:/Li', encoding="utf-8")
    assert not signal.is_ready()


def test_json_that_is_not_an_object_is_refused(signal):
    signal.path.write_text("[1, 2, 3]", encoding="utf-8")
    assert not signal.is_ready()


def test_an_empty_file_is_not_ready(signal):
    signal.path.write_text("", encoding="utf-8")
    assert not signal.is_ready()


# --- the floor -----------------------------------------------------------


def test_a_confirmed_signal_is_ignored_until_the_floor_has_passed():
    # The Remote Script's load hook is UNVERIFIED. If it fires mid-load, honouring
    # it immediately would complete boot EARLIER than the timer it replaces, which
    # is worse than the guess.
    now = [0.0]
    tracker = ReadinessTracker(settle_s=25.0, floor_s=5.0, clock=lambda: now[0])
    tracker.mark_started()
    tracker.mark_confirmed_ready()

    now[0] = 4.9
    assert tracker.state(process_running=True) is Readiness.STARTING
    now[0] = 5.0
    assert tracker.state(process_running=True) is Readiness.CONFIRMED_READY


def test_the_signal_shortens_the_wait_it_never_lengthens_it():
    # With no signal the tracker must still land on ASSUMED_READY at settle_s --
    # i.e. this whole feature can only ever make boot faster.
    now = [0.0]
    tracker = ReadinessTracker(settle_s=25.0, floor_s=5.0, clock=lambda: now[0])
    tracker.mark_started()
    now[0] = 24.9
    assert tracker.state(process_running=True) is Readiness.STARTING
    now[0] = 25.0
    assert tracker.state(process_running=True) is Readiness.ASSUMED_READY


# --- the launcher clears it ----------------------------------------------


def test_the_launcher_clears_the_signal_before_starting(tmp_path):
    from ableton.launcher import AbletonLauncher
    from ableton.process import ProcessHandle

    order = []

    class Controller:
        def start(self, exe, argument):
            order.append("start")
            return ProcessHandle(pid=1, exe=str(exe))

        def is_running(self, handle):
            return False

        def terminate_gracefully(self, handle, timeout_s):
            return True

        def kill(self, handle):
            pass

    class Present:
        def is_present(self):
            return True

    class Watched(ReadySignal):
        def clear(self):
            order.append("clear")
            super().clear()

    exe = tmp_path / "Live.exe"
    exe.write_text("")
    als = tmp_path / "set.als"
    als.write_text("")
    sig = Watched(tmp_path / "ready.json")
    sig.path.write_text('{"set": "old.als"}', encoding="utf-8")

    AbletonLauncher(
        exe=exe, processes=Controller(), audio=Present(), ready_signal=sig
    ).launch(als)

    assert order == ["clear", "start"], "a stale signal must not survive into a launch"
    assert not sig.path.exists()
