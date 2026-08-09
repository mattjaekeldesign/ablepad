"""
Persisted runtime state — the few facts that must survive a restart.

LAYER: Configuration/storage.

WHAT LIVES HERE (eventually)
    Last loaded set, current page, restart-attempt counters. Small, flat, JSON.

WHY ATOMIC
    The rig can lose power at any moment mid-write. os.replace() on the same
    filesystem is atomic on Windows and POSIX, so the file on disk is always
    either the old state or the new state — never half of each.

HOW IT FAILS
    A corrupt or unreadable file is quarantined to <name>.corrupt and defaults
    are returned. An appliance must boot with amnesia rather than not boot;
    the quarantined file preserves the evidence for the bench.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class RuntimeStateStore:
    path: Path

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"expected object, got {type(data).__name__}")
            return data
        except (ValueError, OSError) as exc:
            quarantine = self.path.with_suffix(self.path.suffix + ".corrupt")
            log.warning(
                "runtime state unreadable (%s); quarantining to %s and starting empty",
                exc,
                quarantine,
            )
            try:
                os.replace(self.path, quarantine)
            except OSError:
                pass
            return {}

    def save(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=self.path.parent, prefix=self.path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
