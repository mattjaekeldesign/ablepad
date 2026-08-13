"""
Does a set mark itself modified without anyone touching it?

WHY THIS MATTERS
    Live will not close while it is asking "Save changes to <set>?", and nothing on
    a headless rig can answer that. The rig kills Live after
    GRACEFUL_CLOSE_TIMEOUT_S, so a self-dirtying set costs a few seconds of silence
    on EVERY set switch -- and it means the graceful close, which is what preserves
    preferences and clears the crash journal, effectively never happens.

    A set that stays clean never prompts. That is a far better fix than tuning the
    timeout, but only if the set really is dirtying itself rather than someone
    having nudged a control.

THE EXPERIMENT
    launch the set -> wait for it to finish loading -> touch NOTHING -> ask it to
    close with WM_CLOSE -> see whether it goes.

        closes            the set stays clean; a prompt means someone edited it
        does not close    the set dirties itself on load, and the rig will hit this
                          prompt on every single set switch

    Live is force-killed afterwards either way, so this leaves nothing running. That
    is safe here specifically because crash_recovery.py sweeps the journal before
    every launch.

RUN IT IN THE INTERACTIVE SESSION
    Session 0 cannot post WM_CLOSE to Live's windows -- taskkill reports "can only
    be terminated forcefully", which looks exactly like a save prompt and is not.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

SIGNAL = Path(r"C:\LiveRig\Logs\ableton-ready.json")
#: Time to sit still after the set reports ready, before asking it to close. Long
#: enough that anything settling asynchronously has finished dirtying the set.
QUIET_S = 15.0
CLOSE_WAIT_S = 20.0


def live_procs(psutil):
    return [
        p for p in psutil.process_iter(["name"])
        if "live" in (p.info["name"] or "").lower() and "cpl" not in (p.info["name"] or "").lower()
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    live_set = Path(argv[1])
    if not live_set.exists():
        print("no such set:", live_set)
        return 1

    import psutil  # noqa: PLC0415

    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    exe = next(
        (c for c in Path(r"C:\ProgramData\Ableton").glob("Live */Program/*.exe") if "Live" in c.name),
        None,
    )
    if exe is None:
        print("could not find the Ableton executable")
        return 1

    for p in live_procs(psutil):
        p.kill()
    time.sleep(3)
    SIGNAL.unlink(missing_ok=True)

    print("launching %s, then leaving it completely alone" % live_set.name)
    proc = psutil.Popen([str(exe), str(live_set)])

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline and not SIGNAL.exists():
        time.sleep(0.2)
    if not SIGNAL.exists():
        print("no readiness signal after 90s -- is the Remote Script installed?")
    else:
        print("set reported ready")

    print("sitting still for %.0fs (touching nothing)..." % QUIET_S)
    time.sleep(QUIET_S)

    print("asking Live to close...")
    subprocess.run(["taskkill", "/PID", str(proc.pid)], capture_output=True)

    end = time.monotonic() + CLOSE_WAIT_S
    while time.monotonic() < end:
        if not proc.is_running():
            print()
            print("RESULT: the set does NOT dirty itself.")
            print("  Live closed on request with no save prompt. A prompt you see in")
            print("  normal use therefore means something really did change the set --")
            print("  worth finding, because it is avoidable.")
            return 0
        time.sleep(0.25)

    print()
    print("RESULT: the set DIRTIES ITSELF on load.")
    print("  Live refused to close after %.0fs untouched, which is the save prompt." % CLOSE_WAIT_S)
    print("  Consequences, both real:")
    print("    * every set switch pays GRACEFUL_CLOSE_TIMEOUT_S of silence, then a kill")
    print("    * the graceful close never actually happens, so preference changes are")
    print("      lost and Live's own shutdown never runs")
    print("  Worth chasing upstream: a plugin writing state on load is the usual cause.")
    print("  cleaning up (force kill)...")
    for p in live_procs(psutil):
        p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
