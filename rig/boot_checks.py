"""
The concrete boot checks, assembled from injected callables.

LAYER: Controller policy. Deliberately NOT importing windows/ — every probe arrives
as a plain callable, so this module and everything above it is testable on a Mac with
no Ableton, no Launchpad and no registry.

    main.py            picks real probes (windows/probes.py) or refuses to
    rig/boot_checks.py turns callables into named Checks with a confidence
    rig/boot.py        evaluates them, times out, and names what failed

Reading it bottom-up: the pure policy never learns what a registry is.
"""

from __future__ import annotations

from typing import Callable

from rig.boot import Check, CheckResult, Confidence

__all__ = ["build_checks"]


def build_checks(
    *,
    launchpad_connected: Callable[[], bool],
    evo_present: Callable[[], bool],
    ableton_running: Callable[[], bool],
    ableton_bound_to_evo: Callable[[], bool],
    ableton_settled: Callable[[], bool],
) -> list[Check]:
    """
    The five things that must be true before the rig leaves the splash screen.

    Order matters for the error message, not for correctness: they read from
    "nothing works" to "nearly there", so the first failure listed is usually the
    most fundamental thing wrong.
    """
    return [
        Check(
            name="launchpad",
            confidence=Confidence.CERTAIN,
            probe=lambda: CheckResult(
                launchpad_connected(),
                "connected" if launchpad_connected() else "not connected — no surface, no UI",
            ),
        ),
        Check(
            name="evo8",
            confidence=Confidence.CERTAIN,
            probe=lambda: CheckResult(
                evo_present(),
                "enumerated" if evo_present() else "not on the USB bus — check the cable",
            ),
        ),
        Check(
            name="ableton",
            confidence=Confidence.CERTAIN,
            probe=lambda: CheckResult(
                ableton_running(),
                "running" if ableton_running() else "process not running",
            ),
        ),
        Check(
            # The strongest available answer to "connected to EVO sound". It proves
            # Ableton opened THAT driver rather than Realtek or the Ampero's. It does
            # NOT prove audio is reaching the mixer -- nothing in software does.
            name="ableton_audio",
            confidence=Confidence.STRONG,
            probe=lambda: CheckResult(
                ableton_bound_to_evo(),
                "bound to the EVO's ASIO driver"
                if ableton_bound_to_evo()
                else "not bound to the EVO — wrong audio device selected?",
            ),
        ),
        Check(
            # A timer, and named accordingly. ableton/readiness.py calls the result
            # ASSUMED_READY because there is no load-complete signal until an Ableton
            # Remote Script exists to send one.
            name="settled",
            confidence=Confidence.GUESS,
            probe=lambda: CheckResult(
                ableton_settled(),
                "settle time elapsed (a guess, not a confirmation)"
                if ableton_settled()
                else "still settling",
            ),
        ),
    ]
