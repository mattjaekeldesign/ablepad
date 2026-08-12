"""
launchpad/renderer.py — the compositing stack, asserted surface-by-surface.

The rules here are ported from the Config Lab (viz/lab/grid.js). If the rig renders
differently from the Lab then the Lab is lying to whoever designs a screen in it, so
these tests are as much about that contract as about the Python.
"""

from pathlib import Path

from launchpad import colors, grid
from launchpad.device import Lighting
from launchpad.mappings import load_library
from launchpad.renderer import Overlay, led_spec_from_dict, render
from launchpad.modes import resolve
from rig.state import RigState

REPO = Path(__file__).resolve().parent.parent

LIBRARY, _PROBLEMS = load_library(REPO / "configs", REPO / "animations")
BOOT = resolve(RigState.BOOT, LIBRARY)


def by_index(specs):
    return {s.index: s for s in specs}


# --- shape ---------------------------------------------------------------


def test_always_returns_the_whole_surface():
    specs = render(BOOT)
    assert len(specs) == 81
    assert [s.index for s in specs] == list(grid.ALL_INDICES)


def test_no_config_blanks_everything():
    # SHUTDOWN, or nothing loaded. Showing the previous mode would be a lie.
    specs = render(None)
    assert len(specs) == 81
    assert all(s.colour == colors.OFF for s in specs)


# --- the stack -----------------------------------------------------------


def test_bound_pad_shows_its_idle_led():
    pad, binding = next(iter(BOOT.pads.items()))
    expected = binding.led["idle"]["palette"]
    assert by_index(render(BOOT))[pad].colour == expected


def test_unbound_pad_shows_the_background():
    unbound = next(i for i in grid.ALL_INDICES if i not in BOOT.pads)
    assert by_index(render(BOOT))[unbound].colour == colors.OFF  # boot bg is "off"


def test_pressed_beats_idle():
    pad = next(iter(BOOT.pads))
    BOOT.pads[pad].led["pressed"] = {"type": "static", "palette": colors.RED}
    try:
        assert by_index(render(BOOT, pressed={pad}))[pad].colour == colors.RED
    finally:
        del BOOT.pads[pad].led["pressed"]


def test_pressed_falls_back_to_idle_when_no_pressed_led_is_defined():
    pad, binding = next(iter(BOOT.pads.items()))
    assert "pressed" not in binding.led
    idle = binding.led["idle"]["palette"]
    assert by_index(render(BOOT, pressed={pad}))[pad].colour == idle


def test_intro_covers_everything_including_pads_it_did_not_paint():
    overlay = Overlay(frame={11: {"type": "static", "palette": colors.CYAN}}, cover=True)
    specs = by_index(render(BOOT, overlay=overlay))
    assert specs[11].colour == colors.CYAN
    # A bound pad the intro did not paint must be HIDDEN, not showing through.
    bound = next(i for i in BOOT.pads if i != 11)
    assert specs[bound].colour == colors.OFF


def test_under_layer_loses_to_a_bound_pad():
    bound = next(iter(BOOT.pads))
    idle = BOOT.pads[bound].led["idle"]["palette"]
    overlay = Overlay(frame={bound: {"type": "static", "palette": colors.RED}}, layer="under")
    assert by_index(render(BOOT, overlay=overlay))[bound].colour == idle


def test_under_layer_still_shows_on_unbound_pads():
    unbound = next(i for i in grid.ALL_INDICES if i not in BOOT.pads)
    overlay = Overlay(frame={unbound: {"type": "static", "palette": colors.RED}}, layer="under")
    assert by_index(render(BOOT, overlay=overlay))[unbound].colour == colors.RED


def test_over_layer_beats_a_bound_pad():
    bound = next(iter(BOOT.pads))
    overlay = Overlay(frame={bound: {"type": "static", "palette": colors.RED}}, layer="over")
    assert by_index(render(BOOT, overlay=overlay))[bound].colour == colors.RED


def test_pressed_beats_even_an_over_layer_animation():
    # The player must see their own press. Ambient never wins over feedback.
    bound = next(iter(BOOT.pads))
    BOOT.pads[bound].led["pressed"] = {"type": "static", "palette": colors.BLUE}
    overlay = Overlay(frame={bound: {"type": "static", "palette": colors.RED}}, layer="over")
    try:
        got = by_index(render(BOOT, overlay=overlay, pressed={bound}))[bound]
        assert got.colour == colors.BLUE
    finally:
        del BOOT.pads[bound].led["pressed"]


# --- LED dict translation ------------------------------------------------


def test_flash_carries_both_palette_entries():
    spec = led_spec_from_dict(11, {"type": "flash", "palette": 5, "paletteB": 0})
    assert spec.lighting is Lighting.FLASHING
    assert spec.payload() == (1, 11, 5, 0)


def test_pulse_maps_to_the_pulsing_lighting_type():
    assert led_spec_from_dict(11, {"type": "pulse", "palette": 37}).lighting is Lighting.PULSING


def test_rgb_from_an_animation_frame_survives_translation():
    spec = led_spec_from_dict(11, {"type": "rgb", "rgb": [127, 64, 0]})
    assert spec.payload() == (3, 11, 127, 64, 0)


def test_rgb_out_of_range_is_clamped_not_passed_through():
    # A byte >= 0x80 inside SysEx terminates the message early and corrupts
    # everything after it — this is stream corruption, not a wrong colour.
    spec = led_spec_from_dict(11, {"type": "rgb", "rgb": [999, -5, 128]})
    assert spec.payload() == (3, 11, 127, 0, 127)


def test_unknown_led_type_renders_off_rather_than_raising():
    # Losing one pad is recoverable on stage; raising mid-frame is not.
    assert led_spec_from_dict(11, {"type": "nonsense"}).colour == colors.OFF
    assert led_spec_from_dict(11, None).colour == colors.OFF


# --- the whole thing is one batched write --------------------------------


def test_a_full_frame_fits_the_documented_sysex_ceiling():
    from launchpad.device import MAX_COLOURSPECS

    assert len(render(BOOT)) == MAX_COLOURSPECS
