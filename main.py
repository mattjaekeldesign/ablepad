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

from ableton.crash_recovery import CrashRecovery
from ableton.ready_signal import ReadySignal
from ableton.launcher import AbletonLauncher, LaunchRefused
from ableton.process import PsutilProcessController
from ableton.readiness import Readiness, ReadinessTracker
from ableton.recovery import RestartBudget
from ableton.supervisor import AbletonSupervisor
from launchpad.backend_mido import MidoBackend
from launchpad.mappings import load_library
from launchpad.modes import missing_configs
from launchpad.service import LaunchpadService
from launchpad.surface import Surface
from rig.boot import BootGate, BootOutcome
from rig.boot_choice import BootChoice
from rig.browser_control import SetBrowserControl
from rig.boot_checks import build_checks
from rig.commands import CommandDispatcher
from rig.controller import RigController
from rig.mode_switch import ModeSwitch
from rig.escape_hatch import EscapeHatch
from rig.lifeline import WifiLifeline
from rig.system_commands import Reboot, RestartAbleton, Shutdown
from rig.surface_owner import SurfaceOwner
from rig.events import AbletonClosed, AbletonGaveUp, ActionRequested, EventBus
from rig.exceptions import ConfigError
from rig.state import RigState, StateMachine
from set_browser.service import SetBrowserService
from storage.config_loader import RigConfig, load_config

log = logging.getLogger("main")

#: Set by build() so the AbletonGaveUp subscriber can reach the state machine without
#: build_ableton() taking a parameter it has no other use for.
machine_ref: dict[str, StateMachine] = {}


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
    machine_ref["m"] = machine
    dispatcher = CommandDispatcher()

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

    supervisor = build_ableton(config, bus)

    # Who drives the Launchpad. The rig is the launcher until a set is up; then
    # Ableton's own Launchpad X script takes the surface and the system stuff gets
    # out of the way. ERROR always takes it back -- see rig/surface_owner.py.
    ownership = SurfaceOwner(enabled=config.launchpad.handover_to_ableton)

    def ableton_ready() -> bool:
        """
        Ready, not merely RUNNING.

        OBSERVED 2026-08-13: keyed on is_running() alone, the rig handed the surface
        over 9 ms after launching Ableton and then sat dark for the 25 s Live took to
        load -- "theres no signaling making me aware that its booting". The surface
        belonged to a Live that could not paint it yet, which is the worst of both:
        the rig has stopped showing anything and Ableton has not started.

        Gating on the boot gate means the rig keeps the surface, and its animation,
        until Live can actually drive it.
        """
        if not (boot_done["v"] and supervisor is not None and supervisor.launcher.is_running()):
            return False
        # After the first boot, boot_done stays True forever -- so a SET SWITCH would
        # hand the surface over the instant the new process existed, before Live
        # could paint anything, and the loading pulse would never be seen. The
        # readiness signal is the same evidence the boot gate uses, and the launcher
        # clears it before every start, so it answers for switches too.
        signal = supervisor.launcher.ready_signal
        if signal is not None and signal.is_ready():
            return True

        # FALL BACK ON TIME. The signal accelerates handover; it must not gate it.
        #
        # OBSERVED 2026-08-13: the Ablepad Control Surface had come unselected in
        # Live (a force-kill loses Preferences.cfg), so no signal was ever written --
        # and handover never happened. The rig then painted Programmer Mode while
        # Live drove the same device, the Launchpad showed Ableton's view, and the
        # escape hatch never armed because the rig was never released. One missing
        # Remote Script should not cost the whole surface.
        age = _ableton_age_s()
        return age is not None and age >= config.rig.boot_settle_s

    surface.rig_owns_surface = lambda: ownership.rig_owns(machine.state, ableton_ready())

    # The way back to the launcher without quitting Live. MEASURED: with Live
    # driving interface 1, the Launchpad's CUSTOM layout sends pads to interface 2,
    # which the rig keeps open while released. Hold the top-left pad for 2 s.
    escape = EscapeHatch()

    def on_released_pad(note: int, pressed: bool, now_ms: float) -> None:
        escape.feed(note, pressed, now_ms)

    def on_released_tick(now_ms: float) -> None:
        # Every tick, NOT only on input: a hold sends nothing between press and
        # release, so checking on events alone means it can never complete.
        if escape.wants_surface(now_ms):
            ownership.take_back()
            escape.reset()

    surface.on_released_pad = on_released_pad
    surface.on_released_tick = on_released_tick
    if not config.launchpad.handover_to_ableton:
        log.info("launchpad handover disabled — the rig keeps the surface at all times")

    def on_ableton_closed(event: AbletonClosed) -> None:
        """
        Somebody quit Live. Take the surface back and show the launcher.

        This is the way back from a performance, now that the Launchpad belongs to
        Ableton during one. Not an error and not a crash -- the supervisor already
        told those apart by exit code.
        """
        log.info("Ableton closed (%s) — taking the launchpad back", event.set_name)
        ownership.release_override()  # normal rules again; nothing is playing now
        escape.reset()
        # Live may have left the device in DAW mode and its own layout. If the rig
        # never released the surface there is no acquire() to put that right, so say
        # it explicitly -- otherwise the Launchpad keeps showing Ableton's view with
        # Ableton gone.
        service.reassert()
        browser_control.loading_finished()
        browser_control.forget_loaded()
        if machine.state is not RigState.SET_BROWSER:
            machine.transition(RigState.SET_BROWSER, f"ABLETON_CLOSED {event.set_name}")

    bus.subscribe(AbletonClosed, on_ableton_closed)

    # System Mode's pads, made real. They have existed in configs/system.json since
    # the Config Lab and dispatched to nobody -- the same shape SWITCH_MODE was in.
    # Reachable by holding pad 98 in the Set Browser, which is where the rig lands
    # when Ableton is closed, so troubleshooting is one step from the failure.
    if supervisor is not None:
        from windows.power import WindowsPower  # noqa: PLC0415 -- platform import

        dispatcher.register(
            RestartAbleton(
                launcher=supervisor.launcher,
                # Resolved at press time: the loaded set changes, and a command that
                # captured it at wiring time would restart whatever booted.
                current_set=lambda: browser_control.loaded,
            )
        )
        power = WindowsPower()
        dispatcher.register(Reboot(power=power))
        dispatcher.register(Shutdown(power=power))

    def on_system_action(event: ActionRequested) -> None:
        """
        Route named actions to registered commands.

        Unregistered names are IGNORED here rather than raised: every mode config
        emits actions this dispatcher does not own (LOAD_SET, SWITCH_MODE, PAGE_NEXT
        are handled by their own subscribers), and a rig that died on the first
        LOAD_SET would be worse than one that logs an unknown name.
        """
        if not dispatcher.knows(event.action):
            if event.action in UNIMPLEMENTED:
                # A lit pad is a promise. This one cannot be kept yet, so say so out
                # loud rather than let a press vanish -- silence is how you end up
                # pressing it four times on stage wondering if the rig is dead.
                log.warning(
                    "%s (pad %d) is not implemented yet: %s",
                    event.action, event.pad, UNIMPLEMENTED[event.action],
                )
            return
        try:
            dispatcher.dispatch(event.action, {"pad": event.pad, "params": event.params})
        except Exception:  # noqa: BLE001 -- a bad command must not stop the tick loop
            log.exception("command %s failed", event.action)

    bus.subscribe(ActionRequested, on_system_action)

    # The way back IN. Windows auto-connect alone did not rejoin a hotspot that had
    # been switched off and on (OBSERVED 2026-08-13), because it rescans on its own
    # schedule and iOS sleeps Personal Hotspot until something tries to associate.
    # So the rig asks, repeatedly, and only ever while disconnected.
    lifeline = None
    if config.network.lifeline_ssid:
        try:
            from windows.wifi import WindowsWifi  # noqa: PLC0415 -- platform import

            lifeline = WifiLifeline(
                wifi=WindowsWifi(),
                ssid=config.network.lifeline_ssid,
                clock=time.monotonic,
                retry_interval_s=config.network.retry_interval_s,
            )
            log.info(
                "wifi lifeline armed for %r — the rig will keep asking for it "
                "whenever it has no network",
                config.network.lifeline_ssid,
            )
        except Exception as exc:  # noqa: BLE001 -- not on Windows
            log.warning("wifi lifeline unavailable (%s)", exc)
    else:
        log.info("no network.lifeline_ssid configured — no automatic way back in")

    def on_load_requested(event: ActionRequested) -> None:
        """A set is loading, so hand the surface back to Ableton once it is up."""
        if event.action == "LOAD_SET":
            ownership.release_override()
            escape.reset()

    bus.subscribe(ActionRequested, on_load_requested)

    # Makes every config's SWITCH_MODE pad real. Without it the 'Browse' pad in
    # Performance mode arms, fires, and nothing happens -- the Set Browser exists but
    # is unreachable from the surface.
    ModeSwitch(bus=bus, machine=machine)

    browser = SetBrowserService(sets_dir=Path(config.ableton.sets_dir))
    found = browser.rescan()
    log.info("set browser: %d set(s) under %s", found, config.ableton.sets_dir)
    browser_control = SetBrowserControl(
        browser=browser,
        config=library.modes["set-browser"],
        bus=bus,
        machine=machine,
        launcher=supervisor.launcher if supervisor else None,
        supervisor=supervisor,
    )
    # The surface asks for these each tick while the Set Browser is showing. It never
    # learns what a set is; it asks for pad colours and paints them.
    surface.overrides_for["set-browser"] = browser_control.led_overrides

    # A load that never came up: stop the pulse, or the surface goes on claiming to
    # be working while Error Mode is trying to say the opposite. Subscribed HERE
    # rather than beside the other AbletonGaveUp handler because browser_control does
    # not exist yet at that point.
    bus.subscribe(AbletonGaveUp, lambda e: browser_control.loading_finished())
    # NOTHING is marked loaded here. It used to be: boot launched boot_set
    # immediately, so telling the control that avoided a pointless stop-and-relaunch
    # when its pad was pressed.
    #
    # That stopped being true when boot started WAITING for a choice. Nothing has
    # launched yet, so marking boot_set loaded made its pad a silent no-op --
    # OBSERVED 2026-08-13 as "action LOAD_SET from pad 81" immediately followed by
    # "Test is already loaded", with the hold working perfectly and the rig refusing.
    #
    # mark_loaded() now happens where a set is ACTUALLY launched, below.

    def start_ableton_once() -> None:
        """
        Launch the boot set, at most once per rig start.

        Deliberately not retried in a loop. If the launch is refused the reasons are
        real -- a missing exe, a missing set, no audio interface -- and none of them
        get better by trying again 30 times a second. The boot gate is what notices
        Ableton never appeared, and it reports that in its own words after the
        deadline.
        """
        if supervisor is None or launch_state["tried"]:
            return
        launch_state["tried"] = True
        boot_set = Path(config.ableton.boot_set)

        # ADOPT an Ableton that is already up rather than starting a second one.
        # OBSERVED 2026-08-13: restarting the controller with Live running launched a
        # duplicate, the two fought over the EVO's single ASIO device, the newcomer
        # lost and the rig went to ERROR with a perfectly healthy set still playing.
        #
        # This is not a rare state. The controller restarting under a live Ableton is
        # exactly what a Task Scheduler retry, or a crash of the controller alone,
        # produces -- and the boot gate cannot catch it, because the EXISTING
        # instance makes ableton_audio and settled pass instantly.
        existing = _running_ableton()
        if existing is not None:
            supervisor.launcher.adopt(existing)
            # Supervise it, with boot_set as the RECOVERY target. Which set an
            # adopted process has open is not knowable from the process, so a crash
            # restarts the known-good set rather than guessing. Deliberately NOT
            # marked as loaded in the browser: an unnecessary reload is harmless,
            # while a wrong no-op would leave a pad that silently does nothing.
            supervisor.watch(boot_set)
            # A set is already loaded, so there is nothing to choose -- and sitting
            # in the browser would have the rig painting Programmer Mode while Live
            # drives the same device into DAW mode.
            choice_window.skip("Ableton was already running")
            log.warning(
                "Ableton was already running (pid %d) — adopted it instead of "
                "launching a second instance. Only one process can own the EVO's "
                "ASIO device; the loser of that fight looks like broken hardware. "
                "The set it has open is unknown, so a crash will recover to %s.",
                existing, boot_set.name,
            )
            return

        try:
            supervisor.launcher.launch(boot_set)
            supervisor.watch(boot_set)
            # Marked HERE, where it actually happened -- so its pad is a no-op only
            # when the set really is up.
            browser_control.mark_loaded(boot_set)
            log.info("launched Ableton with %s", boot_set)
        except LaunchRefused as exc:
            # Named, once, and then left alone. Boot will fail on its own terms.
            log.error("not launching Ableton: %s", "; ".join(exc.reasons))

    launch_state = {"tried": False}
    boot_done = {"v": False}
    gate = build_boot_gate(config, service, machine)
    def ready_to_choose() -> bool:
        """
        Can the rig actually launch a set right now?

        The Launchpad has to be attached (or there is nothing to press) and the audio
        interface has to be present (or the launcher refuses anyway). Deliberately
        NOT the full boot gate: Ableton cannot be running yet, because nothing has
        been chosen to run.
        """
        if not service.connected:
            return False
        # Let Boot Mode's animation finish. With everything already attached the rig
        # is ready in a third of a second, and a splash nobody sees is not a splash:
        # the rain IS the signal that the rig is starting.
        if surface.intro_playing:
            return False
        try:
            from windows import probes  # noqa: PLC0415 -- platform import

            return bool(probes.usb_device_bound())
        except Exception:  # noqa: BLE001 -- not on Windows; do not block the browser
            return True

    choice_window = BootChoice(
        seconds=config.rig.boot_choice_s,
        clock=time.monotonic,
        machine=machine,
        bus=bus,
        require_choice=config.rig.boot_requires_choice,
        ready=ready_to_choose,
    )

    def lifeline_tick() -> None:
        """Cheap every tick; the lifeline rate-limits itself to its retry interval."""
        if lifeline is not None:
            lifeline.poll()

    def boot_tick() -> None:
        """
        Drive the gate while, and only while, the rig is on the splash screen.

        BOOT is the one state with an automatic exit. Everything else moves because
        a human pressed something.
        """
        # Latched, NOT keyed on state being BOOT. The choice window moves the rig to
        # SET_BROWSER so the sets are visible, and a state check here would then
        # early-return forever and never launch anything at all.
        if boot_done["v"]:
            return

        # A window to choose a set BEFORE anything is launched.
        #
        # Without it the rig launches boot_set the instant it starts, and by the
        # time a human is looking the surface already belongs to Ableton -- so the
        # Set Browser exists and is never reachable at boot, which is exactly what
        # Matt hit on the first cold boot. The default still loads, so an unattended
        # rig behaves as before; this only buys a few seconds for a hand that is
        # already there.
        # Returning here also means the boot GATE is not evaluated, which is what
        # stops its 90 s deadline running while the rig is waiting for a human.
        # Otherwise waiting for a choice would become a boot failure.
        if choice_window.waiting(time.monotonic()):
            return

        start_ableton_once()
        outcome = gate.evaluate()
        if outcome is BootOutcome.COMPLETE:
            boot_done["v"] = True
            if machine.state is RigState.BOOT:
                machine.transition(RigState.SET_BROWSER, "BOOT_COMPLETE")
            return
        elif outcome is BootOutcome.FAILED:
            boot_done["v"] = True
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
        on_tick=[
            boot_tick,
            (lambda: supervisor.poll()) if supervisor else (lambda: None),
            lifeline_tick,
            lambda: surface.tick(time.monotonic() * 1000.0),
        ],
    )
    return controller, surface



#: Actions a config declares that nothing implements, and WHY. Pressing one logs
#: instead of vanishing. Empty is the goal; an entry here is a promise the surface
#: is making that the rig cannot keep.
UNIMPLEMENTED: dict[str, str] = {
    "HOTSPOT_TOGGLE": (
        "the Beelink's Intel AX101 reports 'Hosted network supported: No', so the "
        "adapter cannot run an access point without an internet connection to share "
        "— see docs/ROADMAP.md Phase 6"
    ),
}


def _ableton_age_s() -> float | None:
    """Seconds since Ableton started, or None if it is not running / unknowable."""
    try:
        from windows import probes  # noqa: PLC0415 -- platform import

        proc = probes.process_running()
        if proc is None:
            return None
        return time.time() - proc.create_time()
    except Exception:  # noqa: BLE001
        return None


def _running_ableton() -> int | None:
    """
    PID of an Ableton that is already up, or None. Never raises.

    Lives here rather than in ableton/ because it is a platform probe, and the
    ableton/ layer is deliberately free of Windows imports so it stays testable
    off-rig.
    """
    try:
        from windows import probes  # noqa: PLC0415 — platform import, deliberate

        proc = probes.process_running()
    except Exception as exc:  # noqa: BLE001 — not on Windows, or psutil unhappy
        log.debug("cannot check for a running Ableton (%s) — assuming none", exc)
        return None
    return proc.pid if proc is not None else None


def build_ableton(config: RigConfig, bus: EventBus) -> AbletonSupervisor | None:
    """
    The launcher and its supervisor, or None when we cannot run Ableton at all.

    None on a non-Windows host: psutil can see processes anywhere, but the exe path
    is a Windows path and the audio probe is a registry read. Returning None rather
    than a crippled object keeps the failure at the wiring layer, where it can be
    logged once, instead of scattering `if platform` through the services.
    """
    try:
        from windows.audio import EvoPresence  # noqa: PLC0415 — platform import
    except Exception as exc:  # noqa: BLE001
        log.warning("no audio-presence probe (%s) — Ableton will not be launched", exc)
        return None

    if not config.ableton.boot_set:
        log.warning(
            "ableton.boot_set is empty — the rig will NOT start Ableton itself. "
            "Boot can only complete if something else already did."
        )
        return None

    recovery = None
    if config.ableton.appdata_dir and config.ableton.crash_quarantine_dir:
        recovery = CrashRecovery(
            ableton_appdata=Path(config.ableton.appdata_dir),
            quarantine=Path(config.ableton.crash_quarantine_dir),
        )
        pending = len(recovery.pending())
        if pending:
            log.info(
                "%d Live crash journal(s) waiting — they will be moved aside before "
                "launch so the recovery dialog cannot block a headless boot",
                pending,
            )
    else:
        log.warning(
            "no ableton.appdata_dir/crash_quarantine_dir configured — Live may show "
            "its 'recover the last session?' dialog, which nothing can answer on a rig "
            "with no keyboard"
        )

    # One instance, shared: the launcher CLEARS it before each start, and the
    # handover rule READS it to know when Live can actually drive the surface.
    ready_signal = (
        ReadySignal(Path(config.ableton.ready_signal_path))
        if config.ableton.ready_signal_path
        else None
    )
    launcher = AbletonLauncher(
        exe=Path(config.ableton.exe),
        processes=PsutilProcessController(),
        audio=EvoPresence(),
        recovery=recovery,
        ready_signal=ready_signal,
    )
    budget = RestartBudget(
        # ONE automatic restart. A restart that crashes again quickly means something
        # is genuinely wrong, and further attempts would thrash the machine mid-gig
        # while the performer watches the LEDs strobe. Roadmap Phase 5.
        max_attempts=config.ableton.restart_attempts,
        # How long a run must survive before the budget refills. This is what
        # separates a transient hiccup from a set that is cursed tonight.
        stable_s=config.ableton.restart_stable_s,
        clock=time.monotonic,
    )
    def left_crash_journal() -> bool:
        """
        Did Live leave a crash journal behind? Its own statement about how it ended.
        Only consulted when exit_code() cannot answer -- i.e. for an adopted process.
        """
        return bool(recovery is not None and recovery.pending())

    supervisor = AbletonSupervisor(
        launcher=launcher,
        budget=budget,
        bus=bus,
        left_crash_journal=left_crash_journal if recovery is not None else None,
    )

    # A crash that exhausts the restart budget is the rig's problem, not the
    # supervisor's: it publishes and the controller decides. Error Mode, naming it.
    bus.subscribe(
        AbletonGaveUp,
        lambda e: machine_ref["m"].transition(RigState.ERROR, f"Ableton gave up: {e.set_name}"),
    )
    return supervisor


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
        #
        # MEASURED 2026-08-13: even cached, each refresh overruns one tick -- 7
        # overruns in 13 s at a 2 s TTL. That is ACCEPTED rather than fixed, because
        # boot_tick() returns immediately once the state leaves BOOT, so the cost is
        # confined to the splash screen where nothing is being performed. A 13 ms
        # hitch in LED painting while waiting for Ableton is invisible; the same
        # hitch during a set would not be. A longer TTL trades boot responsiveness
        # for fewer hitches and changes nothing that matters.
        ableton_proc = probes.cached(lambda: probes.process_running(), ttl_s=1.0)

        # Once Ableton has the ASIO driver mapped it keeps it for the life of the
        # process, so this answer is monotonic per pid: False may become True, True
        # never goes back. Latch it and stop probing.
        #
        # MEASURED 2026-08-13: without the latch, a 90 s boot wait cost 45 tick
        # overruns -- one every two seconds, each a 13 ms memory_maps call re-asking
        # a question already answered. With it, one probe per Ableton process.
        latched: dict[int, bool] = {}

        def ableton_bound() -> bool:
            proc = ableton_proc()
            if proc is None:
                latched.clear()
                return False
            pid = proc.pid
            if latched.get(pid):
                return True
            # Only pay the 13 ms while the answer is still False -- which is exactly
            # the window where it might change.
            latched[pid] = probes.process_has_module(proc, probes.AUDIENT_ASIO_MODULE)
            return latched[pid]

        bound = probes.cached(ableton_bound, ttl_s=1.0)
        readiness = ReadinessTracker(
            settle_s=config.rig.boot_settle_s,
            floor_s=config.rig.boot_floor_s,
            clock=time.monotonic,
        )
        signal = (
            ReadySignal(Path(config.ableton.ready_signal_path))
            if config.ableton.ready_signal_path
            else None
        )
        if signal is None:
            log.warning(
                "no ableton.ready_signal_path configured — boot will wait out the full "
                "%.0fs settle timer instead of asking Live when its set is loaded",
                config.rig.boot_settle_s,
            )
        expected = Path(config.ableton.boot_set) if config.ableton.boot_set else None
        started = {"seen": False}
        confirmed_once = {"said": False}
        last_state: dict[str, object] = {"value": None}

        def settled_detail() -> str:
            """
            Why the settle check passed -- confirmation or timer. The gate labels this
            check GUESS because that is its worst case, so the detail is the only place
            the difference is visible, and it is the difference the whole readiness
            signal exists to create.
            """
            if last_state["value"] is Readiness.CONFIRMED_READY:
                return "Live confirmed the set is loaded (not a guess)"
            if last_state["value"] is Readiness.ASSUMED_READY:
                return (
                    "settle timer elapsed, no confirmation from Live — is the Ablepad "
                    "Remote Script still installed? (remote_script/README.md)"
                )
            return "still settling"

        def settled() -> bool:
            """
            Has Ableton had long enough to load its set?

            Measured from the PROCESS's own start time, not from when this gate first
            noticed it. The rig controller can restart -- a crash, a Task Scheduler
            retry, a manual run -- while Ableton has been up for an hour. Timing from
            "when we looked" would make every one of those restarts sit on the splash
            screen for the full settle period waiting for something that finished long
            ago.

            Still a guess either way: process age is not set-loaded. It is just a less
            wrong guess, and it is free -- psutil already has create_time.
            """
            proc = ableton_proc()
            if proc is None:
                started["seen"] = False
                readiness.mark_gone()
                return False
            try:
                age = time.time() - proc.create_time()
            except Exception:  # noqa: BLE001 -- process vanished mid-check
                age = 0.0
            if age >= config.rig.boot_settle_s:
                return True
            if not started["seen"]:
                started["seen"] = True
                readiness.mark_started()
            if signal is not None and signal.is_ready(expected):
                # Live said so. Still gated by floor_s inside the tracker.
                readiness.mark_confirmed_ready()
            state = readiness.state(process_running=True)
            last_state["value"] = state
            if state is Readiness.CONFIRMED_READY and not confirmed_once["said"]:
                confirmed_once["said"] = True
                log.info(
                    "Live confirmed its set is loaded — boot did not have to wait out "
                    "the %.0fs settle timer",
                    config.rig.boot_settle_s,
                )
            return state in (Readiness.ASSUMED_READY, Readiness.CONFIRMED_READY)

        checks = build_checks(
            launchpad_connected=lambda: service.connected,
            evo_present=lambda: probes.usb_device_bound(),
            ableton_running=lambda: ableton_proc() is not None,
            ableton_bound_to_evo=lambda: bool(bound()),
            ableton_settled=settled,
            settled_detail=settled_detail,
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
