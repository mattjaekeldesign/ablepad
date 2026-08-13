"""
mappings: the Lab contract holds on the Python side.

The strongest tests here load the REAL committed assets (configs/, animations/) —
if the Lab saved it, the rig must load it. The rest exercise each validation rule
and the hard-error/soft-warning split.
"""

import json
from pathlib import Path

import pytest

from launchpad.mappings import (
    ACTION_HOLDS,
    load_library,
    pad_is_button,
    pad_kind,
    validate_animation,
    validate_config,
)
from rig.exceptions import ConfigError

REPO = Path(__file__).parent.parent


# --- the real assets are the contract's proof ----------------------------


def test_real_library_loads_clean():
    library, warnings = load_library(REPO / "configs", REPO / "animations")
    assert {"boot", "error"} <= set(library.modes)
    assert {"boot-rain", "error-spin", "pulse-sweep"} <= set(library.animations)
    # boot/error reference set-browser, which is not designed yet — expected warnings,
    # and they must be warnings, not failures.
    assert all("set-browser" in w for w in warnings)


def test_real_boot_config_typed_view():
    library, _ = load_library(REPO / "configs", REPO / "animations")
    boot = library.modes["boot"]
    assert boot.pads[11].led_for("idle") == {"type": "static", "palette": 23}
    assert boot.pads[11].led_for("pressed") == {"type": "static", "palette": 23}  # falls back
    assert boot.animations["intro"]["ref"] == "boot-rain"
    assert boot.transitions == (("BOOT_COMPLETE", "set-browser"),)


def test_real_error_config_hold_defaults():
    library, _ = load_library(REPO / "configs", REPO / "animations")
    retry = library.modes["error"].pads[11]
    assert retry.action.type == "SWITCH_MODE"
    assert retry.action.hold_ms is None  # SWITCH_MODE has no default hold
    assert retry.led_for("pressed") == {"type": "static", "palette": 21}


# --- pad addressing ------------------------------------------------------


def test_pad_kinds():
    assert pad_kind(11) == "grid" and pad_kind(88) == "grid"
    assert pad_kind(91) == "cc-top" and pad_kind(98) == "cc-top"
    assert pad_kind(19) == "cc-right" and pad_kind(89) == "cc-right"
    assert pad_kind(99) == "logo"
    assert not pad_is_button(99) and pad_is_button(91)


# --- config validation rules ---------------------------------------------


def valid_config():
    return {
        "schemaVersion": 1,
        "id": "test",
        "name": "Test",
        "kind": "mode",
        "background": {"type": "off"},
        "pads": {},
        "animations": {"intro": None, "during": None},
        "transitions": [],
    }


def test_minimal_config_valid():
    assert validate_config(valid_config()) == []


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda c: c.update(schemaVersion=2), "schemaVersion"),
        (lambda c: c.update(id="Bad Id!"), "bad id"),
        (lambda c: c.update(name=""), "name is empty"),
        (lambda c: c.update(background={"type": "static", "palette": 200}), "palette"),
        (lambda c: c.update(pads={"10": {}}), "not a valid programmer-mode index"),
        (lambda c: c.update(pads={"11": {"led": {"hover": {"type": "off"}}}}), "unknown LED state"),
        (lambda c: c.update(pads={"11": {"action": {"type": "EXPLODE"}}}), "unknown action"),
        (lambda c: c.update(pads={"99": {"action": {"type": "PANIC_MUTE"}}}), "logo"),
        (lambda c: c.update(pads={"11": {"action": {"type": "LOAD_SET", "hold_ms": -1}}}), "hold_ms"),
        (lambda c: c.update(animations={"outro": {"ref": "x"}}), "unknown slot"),
        (lambda c: c.update(animations={"during": {"ref": "Bad Ref"}}), "bad ref"),
        (lambda c: c.update(animations={"during": {"ref": "ok", "layer": "middle"}}), "layer"),
        (lambda c: c.update(transitions=[{"on": "X"}]), "transition 0"),
        (lambda c: c.update(pads={"11": {"led": {"idle": {"type": "flash", "palette": 5}}}}), "paletteB"),
        (lambda c: c.update(pads={"11": {"led": {"idle": {"type": "rgb", "rgb": [1, 2]}}}}), "rgb"),
    ],
)
def test_config_rule(mutation, fragment):
    config = valid_config()
    mutation(config)
    errors = validate_config(config)
    assert any(fragment in e for e in errors), errors


# --- animation validation rules ------------------------------------------


def valid_generator_anim():
    return {
        "schemaVersion": 1,
        "id": "a",
        "name": "A",
        "engine": "generator",
        "loop": True,
        "duration_ms": None,
        "generator": {"type": "RAIN", "params": {"density": 6, "seed": 1}},
    }


def test_generator_anim_valid():
    assert validate_animation(valid_generator_anim()) == []


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda a: a.update(engine="video"), "unknown engine"),
        (lambda a: a.update(loop="yes"), "loop"),
        (lambda a: a.update(duration_ms=0), "duration_ms"),
        (lambda a: a["generator"].update(type="TORNADO"), "unknown generator"),
        (lambda a: a["generator"]["params"].update(density=25), "generator.density"),
        (lambda a: a["generator"]["params"].update(colorMode="plaid"), "not an option"),
    ],
)
def test_animation_rule(mutation, fragment):
    anim = valid_generator_anim()
    mutation(anim)
    errors = validate_animation(anim)
    assert any(fragment in e for e in errors), errors


def test_frames_anim_rules():
    anim = {
        "schemaVersion": 1,
        "id": "f",
        "name": "F",
        "engine": "frames",
        "loop": False,
        "frames": [
            {"duration_ms": 250, "pads": {"11": {"type": "pulse", "palette": 5}}},
        ],
    }
    errors = validate_animation(anim)
    assert any("only off/static/rgb" in e for e in errors)  # frames are snapshots
    anim["frames"] = []
    assert any("at least one frame" in e for e in validate_animation(anim))


# --- library loading: hard errors vs soft warnings ------------------------


def write_json(directory, name, payload):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload), encoding="utf-8")


def test_invalid_file_fails_the_whole_load_with_names(tmp_path):
    write_json(tmp_path / "configs", "good.json", valid_config() | {"id": "good"})
    broken = valid_config() | {"id": "broken", "name": ""}
    write_json(tmp_path / "configs", "broken.json", broken)
    with pytest.raises(ConfigError) as excinfo:
        load_library(tmp_path / "configs", tmp_path / "animations")
    assert any("broken.json" in p for p in excinfo.value.problems)


def test_unparseable_json_is_named(tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "junk.json").write_text("{ nope", encoding="utf-8")
    with pytest.raises(ConfigError, match="junk.json"):
        load_library(tmp_path / "configs", tmp_path / "animations")


def test_dangling_refs_warn_but_load(tmp_path):
    config = valid_config() | {
        "id": "solo",
        "animations": {"during": {"ref": "ghost-anim"}},
        "transitions": [{"on": "GO", "to": "nowhere"}],
    }
    config["pads"] = {"11": {"action": {"type": "SWITCH_MODE", "params": {"target": "nirvana"}}}}
    write_json(tmp_path / "configs", "solo.json", config)
    library, warnings = load_library(tmp_path / "configs", tmp_path / "animations")
    assert "solo" in library.modes  # loaded despite three dangling refs
    joined = " ".join(warnings)
    assert "ghost-anim" in joined and "nowhere" in joined and "nirvana" in joined


def test_missing_directories_load_empty(tmp_path):
    library, warnings = load_library(tmp_path / "no-configs", tmp_path / "no-anims")
    assert library.modes == {} and library.animations == {} and warnings == []


def test_load_set_hold_default_applied(tmp_path):
    config = valid_config() | {"id": "holds"}
    config["pads"] = {"12": {"action": {"type": "LOAD_SET", "params": {"slot": 3}}}}
    write_json(tmp_path / "configs", "holds.json", config)
    library, _ = load_library(tmp_path / "configs", tmp_path / "animations")
    action = library.modes["holds"].pads[12].action
    # 1000, not the roadmap's original 2000. Changed after using it on hardware:
    # two seconds is a long time with a finger on a pad. The assertion is against
    # the table rather than a literal so the two cannot drift, and the literal is
    # here so a change is a decision rather than a test quietly following along.
    assert action.hold_ms == ACTION_HOLDS["LOAD_SET"] == 1000
