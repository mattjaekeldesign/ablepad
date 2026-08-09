"""config_loader: valid file parses; every failure is collected and loud."""

import pytest

from rig.exceptions import ConfigError
from storage.config_loader import load_config

VALID = """
rig:
  name: liverig
  tick_hz: 30
launchpad:
  brightness: 40
  port_contains: "LPX"
audio_interface:
  match_any: ["EVO 8"]
  require_status: "OK"
ableton:
  exe: "C:\\\\ProgramData\\\\Ableton\\\\Live 12\\\\Program\\\\Ableton Live.exe"
  sets_dir: "C:\\\\LiveRig\\\\Sets"
logging:
  dir: "logs"
  level: "INFO"
"""


def write(tmp_path, text):
    path = tmp_path / "rig.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_config_loads(tmp_path):
    config = load_config(write(tmp_path, VALID))
    assert config.rig.tick_hz == 30
    assert config.launchpad.brightness == 40
    assert config.audio_interface.match_any == ("EVO 8",)
    assert config.logging.level == "INFO"


def test_missing_file_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_invalid_yaml_is_config_error(tmp_path):
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config(write(tmp_path, "rig: [unclosed"))


def test_missing_section_named_clearly(tmp_path):
    broken = VALID.replace("launchpad:", "launchpadX:")
    with pytest.raises(ConfigError, match="'launchpad' missing"):
        load_config(write(tmp_path, broken))


def test_all_problems_reported_at_once(tmp_path):
    broken = (
        VALID.replace("tick_hz: 30", "tick_hz: fast")
        .replace("brightness: 40", "brightness: 300")
        .replace('level: "INFO"', 'level: "LOUD"')
    )
    with pytest.raises(ConfigError) as excinfo:
        load_config(write(tmp_path, broken))
    assert len(excinfo.value.problems) == 3


def test_bool_does_not_pass_as_int(tmp_path):
    with pytest.raises(ConfigError, match="tick_hz"):
        load_config(write(tmp_path, VALID.replace("tick_hz: 30", "tick_hz: true")))


def test_brightness_range_is_sysex_range(tmp_path):
    with pytest.raises(ConfigError, match="0-127"):
        load_config(write(tmp_path, VALID.replace("brightness: 40", "brightness: 128")))


def test_empty_match_any_rejected(tmp_path):
    with pytest.raises(ConfigError, match="match_any"):
        load_config(write(tmp_path, VALID.replace('match_any: ["EVO 8"]', "match_any: []")))
