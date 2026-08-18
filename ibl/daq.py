"""
The data acquisition side.

DaqWorker lives on its own QThread so a slow or unhappy LabJack can never
freeze the window.  It ticks on a QTimer, reads AIN0..AIN13 in one call,
converts the volts to Torr, and emits the batch.

Flow:
    MainWindow  --start()-->  QThread  -->  DaqWorker._tick()
    DaqWorker   --sample-->   MainWindow (table, plot, CSV)
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from .channels import CHANNELS, AIN_NAMES
from .config import Settings
from .conversion import convert, Reading

# labjack-ljm is only needed for real hardware.  Import it lazily so the
# program still starts (in Simulation mode) on a PC without the LJM driver.
try:
    from labjack import ljm  # type: ignore
    LJM_AVAILABLE = True
    LJM_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - depends on the machine
    ljm = None  # type: ignore
    LJM_AVAILABLE = False
    LJM_IMPORT_ERROR = str(exc)


class Sample:
    """One sweep of all 14 channels."""
    __slots__ = ("timestamp", "readings")

    def __init__(self, timestamp: float, readings: list[Reading]):
        self.timestamp = timestamp
        self.readings = readings

    def by_ain(self) -> dict[int, Reading]:
        return {r.ain: r for r in self.readings}


class _Simulator:
    """Plausible fake voltages so the GUI can be exercised with no T7 plugged in."""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.phase = [random.random() * 6.28 for _ in CHANNELS]

    def read(self) -> list[float]:
        t = time.time() - self.t0
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


class DaqWorker(QObject):
    """Runs inside the acquisition QThread."""

    sample = Signal(object)        # Sample
    status = Signal(str)           # human readable status line
    connection_changed = Signal(bool)

    def __init__(self, settings: Settings):
        super().__init__()
        self._settings = settings
        self._handle = None
        self._sim: _Simulator | None = None
        self._timer: QTimer | None = None
        self._fail_count = 0

    # -- lifecycle ----------------------------------------------------------
    @Slot()
    def start(self) -> None:
        """Called once the thread is running."""
        self._timer = QTimer()
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._open()
        self._apply_interval()
        self._timer.start()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._close()

    @Slot(object)
    def update_settings(self, settings: Settings) -> None:
        """Live-apply GUI changes.  Reopens the device if the link changed."""
        relink = (
            settings.simulate != self._settings.simulate
            or settings.connection != self._settings.connection
            or settings.identifier != self._settings.identifier
            or settings.resolution_index != self._settings.resolution_index
        )
        self._settings = settings
        self._apply_interval()
        if relink:
            self._close()
            self._open()

    def _apply_interval(self) -> None:
        if self._timer is None:
            return
        hz = max(0.05, min(float(self._settings.sample_hz), 20.0))
        self._timer.setInterval(int(round(1000.0 / hz)))

    # -- device -------------------------------------------------------------
    def _open(self) -> None:
        self._fail_count = 0

        if self._settings.simulate:
            self._sim = _Simulator()
            self._handle = None
            self.status.emit("Simulation mode - no hardware in use")
            self.connection_changed.emit(True)
            return

        self._sim = None
        if not LJM_AVAILABLE:
            self.status.emit(
                "LabJack LJM library not found. Install the LJM software from "
                "labjack.com, or tick Simulation mode. (" + LJM_IMPORT_ERROR + ")"
            )
            self.connection_changed.emit(False)
            return

        try:
            self._handle = ljm.openS(
                "T7", self._settings.connection, self._settings.identifier
            )
            info = ljm.getHandleInfo(self._handle)
            serial = info[2]

            # Single-ended, +/-10 V range, chosen resolution, on every AIN we use.
            ljm.eWriteNames(
                self._handle,
                3,
                ["AIN_ALL_NEGATIVE_CH", "AIN_ALL_RANGE", "AIN_ALL_RESOLUTION_INDEX"],
                [199, 10.0, float(self._settings.resolution_index)],
            )
            self.status.emit(
                f"Connected to T7 serial {serial} over {self._settings.connection}"
            )
            self.connection_changed.emit(True)
        except Exception as exc:
            self._handle = None
            self.status.emit(f"Could not open LabJack T7: {exc}")
            self.connection_changed.emit(False)

    def _close(self) -> None:
        if self._handle is not None and LJM_AVAILABLE:
            try:
                ljm.close(self._handle)
            except Exception:
                pass
        self._handle = None
        self._sim = None
        self.connection_changed.emit(False)

    # -- the loop -----------------------------------------------------------
    @Slot()
    def _tick(self) -> None:
        now = time.time()

        if self._sim is not None:
            volts = self._sim.read()
        elif self._handle is not None:
            try:
                volts = ljm.eReadNames(self._handle, len(AIN_NAMES), AIN_NAMES)
                self._fail_count = 0
            except Exception as exc:
                self._fail_count += 1
                self.status.emit(f"Read error ({self._fail_count}): {exc}")
                if self._fail_count >= 5:
                    self.status.emit("Lost the T7 - trying to reconnect...")
                    self._close()
                    self._open()
                return
        else:
            return  # not connected; nothing to do this tick

        fault_v = float(self._settings.fault_volts)
        readings = [
            convert(ch.ain, float(volts[i]), ch.is_ion, fault_v)
            for i, ch in enumerate(CHANNELS)
        ]
        self.sample.emit(Sample(now, readings))
