"""rig/boot_checks.py — the five preconditions, driven by fakes."""

from rig.boot import BootGate, BootOutcome, Confidence
from rig.boot_checks import build_checks


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def checks(**overrides):
    state = dict(
        launchpad_connected=True, evo_present=True, ableton_running=True,
        ableton_bound_to_evo=True, ableton_settled=True,
    )
    state.update(overrides)
    return build_checks(**{k: (lambda v=v: v) for k, v in state.items()})


def gate(clock=None, **overrides):
    return BootGate(checks(**overrides), timeout_s=60, clock=clock or Clock())


def test_all_five_passing_completes_boot():
    assert gate().evaluate() is BootOutcome.COMPLETE


def test_each_precondition_can_block_boot_on_its_own():
    for missing in (
        "launchpad_connected", "evo_present", "ableton_running",
        "ableton_bound_to_evo", "ableton_settled",
    ):
        g = gate(**{missing: False})
        assert g.evaluate() is BootOutcome.WAITING, f"{missing} did not block boot"


def test_the_message_says_which_thing_is_wrong():
    # On a screenless rig this string is the entire diagnosis.
    g = gate(evo_present=False)
    g.evaluate()
    assert g.summary().startswith("evo8:")
    assert "check the cable" in g.summary()

    g = gate(ableton_bound_to_evo=False)
    g.evaluate()
    assert "wrong audio device" in g.summary()


def test_confidence_levels_are_not_all_the_same():
    levels = {c.name: c.confidence for c in checks()}
    assert levels["evo8"] is Confidence.CERTAIN
    assert levels["ableton_audio"] is Confidence.STRONG
    assert levels["settled"] is Confidence.GUESS, (
        "the settle timer is a guess and must keep saying so"
    )


def test_a_late_arriving_ableton_still_boots():
    clock = Clock()
    up = {"v": False}
    g = BootGate(
        build_checks(
            launchpad_connected=lambda: True, evo_present=lambda: True,
            ableton_running=lambda: up["v"], ableton_bound_to_evo=lambda: up["v"],
            ableton_settled=lambda: up["v"],
        ),
        timeout_s=60, clock=clock,
    )
    g.start()
    clock.t = 5
    assert g.evaluate() is BootOutcome.WAITING
    up["v"] = True
    clock.t = 20
    assert g.evaluate() is BootOutcome.COMPLETE


def test_nothing_at_all_fails_at_the_deadline_naming_everything():
    clock = Clock()
    g = BootGate(
        checks(launchpad_connected=False, evo_present=False, ableton_running=False,
               ableton_bound_to_evo=False, ableton_settled=False),
        timeout_s=60, clock=clock,
    )
    g.start()
    clock.t = 60
    assert g.evaluate() is BootOutcome.FAILED
    assert len(g.failures) == 5
