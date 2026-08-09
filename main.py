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

from rig.commands import CommandDispatcher
from rig.controller import RigController
from rig.events import EventBus
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


def build(config: RigConfig) -> RigController:
    bus = EventBus()
    machine = StateMachine(bus=bus)
    dispatcher = CommandDispatcher()
    # Commands register here as later phases add them. Empty in Phase 2 —
    # and dispatch of anything therefore fails loudly, which is correct.
    _ = dispatcher
    return RigController(
        machine=machine,
        bus=bus,
        tick_hz=config.rig.tick_hz,
        clock=time.monotonic,
        sleep=time.sleep,
    )


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

    controller = build(config)
    try:
        controller.run(max_ticks=args.max_ticks)
    except KeyboardInterrupt:
        controller.stop("Ctrl+C")
        log.info("clean exit on Ctrl+C after %d ticks", controller.ticks)
        return 0
    except Exception:
        log.exception("controller crashed — this is a bug")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
