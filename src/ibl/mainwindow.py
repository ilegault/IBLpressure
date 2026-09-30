"""
The one and only window: it wires the panels to the worker, the LinkMonitor,
the History and the CSV logger.  The widgets live in `ibl.ui`.

    TopBar        connect, simulation, dot, status text, CSV label
    PlotPanel     | TablePanel (14 gauges, 7 rows)
    SettingsPanel (collapsible)

Link state (the dot and the status line):

    DaqWorker --link_up/link_down/reconnecting/read_error--> MainWindow
    MainWindow --forwards each, with the clock--> LinkMonitor (ibl.link)
    every 500 ms and after every event: _render_link() asks LinkMonitor.view(now)
    and draws the dot colour and the status text from that one LinkView.

A number is only shown in a pressure cell while the Link is Live; otherwise the
cell shows STALE and the last value moves to the Status column with its age.
Settings changes take effect immediately and are remembered in settings.json.
"""
from __future__ import annotations

import dataclasses
import os
import sys
import time

import numpy as np
from PySide6.QtCore import QMetaObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from . import __version__, driver
from .channels import CHANNELS
from .config import Settings
from .csvlogger import DailyCsvLogger, load_recent_history
from .daq import DaqWorker
from .history import History
from .link import LinkMonitor, LinkState
from .model import Sample
from .theme import DARK_THEME, LIGHT_THEME
from .ui.plot_panel import PlotPanel
from .ui.settings_panel import SettingsPanel
from .ui.table_panel import TablePanel
from .ui.topbar import TopBar


class MainWindow(QMainWindow):
    settings_changed = Signal(object)
    start_worker = Signal()
    stop_worker = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.history = History(len(CHANNELS))
        self._chan_index = {c.ain: i for i, c in enumerate(CHANNELS)}
        self.logger = DailyCsvLogger(settings.csv_dir, settings.csv_include_voltages)
        self._last_csv = 0.0
        self._now = time.time                   # the clock; tests replace it
        self.link = LinkMonitor(settings.late_after_samples, settings.sample_hz)
        self._last_sample: Sample | None = None  # newest Sample, for the STALE display
        self._last_sample_now = 0.0              # window clock when it arrived
        self._driver_msg = ""                    # LJM-missing text, shown only while DOWN
        self._settings_problem = ""              # last settings save failure, until one succeeds
        self._csv_rows = 0
        self._building = True
        # True once the user has pressed Connect.  Nothing connects on its own.
        self._link_wanted = False

        self.setWindowTitle(f"IBL Pressure  -  Beamline Vacuum Monitor  v{__version__}")
        self.resize(1500, 880)

        self._build_ui()
        self._load_settings_into_panels()
        self._building = False

        self._reload_history_from_csv()
        self._start_worker()

        # Ages the status line and the STALE table even when no event arrives.
        self._link_timer = QTimer(self, interval=500)
        self._link_timer.timeout.connect(self._render_link)
        self._link_timer.start()
        self._render_link()

    def _build_ui(self) -> None:
        self.topbar = TopBar()
        self.plot_panel = PlotPanel()
        self.table_panel = TablePanel()
        self.settings_panel = SettingsPanel()

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)
        root.addWidget(self.topbar)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.plot_panel)
        splitter.addWidget(self.table_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 500])
        root.addWidget(splitter, 1)
        root.addWidget(self.settings_panel)
        self.setCentralWidget(central)

        self.topbar.connect_clicked.connect(self._toggle_connection)
        self.topbar.install_clicked.connect(self._install_driver)
        self.topbar.open_log_clicked.connect(
            lambda: self.topbar.open_folder(self.settings.csv_dir))
        self.topbar.chk_sim.toggled.connect(self._on_widget_changed)
        self.topbar.chk_dark.toggled.connect(self._on_dark_toggled)
        self.plot_panel.span_changed.connect(self._on_widget_changed)
        self.plot_panel.clear_requested.connect(self._clear_history)
        self.table_panel.plotted_changed.connect(self._on_plotted_changed)
        self.settings_panel.changed.connect(self._on_widget_changed)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

    # -- Settings <-> panels
    def _load_settings_into_panels(self) -> None:
        s = self.settings
        self.topbar.chk_sim.setChecked(s.simulate)
        self.topbar.chk_dark.setChecked(s.dark_mode)
        self._apply_theme()
        self.settings_panel.load(s)
        self.plot_panel.set_span(s.plot_window_s)
        self.table_panel.load_plotted(s.plotted_ains)
        self.plot_panel.set_plotted(s.plotted_ains)
        self._apply_appearance()

    def _harvest_panels(self) -> Settings:
        s = self.settings
        s.simulate = self.topbar.chk_sim.isChecked()
        self.settings_panel.harvest(s)
        s.plot_window_s = self.plot_panel.span_s()
        s.plotted_ains = self.table_panel.plotted_ains()
        return s

    def _apply_appearance(self) -> None:
        self.table_panel.apply_appearance(self.settings)
        self.plot_panel.apply_appearance(self.settings)

    def _save_settings(self) -> None:
        self._settings_problem = self.settings.save()
        if self._settings_problem:
            print(self._settings_problem, file=sys.stderr)

    def _on_widget_changed(self, *_args) -> None:
        if self._building:
            return
        s = self._harvest_panels()
        self.settings_panel.update_previews(s)
        self._save_settings()
        self.link.configure(s.late_after_samples, s.sample_hz)
        self._render_link()
        self.logger.reconfigure(s.csv_dir, s.csv_include_voltages)
        self._apply_appearance()
        self.settings_changed.emit(dataclasses.replace(s))
        self._redraw_plot()

    def _on_plotted_changed(self) -> None:
        if self._building:
            return
        self.plot_panel.set_plotted(self.table_panel.plotted_ains())
        self._on_widget_changed()

    def _on_dark_toggled(self, checked: bool) -> None:
        if self._building:
            return
        self.settings.dark_mode = checked
        self._save_settings()
        self._apply_theme()
        self._render_link()

    def _apply_theme(self) -> None:
        theme = DARK_THEME if self.settings.dark_mode else LIGHT_THEME
        QApplication.instance().setStyleSheet(theme["stylesheet"])
        self.table_panel.apply_theme(theme)
        self.plot_panel.apply_theme(theme)

    # -- LabJack driver: check on startup, offer a one-click install
    def _refresh_driver_state(self) -> None:
        """Tell the user plainly if the LJM driver is missing, and show the
        Install button when we shipped an installer.  Simulation mode never
        needs the driver, so we stay quiet there."""
        ok, msg = (True, "") if self.settings.simulate else driver.check_ljm()
        installer = not ok and bool(driver.find_installer())
        self.topbar.btn_install.setVisible(installer)
        self._driver_msg = ""
        if not ok:
            self._driver_msg = msg + (
                " - click 'Install driver', or tick Simulation mode." if installer else
                " - install the LJM software from labjack.com, or tick Simulation mode.")

    def _install_driver(self) -> None:
        if self.topbar.run_installer():
            self._driver_msg = ("LabJack installer launched - finish it, then "
                                "restart IBL Pressure.")
            self._render_link()

    # -- Acquisition thread
    def _start_worker(self) -> None:
        self.thread = QThread(self)
        self.worker = DaqWorker(dataclasses.replace(self.settings))
        self.worker.moveToThread(self.thread)

        # Not connected to thread.started: the thread idles until Connect is pressed.
        self.start_worker.connect(self.worker.start)
        self.worker.sample.connect(self._on_sample)
        self.worker.link_up.connect(self._on_link_up)
        self.worker.link_down.connect(self._on_link_down)
        self.worker.reconnecting.connect(self._on_reconnecting)
        self.worker.read_error.connect(self._on_read_error)
        self.settings_changed.connect(self.worker.update_settings)
        self.stop_worker.connect(self.worker.stop)

        self.thread.start()

        self._refresh_driver_state()

    def _toggle_connection(self) -> None:
        now = self._now()
        if self._link_wanted:
            self._link_wanted = False
            self.link.disconnect_requested(now)
            self.stop_worker.emit()
            self.topbar.btn_connect.setText("Connect")
        else:
            self._link_wanted = True
            self.link.connect_requested(now)
            self.topbar.btn_connect.setText("Disconnect")
            # The worker already has the current settings; just tell it to open.
            self.start_worker.emit()
        self._render_link()

    # -- Link events: forwarded to LinkMonitor, then one redraw ---------------
    def _on_link_up(self, description: str) -> None:
        self.link.link_up(self._now(), description)
        self._render_link()

    def _on_link_down(self, reason: str) -> None:
        self.link.link_down(self._now(), reason)
        # If the link is down because the LJM driver is missing, the driver
        # check owns the status line (and shows the Install button).
        if not self.settings.simulate:
            self._refresh_driver_state()
        self._render_link()

    def _on_reconnecting(self, attempt: int) -> None:
        self.link.reconnecting(self._now(), attempt)
        self._render_link()

    def _on_read_error(self, message: str) -> None:
        self.link.read_error(self._now(), message)
        self._render_link()

    def _render_link(self) -> None:
        """The one place the dot and the status line are drawn (AGENTS.md rule 3).

        Also keeps the table honest: a number is shown only while the Link is Live.
        """
        now = self._now()
        view = self.link.view(now)
        text = view.text
        if view.state is LinkState.DOWN and self._driver_msg:
            text = self._driver_msg
        if self._settings_problem:
            text = f"{self._settings_problem} · {text}"
        self.topbar.show_link(view.dot_color, text)
        if view.state is not LinkState.LIVE and self._last_sample is not None:
            self.table_panel.show_stale(self._last_sample,
                                        max(0.0, now - self._last_sample_now))

    # -- New data
    def _on_sample(self, sample: Sample) -> None:
        now = self._now()
        self.link.sample(now)
        self._last_sample = sample
        self._last_sample_now = now
        self.table_panel.show_sample(sample)
        self.history.append(sample.timestamp, self._pressure_row(sample))
        self._maybe_write_csv(sample)
        if self.plot_panel.redraw_due(now, self.settings.sample_hz):
            self._redraw_plot()
        self._render_link()

    def _pressure_row(self, sample: Sample) -> np.ndarray:
        row = np.full(len(CHANNELS), np.nan)
        for r in sample.readings:
            if r.pressure is not None and r.pressure > 0:
                row[self._chan_index[r.ain]] = r.pressure
        return row

    def _reload_history_from_csv(self) -> None:
        """Refill the plot from yesterday's and today's Daily CSVs, once, at startup."""
        loaded, skipped = load_recent_history(
            self.settings.csv_dir, self._now(), self.settings.history_s, self.history)
        if loaded or skipped:
            text = f"History reloaded: {loaded} rows from CSV"
            if skipped:
                text += f" ({skipped} unreadable lines skipped)"
            self.topbar.lbl_csv.setText(text)

    def _maybe_write_csv(self, sample: Sample) -> None:
        lbl = self.topbar.lbl_csv
        if not self.settings.csv_enabled:
            lbl.setText("CSV: off")
            return
        if sample.timestamp - self._last_csv < self.settings.csv_interval_s:
            return
        self._last_csv = sample.timestamp
        if self.logger.write(sample):
            self._csv_rows += 1
            name = os.path.basename(self.logger.current_path)
            lbl.setText(f"CSV: {name}  ({self._csv_rows} rows)")
        else:
            lbl.setText(self.logger.last_error or "CSV: write failed")

    def _redraw_plot(self) -> None:
        self.plot_panel.redraw(self.history, self._now(), self.link.late_threshold_s)

    def _clear_history(self) -> None:
        self.history.clear()
        self._redraw_plot()

    def closeEvent(self, event) -> None:
        problem = self._harvest_panels().save()
        if problem:
            print(problem, file=sys.stderr)  # the window is closing; stderr is all we have
        # Use a blocking call so the worker's stop() (and LJM handle close)
        # finishes on the worker thread before we quit it.  A queued emit
        # would race with thread.quit() and could leave the device open.
        QMetaObject.invokeMethod(self.worker, "stop", Qt.BlockingQueuedConnection)
        self.thread.quit()
        self.thread.wait(5000)
        # Safety net: close every LJM handle so the next launch has no phantom handles.
        self.worker.cleanup()
        self.logger.close()
        super().closeEvent(event)
