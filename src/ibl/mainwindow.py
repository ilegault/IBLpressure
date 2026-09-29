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

Link state (the dot and the status line):

    DaqWorker --link_up/link_down/reconnecting/read_error--> MainWindow
    MainWindow --forwards each, with the clock--> LinkMonitor (ibl.link)
    every 500 ms and after every event: _render_link() asks LinkMonitor.view(now)
    and draws the dot colour and the status text from that one LinkView.

A number is only shown in a pressure cell while the Link is Live; otherwise the
cell shows STALE and the last value moves to the Status column with its age.

Everything on the settings row defaults to what Design.pdf asks for; changing
it takes effect immediately and is remembered in settings.json.
"""
from __future__ import annotations

import bisect
import dataclasses
import os
import sys
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QEvent, QMetaObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__, driver
from .channels import CHANNELS, PAIRS, pair_index
from .config import (
    MAX_CSV_INTERVAL_S,
    MAX_HISTORY_S,
    MAX_SAMPLE_HZ,
    MIN_CSV_INTERVAL_S,
    MIN_HISTORY_S,
    MIN_SAMPLE_HZ,
    Settings,
)
from .csvlogger import DailyCsvLogger
from .daq import DaqWorker
from .link import DOT_COLORS, LinkMonitor, LinkState
from .model import GaugeStatus, Sample
from .theme import CHANNEL_COLORS, DARK_THEME, LIGHT_THEME, TIME_SPANS

# ---------------------------------------------------------------------------
pg.setConfigOptions(antialias=True)

COL_IG_PLOT, COL_CG_PLOT, COL_LOC = 0, 1, 2
COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS = 3, 4, 5
COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS = 6, 7, 8
NUM_PAIRS = len(PAIRS)


def _dot_style(color: str) -> str:
    return f"color: {color}; font-size: 18px;"


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
ROW_APPROX_BG = QColor(LIGHT_THEME["approx_bg"])


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


class CompactSpin(QWidget):
    """Textbox flanked by − / + buttons for integer or float values.

    Clicking the buttons steps the value.  The textbox is also directly
    editable: focusing it strips the suffix so you can type a plain number,
    then pressing Enter or clicking away commits and reformats the value.

    Args:
        min_val, max_val: inclusive range.
        value: initial value.
        step: how much each button press changes the value (default 1).
        decimals: decimal places to display (0 → integer display).
        suffix: unit text appended to the displayed value (e.g. " Hz", "%").
    """
    valueChanged = Signal(object)   # int when decimals=0, float otherwise

    def __init__(self, min_val, max_val, value, *, step=1, decimals=0,
                 suffix="", parent=None):
        super().__init__(parent)
        self._min = float(min_val)
        self._max = float(max_val)
        self._value = float(value)
        self._step = float(step)
        self._decimals = decimals
        self._suffix = suffix

        # Fixed-width only — height floats so the layout makes all three
        # children (btn, textbox, btn) exactly the same height.
        _btn_css = "QPushButton { padding: 2px; font-size: 15px; font-weight: bold; }"
        btn_m = QPushButton("−")
        btn_m.setFixedWidth(26)
        btn_m.setStyleSheet(_btn_css)
        btn_m.clicked.connect(self._decrement)

        txt_w = max(35, len(self._format(self._max)) * 9 + 8)
        self._txt = QLineEdit(self._format(self._value))
        self._txt.setAlignment(Qt.AlignCenter)
        self._txt.setFixedWidth(txt_w)
        self._txt.installEventFilter(self)
        self._txt.editingFinished.connect(self._on_edit)

        btn_p = QPushButton("+")
        btn_p.setFixedWidth(26)
        btn_p.setStyleSheet(_btn_css)
        btn_p.clicked.connect(self._increment)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(btn_m)
        lay.addWidget(self._txt)
        lay.addWidget(btn_p)

    # Strip the suffix when the user focuses the textbox so they can type
    # a plain number without fighting the unit text.
    def eventFilter(self, obj, event) -> bool:
        if obj is self._txt and event.type() == QEvent.Type.FocusIn:
            QTimer.singleShot(0, self._prepare_for_edit)
        return super().eventFilter(obj, event)

    def _prepare_for_edit(self) -> None:
        self._txt.setText(self._format_plain(self._value))
        self._txt.selectAll()

    def _on_edit(self) -> None:
        text = self._txt.text().replace(self._suffix, "").strip()
        try:
            v = float(text)
        except ValueError:
            pass
        else:
            self.setValue(v)
        # Always restore the formatted display (with suffix).
        self._txt.setText(self._format(self._value))

    def _format(self, v: float) -> str:
        if self._decimals > 0:
            return f"{v:.{self._decimals}f}{self._suffix}"
        return f"{round(v)}{self._suffix}"

    def _format_plain(self, v: float) -> str:
        if self._decimals > 0:
            return f"{v:.{self._decimals}f}"
        return str(round(v))

    def minimum(self):
        return self._min

    def maximum(self):
        return self._max

    def value(self):
        if self._decimals > 0:
            return round(self._value, self._decimals)
        return round(self._value)

    def setValue(self, v) -> None:
        v = max(self._min, min(self._max, float(v)))
        if abs(v - self._value) > 1e-9:
            self._value = v
            self._txt.setText(self._format(v))
            self.valueChanged.emit(self.value())

    def _increment(self) -> None:
        self.setValue(self._value + self._step)

    def _decrement(self) -> None:
        self.setValue(self._value - self._step)


class MainWindow(QMainWindow):
    settings_changed = Signal(object)
    start_worker = Signal()
    stop_worker = Signal()

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.series: dict[int, Series] = {c.ain: Series() for c in CHANNELS}
        self.curves: dict[int, pg.PlotDataItem] = {}
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
        self._load_settings_into_widgets()
        self._building = False

        self._start_worker()

        # Ages the status line and the STALE table even when no event arrives.
        self._link_timer = QTimer(self)
        self._link_timer.timeout.connect(self._render_link)
        self._link_timer.start(500)
        self._render_link()

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

        self.btn_connect = QPushButton("Connect")
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
        self.lbl_link.setStyleSheet(_dot_style(DOT_COLORS[LinkState.IDLE]))
        self.lbl_link.setFixedWidth(16)
        bar.addWidget(self.lbl_link)

        self.lbl_status = QLabel("")
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(self.lbl_status, 1)

        self.btn_install = QPushButton("Install driver")
        self.btn_install.setToolTip("Install the LabJack LJM driver that "
                                    "ships in this folder.")
        self.btn_install.clicked.connect(self._install_driver)
        self.btn_install.hide()
        bar.addWidget(self.btn_install)

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

        self.table = QTableWidget(NUM_PAIRS, 9)
        self.table.setHorizontalHeaderLabels([
            "IG", "CG", "Location",
            "IG Pressure", "IG Volts", "IG Status",
            "CG Pressure", "CG Volts", "CG Status",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setAlternatingRowColors(True)

        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)

        mono_big_bold = QFont("Consolas", 12)
        mono_big_bold.setStyleHint(QFont.Monospace)
        mono_big_bold.setBold(True)

        for pair in range(NUM_PAIRS):
            ig_ch, cg_ch = PAIRS[pair]

            ig_chk = QTableWidgetItem()
            ig_chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            ig_chk.setCheckState(Qt.Unchecked)
            ig_chk.setBackground(QColor(CHANNEL_COLORS[ig_ch.ain]))
            self.table.setItem(pair, COL_IG_PLOT, ig_chk)

            cg_chk = QTableWidgetItem()
            cg_chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            cg_chk.setCheckState(Qt.Unchecked)
            cg_chk.setBackground(QColor(CHANNEL_COLORS[cg_ch.ain]))
            self.table.setItem(pair, COL_CG_PLOT, cg_chk)

            self.table.setItem(pair, COL_LOC, QTableWidgetItem(ig_ch.location))

            for col in (COL_IG_VOLTS, COL_CG_VOLTS):
                item = QTableWidgetItem("---")
                item.setFont(mono)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(pair, col, item)

            for col in (COL_IG_PRESS, COL_CG_PRESS):
                item = QTableWidgetItem("---")
                item.setFont(mono_big_bold)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(pair, col, item)

            self.table.setItem(pair, COL_IG_STATUS, QTableWidgetItem(""))
            self.table.setItem(pair, COL_CG_STATUS, QTableWidgetItem(""))

        hh = self.table.horizontalHeader()
        for col in (COL_IG_PLOT, COL_CG_PLOT):
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, 42)
        for col in (COL_LOC, COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS,
                    COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS):
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
        self.spn_ymin = CompactSpin(-12, 4, -9)
        self.spn_ymin.valueChanged.connect(self._apply_y_mode)
        controls.addWidget(self.spn_ymin)
        controls.addWidget(QLabel("to 1e"))
        self.spn_ymax = CompactSpin(-11, 5, 3)
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
        t = DARK_THEME if self.settings.dark_mode else LIGHT_THEME
        self.legend = self.plot.addLegend(offset=(8, 8), labelTextSize="8pt",
                                          brush=pg.mkBrush(*t["legend_brush"]),
                                          pen=pg.mkPen(t["legend_pen"]))
        self.legend.setVisible(self.settings.show_legend)
        lay.addWidget(self.plot, 1)

        for ch in CHANNELS:
            curve = self.plot.plot([], [], pen=pg.mkPen("w"), connect="finite")
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            curve.setVisible(False)
            self.curves[ch.ain] = curve

        self._apply_grid()
        self._apply_curve_appearance()
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

        self.spn_res = CompactSpin(0, 12, 0)
        self.spn_res.setToolTip("T7 ADC resolution index. Higher = quieter but slower. "
                                "0 uses the device default.")
        self.spn_res.valueChanged.connect(self._on_widget_changed)
        f.addRow("Resolution index:", self.spn_res)

        # --- Acquisition ---
        f = add(1, "Acquisition")
        self.spn_hz = CompactSpin(MIN_SAMPLE_HZ, MAX_SAMPLE_HZ, 1.0, step=0.5, decimals=2, suffix=" Hz")
        self.spn_hz.valueChanged.connect(self._on_widget_changed)
        f.addRow("Update rate:", self.spn_hz)

        self.spn_fault = CompactSpin(1.0, 12.0, 10.0, step=0.1, decimals=2, suffix=" V")
        self.spn_fault.setToolTip(
            "Above this the channel reads Gauge Fault.\n"
            "The VGC083A drives its output past +11 V on a fault, but a T7 "
            "analog input saturates just past 10 V, so 10 V is the practical "
            "trip point. Normal output never exceeds 9 V (ion) or 5.66 V "
            "(Convectron)."
        )
        self.spn_fault.valueChanged.connect(self._on_widget_changed)
        f.addRow("Gauge fault above:", self.spn_fault)

        self.spn_hist = CompactSpin(MIN_HISTORY_S // 3600, MAX_HISTORY_S // 3600, 24, suffix=" hr")
        self.spn_hist.valueChanged.connect(self._on_widget_changed)
        f.addRow("Keep history:", self.spn_hist)

        # --- CSV ---
        f = add(2, "CSV logging")
        self.chk_csv = QCheckBox("Enabled  (one file per day, named by date)")
        self.chk_csv.toggled.connect(self._on_widget_changed)
        f.addRow(self.chk_csv)

        self.spn_csv = CompactSpin(MIN_CSV_INTERVAL_S, MAX_CSV_INTERVAL_S, 10.0, step=1.0, decimals=1, suffix=" s")
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

        self.spn_curve_width = CompactSpin(0.5, 10.0, 1.0, step=0.5, decimals=1, suffix=" px")
        self.spn_curve_width.valueChanged.connect(self._on_widget_changed)
        f.addRow("Line width:", self.spn_curve_width)

        self.spn_curve_alpha = CompactSpin(0, 100, 31, suffix="%")
        self.spn_curve_alpha.valueChanged.connect(self._on_widget_changed)
        f.addRow("Line opacity:", self.spn_curve_alpha)

        self.chk_show_grid = QCheckBox("Show background grid")
        self.chk_show_grid.toggled.connect(self._on_widget_changed)
        f.addRow(self.chk_show_grid)

        self.spn_grid_alpha = CompactSpin(0, 100, 30, suffix="%")
        self.spn_grid_alpha.valueChanged.connect(self._on_widget_changed)
        f.addRow("Grid opacity:", self.spn_grid_alpha)

        # --- Table appearance ---
        f = add(4, "Table")
        self.spn_table_font = CompactSpin(6, 72, 12, suffix=" pt")
        self.spn_table_font.valueChanged.connect(self._on_widget_changed)
        f.addRow("Pressure font:", self.spn_table_font)

        self.spn_loc_font = CompactSpin(6, 72, 10, suffix=" pt")
        self.spn_loc_font.valueChanged.connect(self._on_widget_changed)
        f.addRow("Location font:", self.spn_loc_font)

        self.col_chk: dict[int, QCheckBox] = {}
        for col, name in (
            (COL_LOC,       "Location"),
            (COL_IG_PRESS,  "IG Pressure"),
            (COL_IG_VOLTS,  "IG Volts"),
            (COL_IG_STATUS, "IG Status"),
            (COL_CG_PRESS,  "CG Pressure"),
            (COL_CG_VOLTS,  "CG Volts"),
            (COL_CG_STATUS, "CG Status"),
        ):
            chk = QCheckBox(name)
            chk.toggled.connect(self._on_widget_changed)
            f.addRow(chk)
            self.col_chk[col] = chk

        grid.setColumnStretch(5, 1)
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
        self.spn_hist.setValue(max(1, round(s.history_s / 3600)))
        self.chk_csv.setChecked(s.csv_enabled)
        self.spn_csv.setValue(float(s.csv_interval_s))
        self.txt_csvdir.setText(s.csv_dir)
        self.chk_csvv.setChecked(s.csv_include_voltages)
        self.chk_legend.setChecked(s.show_legend)
        self.spn_curve_width.setValue(s.curve_width)
        self.spn_curve_alpha.setValue(s.curve_alpha)
        self.chk_show_grid.setChecked(s.show_grid)
        self.spn_grid_alpha.setValue(s.grid_alpha)
        self.spn_table_font.setValue(s.table_font_size)
        self.spn_loc_font.setValue(s.loc_font_size)
        visible = set(s.table_visible_cols)
        for col, chk in self.col_chk.items():
            chk.setChecked(col in visible)
        self._apply_table_appearance()
        self._apply_curve_appearance()
        self._apply_grid()

        idx = max(0, next((i for i, (_, sec) in enumerate(TIME_SPANS)
                           if sec >= s.plot_window_s), 1))
        self.cmb_span.setCurrentIndex(idx)

        wanted = set(s.plotted_ains)
        for pair in range(NUM_PAIRS):
            ig_ain, cg_ain = (c.ain for c in PAIRS[pair])
            self.table.item(pair, COL_IG_PLOT).setCheckState(
                Qt.Checked if ig_ain in wanted else Qt.Unchecked)
            self.table.item(pair, COL_CG_PLOT).setCheckState(
                Qt.Checked if cg_ain in wanted else Qt.Unchecked)
            self.curves[ig_ain].setVisible(ig_ain in wanted)
            self.curves[cg_ain].setVisible(cg_ain in wanted)
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
        s.curve_width = self.spn_curve_width.value()
        s.curve_alpha = self.spn_curve_alpha.value()
        s.show_grid = self.chk_show_grid.isChecked()
        s.grid_alpha = self.spn_grid_alpha.value()
        s.table_font_size = self.spn_table_font.value()
        s.loc_font_size = self.spn_loc_font.value()
        s.table_visible_cols = [col for col, chk in self.col_chk.items() if chk.isChecked()]
        s.plot_window_s = int(self.cmb_span.currentData())
        s.plotted_ains = [
            ain
            for pair in range(NUM_PAIRS)
            for col, ain in ((COL_IG_PLOT, PAIRS[pair][0].ain), (COL_CG_PLOT, PAIRS[pair][1].ain))
            if self.table.item(pair, col).checkState() == Qt.Checked
        ]
        return s

    def _on_widget_changed(self, *_args) -> None:
        if self._building:
            return
        s = self._harvest_widgets()
        self._settings_problem = s.save()
        if self._settings_problem:
            print(self._settings_problem, file=sys.stderr)
        self.link.configure(s.late_after_samples, s.sample_hz)
        self._render_link()
        self.logger.reconfigure(s.csv_dir, s.csv_include_voltages)
        self.legend.setVisible(s.show_legend)
        self._apply_table_appearance()
        self._apply_curve_appearance()
        self._apply_grid()
        self.settings_changed.emit(dataclasses.replace(s))
        self._redraw_plot()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._building or item.column() not in (COL_IG_PLOT, COL_CG_PLOT):
            return
        pair = item.row()
        ain = PAIRS[pair][0 if item.column() == COL_IG_PLOT else 1].ain
        is_plotting = item.checkState() == Qt.Checked
        self.curves[ain].setVisible(is_plotting)
        self._rebuild_legend()
        self._on_widget_changed()

    def _on_dark_toggled(self, checked: bool) -> None:
        if self._building:
            return
        self.settings.dark_mode = checked
        self._settings_problem = self.settings.save()
        if self._settings_problem:
            print(self._settings_problem, file=sys.stderr)
        self._apply_theme()
        self._render_link()

    def _apply_theme(self) -> None:
        global ROW_FAULT_BG, ROW_RANGE_BG, ROW_APPROX_BG
        theme = DARK_THEME if self.settings.dark_mode else LIGHT_THEME
        ROW_FAULT_BG = QColor(theme["fault_bg"])
        ROW_RANGE_BG = QColor(theme["range_bg"])
        ROW_APPROX_BG = QColor(theme["approx_bg"])

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
        for pair in range(NUM_PAIRS):
            ig_ch, cg_ch = PAIRS[pair]
            ig_on = bool(predicate(ig_ch))
            cg_on = bool(predicate(cg_ch))
            self.table.item(pair, COL_IG_PLOT).setCheckState(
                Qt.Checked if ig_on else Qt.Unchecked)
            self.table.item(pair, COL_CG_PLOT).setCheckState(
                Qt.Checked if cg_on else Qt.Unchecked)
            self.curves[ig_ch.ain].setVisible(ig_on)
            self.curves[cg_ch.ain].setVisible(cg_on)
        self._building = False
        self._rebuild_legend()
        self._on_widget_changed()

    def _apply_curve_appearance(self) -> None:
        alpha = int(self.settings.curve_alpha / 100 * 255)
        width = self.settings.curve_width
        for ch in CHANNELS:
            color = pg.mkColor(CHANNEL_COLORS[ch.ain])
            pen = pg.mkPen((color.red(), color.green(), color.blue(), alpha), width=width)
            self.curves[ch.ain].setPen(pen)

    def _apply_grid(self) -> None:
        alpha = self.settings.grid_alpha / 100
        self.plot.showGrid(x=self.settings.show_grid, y=self.settings.show_grid, alpha=alpha)

    def _apply_table_appearance(self) -> None:
        size = self.settings.table_font_size
        font = QFont("Consolas", size)
        font.setStyleHint(QFont.Monospace)
        font.setBold(True)
        loc_font = QFont("Consolas", self.settings.loc_font_size)
        loc_font.setStyleHint(QFont.Monospace)
        for pair in range(NUM_PAIRS):
            for col in (COL_IG_PRESS, COL_CG_PRESS):
                item = self.table.item(pair, col)
                if item:
                    item.setFont(font)
            item = self.table.item(pair, COL_LOC)
            if item:
                item.setFont(loc_font)
        row_h = max(22, int(size * 2.4))
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        chk_w = max(22, row_h)
        for col in (COL_IG_PLOT, COL_CG_PLOT):
            self.table.setColumnWidth(col, chk_w)
        visible = set(self.settings.table_visible_cols)
        for col in (COL_LOC, COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS,
                    COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS):
            self.table.setColumnHidden(col, col not in visible)

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
        except Exception:  # noqa: BLE001 - any failure is reported or handled here
            QMessageBox.information(self, "Log folder", path)

    # =====================================================================
    # LabJack driver: check on startup, offer a one-click install
    # =====================================================================
    def _refresh_driver_state(self) -> None:
        """Tell the user plainly if the LJM driver is missing, and show the
        Install button when we shipped an installer.  Simulation mode never
        needs the driver, so we stay quiet there."""
        self._driver_msg = ""
        if self.settings.simulate:
            self.btn_install.hide()
            return

        ok, msg = driver.check_ljm()
        if ok:
            self.btn_install.hide()
            return

        if driver.find_installer():
            self.btn_install.show()
            self._driver_msg = (msg + " - click 'Install driver', or tick "
                                "Simulation mode.")
        else:
            self.btn_install.hide()
            self._driver_msg = (msg + " - install the LJM software from "
                                "labjack.com, or tick Simulation mode.")

    def _install_driver(self) -> None:
        path = driver.find_installer()
        if not path:
            QMessageBox.information(
                self, "Install driver",
                "No LabJack installer was bundled with this program.\n\n"
                "Download and run the LJM software installer from labjack.com.")
            return

        if QMessageBox.question(
                self, "Install LabJack driver",
                "This will launch the LabJack LJM installer.\n\n"
                "Windows will ask for administrator permission.  When it "
                "finishes, close and reopen IBL Pressure so it can find the "
                "driver.\n\nContinue?") != QMessageBox.Yes:
            return

        if driver.launch_installer(path):
            self._driver_msg = ("LabJack installer launched - finish it, then "
                                "restart IBL Pressure.")
            self._render_link()
        else:
            QMessageBox.warning(
                self, "Install driver",
                "Could not launch the installer:\n" + path)

    # =====================================================================
    # Acquisition thread
    # =====================================================================
    def _start_worker(self) -> None:
        self.thread = QThread(self)
        self.worker = DaqWorker(dataclasses.replace(self.settings))
        self.worker.moveToThread(self.thread)

        # Deliberately NOT connected to thread.started: the acquisition
        # thread just idles until the user presses Connect.
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
            self.btn_connect.setText("Connect")
        else:
            self._link_wanted = True
            self.link.connect_requested(now)
            self.btn_connect.setText("Disconnect")
            # The worker already has the current settings (every widget
            # change is pushed to it live), so just tell it to open.
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
        self.lbl_link.setStyleSheet(_dot_style(view.dot_color))
        self.lbl_link.setText("\u25cf")
        text = view.text
        if view.state is LinkState.DOWN and self._driver_msg:
            text = self._driver_msg
        if self._settings_problem:
            text = f"{self._settings_problem} \u00b7 {text}"
        self.lbl_status.setText(text)
        if view.state is not LinkState.LIVE:
            self._show_stale(now)

    def _show_stale(self, now: float) -> None:
        """Replace every pressure number with STALE; the last value and its age
        go in that gauge's Status cell."""
        sample = self._last_sample
        if sample is None:
            return
        age = max(0.0, now - self._last_sample_now)
        stale_bg = QColor((DARK_THEME if self.settings.dark_mode else LIGHT_THEME)["stale_bg"])
        by_ain = sample.by_ain()
        self._building = True
        for ch in CHANNELS:
            r = by_ain.get(ch.ain)
            if r is None:
                continue
            pair = pair_index(ch.ain)
            if ch.is_ion:
                press_col, volts_col, status_col = COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS
            else:
                press_col, volts_col, status_col = COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS
            self.table.item(pair, press_col).setText("STALE")
            self.table.item(pair, status_col).setText(f"last {r.display_text()}, {age:.0f} s ago")
            for col in (press_col, volts_col, status_col):
                self.table.item(pair, col).setBackground(stale_bg)
        self._building = False

    # =====================================================================
    # New data
    # =====================================================================
    def _on_sample(self, sample: Sample) -> None:
        now = self._now()
        self.link.sample(now)
        self._last_sample = sample
        self._last_sample_now = now
        self._update_table(sample)
        self._update_series(sample)
        self._maybe_write_csv(sample)
        self._redraw_plot()
        self._render_link()

    def _update_table(self, sample: Sample) -> None:
        self._building = True
        by_ain = sample.by_ain()
        for ch in CHANNELS:
            r = by_ain.get(ch.ain)
            if r is None:
                continue
            pair = pair_index(ch.ain)
            if ch.is_ion:
                press_col, volts_col, status_col = COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS
            else:
                press_col, volts_col, status_col = COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS

            self.table.item(pair, volts_col).setText(f"{r.voltage:8.4f}")
            # Always show pressure or fault status in the pressure column
            self.table.item(pair, press_col).setText(r.display_text())
            self.table.item(pair, status_col).setText("" if r.ok else r.status.value)

            if r.status in (GaugeStatus.FAULT, GaugeStatus.NEGATIVE):
                bg = ROW_FAULT_BG
            elif r.status in (GaugeStatus.UNDER, GaugeStatus.OVER):
                bg = ROW_RANGE_BG
            elif r.status is GaugeStatus.APPROX:
                bg = ROW_APPROX_BG
            else:
                bg = QColor(Qt.transparent)
            for col in (press_col, volts_col, status_col):
                self.table.item(pair, col).setBackground(bg)
        self._building = False

    def _update_series(self, sample: Sample) -> None:
        # Never trim data that still falls within the visible plot window.
        keep = max(self.settings.history_s, self.settings.plot_window_s)
        oldest = sample.timestamp - keep
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

    # =====================================================================
    def closeEvent(self, event) -> None:
        problem = self._harvest_widgets().save()
        if problem:
            print(problem, file=sys.stderr)  # the window is closing; stderr is all we have
        # Use a blocking call so the worker's stop() (and LJM handle close)
        # finishes on the worker thread before we quit it.  A queued emit
        # would race with thread.quit() and could leave the device open.
        QMetaObject.invokeMethod(self.worker, "stop", Qt.BlockingQueuedConnection)
        self.thread.quit()
        self.thread.wait(5000)
        # Final safety net: close every LJM handle in the process so the
        # next launch starts with a clean slate (no phantom handles).
        self.worker.cleanup()
        self.logger.close()
        super().closeEvent(event)
