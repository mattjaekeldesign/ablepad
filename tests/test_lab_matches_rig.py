"""
The Config Lab is for LEARNING the rig, so where it shows behaviour it must show the
rig's behaviour. A Lab that teaches something subtly false is worse than one that
stays silent -- you would only find out on stage.

These are cheap text checks, not a JS test suite. They exist because the two
codebases cannot import each other and drift is silent.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRID_JS = ROOT / "viz" / "lab" / "grid.js"
SCHEMA_JS = ROOT / "viz" / "lab" / "schema.js"


def test_the_labs_hold_ramp_matches_the_rigs():
    # The Lab used to paint a held pad's configured `pressed` colour. The rig now
    # overrides that with progress, so the Lab was teaching a pad that no longer
    # looks like that.
    from launchpad.holdfeedback import HOLD_RAMP, HOLD_THRESHOLDS

    js = GRID_JS.read_text()
    palettes = [int(m) for m in re.findall(r"at: [\d.]+, palette: (\d+)", js)]
    thresholds = [float(m) for m in re.findall(r"at: ([\d.]+), palette", js)]
    assert palettes == list(HOLD_RAMP), (
        f"Lab hold ramp {palettes} != rig {list(HOLD_RAMP)} — "
        "launchpad/holdfeedback.py and viz/lab/grid.js must agree"
    )
    assert thresholds == list(HOLD_THRESHOLDS), (
        f"Lab thresholds {thresholds} != rig {list(HOLD_THRESHOLDS)}"
    )


def test_every_action_a_config_uses_is_described_in_the_lab():
    # A pad on disk calling an action the Lab cannot explain is a hole in the thing
    # Matt reads to understand his own rig.
    js = SCHEMA_JS.read_text()
    documented = set(re.findall(r"^  ([A-Z_]+): \{", js, re.M))
    used = set()
    for config in (ROOT / "configs").glob("*.json"):
        for binding in json.loads(config.read_text()).get("pads", {}).values():
            action = (binding.get("action") or {}).get("type")
            if action and action != "NONE":
                used.add(action)
    assert used <= documented, f"actions used on disk but absent from the Lab: {used - documented}"


def test_the_labs_live_actions_are_actually_registered_in_main():
    # The Lab marks actions 'live' or 'planned'. Claiming 'live' for something no
    # command implements recreates the exact trap the status field exists to close.
    js = SCHEMA_JS.read_text()
    live = set(re.findall(r"^  ([A-Z_]+): \{[^}]*?status: 'live'", js, re.M | re.S))
    main = (ROOT / "main.py").read_text()
    system_commands = (ROOT / "rig" / "system_commands.py").read_text()

    # Handled by their own subscribers rather than the command dispatcher.
    by_subscriber = {"SWITCH_MODE", "LOAD_SET", "PAGE_NEXT", "PAGE_PREV", "RESCAN_SETS"}
    for action in live - by_subscriber:
        assert action in system_commands or action in main, (
            f"Lab claims {action} is live, but nothing implements it"
        )


def test_the_labs_planned_actions_are_not_quietly_implemented():
    # The reverse drift: an action built later and never un-marked reads as a dead
    # end forever, and the pad goes unused.
    js = SCHEMA_JS.read_text()
    planned = set(re.findall(r"^  ([A-Z_]+): \{[^}]*?status: 'planned'", js, re.M | re.S))
    system_commands = (ROOT / "rig" / "system_commands.py").read_text()
    for action in planned:
        assert f'name = "{action}"' not in system_commands, (
            f"{action} is implemented but the Lab still calls it planned"
        )


def test_every_config_on_disk_has_a_mode_note():
    js = SCHEMA_JS.read_text()
    noted = set(re.findall(r"^  '?([a-z-]+)'?: \{\n    summary:", js, re.M))
    on_disk = {p.stem for p in (ROOT / "configs").glob("*.json")}
    assert on_disk <= noted, f"configs with no explanation in the Lab: {on_disk - noted}"
