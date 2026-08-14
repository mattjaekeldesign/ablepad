"""
The 81+97 chord: gesture detection only. What main.py does when it fires
(AbletonSupervisor.force_close) is covered in tests/test_supervisor.py.

MEASURED 2026-08-13: with Ableton driving interface 1, the Launchpad's Custom layout
routes pads to interface 2 -- the rig's port. grid.py does not apply to this layout.
"""

import pytest

from rig.escape_hatch import ESCAPE_HOLD_MS, ESCAPE_NOTES, EscapeHatch
from rig.state import RigState
from rig.surface_owner import Owner, SurfaceOwner


@pytest.fixture
def hatch():
    return EscapeHatch()


def hold(hatch, ms, notes=None):
    """Press every control in the chord, then look ms later."""
    for note in (notes if notes is not None else ESCAPE_NOTES):
        hatch.feed(note, True, 0.0)
    return hatch.completed(ms)


def test_a_full_hold_completes(hatch):
    assert hold(hatch, ESCAPE_HOLD_MS)


def test_a_brush_does_not(hatch):
    # Force-closing Ableton mid-song would be worse than not having the feature.
    assert not hold(hatch, 300)


def test_releasing_early_cancels_it(hatch):
    for note in ESCAPE_NOTES:
        hatch.feed(note, True, 0.0)
    hatch.feed(sorted(ESCAPE_NOTES)[0], False, 500.0)
    assert not hatch.completed(9999.0)


def test_other_pads_are_ignored(hatch):
    # The performer is playing; only the chord means anything.
    assert not hold(hatch, ESCAPE_HOLD_MS, notes={max(ESCAPE_NOTES) + 1})


def test_one_control_alone_is_not_enough():
    # THE point of the chord. The Custom layout is a view Matt uses in Ableton --
    # "clicking custom shouldnt be enough to load the set bank" -- so a single
    # control, however long it is held, must do nothing.
    for note in ESCAPE_NOTES:
        h = EscapeHatch()
        h.feed(note, True, 0.0)
        assert not h.completed(60_000.0), f"{note} alone must never fire"


def test_the_clock_starts_when_the_LAST_control_joins():
    # Otherwise resting on one control and later touching the other fires instantly,
    # which is the opposite of a deliberate gesture.
    first, second = sorted(ESCAPE_NOTES)
    h = EscapeHatch()
    h.feed(first, True, 0.0)
    h.feed(second, True, 10_000.0)
    assert not h.completed(10_500.0)
    assert h.completed(10_000.0 + ESCAPE_HOLD_MS)


def test_breaking_the_chord_abandons_the_attempt():
    first, second = sorted(ESCAPE_NOTES)
    h = EscapeHatch()
    h.feed(first, True, 0.0)
    h.feed(second, True, 0.0)
    h.feed(second, False, 500.0)
    h.feed(second, True, 600.0)
    # Re-pressing restarts the clock; it must not inherit the first 500 ms.
    assert not h.completed(600.0 + ESCAPE_HOLD_MS - 1)


def test_it_fires_once_not_continuously(hatch):
    assert hold(hatch, ESCAPE_HOLD_MS)
    assert not hatch.completed(ESCAPE_HOLD_MS + 1000)


def test_reset_abandons_a_hold_in_progress(hatch):
    # Ownership changed underneath it; a part-finished gesture must not survive and
    # fire later, when it would mean something completely different.
    for note in ESCAPE_NOTES:
        hatch.feed(note, True, 0.0)
    hatch.reset()
    assert not hatch.completed(ESCAPE_HOLD_MS)


def test_it_can_be_switched_off():
    off = EscapeHatch(enabled=False)
    assert not hold(off, ESCAPE_HOLD_MS)


# --- SurfaceOwner.take_back(): unrelated to the chord now, still its own primitive --


def test_taking_back_overrides_handover_while_ableton_plays_on():
    owner = SurfaceOwner(enabled=True)
    assert owner.owner(RigState.PERFORMANCE, ableton_ready=True) == Owner.ABLETON
    owner.take_back()
    assert owner.owner(RigState.PERFORMANCE, ableton_ready=True) == Owner.RIG


def test_loading_a_set_restores_normal_handover():
    # Otherwise the rig would keep the surface through the next performance.
    owner = SurfaceOwner(enabled=True)
    owner.take_back()
    owner.release_override()
    assert owner.owner(RigState.PERFORMANCE, ableton_ready=True) == Owner.ABLETON


def test_a_hold_completes_without_any_further_events(hatch):
    # THE regression. A hold sends nothing between press and release, so a design
    # that only evaluates on input never fires: measured on the rig as
    # "escape chord broken after 7000 ms of 2000 - not force-closing Ableton".
    for note in ESCAPE_NOTES:
        hatch.feed(note, True, 0.0)
    assert not hatch.completed(ESCAPE_HOLD_MS - 1)
    assert hatch.completed(ESCAPE_HOLD_MS), "must complete on a tick, not on input"
