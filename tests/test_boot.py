"""
rig/boot.py — what has to be true before the rig leaves the splash screen.

The definition being implemented: "Ableton up and running smoothly, connected to EVO
sound, with no complications — otherwise the error screen." These tests are mostly
about the failure half of that sentence, because a rig that boots when it should not
is worse than one that refuses to.
"""

from rig.boot import BootGate, BootOutcome, Check, CheckResult, Confidence


def check(name, ok, detail="", required=True, confidence=Confidence.CERTAIN):
    return Check(name=name, confidence=confidence, probe=lambda: CheckResult(ok, detail), required=required)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


# --- the happy path ------------------------------------------------------


def test_all_checks_passing_completes_boot():
    gate = BootGate([check("launchpad", True), check("ableton", True)], timeout_s=30, clock=Clock())
    assert gate.evaluate() is BootOutcome.COMPLETE
    assert gate.failures == []


def test_no_checks_at_all_completes_immediately():
    assert BootGate([], timeout_s=30, clock=Clock()).evaluate() is BootOutcome.COMPLETE


# --- waiting, then failing ----------------------------------------------


def test_a_failing_check_holds_boot_without_failing_it():
    clock = Clock()
    gate = BootGate([check("ableton", False, "process not running")], timeout_s=30, clock=clock)
    gate.start()
    clock.t = 10.0
    assert gate.evaluate() is BootOutcome.WAITING


def test_the_deadline_turns_waiting_into_failure():
    clock = Clock()
    gate = BootGate([check("ableton", False, "process not running")], timeout_s=30, clock=clock)
    gate.start()
    clock.t = 30.0
    assert gate.evaluate() is BootOutcome.FAILED


def test_failure_names_the_check_not_just_boot():
    # On a screenless rig, "EVO 8 missing" vs "Ableton not running" is the difference
    # between checking a cable and checking a set.
    clock = Clock()
    gate = BootGate(
        [check("evo8", False, "no device with VID_2708"), check("ableton", True)],
        timeout_s=1, clock=clock,
    )
    gate.start()
    clock.t = 1.0
    assert gate.evaluate() is BootOutcome.FAILED
    assert gate.summary() == "evo8: no device with VID_2708"


def test_every_failing_check_is_reported_not_just_the_first():
    clock = Clock()
    gate = BootGate(
        [check("evo8", False, "absent"), check("ableton", False, "not running")],
        timeout_s=1, clock=clock,
    )
    gate.start()
    clock.t = 1.0
    gate.evaluate()
    assert gate.failures == ["evo8: absent", "ableton: not running"]


# --- robustness ----------------------------------------------------------


def test_a_probe_that_raises_counts_as_a_failure_not_a_crash():
    # A boot check that throws would take down the boot sequence it exists to protect.
    def explode():
        raise OSError("wmi is having a day")

    gate = BootGate(
        [Check("evo8", Confidence.CERTAIN, explode)], timeout_s=1, clock=Clock()
    )
    assert gate.evaluate() is BootOutcome.WAITING
    assert "probe raised" in gate.summary()


def test_optional_checks_do_not_block_boot():
    gate = BootGate(
        [check("launchpad", True), check("sets_folder", False, "empty", required=False)],
        timeout_s=30, clock=Clock(),
    )
    assert gate.evaluate() is BootOutcome.COMPLETE


def test_recovery_before_the_deadline_still_completes():
    # A device that appears late must not be punished for being slow.
    clock = Clock()
    state = {"up": False}
    gate = BootGate(
        [Check("ableton", Confidence.CERTAIN, lambda: CheckResult(state["up"], "..."))],
        timeout_s=30, clock=clock,
    )
    gate.start()
    clock.t = 10.0
    assert gate.evaluate() is BootOutcome.WAITING
    state["up"] = True
    clock.t = 20.0
    assert gate.evaluate() is BootOutcome.COMPLETE


# --- the honesty the module exists for -----------------------------------


def test_confidence_is_carried_not_averaged_away():
    # "settle time elapsed" is a timing guess and "process exists" is not. Collapsing
    # them into one boolean is how a rig starts claiming things it cannot know.
    checks = [
        check("evo8", True, confidence=Confidence.CERTAIN),
        check("ableton_asio", True, confidence=Confidence.STRONG),
        check("settled", True, confidence=Confidence.GUESS),
    ]
    gate = BootGate(checks, timeout_s=30, clock=Clock())
    assert gate.evaluate() is BootOutcome.COMPLETE
    assert {c.confidence for c in gate.checks} == {
        Confidence.CERTAIN, Confidence.STRONG, Confidence.GUESS
    }


def test_passing_boot_does_not_mean_audio_is_reaching_the_mixer():
    # An ESD-wedged EVO enumerates, loads its driver, and outputs silence. Every
    # check here would pass. This test exists so nobody later "improves" the gate
    # into claiming sound is happening.
    gate = BootGate(
        [check("evo8_present", True, "VID_2708 enumerated"),
         check("ableton_asio", True, "audientusbaudioasio loaded", confidence=Confidence.STRONG)],
        timeout_s=30, clock=Clock(),
    )
    assert gate.evaluate() is BootOutcome.COMPLETE
    assert not any("audio" in c.name and "flow" in c.name for c in gate.checks), (
        "there is no software check for audio actually reaching the mixer"
    )
