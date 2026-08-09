"""AnimationPlayer: intro/during contract, skip, cancel, failsafe, single on_finished."""

from launchpad.animations import ANIM_TICK_MS
from launchpad.player import INTRO_FAILSAFE_MS, AnimationPlayer, PlayMode

RAIN_2S = {
    "id": "test-rain",
    "engine": "generator",
    "loop": False,
    "duration_ms": 2000,
    "generator": {"type": "RAIN", "params": {"seed": 7}},
}
LOOP_FOREVER = {
    "id": "test-loop",
    "engine": "generator",
    "loop": True,
    "generator": {"type": "PULSE_WAVE", "params": {"seed": 3}},
}


def test_plays_then_finishes_and_reports_once():
    player = AnimationPlayer()
    finished = []
    player.play(RAIN_2S, PlayMode.INTRO, now_ms=1000.0, on_finished=lambda: finished.append(1))
    assert player.frame(1000.0)  # t=0: painting
    assert player.frame(2500.0)  # t=1500: still painting
    assert player.frame(3000.0 + ANIM_TICK_MS) is None  # past the end
    assert not player.is_playing
    assert finished == [1]
    assert player.frame(4000.0) is None  # idle stays idle, callback not re-fired
    assert finished == [1]


def test_during_loops_forever_until_cancel():
    player = AnimationPlayer()
    player.play(LOOP_FOREVER, PlayMode.DURING, now_ms=0.0)
    assert player.frame(100_000.0) is not None  # far future: still looping
    player.cancel()
    assert player.frame(100_100.0) is None
    assert not player.is_playing


def test_any_press_skips_an_intro():
    player = AnimationPlayer()
    finished = []
    player.play(RAIN_2S, PlayMode.INTRO, now_ms=0.0, on_finished=lambda: finished.append(1))
    assert player.skip() is True
    assert player.frame(100.0) is None
    assert finished == [1]


def test_presses_do_not_skip_a_during_loop():
    player = AnimationPlayer()
    player.play(LOOP_FOREVER, PlayMode.DURING, now_ms=0.0)
    assert player.skip() is False
    assert player.frame(50.0) is not None


def test_intro_failsafe_caps_even_a_looping_animation():
    player = AnimationPlayer()
    finished = []
    player.play(LOOP_FOREVER, PlayMode.INTRO, now_ms=0.0, on_finished=lambda: finished.append(1))
    assert player.frame(INTRO_FAILSAFE_MS - 1) is not None
    assert player.frame(INTRO_FAILSAFE_MS) is None  # capped exactly at the failsafe
    assert finished == [1]


def test_replacing_an_animation_finishes_the_old_one():
    player = AnimationPlayer()
    finished = []
    player.play(LOOP_FOREVER, PlayMode.DURING, now_ms=0.0, on_finished=lambda: finished.append("old"))
    player.play(RAIN_2S, PlayMode.INTRO, now_ms=500.0, on_finished=lambda: finished.append("new"))
    assert finished == ["old"]
    assert player.frame(500.0) is not None  # the new one plays from its own t=0


def test_cancel_when_idle_is_safe():
    AnimationPlayer().cancel()
