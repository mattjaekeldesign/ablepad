"""
How long does a set ACTUALLY take to become playable, and is the readiness signal
telling the truth about it?

WHY THIS EXISTS
    boot_floor_s (5 s) is the guard that stops an over-eager readiness signal from
    completing boot before a set is playable. It was chosen without evidence,
    because the only set on the rig loads nothing heavy. This measures the gap the
    floor has to cover.

WHAT IT RECORDS, and what each is worth
    launch          t0. certain.
    asio            Ableton mapped the Audient ASIO driver. Certain that it opened
                    that driver; says nothing about the set (MEASURED: ~4 s for both
                    a 7 KB and a 15 KB set, which is why it cannot serve as readiness).
    signal          the Ablepad Remote Script wrote its handshake. This is
                    control_surface_init -- Live STARTING the script, not Live
                    FINISHING the set. Whether those coincide is the open question.
    window          Live's main window acquired a title. A proxy for "the UI is up",
                    and the only objective late signal available without a human.
    cpu_settled     Live's CPU dropped below a threshold for 2 consecutive seconds
                    after having been busy. A proxy for "it stopped loading things".
                    KNOWN BROKEN: reported NEVER on the 2026-08-13 baseline. The
                    busy threshold is not reached, probably because cpu_percent()
                    sampled every 50 ms on a multi-core box reports normalised values
                    well under 25 even while a core is saturated. Left in, and left
                    honest, rather than deleted -- on a heavy set it may be the most
                    informative marker of the four, and it needs a per-core threshold
                    and a longer sampling interval before it is worth trusting.

    NONE of these prove audio reaches the mixer. Nothing in software does -- an
    ESD-wedged EVO enumerates, loads its driver and outputs silence. The final
    arbiter is a human with ears, which is why the output ends with a prompt for it.

USAGE (on the rig, in the interactive session -- session 0 cannot see Live's windows)
    .venv\\Scripts\\python.exe tools\\measure_load.py "C:\\LiveRig\\Sets\\...\\set.als"
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SIGNAL = Path(r"C:\LiveRig\Logs\ableton-ready.json")
ASIO_HINT = "audientusbaudioasio"
POLL_S = 0.05
#: Window titles cost a PowerShell process each, so they are sampled ~1/s rather
#: than every poll. At 20/s the sampler burned more CPU than Live did and corrupted
#: cpu_settled, which is the marker it sits next to -- an observer loud enough to
#: drown the signal.
TITLE_POLL_S = 1.0
GIVE_UP_S = 180.0
CPU_IDLE_PCT = 8.0
CPU_IDLE_HOLD_S = 2.0


def live_processes(psutil):
    return [
        p for p in psutil.process_iter(["name"])
        if "live" in (p.info["name"] or "").lower() and "cpl" not in (p.info["name"] or "").lower()
    ]


def close_live(psutil) -> None:
    """Graceful, so the next launch is not fighting a recovery dialog."""
    procs = live_processes(psutil)
    if not procs:
        return
    for p in procs:
        subprocess.run(["taskkill", "/PID", str(p.pid)], capture_output=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and live_processes(psutil):
        time.sleep(0.2)
    if live_processes(psutil):
        print("WARNING: Live did not close. Check the screen for a save prompt.")
        sys.exit(1)


def window_title(proc) -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-Process -Id %d).MainWindowTitle" % proc.pid],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    live_set = Path(argv[1])
    if not live_set.exists():
        print("no such set:", live_set)
        return 1

    import psutil  # noqa: PLC0415 -- rig-only dependency

    exe = None
    for candidate in Path(r"C:\ProgramData\Ableton").glob("Live */Program/*.exe"):
        if "Live" in candidate.name:
            exe = candidate
            break
    if exe is None:
        print("could not find the Ableton executable under C:\\ProgramData\\Ableton")
        return 1

    # Unbuffered, or a redirected run shows an empty log until the process exits and
    # there is no way to tell "still measuring" from "hung".
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    print("closing any running Live, gracefully...")
    close_live(psutil)
    SIGNAL.unlink(missing_ok=True)

    print("launching", live_set.name)
    marks: dict[str, float] = {}
    t0 = time.monotonic()
    proc = psutil.Popen([str(exe), str(live_set)])
    busy_seen = False
    idle_since: float | None = None
    last_title_poll = 0.0
    peak_cpu = 0.0

    while time.monotonic() - t0 < GIVE_UP_S:
        now = time.monotonic() - t0

        if "signal" not in marks and SIGNAL.exists():
            try:
                json.loads(SIGNAL.read_text(encoding="utf-8"))
                marks["signal"] = now
            except Exception:
                pass

        if "asio" not in marks:
            try:
                if any(ASIO_HINT in m.path.lower() for m in proc.memory_maps()):
                    marks["asio"] = now
            except Exception:
                pass

        if (
            "window" not in marks
            and now > 1.0
            and now - last_title_poll >= TITLE_POLL_S
        ):
            last_title_poll = now
            if window_title(proc):
                marks["window"] = now

        try:
            cpu = proc.cpu_percent(interval=None)
        except Exception:
            cpu = 0.0
        peak_cpu = max(peak_cpu, cpu)
        if cpu > 25.0:
            busy_seen = True
            idle_since = None
        elif busy_seen and cpu < CPU_IDLE_PCT:
            idle_since = idle_since or now
            if "cpu_settled" not in marks and now - idle_since >= CPU_IDLE_HOLD_S:
                marks["cpu_settled"] = now

        if {"signal", "asio", "window", "cpu_settled"} <= marks.keys():
            break
        time.sleep(POLL_S)

    print("\n--- timeline (seconds from launch) ---")
    for name in ("asio", "signal", "window", "cpu_settled"):
        value = marks.get(name)
        print("  %-12s %s" % (name, ("%.2f" % value) if value is not None else "NEVER"))

    signal = marks.get("signal")
    latest = max((v for k, v in marks.items() if k != "signal"), default=None)
    if "cpu_settled" not in marks:
        print("\n  NOTE: cpu_settled did not fire. Known limitation of this tool, not")
        print("  a statement about the set -- see the module docstring. Peak CPU seen")
        print("  was %.0f%%." % peak_cpu)

    print("\n--- what this says about boot_floor_s ---")
    if signal is None:
        print("  no readiness signal at all. Is the Ablepad Remote Script installed")
        print("  and selected as a Control Surface? (remote_script/README.md)")
    elif latest is None:
        print("  signal at %.2fs but nothing else completed; inconclusive." % signal)
    else:
        gap = latest - signal
        print("  signal fired %.2fs after launch" % signal)
        print("  last objective marker at %.2fs" % latest)
        print("  signal is optimistic by %.2fs" % gap)
        print()
        # boot_floor_s is measured from LAUNCH, not from the signal. An earlier
        # version of this recommended gap + margin, which is the wrong quantity: it
        # produced 5 s for a set whose window did not exist until 6.25 s, so boot
        # completed before Live had a UI. The floor must cover launch -> playable.
        print("  boot_floor_s is measured from LAUNCH, so it must cover the LAST")
        print("  marker, not the gap:")
        print("  -> boot_floor_s: %.0f   (last marker %.2fs + %.0fs margin)" % (
            latest + 2.0, latest, 2.0,
        ))
        print("  A floor below %.2fs completes boot before Live has a window." % latest)
    print("\n  These are proxies. Play a note and time it yourself before trusting")
    print("  any of them -- nothing here proves audio reaches the mixer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
