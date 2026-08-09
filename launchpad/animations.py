"""
Animation frame engine — the Python port of viz/lab/anim.js.

LAYER: Services (pure math). No MIDI, no I/O, no clock. The Phase 3 player will
call animation_frame() once per controller tick and hand the frame to the
renderer; THIS module never touches a port.

THE DETERMINISM CONTRACT
    Same spec + same time = the same frame, bit-for-bit, in JS and in Python.
    Verified by tests/golden/animation-frames.json, which is dumped from the
    real Lab engine by node (scratchpad dump script; regenerate after ANY edit
    to viz/lab/anim.js and re-run the tests). The Lab is the design tool — if
    the two engines disagree, what Matt designed is not what the rig plays.

PORTING NOTES — the three traps, so nobody "cleans them up":
    1. All 32-bit ops are masked (& 0xFFFFFFFF). JS mixes signed (Math.imul,
       |0) and unsigned (>>>) views of the same bits; addition, XOR and
       multiplication agree modulo 2^32, so an all-unsigned port is bit-exact.
    2. _js_round is floor(x + 0.5): JS Math.round rounds half UP, Python's
       round() rounds half to even. Inputs here are always >= 0.
    3. Time quantisation is floor(t*30/1000)*1000/30 — the exact double-op
       sequence from anim.js. Both runtimes use IEEE-754 doubles, so keeping
       the operation ORDER identical keeps every result identical.

WHO CALLS IT
    Phase 3 player (once it exists) and the golden tests. Frames map int pad
    index (11–99, Programmer-mode numbering) -> LED spec dict, e.g.
    {'type': 'rgb', 'rgb': [r, g, b]} with each channel 0–127 (SysEx type 3,
    manual p.15). Generators emit RGB only, never palette indices — the
    palette is Phase 1 UNVERIFIED and must not become load-bearing here.
"""

from __future__ import annotations

import math
from typing import Callable

ANIM_TICK_MS = 1000 / 30  # 30 fps design target; hardware feasibility UNVERIFIED (Phase 1)

_MASK = 0xFFFFFFFF

PAD_IDS: tuple[int, ...] = tuple(r * 10 + c for r in range(1, 10) for c in range(1, 10))

GENERATOR_DEFAULTS: dict[str, dict] = {
    # Mirrors viz/lab/schema.js GENERATORS — the catalogue is the contract.
    "RAIN": {"density": 6, "speed": 8, "tail": 3, "colorMode": "random", "hue": 0, "seed": 1},
    "PULSE_WAVE": {
        "direction": "random",
        "period_ms": 1400,
        "width": 2.5,
        "colorMode": "random",
        "hue": 0,
        "seed": 1,
    },
    "SPIN_SQUARE": {
        "size": 6,
        "period_ms": 1600,
        "tail": 6,
        "colorMode": "random",
        "hue": 0,
        "seed": 1,
    },
}

Frame = dict[int, dict]
Rng = Callable[[], float]


# --------------------------------------------------------------- deterministic randomness


def _imul(x: int, y: int) -> int:
    """Math.imul modulo 2^32 (sign difference is erased by downstream masking)."""
    return (x * y) & _MASK


def _mulberry32(seed: int) -> Rng:
    a = seed & _MASK

    def rand() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _MASK
        t = _imul(a ^ (a >> 15), a | 1)
        t = ((t + _imul(t ^ (t >> 7), t | 61)) ^ t) & _MASK
        return ((t ^ (t >> 14)) & _MASK) / 4294967296

    return rand


def _rng_for(seed: int | None, n: int) -> Rng:
    # JS: (((seed ?? 0) * 0x9e3779b1) + n * 0x85ebca6b) >>> 0. All-integer and
    # < 2^53 for catalogue-range inputs, so plain int arithmetic + mask matches.
    return _mulberry32(((seed or 0) * 0x9E3779B1 + n * 0x85EBCA6B) & _MASK)


# ------------------------------------------------------------------------------- colour


def _hue_rgb(h: float) -> tuple[float, float, float]:
    def f(n: int) -> float:
        k = (n + h * 6) % 6
        return 1 - max(0.0, min(k, 4 - k, 1.0))

    return (f(5), f(3), f(1))


def _js_round(x: float) -> int:
    return math.floor(x + 0.5)


def _to_led(unit: tuple[float, float, float], b: float) -> dict:
    return {"type": "rgb", "rgb": [_js_round(v * b * 127) for v in unit]}


def _color_for(params: dict, rng: Rng) -> tuple[float, float, float]:
    random = rng()  # consumed in BOTH modes so geometry streams stay aligned
    if params.get("colorMode") == "hue":
        return _hue_rgb((params.get("hue") or 0) / 360)
    return _hue_rgb(random)


def _blend_max(out: Frame, pad: int, spec: dict) -> None:
    prev = out.get(pad)
    if prev is None or sum(spec["rgb"]) > sum(prev["rgb"]):
        out[pad] = spec


# --------------------------------------------------------------------------- generators


_ring_cache: dict[int, tuple[int, ...]] = {}


def _ring_cells(size: int) -> tuple[int, ...]:
    """Perimeter of a centred square on the 8x8 grid, clockwise from top-left."""
    if size in _ring_cache:
        return _ring_cache[size]
    lo = 5 - size // 2
    hi = lo + size - 1
    cells: list[int] = []
    cells += [hi * 10 + c for c in range(lo, hi + 1)]
    cells += [r * 10 + hi for r in range(hi - 1, lo - 1, -1)]
    cells += [lo * 10 + c for c in range(hi - 1, lo - 1, -1)]
    cells += [r * 10 + lo for r in range(lo + 1, hi)]
    _ring_cache[size] = tuple(cells)
    return _ring_cache[size]


def _rain(p: dict, t: float) -> Frame:
    out: Frame = {}
    travel_ms = ((8 + p["tail"]) / p["speed"]) * 1000
    for d in range(int(p["density"])):
        offset = _rng_for(p["seed"], d)() * travel_ms
        pass_n = math.floor((t + offset) / travel_ms)
        rng = _rng_for(p["seed"], d * 7919 + pass_n * 104729)
        col = 1 + math.floor(rng() * 9)
        color = _color_for(p, rng)
        head = 9 - (((t + offset) % travel_ms) / travel_ms) * (8 + p["tail"])
        for row in range(1, 10):
            trail = row - head
            if trail < 0 or trail >= p["tail"]:
                continue
            b = 1 - trail / p["tail"]
            _blend_max(out, row * 10 + col, _to_led(color, b * b))
    return out


def _pulse_wave(p: dict, t: float) -> Frame:
    out: Frame = {}
    sweep = math.floor(t / p["period_ms"])
    rng = _rng_for(p["seed"], sweep)
    dir_draw = rng()  # consumed even when direction is fixed — keeps streams aligned
    if p["direction"] == "random":
        direction = ("up", "down", "left", "right")[math.floor(dir_draw * 4)]
    else:
        direction = p["direction"]
    color = _color_for(p, rng)
    frac = (t % p["period_ms"]) / p["period_ms"]
    span = 8 + 2 * p["width"]
    if direction in ("up", "right"):
        pos = 1 - p["width"] + frac * span
    else:
        pos = 9 + p["width"] - frac * span
    row_wise = direction in ("up", "down")
    for pad in PAD_IDS:
        along = pad // 10 if row_wise else pad % 10
        d = abs(along - pos)
        if d >= p["width"]:
            continue
        b = 1 - d / p["width"]
        out[pad] = _to_led(color, b * b)
    return out


def _spin_square(p: dict, t: float) -> Frame:
    out: Frame = {}
    cells = _ring_cells(int(p["size"]))
    n = len(cells)
    rng = _rng_for(p["seed"], math.floor(t / p["period_ms"]))
    color = _color_for(p, rng)
    head = ((t % p["period_ms"]) / p["period_ms"]) * n
    tail = min(p["tail"], n - 1)
    for i in range(n):
        behind = (head - i + n) % n
        if behind >= tail:
            continue
        b = 1 - behind / tail
        out[cells[i]] = _to_led(color, b * b)
    return out


_IMPL: dict[str, Callable[[dict, float], Frame]] = {
    "RAIN": _rain,
    "PULSE_WAVE": _pulse_wave,
    "SPIN_SQUARE": _spin_square,
}


# ------------------------------------------------------------------------ frames engine


def frames_total_ms(anim: dict) -> float:
    return sum(f.get("duration_ms") or 0 for f in anim.get("frames") or [])


def _pads_of(frame: dict) -> Frame:
    return {int(k): v for k, v in (frame.get("pads") or {}).items()}


def _frames_frame(anim: dict, t: float) -> Frame | None:
    frames = anim.get("frames") or []
    total = frames_total_ms(anim)
    if not frames or total <= 0:
        return {}
    if not anim.get("loop") and t >= total:
        return None
    tt = t % total
    for f in frames:
        if tt < (f.get("duration_ms") or 0):
            return _pads_of(f)
        tt -= f.get("duration_ms") or 0
    return _pads_of(frames[-1])


# --------------------------------------------------------------------------- public API


def _gen_params(generator: dict | None) -> dict:
    generator = generator or {}
    merged = dict(GENERATOR_DEFAULTS.get(generator.get("type"), {}))
    merged.update(generator.get("params") or {})
    return merged


def animation_frame(anim: dict | None, t_ms: float) -> Frame | None:
    """
    The frame at time t_ms, or None when a non-looping animation has finished.
    Unpainted pads are transparent — compositing is the caller's business.
    """
    if not anim:
        return None
    # Integer tick index first — same double-op order as anim.js, see module notes.
    t = math.floor(t_ms * 30 / 1000) * 1000 / 30
    if anim.get("engine") == "frames":
        return _frames_frame(anim, t)
    if not anim.get("loop") and anim.get("duration_ms") is not None and t >= anim["duration_ms"]:
        return None
    generator = anim.get("generator") or {}
    impl = _IMPL.get(generator.get("type"))
    if impl is None:
        return {}  # unknown type: transparent, never crash
    return impl(_gen_params(generator), t)


def animation_duration(anim: dict | None) -> float | None:
    """Total length in ms, or None for 'runs forever'."""
    if not anim:
        return 0
    if anim.get("loop"):
        return None
    if anim.get("engine") == "frames":
        return frames_total_ms(anim)
    return anim.get("duration_ms")
