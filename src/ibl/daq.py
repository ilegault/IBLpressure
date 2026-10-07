"""
The data acquisition side — command-response mode (NOT stream).

DaqWorker lives on its own QThread so a slow or unhappy LabJack can never
freeze the window.  It ticks on a QTimer, reads AIN0..AIN13 in one
ljm.eReadNames() call (command-response), converts the volts to Torr,
and emits the batch.

Command-response is more reliable than stream mode for this application:
each tick sends one request and waits for one reply, so there are no
streaming buffers to overflow and the device link recovers naturally from
brief USB or Ethernet glitches.

Flow:
    MainWindow  --start()-->  QThread  -->  DaqWorker._tick()
    DaqWorker   --sample-->   MainWindow (table, plot, CSV)
    DaqWorker   --link_up / link_down / reconnecting / read_error-->  MainWindow
                --> LinkMonitor, the one place that turns these events (and the
                    clock) into the status dot and the status line.

The worker only *reports* what happened, as structured events; it never words
the status line itself.  It never shares a mutable object with the window: it
gets a copy of Settings each time they change.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from .acquisition import _Simulator
from .channels import AIN_NAMES, CHANNELS
from .config import MAX_SAMPLE_HZ, MIN_SAMPLE_HZ, Settings
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


class DaqWorker(QObject):
    """Runs inside the acquisition QThread."""

    sample = Signal(object)        # Sample
    link_up = Signal(str)          # "T7 #<serial> over <connection>" or "Simulation mode"
    link_down = Signal(str)        # reason the device could not be opened
    reconnecting = Signal(int)     # attempt number, sent before each reopen after a loss
    read_error = Signal(str)       # one failed read; the link may still recover

    def __init__(self, settings: Settings):
        super().__init__()
        self._settings = settings
        self._handle = None
        self._sim: _Simulator | None = None
        self._timer: QTimer | None = None
        self._fail_count = 0
        self._attempt = 0                 # reconnect attempts since the link was last up
        self._reconnect_at: float = 0.0   # timestamp of last _open() attempt
        self._running = False             # True only between start() and stop()

    # -- lifecycle ----------------------------------------------------------
    @Slot()
    def start(self) -> None:
        """Open the device and begin sampling.

        Nothing calls this at startup - only the Connect button does.  It is
        safe to call twice: the sampling timer is created once and reused, so
        repeated Connect presses can never stack up timers.
        """
        if self._running:
            return
        self._running = True
        self._attempt = 0
        if self._timer is None:
            self._timer = QTimer()
            self._timer.setTimerType(Qt.PreciseTimer)
            self._timer.timeout.connect(self._tick)
        self._open()
        self._apply_interval()
        self._timer.start()

    @Slot()
    def stop(self) -> None:
        self._running = False
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
        if relink and self._running:
            self._close()
            self._open()

    def _apply_interval(self) -> None:
        if self._timer is None:
            return
        hz = max(MIN_SAMPLE_HZ, min(float(self._settings.sample_hz), MAX_SAMPLE_HZ))
        self._timer.setInterval(round(1000.0 / hz))

    # -- device -------------------------------------------------------------
    def _open(self) -> None:
        self._fail_count = 0
        self._reconnect_at = time.time()  # throttle future auto-reconnect attempts

        if self._settings.simulate:
            self._sim = _Simulator(time.time())
            self._handle = None
            self._attempt = 0
            self.link_up.emit("Simulation mode")
            return

        self._sim = None
        if not LJM_AVAILABLE:
            self.link_down.emit(f"LabJack LJM library not found ({LJM_IMPORT_ERROR})")
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
            self._attempt = 0
            self.link_up.emit(f"T7 #{serial} over {self._settings.connection}")
        except Exception as exc:  # noqa: BLE001 - any failure is reported or handled here
            self._handle = None
            self.link_down.emit(str(exc))

    def _close(self) -> None:
        if self._handle is not None and LJM_AVAILABLE:
            try:
                ljm.close(self._handle)
            except Exception:  # noqa: BLE001, S110 - pre-existing best-effort cleanup, error ignored
                pass
            finally:
                self._handle = None
        self._sim = None

    def cleanup(self) -> None:
        """Final teardown — call once at application exit.

        Closes this worker's handle *and* calls ljm.closeAll() so the LJM
        library releases every device handle in the process.  This prevents
        the "phantom open handle" problem where a stale handle from a
        previous session makes the next launch fail to connect.
        """
        if self._timer is not None:
            self._timer.stop()
        self._running = False
        if self._handle is not None and LJM_AVAILABLE:
            try:
                ljm.close(self._handle)
            except Exception:  # noqa: BLE001, S110 - pre-existing best-effort cleanup, error ignored
                pass
            self._handle = None
        if LJM_AVAILABLE:
            try:
                ljm.closeAll()
            except Exception:  # noqa: BLE001, S110 - pre-existing best-effort cleanup, error ignored
                pass
        self._sim = None

    # -- the loop -----------------------------------------------------------
    @Slot()
    def _tick(self) -> None:
        now = time.time()

        if self._sim is not None:
            volts = self._sim.read(now)
        elif self._handle is not None:
            try:
                volts = ljm.eReadNames(self._handle, len(AIN_NAMES), AIN_NAMES)
                self._fail_count = 0
            except Exception as exc:  # noqa: BLE001 - any failure is reported or handled here
                self._fail_count += 1
                self.read_error.emit(str(exc))
                if self._fail_count >= 3:
                    self._attempt += 1
                    self.reconnecting.emit(self._attempt)
                    self._close()
                    # Brief pause before reopening so the OS can release the
                    # USB/Ethernet handle cleanly.
                    time.sleep(0.5)
                    self._open()
                return
        else:
            # Not connected.  If the LJM driver is present and we are not in
            # simulation mode, retry the connection every 5 seconds so a
            # USB glitch or a briefly-missing T7 recovers automatically.
            if (self._running and LJM_AVAILABLE and not self._settings.simulate
                    and now - self._reconnect_at >= 5.0):
                self._attempt += 1
                self.reconnecting.emit(self._attempt)
                self._open()
            return

        fault_v = float(self._settings.fault_volts)
        readings = [
            convert(ch.ain, float(volts[i]), ch.is_ion, fault_v)
            for i, ch in enumerate(CHANNELS)
        ]
        self.sample.emit(Sample(now, readings))
