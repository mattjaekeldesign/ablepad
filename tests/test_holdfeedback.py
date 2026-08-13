"""
Hold progress: the pad has to say something while you are holding it.

The bug this closes was observed on hardware -- a 1000 ms hold released at 453 ms
and 391 ms, reported as "I hit it but nothing happened". The rig was correct and
silent, which on a screenless instrument is the same as broken.
"""

from dataclasses import dataclass

import pytest

from launchpad import colors
from launchpad.holdfeedback import HOLD_RAMP, HOLD_THRESHOLDS, hold_leds, sanity_check, stage


@dataclass
class FakeHold:
    hold_ms: int
    started_ms: float = 0.0

    def elapsed(self, now_ms: float) -> float:
        return now_ms - self.started_ms


def palette_at(hold_ms, now_ms):
    return hold_leds({11: FakeHold(hold_ms)}, now_ms)[11]["palette"]


def test_every_ramp_colour_has_been_seen_on_hardware():
    # Feedback whose entire job is to be visible must not depend on a guessed index.
    assert all(colors.is_verified(c) for c in HOLD_RAMP)


def test_every_ramp_stage_is_distinct():
    # A repeat would be a stage that looks identical to the one before it -- progress
    # that stops moving while the hold is still running.
    assert len(set(HOLD_RAMP)) == len(HOLD_RAMP)
    assert HOLD_RAMP == (colors.RED, colors.YELLOW, colors.GREEN_BRIGHT)


def test_the_ramp_avoids_the_set_browser_idle_colour():
    # colors.GREEN is what a set pad shows at rest. A ramp stage equal to it would
    # look like the hold had been abandoned, mid-hold.
    assert colors.GREEN not in HOLD_RAMP


@pytest.mark.parametrize(
    "now_ms,expected_stage",
    [(0, 0), (1, 0), (999, 0), (1499, 0), (1500, 1), (2699, 1), (2700, 2), (2999, 2)],
)
def test_a_3000ms_hold_reaches_its_final_colour_only_at_the_end(now_ms, expected_stage):
    assert palette_at(3000, now_ms) == HOLD_RAMP[expected_stage]


def test_the_final_stage_is_short_enough_to_mean_now_not_done():
    # THE regression guard, from hardware: with equal thirds a 2000 ms LOAD_SET went
    # bright at 1333 ms and was released at 1484 ms -- read as "it fired". A final
    # stage that occupies a third of the hold invites exactly that.
    assert HOLD_THRESHOLDS[-1] >= 0.85

    hold_ms = 2000
    first_final_ms = next(
        ms for ms in range(hold_ms + 1) if palette_at(hold_ms, ms) == HOLD_RAMP[-1]
    )
    assert hold_ms - first_final_ms <= 300, "bright must mean NOW, not DONE"


def test_the_first_stage_is_long_because_it_answers_is_this_responding():
    assert palette_at(2000, 5) == HOLD_RAMP[0]
    assert palette_at(2000, 900) == HOLD_RAMP[0]


def test_the_two_tables_cannot_drift_apart():
    sanity_check()
    assert len(HOLD_THRESHOLDS) == len(HOLD_RAMP)


def test_progress_past_completion_does_not_fall_off_the_ramp():
    # Reachable for one tick between a hold completing and the surface firing it.
    # An IndexError here would blank the whole surface at the moment of success.
    assert palette_at(1000, 5000) == HOLD_RAMP[-1]
    assert stage(99.0) == len(HOLD_RAMP) - 1


def test_negative_progress_is_clamped():
    # A clock that steps backwards must not crash the render.
    assert stage(-1.0) == 0
    assert palette_at(1000, -500) == HOLD_RAMP[0]


def test_nothing_held_paints_nothing():
    assert hold_leds({}, 1234) == {}


def test_a_zero_length_hold_is_skipped_rather_than_dividing_by_zero():
    assert hold_leds({11: FakeHold(0)}, 100) == {}


def test_each_held_pad_is_reported_independently():
    leds = hold_leds({11: FakeHold(1000), 81: FakeHold(6000)}, 900)
    assert leds[11]["palette"] == HOLD_RAMP[2]  # nearly there
    assert leds[81]["palette"] == HOLD_RAMP[0]  # barely started
