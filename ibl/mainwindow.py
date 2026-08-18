"""
The one and only window.

Layout:

    +--------------------------------------------------------------+
    | [Connect] [x] Simulation      status text ...        CSV: ... |
    +----------------------------+---------------------------------+
    | live table, 14 rows        | time span [5 min v] [x] auto Y  |
    | Plot|Location|Gauge|AIN|   |                                 |
    |     |Volts|Pressure|Status |      log-scale pressure plot     |
    | [All][None][IG][CG]        |                                 |
    +----------------------------+---------------------------------+
    | v Settings  (collapsible: link, rates, fault level, CSV, ...) |
    +--------------------------------------------------------------+

Everything on the settings row defaults to what Design.pdf asks for; changing
it takes effect immediately and is remembered in settings.json.
"""
from __future__ import annotations

import bisect
import datetime as _dt
import os
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSizePolicy, QSpinBox,
    QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import __version__
from .channels import CHANNELS
from .config import Settings
from .conversion import FAULT, OK, OVER, UNDER
from .csvlogger import DailyCsvLogger
from .daq import DaqWorker, Sample, LJM_AVAILABLE

# ---------------------------------------------------------------------------
pg.setConfigOptions(antialias=True)

# -- theme palettes --------------------------------------------------------
LIGHT_THEME = {
    "pg_bg": "w", "pg_fg": "k",
    "legend_brush": (255, 255, 255, 240), "legend_pen": "#888888",
    "fault_bg": "#ffd6d6", "range_bg": "#fff3cd", "stale_bg": "#f0f0f0",
    "stylesheet": """
        QMainWindow, QWidget { background-color: #f0f0f0; color: #1a1a1a; }
        QGroupBox { border: 1px solid #bbb; border-radius: 4px;
                    margin-top: 6px; padding-top: 10px; color: #1a1a1a;
                    background-color: #f5f5f5; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        QTableWidget { background-color: #ffffff; alternate-background-color: #f5f5f5;
                       color: #1a1a1a; gridline-color: #d0d0d0; }
        QHeaderView::section { background-color: #e8e8e8; color: #1a1a1a;
                               border: 1px solid #ccc; padding: 3px; }
        QPushButton { background-color: #e0e0e0; color: #1a1a1a;
                      border: 1px solid #aaa; border-radius: 3px; padding: 4px 12px; }
        QPushButton:hover { background-color: #d0d0d0; }
        QPushButton:pressed { background-color: #c0c0c0; }
        QComboBox { background-color: #ffffff; color: #1a1a1a; border: 1px solid #aaa; }
        QComboBox QAbstractItemView { background-color: #ffffff; color: #1a1a1a; }
        QLineEdit, QSpinBox, QDoubleSpinBox { background-color: #ffffff;
                      color: #1a1a1a; border: 1px solid #aaa; }
        QCheckBox { color: #1a1a1a; }
        QCheckBox::indicator, QGroupBox::indicator { border: 2px solid #888;
                               border-radius: 2px; width: 14px; height: 14px;
                               background-color: #ffffff; }
        QCheckBox::indicator:checked, QGroupBox::indicator:checked {
                               background-color: #3078c6; border-color: #3078c6; }
        QLabel { color: #1a1a1a; }
        QSplitter::handle { background-color: #ccc; }
    """,
}
DARK_THEME = {
    "pg_bg": "#1e1e1e", "pg_fg": "#d4d4d4",
    "legend_brush": (40, 40, 40, 240), "legend_pen": "#999999",
    "fault_bg": "#6b2020", "range_bg": "#5c4a1a", "stale_bg": "#333333",
    "stylesheet": """
        QMainWindow, QWidget { background-color: #2b2b2b; color: #d4d4d4; }
        QGroupBox { border: 1px solid #555; border-radius: 4px;
                    margin-top: 6px; padding-top: 10px; color: #d4d4d4; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        QTableWidget { background-color: #1e1e1e; alternate-background-color: #2a2a2a;
                       color: #d4d4d4; gridline-color: #444; }
        QHeaderView::section { background-color: #333; color: #d4d4d4;
                               border: 1px solid #444; padding: 3px; }
        QPushButton { background-color: #3c3c3c; color: #d4d4d4;
                      border: 1px solid #555; border-radius: 3px; padding: 4px 12px; }
        QPushButton:hover { background-color: #505050; }
        QPushButton:pressed { background-color: #606060; }
        QComboBox { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; }
        QComboBox QAbstractItemView { background-color: #2b2b2b; color: #d4d4d4; }
        QLineEdit, QSpinBox, QDoubleSpinBox { background-color: #3c3c3c;
                      color: #d4d4d4; border: 1px solid #555; }
        QCheckBox { color: #d4d4d4; }
        QCheckBox::indicator, QGroupBox::indicator { border: 2px solid #888;
                               border-radius: 2px; width: 14px; height: 14px;
                               background-color: #3c3c3c; }
        QCheckBox::indicator:checked, QGroupBox::indicator:checked {
                               background-color: #4a9eff; border-color: #4a9eff; }
        QLabel { color: #d4d4d4; }
        QSplitter::handle { background-color: #444; }
    """,
}

# One colour per AIN.  Ion gauges get the saturated colours, Convectrons the
# lighter partner of the same hue, so a location's pair reads as a pair.
CHANNEL_COLORS = [
    "#1f77b4", "#8fbfe0",   # SNICS
    "#d62728", "#f0a3a3",   # Injector
    "#2ca02c", "#98d798",   # Post-accel
    "#9467bd", "#c9b3de",   # Switching Magnet
    "#ff7f0e", "#ffc38a",   # Left Chamber
    "#17becf", "#96e2ea",   # Middle Chamber
    "#8c564b", "#c4a09b",   # Right Chamber
]

TIME_SPANS = [
    ("1 minute", 60), ("5 minutes", 300), ("15 minutes", 900),
    ("30 minutes", 1800), ("1 hour", 3600), ("3 hours", 10800),
    ("6 hours", 21600), ("12 hours", 43200), ("24 hours", 86400),
]

COL_PLOT, COL_LOC, COL_PRESS, COL_GAUGE, COL_AIN, COL_VOLTS, COL_STATUS = range(7)


class TorrAxis(pg.AxisItem):
    """Log Y axis that labels ticks 1E-06 instead of 0.000001."""

    def logTickStrings(self, values, scale, spacing):
        out = []
        for v in values:
            p = 10.0 ** v
            if p == 0:
                out.append("0")
            else:
                out.append(f"{p:.0E}".replace("E-0", "E-").replace("E+0", "E+"))
        return out

ROW_FAULT_BG = QColor(LIGHT_THEME["fault_bg"])
ROW_RANGE_BG = QColor(LIGHT_THEME["range_bg"])
ROW_STALE_BG = QColor(LIGHT_THEME["stale_bg"])


class Series:
    """Rolling history for one channel. Plain lists, trimmed by age."""

    def __init__(self) -> None:
        self.t: list[float] = []
        self.p: list[float] = []

    def append(self, t: float, p: float) -> None:
        self.t.append(t)
        self.p.append(p)  # may be nan for a fault, which breaks the line

    def trim(self, oldest_allowed: float) -> None:
        if self.t and self.t[0] < oldest_allowed:
            i = bisect.bisect_left(self.t, oldest_allowed)
            if i:
                del self.t[:i]
                del self.p[:i]

    def window(self, since: float) -> tuple[np.ndarray, np.ndarray]:
        i = bisect.bisect_left(self.t, since)
        return np.asarray(self.t[i:], dtype=float), np.asarray(self.p[i:], dtype=float)

    def clear(self) -> None:
        self.t.clear()
        self.p.clear()


class MainWindow(QMainWindow):
    settings_changed = Signal(object)
    stop_worker = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.series: dict[int, Series] = {c.ain: Series() for c in CHANNELS}
        self.curves: dict[int, pg.PlotDataItem] = {}
        self.logger = DailyCsvLogger(settings.csv_dir, settings.csv_include_voltages)
        self._last_csv = 0.0
        self._last_sample_at = 0.0
        self._csv_rows = 0
        self._building = True

        self.setWindowTitle(f"IBL Pressure  -  Beamline Vacuum Monitor  v{__version__}")
        self.resize(1500, 880)

        self._build_ui()
        self._load_settings_into_widgets()
        self._building = False

        self._start_worker()

        # Greys out the table if samples stop arriving.
        self._watchdog = QTimer(self)
        self._watchdog.timeout.connect(self._check_stale)
        self._watchdog.start(2000)

    # =====================================================================
    # UI construction
    # =====================================================================
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addLayout(self._build_topbar())

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_plot_panel())
        splitter.addWidget(self._build_table_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([1000, 500])
        root.addWidget(splitter, 1)

        root.addWidget(self._build_settings_panel())
        self.setCentralWidget(central)

        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

    # -- top bar -----------------------------------------------------------
    def _build_topbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()

        self.btn_connect = QPushButton("Disconnect")
        self.btn_connect.setFixedWidth(110)
        self.btn_connect.clicked.connect(self._toggle_connection)
        bar.addWidget(self.btn_connect)

        self.chk_sim = QCheckBox("Simulation mode")
        self.chk_sim.setToolTip("Generate fake gauge data so the program can be "
                                "used with no LabJack attached.")
        self.chk_sim.toggled.connect(self._on_widget_changed)
        bar.addWidget(self.chk_sim)

        self.chk_dark = QCheckBox("Dark mode")
        self.chk_dark.toggled.connect(self._on_dark_toggled)
        bar.addWidget(self.chk_dark)

        self.lbl_link = QLabel("\u25cf")
        self.lbl_link.setStyleSheet("color: #999; font-size: 18px;")
        self.lbl_link.setFixedWidth(16)
        bar.addWidget(self.lbl_link)

        self.lbl_status = QLabel("Starting up...")
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(self.lbl_status, 1)

        self.lbl_csv = QLabel("CSV: off")
        bar.addWidget(self.lbl_csv)

        btn_open = QPushButton("Open log folder")
        btn_open.clicked.connect(self._open_log_folder)
        bar.addWidget(btn_open)
        return bar

    # -- table -------------------------------------------------------------
    def _build_table_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)

        header = QLabel("Live pressures")
        f = header.font()
        f.setBold(True)
        header.setFont(f)
        lay.addWidget(header)

        self.table = QTableWidget(len(CHANNELS), 7)
        self.table.setHorizontalHeaderLabels(
            ["Plot", "Location", "Pressure (Torr)", "Gauge", "AIN", "Volts", "Status"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)

        mono_big_bold = QFont("Consolas", 12)
        mono_big_bold.setStyleHint(QFont.Monospace)
        mono_big_bold.setBold(True)

        for row, ch in enumerate(CHANNELS):
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Unchecked)
            chk.setBackground(QColor(CHANNEL_COLORS[ch.ain]))
            self.table.setItem(row, COL_PLOT, chk)

            self.table.setItem(row, COL_LOC, QTableWidgetItem(ch.location))
            self.table.setItem(row, COL_GAUGE,
                               QTableWidgetItem("Ion" if ch.is_ion else "Convectron"))
            ain_item = QTableWidgetItem(str(ch.ain))
            ain_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, COL_AIN, ain_item)

            volts_item = QTableWidgetItem("---")
            volts_item.setFont(mono)
            volts_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, COL_VOLTS, volts_item)

            press_item = QTableWidgetItem("---")
            press_item.setFont(mono_big_bold)
            press_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, COL_PRESS, press_item)

            self.table.setItem(row, COL_STATUS, QTableWidgetItem(""))

        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_PLOT, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_PLOT, 42)
        hh.setSectionResizeMode(COL_LOC, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_PRESS, QHeaderView.ResizeToContents)
        for col in (COL_GAUGE, COL_AIN, COL_VOLTS, COL_STATUS):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_table_item_changed)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        for text, fn in (
            ("Plot all", lambda: self._set_plotted(lambda c: True)),
            ("Plot none", lambda: self._set_plotted(lambda c: False)),
            ("Ion only", lambda: self._set_plotted(lambda c: c.is_ion)),
            ("Convectron only", lambda: self._set_plotted(lambda c: not c.is_ion)),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        return panel

    # -- plot --------------------------------------------------------------
    def _build_plot_panel(self) -> QWidget:
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Time span:"))
        self.cmb_span = QComboBox()
        for label, secs in TIME_SPANS:
            self.cmb_span.addItem(label, secs)
        self.cmb_span.currentIndexChanged.connect(self._on_widget_changed)
        controls.addWidget(self.cmb_span)

        self.chk_autoy = QCheckBox("Auto Y")
        self.chk_autoy.setChecked(True)
        self.chk_autoy.toggled.connect(self._apply_y_mode)
        controls.addWidget(self.chk_autoy)

        controls.addWidget(QLabel("Y from 1e"))
        self.spn_ymin = QSpinBox()
        self.spn_ymin.setRange(-12, 4)
        self.spn_ymin.setValue(-9)
        self.spn_ymin.valueChanged.connect(self._apply_y_mode)
        controls.addWidget(self.spn_ymin)
        controls.addWidget(QLabel("to 1e"))
        self.spn_ymax = QSpinBox()
        self.spn_ymax.setRange(-11, 5)
        self.spn_ymax.setValue(3)
        self.spn_ymax.valueChanged.connect(self._apply_y_mode)
        controls.addWidget(self.spn_ymax)

        btn_clear = QPushButton("Clear history")
        btn_clear.clicked.connect(self._clear_history)
        controls.addWidget(btn_clear)
        controls.addStretch(1)
        lay.addLayout(controls)

        self.plot = pg.PlotWidget(axisItems={
            "bottom": pg.DateAxisItem(orientation="bottom"),
            "left": TorrAxis(orientation="left"),
            "right": TorrAxis(orientation="right"),
        })
        self.plot.setLabel("left", "Pressure [Torr]")
        self.plot.showAxis("right")
        self.plot.getAxis("right").setStyle(showValues=True)
        self.plot.getAxis("right").enableAutoSIPrefix(False)
        # pyqtgraph would otherwise "helpfully" rescale Torr to mTorr.
        self.plot.getAxis("left").enableAutoSIPrefix(False)
        self.plot.getAxis("bottom").enableAutoSIPrefix(False)
        self.plot.setLogMode(x=False, y=True)
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        t = DARK_THEME if self.settings.dark_mode else LIGHT_THEME
        self.legend = self.plot.addLegend(offset=(8, 8), labelTextSize="8pt",
                                          brush=pg.mkBrush(*t["legend_brush"]),
                                          pen=pg.mkPen(t["legend_pen"]))
        self.legend.setVisible(self.settings.show_legend)
        lay.addWidget(self.plot, 1)

        for ch in CHANNELS:
            pen = pg.mkPen(CHANNEL_COLORS[ch.ain], width=1.6)
            curve = self.plot.plot([], [], pen=pen, connect="finite")
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            curve.setVisible(False)
            self.curves[ch.ain] = curve

        self._apply_y_mode()
        return panel

    def _rebuild_legend(self) -> None:
        """Only list the channels actually being plotted, so 14 entries do not
        cover the graph when you are watching two of them."""
        self.legend.clear()
        for ch in CHANNELS:
            curve = self.curves[ch.ain]
            if curve.isVisible():
                self.legend.addItem(curve, ch.name)

    # -- settings ----------------------------------------------------------
    def _build_settings_panel(self) -> QWidget:
        box = QGroupBox("Settings")
        box.setCheckable(True)
        box.setChecked(False)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(6, 2, 6, 4)
        inner = QWidget()
        outer.addWidget(inner)
        # Unchecking the group box should give the space back to the plot,
        # not just grey the controls out.
        box.toggled.connect(inner.setVisible)
        inner.setVisible(False)
        grid = QGridLayout(inner)
        grid.setContentsMargins(4, 4, 4, 4)

        def add(col: int, title: str) -> QFormLayout:
            g = QGroupBox(title)
            form = QFormLayout(g)
            form.setContentsMargins(8, 6, 8, 6)
            grid.addWidget(g, 0, col)
            return form

        # --- LabJack ---
        f = add(0, "LabJack T7")
        self.cmb_conn = QComboBox()
        self.cmb_conn.addItems(["USB", "ETHERNET", "ANY"])
        self.cmb_conn.currentIndexChanged.connect(self._on_widget_changed)
        f.addRow("Connection:", self.cmb_conn)

        self.txt_ident = QLineEdit()
        self.txt_ident.setToolTip("Serial number or IP address. ANY = first T7 found.")
        self.txt_ident.editingFinished.connect(self._on_widget_changed)
        f.addRow("Identifier:", self.txt_ident)

        self.spn_res = QSpinBox()
        self.spn_res.setRange(0, 12)
        self.spn_res.setToolTip("T7 ADC resolution index. Higher = quieter but slower. "
                                "0 uses the device default.")
        self.spn_res.valueChanged.connect(self._on_widget_changed)
        f.addRow("Resolution index:", self.spn_res)

        # --- Acquisition ---
        f = add(1, "Acquisition")
        self.spn_hz = QDoubleSpinBox()
        self.spn_hz.setRange(0.1, 20.0)
        self.spn_hz.setSingleStep(0.5)
        self.spn_hz.setDecimals(2)
        self.spn_hz.setSuffix("  Hz")
        self.spn_hz.valueChanged.connect(self._on_widget_changed)
        f.addRow("Update rate:", self.spn_hz)

        self.spn_fault = QDoubleSpinBox()
        self.spn_fault.setRange(1.0, 12.0)
        self.spn_fault.setSingleStep(0.1)
        self.spn_fault.setDecimals(2)
        self.spn_fault.setSuffix("  V")
        self.spn_fault.setToolTip(
            "Above this the channel reads Gauge Fault.\n"
            "The VGC083A drives its output past +11 V on a fault, but a T7 "
            "analog input saturates just past 10 V, so 10 V is the practical "
            "trip point. Normal output never exceeds 9 V (ion) or 5.66 V "
            "(Convectron)."
        )
        self.spn_fault.valueChanged.connect(self._on_widget_changed)
        f.addRow("Gauge fault above:", self.spn_fault)

        self.spn_hist = QSpinBox()
        self.spn_hist.setRange(1, 48)
        self.spn_hist.setSuffix("  hours")
        self.spn_hist.valueChanged.connect(self._on_widget_changed)
        f.addRow("Keep history:", self.spn_hist)

        # --- CSV ---
        f = add(2, "CSV logging")
        self.chk_csv = QCheckBox("Enabled  (one file per day, named by date)")
        self.chk_csv.toggled.connect(self._on_widget_changed)
        f.addRow(self.chk_csv)

        self.spn_csv = QDoubleSpinBox()
        self.spn_csv.setRange(1.0, 3600.0)
        self.spn_csv.setSingleStep(1.0)
        self.spn_csv.setDecimals(1)
        self.spn_csv.setSuffix("  s")
        self.spn_csv.setMaximumWidth(130)
        self.spn_csv.valueChanged.connect(self._on_widget_changed)
        f.addRow("Write every:", self.spn_csv)

        folder_row = QHBoxLayout()
        self.txt_csvdir = QLineEdit()
        self.txt_csvdir.editingFinished.connect(self._on_widget_changed)
        folder_row.addWidget(self.txt_csvdir, 1)
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse_csv_dir)
        folder_row.addWidget(btn_browse)
        wrap = QWidget()
        wrap.setLayout(folder_row)
        f.addRow("Folder:", wrap)

        self.chk_csvv = QCheckBox("Also record raw volts")
        self.chk_csvv.toggled.connect(self._on_widget_changed)
        f.addRow(self.chk_csvv)

        # --- Plot appearance ---
        f = add(3, "Plot")
        self.chk_legend = QCheckBox("Show legend on plot")
        self.chk_legend.toggled.connect(self._on_widget_changed)
        f.addRow(self.chk_legend)

        grid.setColumnStretch(3, 1)
        return box

    # =====================================================================
    # Settings <-> widgets
    # =====================================================================
    def _load_settings_into_widgets(self) -> None:
        s = self.settings
        self.chk_sim.setChecked(s.simulate)
        self.chk_dark.setChecked(s.dark_mode)
        self._apply_theme()
        self.cmb_conn.setCurrentText(s.connection)
        self.txt_ident.setText(s.identifier)
        self.spn_res.setValue(int(s.resolution_index))
        self.spn_hz.setValue(float(s.sample_hz))
        self.spn_fault.setValue(float(s.fault_volts))
        self.spn_hist.setValue(max(1, int(round(s.history_s / 3600))))
        self.chk_csv.setChecked(s.csv_enabled)
        self.spn_csv.setValue(float(s.csv_interval_s))
        self.txt_csvdir.setText(s.csv_dir)
        self.chk_csvv.setChecked(s.csv_include_voltages)
        self.chk_legend.setChecked(s.show_legend)

        idx = max(0, next((i for i, (_, sec) in enumerate(TIME_SPANS)
                           if sec >= s.plot_window_s), 1))
        self.cmb_span.setCurrentIndex(idx)

        wanted = set(s.plotted_ains)
        for row, ch in enumerate(CHANNELS):
            item = self.table.item(row, COL_PLOT)
            item.setCheckState(Qt.Checked if ch.ain in wanted else Qt.Unchecked)
            self.curves[ch.ain].setVisible(ch.ain in wanted)
        self._rebuild_legend()

    def _harvest_widgets(self) -> Settings:
        s = self.settings
        s.simulate = self.chk_sim.isChecked()
        s.connection = self.cmb_conn.currentText()
        s.identifier = self.txt_ident.text().strip() or "ANY"
        s.resolution_index = self.spn_res.value()
        s.sample_hz = self.spn_hz.value()
        s.fault_volts = self.spn_fault.value()
        s.history_s = self.spn_hist.value() * 3600
        s.csv_enabled = self.chk_csv.isChecked()
        s.csv_interval_s = self.spn_csv.value()
        s.csv_dir = self.txt_csvdir.text().strip() or s.csv_dir
        s.csv_include_voltages = self.chk_csvv.isChecked()
        s.show_legend = self.chk_legend.isChecked()
        s.plot_window_s = int(self.cmb_span.currentData())
        s.plotted_ains = [
            ch.ain for row, ch in enumerate(CHANNELS)
            if self.table.item(row, COL_PLOT).checkState() == Qt.Checked
        ]
        return s

    def _on_widget_changed(self, *_args) -> None:
        if self._building:
            return
        s = self._harvest_widgets()
        s.save()
        self.logger.reconfigure(s.csv_dir, s.csv_include_voltages)
        self.legend.setVisible(s.show_legend)
        self.settings_changed.emit(s)
        self._redraw_plot()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._building or item.column() != COL_PLOT:
            return
        ch = CHANNELS[item.row()]
        self.curves[ch.ain].setVisible(item.checkState() == Qt.Checked)
        self._rebuild_legend()
        self._on_widget_changed()

    def _on_dark_toggled(self, checked: bool) -> None:
        if self._building:
            return
        self.settings.dark_mode = checked
        self.settings.save()
        self._apply_theme()

    def _apply_theme(self) -> None:
        global ROW_FAULT_BG, ROW_RANGE_BG, ROW_STALE_BG
        theme = DARK_THEME if self.settings.dark_mode else LIGHT_THEME
        ROW_FAULT_BG = QColor(theme["fault_bg"])
        ROW_RANGE_BG = QColor(theme["range_bg"])
        ROW_STALE_BG = QColor(theme["stale_bg"])

        from PySide6.QtWidgets import QApplication
        QApplication.instance().setStyleSheet(theme["stylesheet"])

        self.plot.setBackground(theme["pg_bg"])
        for axis_name in ("left", "bottom", "right"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(theme["pg_fg"])
            axis.setTextPen(theme["pg_fg"])
        self.plot.getAxis("left").setLabel("Pressure [Torr]",
                                           color=theme["pg_fg"])

        self.legend.setBrush(pg.mkBrush(*theme["legend_brush"]))
        self.legend.setPen(pg.mkPen(theme["legend_pen"]))
        for item in self.legend.items:
            for single in item:
                if isinstance(single, pg.graphicsItems.LabelItem.LabelItem):
                    single.setText(single.text, color=theme["pg_fg"])

    def _set_plotted(self, predicate) -> None:
        self._building = True
        for row, ch in enumerate(CHANNELS):
            on = bool(predicate(ch))
            self.table.item(row, COL_PLOT).setCheckState(
                Qt.Checked if on else Qt.Unchecked)
            self.curves[ch.ain].setVisible(on)
        self._building = False
        self._rebuild_legend()
        self._on_widget_changed()

    def _browse_csv_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose the CSV log folder",
                                             self.txt_csvdir.text())
        if d:
            self.txt_csvdir.setText(d)
            self._on_widget_changed()

    def _open_log_folder(self) -> None:
        path = self.settings.csv_dir
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]  (Windows)
        except Exception:
            QMessageBox.information(self, "Log folder", path)

    # =====================================================================
    # Acquisition thread
    # =====================================================================
    def _start_worker(self) -> None:
        self.thread = QThread(self)
        self.worker = DaqWorker(self.settings)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.start)
        self.worker.sample.connect(self._on_sample)
        self.worker.status.connect(self._on_status)
        self.worker.connection_changed.connect(self._on_connection_changed)
        self.settings_changed.connect(self.worker.update_settings)
        self.stop_worker.connect(self.worker.stop)

        self.thread.start()

        if not LJM_AVAILABLE and not self.settings.simulate:
            self._on_status("LabJack LJM driver not found - tick Simulation mode, "
                            "or install the LJM software from labjack.com")

    def _toggle_connection(self) -> None:
        if self.btn_connect.text() == "Disconnect":
            self.stop_worker.emit()
            self.btn_connect.setText("Connect")
            self._on_status("Disconnected")
        else:
            self.settings_changed.emit(self.settings)
            QTimer.singleShot(0, self.worker.start)
            self.btn_connect.setText("Disconnect")

    def _on_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def _on_connection_changed(self, up: bool) -> None:
        self.lbl_link.setStyleSheet(
            f"color: {'#2ca02c' if up else '#d62728'}; font-size: 18px;")
        self.lbl_link.setText("\u25cf")
        self.btn_connect.setText("Disconnect" if up else "Connect")

    # =====================================================================
    # New data
    # =====================================================================
    def _on_sample(self, sample: Sample) -> None:
        self._last_sample_at = time.time()
        self._update_table(sample)
        self._update_series(sample)
        self._maybe_write_csv(sample)
        self._redraw_plot()

    def _update_table(self, sample: Sample) -> None:
        self._building = True
        by_ain = sample.by_ain()
        for row, ch in enumerate(CHANNELS):
            r = by_ain.get(ch.ain)
            if r is None:
                continue
            self.table.item(row, COL_VOLTS).setText(f"{r.voltage:8.4f}")
            self.table.item(row, COL_PRESS).setText(r.display_text())
            self.table.item(row, COL_STATUS).setText("" if r.ok else r.status)

            if r.status == FAULT:
                bg = ROW_FAULT_BG
            elif r.status in (UNDER, OVER):
                bg = ROW_RANGE_BG
            else:
                bg = QColor(Qt.transparent)
            for col in (COL_LOC, COL_GAUGE, COL_AIN, COL_VOLTS, COL_PRESS, COL_STATUS):
                self.table.item(row, col).setBackground(bg)
        self._building = False

    def _update_series(self, sample: Sample) -> None:
        oldest = sample.timestamp - self.settings.history_s
        for r in sample.readings:
            s = self.series[r.ain]
            s.append(sample.timestamp,
                     float("nan") if r.pressure is None or r.pressure <= 0
                     else r.pressure)
            s.trim(oldest)

    def _maybe_write_csv(self, sample: Sample) -> None:
        if not self.settings.csv_enabled:
            self.lbl_csv.setText("CSV: off")
            return
        if sample.timestamp - self._last_csv < self.settings.csv_interval_s:
            return
        self._last_csv = sample.timestamp
        if self.logger.write(sample):
            self._csv_rows += 1
            name = os.path.basename(self.logger.current_path)
            self.lbl_csv.setText(f"CSV: {name}  ({self._csv_rows} rows)")
        else:
            self.lbl_csv.setText(self.logger.last_error or "CSV: write failed")

    # =====================================================================
    # Plot
    # =====================================================================
    def _apply_y_mode(self, *_args) -> None:
        if self.chk_autoy.isChecked():
            self.plot.enableAutoRange(axis="y")
        else:
            lo = min(self.spn_ymin.value(), self.spn_ymax.value() - 1)
            hi = max(self.spn_ymax.value(), lo + 1)
            self.plot.disableAutoRange(axis="y")
            self.plot.setYRange(lo, hi, padding=0)   # log mode: these are exponents

    def _redraw_plot(self) -> None:
        span = int(self.cmb_span.currentData() or 300)
        now = time.time()
        since = now - span
        any_data = False
        for ch in CHANNELS:
            curve = self.curves[ch.ain]
            if not curve.isVisible():
                continue
            t, p = self.series[ch.ain].window(since)
            if t.size:
                any_data = True
            curve.setData(t, p)
        if any_data:
            self.plot.setXRange(since, now, padding=0)

    def _clear_history(self) -> None:
        for s in self.series.values():
            s.clear()
        self._redraw_plot()

    def _check_stale(self) -> None:
        if self._last_sample_at and time.time() - self._last_sample_at > 5:
            self.lbl_link.setStyleSheet("color: #d62728; font-size: 18px;")

    # =====================================================================
    def closeEvent(self, event) -> None:
        try:
            self._harvest_widgets().save()
        except Exception:
            pass
        self.stop_worker.emit()
        self.thread.quit()
        self.thread.wait(3000)
        self.logger.close()
        super().closeEvent(event)
