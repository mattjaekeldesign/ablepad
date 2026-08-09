"""
Golden-frame verification: the Python engine vs the real Lab engine.

tests/golden/animation-frames.json is dumped from viz/lab/anim.js by node
(scratchpad/dump-golden.mjs). 16 cases x 15 sample times cover: the three
committed animation assets, sparse-params default filling, fixed-hue and
random colour modes, all four pulse directions, all spin sizes, tail clamping,
non-loop end (null), the frames engine (loop/once/empty), and unknown
generator types.

EXACT equality is the assertion — same ints, same keys, no tolerance. The
determinism contract is bit-for-bit or it is nothing: an off-by-one in the RNG
would produce plausible-looking frames that drift from every design in the Lab.

If viz/lab/anim.js changes, regenerate the golden file with node and re-run.
"""

import json
from pathlib import Path

import pytest

from launchpad.animations import animation_duration, animation_frame, frames_total_ms

GOLDEN = Path(__file__).parent / "golden" / "animation-frames.json"


def load_cases():
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for name, case in data.items():
        for t_str, expected in case["samples"].items():
            yield pytest.param(case["spec"], float(t_str), expected, id=f"{name}@{t_str}ms")


def normalise(frame_json: dict | None) -> dict | None:
    """JS Map keys serialise as strings; the Python engine keys by int."""
    if frame_json is None:
        return None
    return {int(k): v for k, v in frame_json.items()}


@pytest.mark.parametrize(("spec", "t_ms", "expected"), list(load_cases()))
def test_frame_matches_js_engine_exactly(spec, t_ms, expected):
    assert animation_frame(spec, t_ms) == normalise(expected)


def test_golden_file_is_substantial():
    # Guard against a truncated regeneration quietly weakening the suite.
    data = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(data) >= 16
    non_empty = sum(
        1
        for case in data.values()
        for frame in case["samples"].values()
        if frame  # not None, not {}
    )
    assert non_empty >= 100, "most sampled frames should actually paint pads"


def test_duration_semantics():
    assert animation_duration(None) == 0
    assert animation_duration({"loop": True}) is None
    assert animation_duration({"engine": "generator", "loop": False, "duration_ms": 4000}) == 4000
    frames = {
        "engine": "frames",
        "loop": False,
        "frames": [{"duration_ms": 300, "pads": {}}, {"duration_ms": 200, "pads": {}}],
    }
    assert animation_duration(frames) == 500
    assert frames_total_ms(frames) == 500
