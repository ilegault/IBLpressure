"""Acquisition: the whole T7 conversation, with no Qt, so it can run in a child process.

WHY THIS EXISTS
---------------
LJM is a DLL loaded once per process; a wedged LJM state survives every in-app retry, and one
stuck LJM call used to block the window's thread (ADR 0003). So the T7 conversation lives
here and runs in a child process started by the Supervisor (ticket 19). The window process
keeps History, plot, Daily CSV, LinkMonitor and the Link log, and never waits on LJM.

`Acquisition` turns each command and each `tick(now)` into a list of events. `run` is the
thin loop that moves them over two queues. Messages are plain, picklable dataclasses:

    commands (window -> child)            events (child -> window)
    Start(settings)                       Alive()            at least every HEARTBEAT_S
    ApplySettings(settings)               LinkUp(description, ljm_version, firmware, warning)
    Reopen()                              LinkDown(reason)   an open failed
    LibraryReset()                        Lost(reason)       3 reads in a row failed; closed
    Quit()                                ReadError(message), SampleReady(sample)

THE CHILD NEVER RETRIES ON ITS OWN. After 3 failed reads it closes the handle and reports
`Lost`; it opens again only when told: `Start`, `Reopen`, `LibraryReset`, or an
`ApplySettings` that changes connection, identifier, resolution or Simulation. Only the
Supervisor, through Escalation, decides what happens next.

Every method takes `now` in seconds. `run` is the only place the wall clock is read.
"""
from __future__ import annotations

import logging
import math
import queue
import random
import time
from dataclasses import dataclass

from .channels import AIN_NAMES, CHANNELS
from .config import HEARTBEAT_S, MAX_SAMPLE_HZ, MIN_SAMPLE_HZ, Settings
from .conversion import convert
from .model import Sample

# labjack-ljm is only needed for real hardware.  Import it lazily so the
# program still starts (in Simulation mode) on a PC without the LJM driver.
try:
    from labjack import ljm  # type: ignore
    LJM_AVAILABLE = True
    LJM_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - depends on the machine  # noqa: BLE001 - any failure is reported or handled here
    ljm = None  # type: ignore
    LJM_AVAILABLE = False
    LJM_IMPORT_ERROR = str(exc)

_log = logging.getLogger(__name__)

READS_BEFORE_LOST = 3


# --- messages ---------------------------------------------------------------
@dataclass(frozen=True)
class Start:
    settings: Settings


@dataclass(frozen=True)
class ApplySettings:
    settings: Settings


@dataclass(frozen=True)
class Reopen:
    pass


@dataclass(frozen=True)
class LibraryReset:
    pass


@dataclass(frozen=True)
class Quit:
    pass


@dataclass(frozen=True)
class Alive:
    pass


@dataclass(frozen=True)
class LinkUp:
    description: str      # "T7 #<serial> over <connection>" or "Simulation mode"
    ljm_version: str
    firmware: str
    warning: str          # something worth showing that did not stop the Link, else ""


@dataclass(frozen=True)
class LinkDown:
    reason: str


@dataclass(frozen=True)
class Lost:
    reason: str


@dataclass(frozen=True)
class ReadError:
    message: str


@dataclass(frozen=True)
class SampleReady:
    sample: Sample


class _Simulator:
    """Plausible fake voltages so the GUI can be exercised with no T7 plugged in."""

    def __init__(self, now: float) -> None:
        self.t0 = now
        self.phase = [random.random() * 6.28 for _ in CHANNELS]

    def read(self, now: float) -> list[float]:
        t = now - self.t0
        volts: list[float] = []
        for i, ch in enumerate(CHANNELS):
            wobble = math.sin(t / 40.0 + self.phase[i])
            if ch.is_ion:
                # centre near 1e-3 Torr (7 V), drifting a decade either way
                v = 7.0 + 0.8 * wobble + random.gauss(0, 0.004)
                v = min(max(v, 1.0), 10.0)
            else:
                # A pumped beamline sits at the bottom of the Convectron's
                # useful range, a few mTorr, i.e. around 0.40-0.46 V.
                v = 0.435 + 0.030 * wobble + random.gauss(0, 0.0006)
                v = min(max(v, 0.376), 5.65)
            volts.append(v)
        # Every so often, fake a gauge fault on SNICS IG so the red row is testable
        if int(t) % 120 < 6:
            volts[0] = 10.9
        return volts


class Acquisition:
    def __init__(self) -> None:
        self._settings = Settings()
        self._handle = None
        self._sim: _Simulator | None = None
        self._started = False             # Start received, Quit not yet
        self._fail_count = 0
        self._next_read = 0.0
        self._last_read_at: float | None = None
        self._last_event_at = -math.inf   # when we last returned any event
        self.finished = False             # Quit handled: `run` returns

    # --- commands ---------------------------------------------------------
    def handle(self, command: object, now: float) -> list[object]:
        events = self._dispatch(command, now)
        if events:
            self._last_event_at = now
        return events

    def _dispatch(self, command: object, now: float) -> list[object]:
        if isinstance(command, Start):
            self._settings = command.settings
            self._started = True
            return self._reopen(now)
        if isinstance(command, ApplySettings):
            return self._apply_settings(command.settings, now)
        if isinstance(command, Reopen):
            return self._reopen(now)
        if isinstance(command, LibraryReset):
            return self._library_reset(now)
        if isinstance(command, Quit):
            self._quit()
            return []
        _log.warning("Acquisition ignored an unknown command: %r", command)
        return []

    def _apply_settings(self, settings: Settings, now: float) -> list[object]:
        old = self._settings
        relink = (
            settings.simulate != old.simulate
            or settings.connection != old.connection
            or settings.identifier != old.identifier
            or settings.resolution_index != old.resolution_index
        )
        self._settings = settings
        if relink and self._started:
            return self._reopen(now)
        if self._last_read_at is not None:
            # A new sample rate takes effect from the last read, as the old QTimer's did.
            self._next_read = self._last_read_at + self._interval()
        return []

    def _interval(self) -> float:
        hz = max(MIN_SAMPLE_HZ, min(float(self._settings.sample_hz), MAX_SAMPLE_HZ))
        return 1.0 / hz

    def _reopen(self, now: float) -> list[object]:
        self._close()
        return self._open(now)

    def _library_reset(self, now: float) -> list[object]:
        self._close()
        reset_error = ""
        if LJM_AVAILABLE and not self._settings.simulate:
            try:
                ljm.closeAll()
            except Exception as exc:  # noqa: BLE001 - reported on the LinkUp warning below
                reset_error = f"Library reset failed: {exc}"
                _log.warning(reset_error)
        events = self._open(now)
        if reset_error:
            events = [
                LinkUp(e.description, e.ljm_version, e.firmware,
                       "; ".join(w for w in (e.warning, reset_error) if w))
                if isinstance(e, LinkUp) else e
                for e in events
            ]
        return events

    def _quit(self) -> None:
        self._started = False
        self._close()
        if LJM_AVAILABLE and not self._settings.simulate:
            try:
                ljm.closeAll()
            except Exception as exc:  # noqa: BLE001 - we are exiting; leave a trace in the log
                _log.warning("ljm.closeAll failed at quit: %s", exc)
        self.finished = True

    # --- device -----------------------------------------------------------
    def _open(self, now: float) -> list[object]:
        self._fail_count = 0
        self._next_read = now               # first Sample as soon as the next tick
        self._last_read_at = None

        if self._settings.simulate:
            self._sim = _Simulator(now)
            self._handle = None
            return [LinkUp("Simulation mode", "", "", "")]

        self._sim = None
        if not LJM_AVAILABLE:
            return [LinkDown(f"LabJack LJM library not found ({LJM_IMPORT_ERROR})")]

        handle = None
        try:
            handle = ljm.openS("T7", self._settings.connection, self._settings.identifier)
            info = ljm.getHandleInfo(handle)
            serial = info[2]

            # Single-ended, +/-10 V range, chosen resolution, on every AIN we use.
            ljm.eWriteNames(
                handle,
                3,
                ["AIN_ALL_NEGATIVE_CH", "AIN_ALL_RANGE", "AIN_ALL_RESOLUTION_INDEX"],
                [199, 10.0, float(self._settings.resolution_index)],
            )
            self._handle = handle
            version, firmware, warning = self._describe(handle)
            return [LinkUp(f"T7 #{serial} over {self._settings.connection}",
                           version, firmware, warning)]
        except Exception as exc:  # noqa: BLE001 - any failure is reported or handled here
            self._handle = None
            if handle is not None:
                self._close_handle(handle)
            return [LinkDown(str(exc))]

    def _describe(self, handle) -> tuple[str, str, str]:
        """LJM version, T7 firmware and a warning for things that did not stop the Link."""
        try:
            version = f"{float(ljm.readLibraryConfigS('LJM_LIBRARY_VERSION')):.4f}"
            firmware = f"{float(ljm.eReadName(handle, 'FIRMWARE_VERSION')):.4f}"
        except Exception as exc:  # noqa: BLE001 - informational only; reported on the warning
            return "", "", f"Version info unavailable: {exc}"
        return version, firmware, ""

    def _close(self) -> None:
        handle, self._handle = self._handle, None
        self._sim = None
        if handle is not None:
            self._close_handle(handle)

    @staticmethod
    def _close_handle(handle) -> None:
        if not LJM_AVAILABLE:
            return
        try:
            ljm.close(handle)
        except Exception as exc:  # noqa: BLE001 - nothing more to do; leave a trace in the log
            _log.warning("ljm.close failed: %s", exc)

    # --- the loop ---------------------------------------------------------
    def tick(self, now: float) -> list[object]:
        events: list[object] = []
        if now >= self._next_read and (self._sim is not None or self._handle is not None):
            events.extend(self._read(now))
        if not events and now - self._last_event_at >= HEARTBEAT_S:
            events.append(Alive())
        if events:
            self._last_event_at = now
        return events

    def _read(self, now: float) -> list[object]:
        self._last_read_at = now
        self._next_read = now + self._interval()

        if self._sim is not None:
            volts = self._sim.read(now)
        else:
            try:
                volts = ljm.eReadNames(self._handle, len(AIN_NAMES), AIN_NAMES)
                self._fail_count = 0
            except Exception as exc:  # noqa: BLE001 - any failure is reported or handled here
                self._fail_count += 1
                events: list[object] = [ReadError(str(exc))]
                if self._fail_count >= READS_BEFORE_LOST:
                    self._close()
                    events.append(Lost(str(exc)))
                return events

        fault_v = float(self._settings.fault_volts)
        readings = [
            convert(ch.ain, float(volts[i]), ch.is_ion, fault_v)
            for i, ch in enumerate(CHANNELS)
        ]
        return [SampleReady(Sample(now, readings))]


def run(commands, events, poll_s: float = 0.05, clock=time.time) -> None:
    """Child-process main loop: commands in, events out, until Quit."""
    acq = Acquisition()
    while not acq.finished:
        out: list[object] = []
        try:
            command = commands.get(timeout=poll_s)
        except queue.Empty:
            command = None
        now = clock()
        if command is not None:
            out.extend(acq.handle(command, now))
        if not acq.finished:
            out.extend(acq.tick(now))
        for event in out:
            events.put(event)
