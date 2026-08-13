"""
Command protocol and dispatcher.

LAYER: Controller boundary. This is the generalisation rule from CLAUDE.md §4
made concrete: there is no RestartAbletonButton — there are commands with names,
and modes map pads to command NAMES in configuration, never to functions.

WHO CALLS IT
    rig/controller.py dispatches by name when a mode mapping fires. Commands are
    registered at wiring time in main.py. Later phases contribute commands
    (launch_set, toggle_hotspot, reboot) without this module changing.

HOW IT FAILS
    Dispatching an unregistered name raises UnknownCommand — loudly, because a
    pad mapped to a missing command is a wiring bug that must surface in the
    bench, not silently do nothing at a gig.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Mapping, Protocol

from rig.exceptions import UnknownCommand

log = logging.getLogger(__name__)


class Command(Protocol):
    """
    One nameable rig action. `name` is what configuration refers to;
    `execute` receives a context mapping the controller assembles.
    """

    @property
    def name(self) -> str: ...

    def execute(self, context: Mapping[str, object]) -> None: ...


@dataclass
class CommandDispatcher:
    _commands: dict[str, Command] = field(default_factory=dict)

    def register(self, command: Command) -> None:
        if command.name in self._commands:
            raise ValueError(
                f"command {command.name!r} registered twice — two owners means no owner"
            )
        self._commands[command.name] = command

    def knows(self, name: str) -> bool:
        """
        Is this a command we own?

        Exists because ActionRequested carries EVERY named action the surface
        resolves, most of which belong to other subscribers (LOAD_SET, SWITCH_MODE,
        PAGE_NEXT). A subscriber that dispatched blindly would raise UnknownCommand
        on the first set load. dispatch() still raises for a name nobody owns --
        that is a wiring bug and must surface loudly.
        """
        return name in self._commands

    def dispatch(self, name: str, context: Mapping[str, object]) -> None:
        command = self._commands.get(name)
        if command is None:
            raise UnknownCommand(
                f"no command named {name!r}. Registered: {sorted(self._commands)}"
            )
        log.info("dispatch %r", name)
        command.execute(context)

    def known(self) -> list[str]:
        return sorted(self._commands)
