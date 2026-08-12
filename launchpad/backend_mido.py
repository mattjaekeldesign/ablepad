"""
The real MIDI backend. The ONLY place in the application that imports mido.

LAYER: drivers, adapter. Implements launchpad.device.MidiBackend against mido +
python-rtmidi. Swapping to a different transport (or to Bome, if Phase 8 goes that
way) means writing a sibling of this file and changing one injection site.

Kept separate from device.py so the driver's logic — the connect sequence, the
restore contract, event decoding — stays testable with a fake and no MIDI stack
installed at all.
"""

from __future__ import annotations

import logging
from typing import Sequence

log = logging.getLogger(__name__)


class MidoBackend:
    """mido + python-rtmidi. Imports lazily so importing this module never fails."""

    def __init__(self) -> None:
        try:
            import mido  # noqa: PLC0415 — deliberate: absence must be a clear error
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "mido is not installed. pip install -r requirements.txt"
            ) from exc
        self._mido = mido

    def input_names(self) -> list[str]:
        return list(self._mido.get_input_names())

    def output_names(self) -> list[str]:
        return list(self._mido.get_output_names())

    def open_input(self, name: str):
        return self._mido.open_input(name)

    def open_output(self, name: str):
        return self._mido.open_output(name)

    def sysex(self, payload: Sequence[int]):
        return self._mido.Message("sysex", data=list(payload))

    def deliver_sysex(self, port) -> None:
        """
        Stop rtmidi throwing SysEx replies away.

        RtMidiIn defaults to ignoreTypes(sysex=True, timing=True, active_sense=True)
        and mido does not clear it. MEASURED consequence 2026-08-12: the device
        inquiry reply never arrived, so a working Launchpad reported "no reply".
        Notes and CCs were unaffected, which is what made it look like hardware.
        Every readback command in the manual's table is dead without this.
        """
        rt = getattr(port, "_rt", None) or getattr(port, "_port", None)
        if rt is None:
            log.warning("could not reach the rtmidi object; SysEx replies may be dropped")
            return
        try:
            rt.ignore_types(sysex=False, timing=False, active_sense=False)
        except Exception as exc:  # noqa: BLE001 — a different backend may not have it
            log.warning("could not clear rtmidi ignore_types: %s", exc)
