"""
Rig state -> the 81 LEDs the surface should show. Pure: no device, no IO, no clock.

LAYER: services. Sits between modes.py (which config) and device.py (which bytes).

WHY PURE
    The renderer is called every tick. Making it a function of its inputs means the
    surface can be asserted in tests -- "in this state, with this animation frame,
    with pad 34 held, the surface looks exactly like THIS" -- with no hardware and no
    time. It also removes a whole class of bug by construction: there is no retained
    "currently animated" set to fall out of sync, which is precisely what went wrong
    in the Config Lab's JS compositor (a pad hidden under an intro was dropped from
    the animated set and never restored when the intro ended).

THE COMPOSITING STACK, top wins
    intro (full cover)
      -> pressed feedback
      -> during-animation on layer 'over'
      -> the pad's own bound LED
      -> during-animation on layer 'under'   (unbound pads only)
      -> the config's background

    Ported from the Config Lab (viz/lab/grid.js), which is the design authority for
    what a screen looks like -- same discipline as mappings.py porting its schema.
    A rig that renders differently from the Lab makes the Lab a liar.

    'under' vs 'over' is the interesting one: an ambient animation on 'under' must
    not hide a pad that means something. A bound pad always beats it. On 'over' the
    animation wins, which is what you want for a full-surface alert.
"""

from __future__ import annotations

from dataclasses import dataclass

from launchpad import colors, grid
from launchpad.device import LedSpec, Lighting
from launchpad.mappings import ModeConfig

__all__ = ["Overlay", "render", "led_spec_from_dict", "OFF_SPEC"]

#: What an unpainted cell under a covering intro shows. Palette 0 is off, not grey (p.14).
OFF_SPEC = {"type": "off"}

_LIGHTING_FOR_TYPE = {
    "static": Lighting.STATIC,
    "flash": Lighting.FLASHING,
    "pulse": Lighting.PULSING,
    "rgb": Lighting.RGB,
}


@dataclass(frozen=True)
class Overlay:
    """
    An animation frame to composite, plus how it should behave.

    cover=True is an intro: it owns the whole surface and unpainted cells read as
    off, so the mode underneath is genuinely hidden rather than showing through.
    """

    frame: dict[int, dict]  # pad index -> LED spec dict, from animations.animation_frame
    cover: bool = False
    layer: str = "under"  # 'under' | 'over'; ignored when cover is True


def led_spec_from_dict(index: int, led: dict | None) -> LedSpec:
    """
    Translate one Config Lab / animation LED dict into a driver LedSpec.

    Unknown or malformed types render as OFF rather than raising. A surface that
    loses one pad is recoverable on stage; one that raises mid-frame is not, and the
    validator in mappings.py is where bad configs are supposed to be caught.
    """
    if not led:
        return LedSpec(index=index, colour=colors.OFF)
    kind = led.get("type", "off")
    if kind == "rgb":
        raw = led.get("rgb") or (0, 0, 0)
        rgb = tuple(int(v) for v in (list(raw) + [0, 0, 0])[:3])
        return LedSpec(index=index, lighting=Lighting.RGB, rgb=rgb)  # type: ignore[arg-type]
    lighting = _LIGHTING_FOR_TYPE.get(kind)
    if lighting is None:  # "off", or something the validator should have rejected
        return LedSpec(index=index, colour=colors.OFF)
    return LedSpec(
        index=index,
        colour=int(led.get("palette", colors.OFF)),
        lighting=lighting,
        colour_b=int(led["paletteB"]) if "paletteB" in led else None,
    )


def _visible(
    index: int, config: ModeConfig, overlay: Overlay | None, pressed: frozenset[int]
) -> dict:
    """The LED dict this pad should show, resolved through the stack. Still a dict."""
    binding = config.pads.get(index)

    if overlay is not None:
        spec = overlay.frame.get(index)
        if overlay.cover:
            # An intro owns everything, including the pads it did not paint.
            return spec or OFF_SPEC
        if spec is not None and index not in pressed:
            # Pressed feedback beats ambient: the player needs to see their own press.
            if overlay.layer == "over" or binding is None:
                return spec

    if binding is not None:
        led = binding.led
        if index in pressed:
            return led.get("pressed") or led.get("idle") or OFF_SPEC
        return led.get("idle") or OFF_SPEC

    return config.background or OFF_SPEC


def render(
    config: ModeConfig | None,
    *,
    overlay: Overlay | None = None,
    pressed: frozenset[int] | set[int] | None = None,
) -> list[LedSpec]:
    """
    The whole surface for this instant: 81 LedSpecs, always, in a stable order.

    Always 81 -- never a diff. The device batches all of them into one SysEx (p.15,
    measured), so there is nothing to gain from computing a delta, and a full frame
    means a dropped message self-heals on the next tick instead of leaving a stale
    pad lit until something happens to repaint it.

    config=None blanks the surface. That is what SHUTDOWN wants, and it is also the
    honest thing to show when no mode is loaded -- rather than whatever was there.
    """
    held = frozenset(pressed or ())
    if config is None:
        return [LedSpec(index=i, colour=colors.OFF) for i in grid.ALL_INDICES]
    return [
        led_spec_from_dict(i, _visible(i, config, overlay, held)) for i in grid.ALL_INDICES
    ]
