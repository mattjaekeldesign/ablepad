"""
Clear Live's crash journal before launch, so the recovery dialog never appears.

LAYER: Services. Pure filesystem — no Windows API, no process control, so the
whole thing is testable on macOS against a tmp_path.

WHERE THE TRIGGER ACTUALLY LIVES  (MEASURED on the rig, 2026-08-13, Live 12.4.3)
    The obvious target is Preferences\\Crash\\, and it is the WRONG one. Caught by
    sweeping all 18 entries there, launching, and watching the dialog appear anyway.

        Preferences\\
            CrashRecoveryInfo.cfg    1182 B, stamped with the LAST run   <-- trigger
            Undo\\{0.band, bands.cfg}       stamped with the LAST run   <-- payload
            CrashDetection.cfg         68 B, rewritten every launch
            Undo.lock                   0 B, present while Live runs
        Preferences\\Crash\\
            <stamp>_BaseFiles\\, <stamp>_Undo\\, <stamp>_CrashRecoveryInfo.cfg

    At startup Live COPIES the root recovery state into Crash\\<stamp>_*. So Crash\\
    is an ARCHIVE of past recoveries -- housekeeping, and unbounded -- while the
    thing that makes the dialog appear sits at the Preferences root and survives
    any amount of sweeping underneath it.

    Both are handled here: the root state because it is the trigger, the archive
    because nothing else ever removes it.
    %APPDATA%\\Ableton\\Live 12.4.3\\Preferences\\Crash\\
        2026_08_12__23_17_39_BaseFiles\\test.als
        2026_08_12__23_17_39_Undo\\{0.band, bands.cfg}
        2026_08_12__23_17_39_CrashRecoveryInfo.cfg

    THREE entries per run, and the third is a FILE, not a directory. That is worth
    stating because an is_dir() filter looks obviously correct here and is not: it
    sweeps the two folders, leaves the .cfg -- which is the entry actually named
    after crash recovery -- and the dialog very likely still appears. Everything in
    this folder gets swept, files included. The folder appears when Live starts and is
    removed when Live exits cleanly, which is the mechanism behind the dialog:
    a journal still present at startup means the previous run did not shut down,
    so Live offers to recover it.

    Six pairs were sitting there, matching six hard kills exactly. Nothing in
    the rig had ever cleared them.

WHY THIS MOVES AND DOES NOT DELETE
    A journal is only worthless if the previous run had nothing worth keeping.
    That is true of the performance rig and NOT true of this machine, which is
    also where sets get built. Deleting the journal after a real crash mid-edit
    would trade the user's unsaved work for the convenience of skipping a
    dialog. So it is moved to a quarantine folder and the newest `keep` are
    retained.

    Recovering by hand is then: copy the folder back under Preferences\\Crash
    and start Live, which will offer it.

WHY THE VERSION IS GLOBBED
    The path contains "Live 12.4.3". That changes on every Live update, and a
    pinned path would silently stop matching — the sweep would report success
    while clearing nothing, and the dialog would come back with no error to
    explain it. The version segment is a glob and a run that matches no
    directory says so.

WHEN IT IS SAFE TO CALL
    ONLY when Live is not running. The newest journal belongs to the LIVE
    PROCESS, not to history, and moving it out from underneath a running Live
    is meddling with a file it has open. The launcher calls this immediately
    before start(), which is the one moment both facts hold.

HOW IT FAILS
    Every failure is logged and swallowed. A journal that cannot be moved means
    a recovery dialog, which is a nuisance; an exception here would mean no
    Ableton at all, which is the show. Cosmetic problems must not outrank
    starting.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

__all__ = ["CrashRecovery"]

#: Matches the version segment, e.g. "Live 12.4.3". See the module docstring —
#: pinning the version is how this silently stops working after an update.
LIVE_DIR_GLOB = "Live *"

#: Where everything below lives, inside a versioned Live directory.
PREFERENCES_SUBDIR = "Preferences"

#: THE TRIGGER. Moved wholesale, relative to the Preferences folder. Without these
#: Live has no session to offer and the dialog cannot appear. Live recreates both.
RECOVERY_STATE = ("CrashRecoveryInfo.cfg", "Undo")

#: The archive of previous recoveries. Its CONTENTS are swept; the folder stays,
#: because Live expects to find it. Clearing this alone does nothing to the dialog.
ARCHIVE_SUBDIR = "Crash"


@dataclass
class CrashRecovery:
    """
    Sweeps Live's crash journals aside.

    `ableton_appdata` is the folder holding the versioned Live directories --
    %APPDATA%\\Ableton on Windows. Given rather than derived so that tests, and
    a future non-Windows host, do not need an environment variable.
    """

    ableton_appdata: Path
    quarantine: Path
    #: How many swept ENTRIES to keep -- and a run produces three, so this is
    #: roughly "the last ten sessions". Enough to recover from a crash noticed a day
    #: later, small enough that a rig crash-looping cannot fill the disk with copies
    #: of a broken set.
    keep: int = 30

    _swept: int = field(default=0, init=False)

    def preferences_dirs(self) -> list[Path]:
        """Every versioned Preferences folder. Usually one; more after an upgrade."""
        if not self.ableton_appdata.is_dir():
            return []
        found = [
            path
            for live_dir in sorted(self.ableton_appdata.glob(LIVE_DIR_GLOB))
            if (path := live_dir / PREFERENCES_SUBDIR).is_dir()
        ]
        if not found:
            log.warning(
                "no %s/%s under %s — the recovery sweep will do nothing. Either the "
                "path is wrong or Live's layout changed; the dialog will come back "
                "with no other symptom, so this is worth fixing rather than ignoring.",
                LIVE_DIR_GLOB, PREFERENCES_SUBDIR, self.ableton_appdata,
            )
        return found

    def pending(self) -> list[Path]:
        """
        Everything that would be swept -- trigger first, then the archive.

        Files AND directories: the trigger is one of each, and an is_dir() filter
        here silently keeps CrashRecoveryInfo.cfg, which is the whole ballgame.
        """
        entries: list[Path] = []
        for prefs in self.preferences_dirs():
            entries.extend(prefs / name for name in RECOVERY_STATE if (prefs / name).exists())
            archive = prefs / ARCHIVE_SUBDIR
            if archive.is_dir():
                # Contents only. Live expects the folder itself to exist.
                entries.extend(sorted(archive.iterdir()))
        return entries

    def clear(self) -> int:
        """
        Move every journal to quarantine. Returns how many moved.

        Call ONLY with Live stopped — see the module docstring.
        """
        journals = self.pending()
        if not journals:
            return 0

        moved = 0
        for journal in journals:
            try:
                self.quarantine.mkdir(parents=True, exist_ok=True)
                shutil.move(str(journal), str(self._destination(journal)))
                moved += 1
            except OSError as exc:
                # Live may still hold a handle, or the disk is full. Either way the
                # cost is one dialog, and refusing to launch over it would be worse.
                log.warning("could not quarantine crash journal %s: %s", journal.name, exc)

        if moved:
            self._swept += moved
            log.info(
                "cleared %d Live crash journal(s) to %s — the recovery dialog will not "
                "appear. Unsaved work from those runs is recoverable from there.",
                moved, self.quarantine,
            )
            self._prune()
        return moved

    # -- internals --------------------------------------------------------

    def _destination(self, journal: Path) -> Path:
        """
        A free name inside quarantine.

        Journal names are timestamped so collisions are rare, but two Live versions
        can produce the same stamp and overwriting one recovery with another would
        destroy the exact thing this function exists to preserve.
        """
        target = self.quarantine / journal.name
        suffix = 1
        while target.exists():
            target = self.quarantine / f"{journal.name}~{suffix}"
            suffix += 1
        return target

    def _prune(self) -> None:
        """Keep the newest `keep` journals; delete the rest."""
        try:
            entries = sorted(
                self.quarantine.iterdir(), key=lambda e: e.stat().st_mtime, reverse=True
            )
        except OSError as exc:
            log.debug("cannot prune quarantine: %s", exc)
            return
        for stale in entries[self.keep:]:
            try:
                if stale.is_dir():
                    shutil.rmtree(stale)
                else:
                    stale.unlink()
            except OSError as exc:
                log.debug("cannot remove old quarantined journal %s: %s", stale.name, exc)

    @property
    def swept(self) -> int:
        """Total journals moved this run. A rising count is a crash story."""
        return self._swept
