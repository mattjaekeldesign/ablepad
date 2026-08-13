"""
Entry point. The only module allowed to touch sys.argv, signals and process exit.

LAYER: Application Logic (wiring only — no behaviour lives here).

EXECUTION FLOW
    parse args -> load config (fail loudly) -> set up logging -> wire
    bus/machine/dispatcher/controller -> run -> exit codes:
        0  clean stop (Ctrl+C or stop command)
        2  configuration rejected
        1  anything else — which is a bug, and is logged as one

WHO STARTS IT
    A human during development; Windows Task Scheduler in Phase 7. Task Scheduler
    restarts on non-zero exit, so exit codes are behaviour, not decoration.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from ableton.readiness import Readiness, ReadinessTracker
from launchpad.backend_mido import MidoBackend
from launchpad.mappings import load_library
from launchpad.modes import missing_configs
from launchpad.service import LaunchpadService
from launchpad.surface import Surface
from rig.boot import BootGate, BootOutcome
from rig.boot_checks import build_checks
from rig.commands import CommandDispatcher
from rig.controller import RigController
from rig.events import ActionRequested, EventBus
from rig.exceptions import ConfigError
from rig.state import RigState, StateMachine
from storage.config_loader import RigConfig, load_config

log = logging.getLogger("main")


def setup_logging(config: RigConfig) -> None:
    """File + console, per the Phase 2 exit checklist. File dir comes from config."""
    log_dir = Path(config.logging.dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(log_dir / "rig.log", encoding="utf-8"),
    ]
    logging.basicConfig(
        level=getattr(logging, config.logging.level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )


def build(config: RigConfig, root: Path) -> tuple[RigController, Surface]:
    """
    Wire everything. No behaviour here — if a line does more than connect two
    objects it belongs in the module that owns the behaviour.
    """
    bus = EventBus()
    machine = StateMachine(bus=bus)
    dispatcher = CommandDispatcher()
    # Commands register here as later phases add them. Empty still — and dispatch of
    # anything therefore fails loudly, which is correct.
    _ = dispatcher

    library, warnings = load_library(root / "configs", root / "animations")
    # Every RigState must have a surface BEFORE the loop starts. Discovered here it
    # is a line in the log while a monitor is attached; discovered on a mode switch
    # it is a black surface halfway through a set.
    if missing := missing_configs(library):
        raise ConfigError([f"no config for mode(s): {', '.join(missing)}"])
    if warnings:
        log.warning("%d library warning(s) — see above", len(warnings))

    service = LaunchpadService(
        backend=MidoBackend(),
        bus=bus,
        brightness=config.launchpad.brightness,
    )
    surface = Surface(service=service, library=library, machine=machine, bus=bus)

    # Until the dispatcher has commands registered, log what the surface resolves.
    # This is the Phase 3 exit criterion made visible: a press must arrive as a
    # named action, never as a note number.
    bus.subscribe(
        ActionRequested,
        lambda e: log.info("ACTION %s from pad %d params=%s", e.action, e.pad, e.params),
    )

    gate = build_boot_gate(config, service, machine)

    def boot_tick() -> None:
        """
        Drive the gate while, and only while, the rig is on the splash screen.

        BOOT is the one state with an automatic exit. Everything else moves because
        a human pressed something.
        """
        if machine.state is not RigState.BOOT:
            return
        outcome = gate.evaluate()
        if outcome is BootOutcome.COMPLETE:
            machine.transition(RigState.SET_BROWSER, "BOOT_COMPLETE")
        elif outcome is BootOutcome.FAILED:
            # Error Mode, naming the fault. On a screenless rig "EVO 8 not on the USB
            # bus" and "Ableton not running" need different hands doing different
            # things, and a plain red screen tells you neither.
            machine.transition(RigState.ERROR, gate.summary())

    controller = RigController(
        machine=machine,
        bus=bus,
        tick_hz=config.rig.tick_hz,
        clock=time.monotonic,
        sleep=time.sleep,
        on_tick=[boot_tick, lambda: surface.tick(time.monotonic() * 1000.0)],
    )
    return controller, surface


def build_boot_gate(config: RigConfig, service: LaunchpadService, machine: StateMachine) -> BootGate:
    """
    Assemble the real probes, or degrade honestly if we are not on the target.

    On anything but Windows the platform probes cannot run. Rather than pretending
    they pass — which would let a Mac "boot complete" into a rig that does not exist
    — the unavailable ones report False and the gate simply never completes. The log
    says why once, and the rest of the stack stays exercisable.
    """
    try:
        from windows import probes  # noqa: PLC0415 — platform import, deliberate
    except Exception as exc:  # noqa: BLE001
        log.warning("platform probes unavailable (%s) — boot cannot complete here", exc)
        probes = None

    if probes is None:
        false = lambda: False  # noqa: E731
        checks = build_checks(
            launchpad_connected=lambda: service.connected,
            evo_present=false, ableton_running=false,
            ableton_bound_to_evo=false, ableton_settled=false,
        )
    else:
        # memory_maps() costs ~13 ms; at 30 Hz that is 38% of the tick budget, so it
        # is cached. The registry probes are 0.03 ms and run uncached.
        ableton_proc = probes.cached(lambda: probes.process_running(), ttl_s=1.0)
        bound = probes.cached(
            lambda: (p := ableton_proc()) is not None
            and probes.process_has_module(p, probes.AUDIENT_ASIO_MODULE),
            ttl_s=2.0,
        )
        readiness = ReadinessTracker(settle_s=config.rig.boot_settle_s, clock=time.monotonic)
        started = {"seen": False}

        def settled() -> bool:
            if ableton_proc() is None:
                started["seen"] = False
                readiness.mark_gone()
                return False
            if not started["seen"]:
                started["seen"] = True
                readiness.mark_started()
            return readiness.state(process_running=True) in (
                Readiness.ASSUMED_READY, Readiness.CONFIRMED_READY,
            )

        checks = build_checks(
            launchpad_connected=lambda: service.connected,
            evo_present=lambda: probes.usb_device_bound(),
            ableton_running=lambda: ableton_proc() is not None,
            ableton_bound_to_evo=lambda: bool(bound()),
            ableton_settled=settled,
        )

    return BootGate(checks=checks, timeout_s=config.rig.boot_timeout_s, clock=time.monotonic)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ablepad rig controller")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "config" / "rig.yaml",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=None,
        help="stop after N ticks (bench/smoke use; production omits this)",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        # Logging is not configured yet — config told us where logs go and it
        # just failed. stderr is all there is, so make it count.
        print(f"REFUSING TO START — {exc}", file=sys.stderr)
        return 2

    setup_logging(config)
    log.info("config accepted: rig=%r tick_hz=%d", config.rig.name, config.rig.tick_hz)

    try:
        controller, surface = build(config, Path(__file__).parent)
    except ConfigError as exc:
        log.error("REFUSING TO START — %s", exc)
        return 2

    try:
        controller.run(max_ticks=args.max_ticks)
        return 0
    except KeyboardInterrupt:
        controller.stop("Ctrl+C")
        log.info("clean exit on Ctrl+C after %d ticks", controller.ticks)
        return 0
    except Exception:
        log.exception("controller crashed — this is a bug")
        return 1
    finally:
        # NON-NEGOTIABLE. Programmer Mode disables the Launchpad's Setup menu, so a
        # controller that exits without restoring Live Mode leaves a headless rig
        # with an unreachable front panel. finally, not a happy path.
        surface.service.close()


if __name__ == "__main__":
    sys.exit(main())
