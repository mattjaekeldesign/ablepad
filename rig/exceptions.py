"""
Exception vocabulary for the rig.

LAYER: shared by all rig layers. Depends on nothing.

WHY ONE MODULE
    Every failure the rig can raise deliberately lives here, so a reader can see
    the complete failure surface in one screen. Catch-points catch RigError; a
    bare Exception escaping to main.py is by definition a bug.
"""

from __future__ import annotations


class RigError(Exception):
    """Base for every deliberate failure. Always carries an actionable message."""


class IllegalTransition(RigError):
    """A state change the transition table forbids. The table is the spec."""


class ConfigError(RigError):
    """
    rig.yaml is unusable. Carries EVERY problem found, not just the first —
    a headless rig gets one shot at reporting why it refused to start.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__(
            f"{len(self.problems)} config problem(s):\n"
            + "\n".join(f"  - {p}" for p in self.problems)
        )


class UnknownCommand(RigError):
    """Dispatch of a command name nothing registered. A wiring bug, not user error."""
