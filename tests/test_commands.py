"""CommandDispatcher: registration, dispatch, loud failure on unknown names."""

import pytest

from rig.commands import CommandDispatcher
from rig.exceptions import UnknownCommand


class FakeCommand:
    def __init__(self, name):
        self._name = name
        self.calls = []

    @property
    def name(self):
        return self._name

    def execute(self, context):
        self.calls.append(dict(context))


def test_dispatch_reaches_the_named_command():
    dispatcher = CommandDispatcher()
    command = FakeCommand("launch_set")
    dispatcher.register(command)
    dispatcher.dispatch("launch_set", {"set": "worship.als"})
    assert command.calls == [{"set": "worship.als"}]


def test_unknown_name_raises_with_the_known_list():
    dispatcher = CommandDispatcher()
    dispatcher.register(FakeCommand("reboot"))
    with pytest.raises(UnknownCommand) as excinfo:
        dispatcher.dispatch("restart_ableton", {})
    assert "reboot" in str(excinfo.value)


def test_double_registration_rejected():
    dispatcher = CommandDispatcher()
    dispatcher.register(FakeCommand("reboot"))
    with pytest.raises(ValueError):
        dispatcher.register(FakeCommand("reboot"))
