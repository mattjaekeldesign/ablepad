"""
Clearing Live's crash journal, without throwing away anyone's work.

Layout mirrors what was measured on the rig (Live 12.4.3). The distinction these
tests exist to protect: the DIALOG TRIGGER is at the Preferences root, and
Preferences/Crash/ is only an archive of past recoveries.

    <appdata>/Live 12.4.3/Preferences/CrashRecoveryInfo.cfg      <-- trigger
                                     /Undo/{0.band, bands.cfg}   <-- payload
                                     /Crash/<stamp>_*            <-- archive
"""

import logging

import pytest

from ableton.crash_recovery import CrashRecovery


def make_trigger(appdata, version="Live 12.4.3", contents="unsaved work"):
    """The state that actually makes Live offer to recover."""
    prefs = appdata / version / "Preferences"
    undo = prefs / "Undo"
    undo.mkdir(parents=True, exist_ok=True)
    (prefs / "CrashRecoveryInfo.cfg").write_text(contents)
    (undo / "0.band").write_text("band")
    (undo / "bands.cfg").write_text("bands")
    return prefs


def make_journal(appdata, stamp, version="Live 12.4.3", contents="unsaved work"):
    """An archived recovery under Crash/ -- history, not the trigger."""
    crash = appdata / version / "Preferences" / "Crash"
    base = crash / f"{stamp}_BaseFiles"
    undo = crash / f"{stamp}_Undo"
    base.mkdir(parents=True)
    undo.mkdir(parents=True)
    (base / "test.als").write_text(contents)
    (undo / "bands.cfg").write_text("bands")
    (crash / f"{stamp}_CrashRecoveryInfo.cfg").write_text("recovery")
    return base, undo


@pytest.fixture
def recovery(tmp_path):
    return CrashRecovery(
        ableton_appdata=tmp_path / "appdata",
        quarantine=tmp_path / "quarantine",
    )


def test_the_root_recovery_state_is_swept(recovery, tmp_path):
    # THE regression guard. Sweeping only Crash/ passes every other test in this
    # file and leaves the dialog exactly as it was -- observed on the rig.
    prefs = make_trigger(tmp_path / "appdata")
    assert recovery.clear() == 2  # CrashRecoveryInfo.cfg + Undo/
    assert not (prefs / "CrashRecoveryInfo.cfg").exists()
    assert not (prefs / "Undo").exists()
    assert recovery.pending() == []


def test_the_archive_is_swept_too_so_it_cannot_grow_forever(recovery, tmp_path):
    make_journal(tmp_path / "appdata", "2026_08_12__23_17_39")
    assert recovery.clear() == 3  # _BaseFiles, _Undo, _CrashRecoveryInfo.cfg
    assert recovery.pending() == []


def test_the_crash_folder_itself_survives(recovery, tmp_path):
    # Live expects to find it. Only the contents are ours to move.
    make_journal(tmp_path / "appdata", "2026_08_12__23_17_39")
    recovery.clear()
    assert (tmp_path / "appdata" / "Live 12.4.3" / "Preferences" / "Crash").is_dir()


def test_the_work_survives_the_move(recovery, tmp_path):
    # The whole reason this moves instead of deleting. The trigger IS someone's
    # unsaved session; deleting it to skip a dialog would throw the work away.
    make_trigger(tmp_path / "appdata", contents="two hours of work")
    recovery.clear()
    rescued = list((tmp_path / "quarantine").rglob("CrashRecoveryInfo.cfg"))
    assert len(rescued) == 1
    assert rescued[0].read_text() == "two hours of work"


def test_every_live_version_is_swept(recovery, tmp_path):
    # The version is in the path and changes on update. A pinned path would sweep
    # nothing and report success, and the dialog would return unexplained.
    make_trigger(tmp_path / "appdata", version="Live 12.4.3")
    make_trigger(tmp_path / "appdata", version="Live 12.5.0")
    assert recovery.clear() == 4


def test_the_recovery_cfg_is_swept_not_just_the_folders(recovery, tmp_path):
    # is_dir() looks right and is not: it would keep every CrashRecoveryInfo.cfg,
    # which is the one entry named after the thing being cleared.
    make_journal(tmp_path / "appdata", "2026_08_13__09_12_41")
    recovery.clear()
    assert recovery.pending() == []
    assert list((tmp_path / "quarantine").glob("*CrashRecoveryInfo.cfg"))


def test_a_clean_machine_is_a_no_op(recovery):
    assert recovery.clear() == 0
    assert recovery.pending() == []


def test_a_missing_appdata_is_not_an_error(tmp_path):
    # A fresh install, or a wrong path in rig.yaml. Neither may stop a launch.
    r = CrashRecovery(ableton_appdata=tmp_path / "nope", quarantine=tmp_path / "q")
    assert r.preferences_dirs() == []
    assert r.clear() == 0


def test_successive_sweeps_do_not_overwrite_each_other(recovery, tmp_path):
    # The trigger has a FIXED name, so every sweep collides. Overwriting would mean
    # each crash destroyed the previous crash's rescued work.
    make_trigger(tmp_path / "appdata", contents="first")
    recovery.clear()
    make_trigger(tmp_path / "appdata", contents="second")
    recovery.clear()
    # The second lands as CrashRecoveryInfo.cfg~1 -- the collision guard renames
    # rather than overwrites, so recovering it by hand means dropping the suffix.
    saved = sorted(p.read_text() for p in (tmp_path / "quarantine").rglob("CrashRecoveryInfo.cfg*"))
    assert saved == ["first", "second"]


def test_quarantine_is_capped_so_a_crash_loop_cannot_fill_the_disk(tmp_path):
    r = CrashRecovery(
        ableton_appdata=tmp_path / "appdata", quarantine=tmp_path / "quarantine", keep=4
    )
    for _ in range(6):
        make_trigger(tmp_path / "appdata")
        r.clear()
    assert len(list((tmp_path / "quarantine").iterdir())) == 4


def test_an_unmovable_journal_is_logged_and_does_not_raise(recovery, tmp_path, monkeypatch, caplog):
    # A dialog is a nuisance; no Ableton is the show.
    make_trigger(tmp_path / "appdata")

    def boom(*_args, **_kwargs):
        raise OSError("in use by another process")

    monkeypatch.setattr("ableton.crash_recovery.shutil.move", boom)
    with caplog.at_level(logging.WARNING):
        assert recovery.clear() == 0
    assert "could not quarantine" in caplog.text


def test_the_launcher_sweeps_before_starting(tmp_path):
    # Ordering is the point: sweeping after start would move the journal of the
    # process that just opened it.
    from ableton.launcher import AbletonLauncher
    from ableton.process import ProcessHandle

    order = []

    class Recorder:
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

    class Sweep(CrashRecovery):
        def clear(self):
            order.append("clear")
            return 0

    exe = tmp_path / "Live.exe"
    exe.write_text("")
    als = tmp_path / "set.als"
    als.write_text("")

    AbletonLauncher(
        exe=exe,
        processes=Recorder(),
        audio=Present(),
        recovery=Sweep(ableton_appdata=tmp_path / "a", quarantine=tmp_path / "q"),
    ).launch(als)

    assert order == ["clear", "start"]


def test_a_refused_launch_does_not_sweep(tmp_path):
    # Nothing is going to start, so the journals on disk may still be the newest
    # thing anyone has. Leave them where Live can offer them.
    from ableton.launcher import AbletonLauncher, LaunchRefused
    from ableton.process import ProcessHandle

    swept = []

    class Never:
        def start(self, exe, argument):
            raise AssertionError("must not start")

        def is_running(self, handle):
            return False

        def terminate_gracefully(self, handle, timeout_s):
            return True

        def kill(self, handle):
            pass

    class Absent:
        def is_present(self):
            return False

    class Sweep(CrashRecovery):
        def clear(self):
            swept.append(1)
            return 0

    exe = tmp_path / "Live.exe"
    exe.write_text("")
    als = tmp_path / "set.als"
    als.write_text("")

    with pytest.raises(LaunchRefused):
        AbletonLauncher(
            exe=exe,
            processes=Never(),
            audio=Absent(),
            recovery=Sweep(ableton_appdata=tmp_path / "a", quarantine=tmp_path / "q"),
        ).launch(als)
    assert swept == []


# --- adoption ------------------------------------------------------------


def test_adopting_lets_stop_and_is_running_work_on_a_process_we_did_not_start(tmp_path):
    # The guard against a second Ableton. Two instances fight over one ASIO device
    # and the loser looks like broken hardware.
    from ableton.launcher import AbletonLauncher

    stopped = []

    class Controller:
        def start(self, exe, argument):
            raise AssertionError("must not start a second instance")

        def is_running(self, handle):
            return True

        def terminate_gracefully(self, handle, timeout_s):
            stopped.append(handle.pid)
            return True

        def kill(self, handle):
            pass

    class Present:
        def is_present(self):
            return True

    exe = tmp_path / "Live.exe"
    exe.write_text("")
    launcher = AbletonLauncher(exe=exe, processes=Controller(), audio=Present())

    assert not launcher.is_running()
    launcher.adopt(4321)
    assert launcher.is_running()
    launcher.stop()
    assert stopped == [4321]


def test_launching_while_one_is_adopted_is_refused(tmp_path):
    from ableton.launcher import AbletonLauncher, LaunchRefused

    class Controller:
        def start(self, exe, argument):
            raise AssertionError("must not start a second instance")

        def is_running(self, handle):
            return True

        def terminate_gracefully(self, handle, timeout_s):
            return True

        def kill(self, handle):
            pass

    class Present:
        def is_present(self):
            return True

    exe = tmp_path / "Live.exe"
    exe.write_text("")
    als = tmp_path / "set.als"
    als.write_text("")
    launcher = AbletonLauncher(exe=exe, processes=Controller(), audio=Present())
    launcher.adopt(4321)
    with pytest.raises(LaunchRefused):
        launcher.launch(als)
