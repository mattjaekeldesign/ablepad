r"""
ablepad readiness Remote Script — runs INSIDE Ableton Live, not in the rig.

DEPLOY TO
    C:\ProgramData\Ableton\Live 12 Suite\Resources\MIDI Remote Scripts\Ablepad\
    then Preferences -> Link, Tempo & MIDI -> Control Surface -> "Ablepad".
    No input or output port is needed: this script never sends MIDI.

    MEASURED 2026-08-13 on Live 12.4.3. The two user-scoped locations everyone
    recommends -- Preferences\User Remote Scripts\ and <User Library>\Remote
    Scripts\ -- are NOT listed by Live 12.4.3. See remote_script/README.md.

    Consequence: this lives inside the Live installation, so a Live update will
    delete it. The rig falls back to its settle timer and says so in the log; it
    gets slower, not broken. Reinstall after every Live update.

WHY IT EXISTS
    Nothing outside Live can tell whether a set has finished loading. The rig's
    boot gate was therefore waiting on a fixed timer long enough for the slowest
    set, every single boot, and still guessing. This writes one small file when
    the set is up; ableton/ready_signal.py reads it.

WHY IT WRITES A FILE AND SENDS NO MIDI
    MIDI would need a port assigned in this same preferences pane, competing with
    the two Launchpad ports the rig already depends on. A file needs no routing
    and can name the set, which is what lets the rig detect a stale signal.

THIS FILE RUNS IN LIVE'S PYTHON, NOT THE RIG'S
    So: no imports from the ablepad package, no f-strings beyond what Live's
    interpreter supports, no third-party modules, and no exception may escape.
    A Remote Script that raises is disabled by Live, silently, and the only
    evidence is a traceback in Live's own Log.txt. Everything here is wrapped.

UNVERIFIED — READ BEFORE TRUSTING
    Whether ControlSurface.__init__ runs BEFORE or AFTER the set has finished
    loading its devices is not documented and has not been measured here. If it
    runs early, this file appears too soon and the rig would complete boot before
    the set is playable.

    That is why ReadinessTracker.floor_s exists: a confirmed signal is ignored
    until a minimum time has passed, so an over-eager script can never make boot
    complete earlier than the floor. Measure the real gap (docs/ROADMAP.md Phase 5)
    before lowering that floor.
"""

import json
import os
import time

# Must match ableton.ready_signal.SIGNAL_FILENAME. Two constants, two interpreters,
# no import that can join them -- if you change one, change the other.
SIGNAL_PATH = os.path.join("C:\\", "LiveRig", "Logs", "ableton-ready.json")

SCHEMA_VERSION = 1


def _song_path(song):
    """Best-effort path of the loaded set. Never raises."""
    try:
        doc = song.file_path
    except Exception:
        return ""
    return doc or ""


def write_ready(song, reason):
    """
    Write the handshake file. Swallows everything.

    A failure here costs the rig its fast path and nothing else: with no signal,
    the boot gate falls back to the settle timer exactly as it did before this
    script existed.
    """
    try:
        payload = {
            "schema": SCHEMA_VERSION,
            "set": _song_path(song),
            "loaded_at": time.time(),
            "reason": reason,
        }
        directory = os.path.dirname(SIGNAL_PATH)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory)
        # Write-then-rename so the rig can never read a half-written file. It polls
        # at 30 Hz, so it WILL hit the middle of a plain write eventually.
        temporary = SIGNAL_PATH + ".part"
        handle = open(temporary, "w")
        try:
            handle.write(json.dumps(payload))
        finally:
            handle.close()
        if os.path.exists(SIGNAL_PATH):
            os.remove(SIGNAL_PATH)
        os.rename(temporary, SIGNAL_PATH)
    except Exception:
        pass


class Ablepad(object):
    """
    Minimal control surface. Owns no MIDI, draws nothing, controls nothing.

    Deliberately NOT a _Framework.ControlSurface subclass: that base class brings
    MIDI plumbing, component guards and a display model this needs none of, and
    every one of them is another way for the script to raise and be disabled.
    """

    def __init__(self, c_instance):
        self._c_instance = c_instance
        try:
            song = c_instance.song()
        except Exception:
            song = None
        write_ready(song, "control_surface_init")

    # -- the interface Live calls -----------------------------------------
    #
    # All no-ops. Live calls these on every script; omitting them is how a Remote
    # Script ends up raising AttributeError halfway through a set.

    def refresh_state(self):
        pass

    def update_display(self):
        pass

    def build_midi_map(self, midi_map_handle):
        pass

    def receive_midi(self, midi_bytes):
        pass

    def can_lock_to_devices(self):
        return False

    def suggest_input_port(self):
        return ""

    def suggest_output_port(self):
        return ""

    def disconnect(self):
        pass


def create_instance(c_instance):
    """Entry point Live looks for. Its name is fixed by Live, not by us."""
    return Ablepad(c_instance)
