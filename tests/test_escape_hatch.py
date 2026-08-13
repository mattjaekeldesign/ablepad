"""
Getting the launcher back without quitting Live.

MEASURED 2026-08-13: with Ableton driving interface 1, the Launchpad's Custom layout
routes pads to interface 2 -- the rig's port. Note 64 is the top-left grid pad there,
which is NOT its Programmer Mode number; grid.py does not apply to this layout.
"""

import pytest

from rig.escape_hatch import ESCAPE_HOLD_MS, ESCAPE_NOTE, EscapeHatch
from rig.state import RigState
from rig.surface_owner import Owner, SurfaceOwner


@pytest.fixture
def hatch():
    return EscapeHatch()


def hold(hatch, ms, note=ESCAPE_NOTE):
    hatch.feed(note, True, 0.0)
    return hatch.wants_surface(ms)


def test_a_full_hold_asks_for_the_surface(hatch):
    assert hold(hatch, ESCAPE_HOLD_MS)


def test_a_brush_does_not(hatch):
    # Taking the surface away mid-song would be worse than not having the feature.
    assert not hold(hatch, 300)


def test_releasing_early_cancels_it(hatch):
    hatch.feed(ESCAPE_NOTE, True, 0.0)
    hatch.feed(ESCAPE_NOTE, False, 500.0)
    assert not hatch.wants_surface(9999.0)


def test_other_pads_are_ignored(hatch):
    # The performer is playing; only the one gesture means anything.
    assert not hold(hatch, ESCAPE_HOLD_MS, note=ESCAPE_NOTE + 1)


def test_it_fires_once_not_continuously(hatch):
    assert hold(hatch, ESCAPE_HOLD_MS)
    assert not hatch.wants_surface(ESCAPE_HOLD_MS + 1000)


def test_reset_abandons_a_hold_in_progress(hatch):
    # Ownership changed underneath it; a part-finished gesture must not survive and
    # fire later, when it would mean something completely different.
    hatch.feed(ESCAPE_NOTE, True, 0.0)
    hatch.reset()
    assert not hatch.wants_surface(ESCAPE_HOLD_MS)


def test_it_can_be_switched_off():
    off = EscapeHatch(enabled=False)
    assert not hold(off, ESCAPE_HOLD_MS)


# --- what it does to ownership -------------------------------------------


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
    # "escape gesture released after 7000 ms of 2000 - not taking the surface back".
    hatch.feed(ESCAPE_NOTE, True, 0.0)
    assert not hatch.wants_surface(1999.0)
    assert hatch.wants_surface(2000.0), "must complete on a clock tick, not on input"
