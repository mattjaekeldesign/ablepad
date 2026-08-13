"""
The handshake: Live telling the rig its set has actually finished loading.

LAYER: Services. Pure filesystem and JSON — no Live API, no Windows API, so this
half is fully testable off-rig. The half that runs INSIDE Live is
`remote_script/Ablepad/`, which cannot be tested here at all.

WHAT PROBLEM THIS SOLVES
    `boot_settle_s` was a wall-clock guess with nothing behind it. MEASURED
    2026-08-13: `ableton_audio` binds ~4 s after launch for BOTH a 7 KB set and a
    15 KB one, which proves that check measures Ableton's own startup and says
    nothing about whether the set is loaded. A set with a NAM model and IRs takes
    considerably longer, and the rig had no way to know.

    So the timer had to be set long enough for the worst set (slow every boot) and
    was still a guess (wrong for the set that is slower still).

WHY A FILE AND NOT MIDI
    A Remote Script can send MIDI, but that requires a port assigned in Live's
    Preferences GUI, competes with the two Launchpad ports the rig already needs,
    and carries a byte. A file needs no routing configuration and can say WHICH set
    loaded and WHEN -- which is what makes staleness detectable.

STALENESS IS THE WHOLE DIFFICULTY
    A handshake file from the previous boot looks exactly like one from this boot.
    Reading a stale file would confirm readiness for a set that is not loaded --
    the failure this module exists to prevent, dressed as success.

    Two defences, deliberately belt and braces:
      * clear() before launch, so any file that appears afterwards is new. The
        launcher does this in the same breath as the crash sweep.
      * the file names the set it loaded, and read() rejects one naming a different
        set. That catches the case where clear() failed silently.

    Not used: file mtime against a launch timestamp. Clock skew, timezone handling
    and second-resolution timestamps make it fragile, and the two checks above do
    not depend on any clock agreeing with any other.

HOW IT FAILS
    Every failure path returns "not ready" and is logged, never raised. A missing,
    empty, half-written or malformed file is indistinguishable from "the set is
    still loading" and must be treated as such — the boot gate's own timeout is
    what turns a permanently absent signal into an error, and it already says so
    in its own words.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["ReadySignal", "SIGNAL_FILENAME"]

#: Written by the Remote Script, read here. Also hardcoded in
#: remote_script/Ablepad/__init__.py -- the two must agree, and there is no import
#: that can enforce it because that file runs inside Live's interpreter.
SIGNAL_FILENAME = "ableton-ready.json"


def _basename(path: str) -> str:
    """
    Last path segment, splitting on BOTH separators regardless of host.

    pathlib is the obvious tool and the wrong one here. The signal is always written
    by Live on Windows, so it carries backslashes -- and PurePosixPath treats those
    as ordinary filename characters, making the "name" of
    C:\\LiveRig\\Sets\\test.als the entire string. That is invisible on the rig and
    fails every time off it, which is exactly backwards for a module whose value is
    being testable off-rig.
    """
    return path.replace("\\", "/").rstrip("/").rpartition("/")[2]


@dataclass
class ReadySignal:
    """
    Reads the handshake file the Remote Script writes when a set finishes loading.

    `path` is the file itself. Given rather than derived so tests need no
    environment and the location stays a configuration decision.
    """

    path: Path

    def clear(self) -> None:
        """
        Remove any signal from a previous run. Call immediately before launching.

        Failure is logged, not raised: the set-name check in read() is the second
        line of defence precisely so this one is allowed to fail.
        """
        try:
            self.path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning(
                "could not clear the readiness signal at %s (%s) — a stale file could "
                "now confirm the wrong set, so read() will fall back to matching on "
                "the set name",
                self.path, exc,
            )

    def read(self, expected_set: Path | None = None) -> dict | None:
        """
        The signal, or None if there is not a usable one for this launch.

        `expected_set` is the .als the rig believes it launched. When given, a signal
        naming a different set is rejected — that is a stale file, not a confirmation.
        """
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None  # the overwhelmingly common case: still loading
        except OSError as exc:
            log.debug("readiness signal unreadable (%s) — treating as not ready", exc)
            return None

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            # Almost certainly a half-written file caught mid-flush. The next tick
            # will read it whole, so this is not worth a warning every 33 ms.
            log.debug("readiness signal is not valid JSON yet — treating as not ready")
            return None

        if not isinstance(payload, dict):
            log.warning("readiness signal is %s, expected an object", type(payload).__name__)
            return None

        if expected_set is not None and not self._matches(payload, expected_set):
            log.warning(
                "ignoring a readiness signal for %r while waiting for %s — this is a "
                "stale file from an earlier run, and honouring it would confirm a set "
                "that is not loaded",
                payload.get("set"), expected_set.name,
            )
            return None
        return payload

    def is_ready(self, expected_set: Path | None = None) -> bool:
        return self.read(expected_set) is not None

    # -- internals --------------------------------------------------------

    @staticmethod
    def _matches(payload: dict, expected_set: Path) -> bool:
        """
        Does this signal name the set we are waiting for?

        Compared on FILENAME, case-insensitively. Not on the full path: Live reports
        the path it opened, which can differ from the one passed on the command line
        by drive-letter case, trailing separators, or a symlinked Sets folder, and a
        false mismatch here would stall boot until the timeout with a confusing
        message. The filename is specific enough to catch the real case this guards
        (a different set from a previous run) without inventing path-equality rules.
        """
        reported = payload.get("set")
        if not isinstance(reported, str) or not reported:
            # No claim made. Trust it -- clear() is then the only defence, which is
            # the situation the rig was in before any of this existed.
            return True
        return _basename(reported).lower() == _basename(str(expected_set)).lower()
