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

from launchpad.backend_mido import MidoBackend
from launchpad.mappings import load_library
from launchpad.modes import missing_configs
from launchpad.service import LaunchpadService
from launchpad.surface import Surface
from rig.commands import CommandDispatcher
from rig.controller import RigController
from rig.events import ActionRequested, EventBus
from rig.exceptions import ConfigError
from rig.state import StateMachine
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

    controller = RigController(
        machine=machine,
        bus=bus,
        tick_hz=config.rig.tick_hz,
        clock=time.monotonic,
        sleep=time.sleep,
        on_tick=[lambda: surface.tick(time.monotonic() * 1000.0)],
    )
    return controller, surface


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
