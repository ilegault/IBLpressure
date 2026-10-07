"""The collapsible settings box: every control that maps onto a Settings field."""
from __future__ import annotations

import math

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    MAX_CSV_INTERVAL_S,
    MAX_HISTORY_S,
    MAX_LATE_AFTER_SAMPLES,
    MAX_SAMPLE_HZ,
    MIN_CSV_INTERVAL_S,
    MIN_HISTORY_S,
    MIN_LATE_AFTER_SAMPLES,
    MIN_SAMPLE_HZ,
    Settings,
    late_preview,
)
from ..csvlogger import estimate_bytes_per_day, format_size_preview
from ..help_text import HELP_HINT
from .table_panel import (
    COL_CG_PRESS,
    COL_CG_STATUS,
    COL_CG_VOLTS,
    COL_IG_PRESS,
    COL_IG_STATUS,
    COL_IG_VOLTS,
    COL_LOC,
)
from .widgets import CompactSpin


class SettingsPanel(QGroupBox):
    """Owns the LabJack, Acquisition, CSV, Plot and Table controls.

    Simulation and Dark mode live on the top bar; the time span and the plotted
    channels live on the plot and table panels.
    """
    changed = Signal()
    open_link_log_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__("Settings", parent)
        box = self
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
        self.cmb_conn.currentIndexChanged.connect(self.changed)
        f.addRow("Connection:", self.cmb_conn)

        self.txt_ident = QLineEdit()
        self.txt_ident.setToolTip("Serial number or IP address. ANY = first T7 found.")
        self.txt_ident.editingFinished.connect(self.changed)
        f.addRow("Identifier:", self.txt_ident)

        self.spn_res = CompactSpin(0, 12, 0)
        self.spn_res.setToolTip("T7 ADC resolution index. Higher = quieter but slower. "
                                "0 uses the device default.")
        self.spn_res.valueChanged.connect(self.changed)
        f.addRow("Resolution index:", self.spn_res)

        # --- Acquisition ---
        f = add(1, "Acquisition")
        self.spn_hz = CompactSpin(MIN_SAMPLE_HZ, MAX_SAMPLE_HZ, 1.0, step=0.5, decimals=2, suffix=" Hz")
        self.spn_hz.valueChanged.connect(self.changed)
        f.addRow("Update rate:", self.spn_hz)

        self.spn_late = CompactSpin(MIN_LATE_AFTER_SAMPLES, MAX_LATE_AFTER_SAMPLES, 3,
                                    suffix=" samples")
        tip = ("The status turns amber (Late) and the table shows STALE "
               "when this many samples in a row are missing. "
               + HELP_HINT)
        self.spn_late.setToolTip(tip)
        self.spn_late.valueChanged.connect(self.changed)
        self.lbl_late_preview = QLabel()
        self.lbl_late_preview.setToolTip(tip)
        late_row = QHBoxLayout()
        late_row.addWidget(self.spn_late)
        late_row.addWidget(self.lbl_late_preview, 1)
        late_wrap = QWidget()
        late_wrap.setLayout(late_row)
        f.addRow("Late after:", late_wrap)

        self.spn_fault = CompactSpin(1.0, 12.0, 10.0, step=0.1, decimals=2, suffix=" V")
        self.spn_fault.setToolTip(
            "Above this the channel reads Gauge Fault.\n"
            "The VGC083A drives its output past +11 V on a fault, but a T7 "
            "analog input saturates just past 10 V, so 10 V is the practical "
            "trip point. Normal output never exceeds 9 V (ion) or 5.66 V "
            "(Convectron)."
        )
        self.spn_fault.valueChanged.connect(self.changed)
        f.addRow("Gauge fault above:", self.spn_fault)

        self.spn_hist = CompactSpin(MIN_HISTORY_S // 3600, MAX_HISTORY_S // 3600, 24, suffix=" hr")
        self.spn_hist.valueChanged.connect(self.changed)
        f.addRow("Keep history:", self.spn_hist)

        # --- CSV ---
        f = add(2, "CSV logging")
        self.chk_csv = QCheckBox("Enabled  (one file per day, named by date)")
        self.chk_csv.toggled.connect(self.changed)
        f.addRow(self.chk_csv)

        self.spn_csv = CompactSpin(MIN_CSV_INTERVAL_S, MAX_CSV_INTERVAL_S, 10.0, step=1.0, decimals=1, suffix=" s")
        self.spn_csv.valueChanged.connect(self.changed)
        f.addRow("Write every:", self.spn_csv)

        self.lbl_csv_size = QLabel()
        self.lbl_csv_size.setToolTip("Estimated size of one day's file at this interval. " + HELP_HINT)
        f.addRow(self.lbl_csv_size)

        folder_row = QHBoxLayout()
        self.txt_csvdir = QLineEdit()
        self.txt_csvdir.editingFinished.connect(self.changed)
        folder_row.addWidget(self.txt_csvdir, 1)
        btn_browse = QPushButton("...")
        btn_browse.setFixedWidth(30)
        btn_browse.clicked.connect(self._browse_csv_dir)
        folder_row.addWidget(btn_browse)
        wrap = QWidget()
        wrap.setLayout(folder_row)
        f.addRow("Folder:", wrap)

        self.chk_csvv = QCheckBox("Also record raw volts")
        self.chk_csvv.toggled.connect(self.changed)
        f.addRow(self.chk_csvv)

        # --- Plot appearance ---
        f = add(3, "Plot")
        self.chk_legend = QCheckBox("Show legend on plot")
        self.chk_legend.toggled.connect(self.changed)
        f.addRow(self.chk_legend)

        self.spn_curve_width = CompactSpin(0.5, 10.0, 1.0, step=0.5, decimals=1, suffix=" px")
        self.spn_curve_width.valueChanged.connect(self.changed)
        f.addRow("Line width:", self.spn_curve_width)

        self.spn_curve_alpha = CompactSpin(0, 100, 31, suffix="%")
        self.spn_curve_alpha.valueChanged.connect(self.changed)
        f.addRow("Line opacity:", self.spn_curve_alpha)

        self.chk_show_grid = QCheckBox("Show background grid")
        self.chk_show_grid.toggled.connect(self.changed)
        f.addRow(self.chk_show_grid)

        self.spn_grid_alpha = CompactSpin(0, 100, 30, suffix="%")
        self.spn_grid_alpha.valueChanged.connect(self.changed)
        f.addRow("Grid opacity:", self.spn_grid_alpha)

        # --- Table appearance ---
        f = add(4, "Table")
        self.spn_table_font = CompactSpin(6, 72, 12, suffix=" pt")
        self.spn_table_font.valueChanged.connect(self.changed)
        f.addRow("Pressure font:", self.spn_table_font)

        self.spn_loc_font = CompactSpin(6, 72, 10, suffix=" pt")
        self.spn_loc_font.valueChanged.connect(self.changed)
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
            chk.toggled.connect(self.changed)
            f.addRow(chk)
            self.col_chk[col] = chk

        # --- Connection: today's recoveries and the latest Link log lines (read-only) ---
        f = add(5, "Connection")
        self.lbl_link_summary = QLabel("Today: no recoveries")
        self.lbl_link_summary.setToolTip(
            "How often the app got the T7 back on its own today, and by which step. "
            + HELP_HINT)
        f.addRow(self.lbl_link_summary)
        self.lst_link_events = QListWidget()
        self.lst_link_events.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.lst_link_events.setSelectionMode(QAbstractItemView.NoSelection)
        self.lst_link_events.setWordWrap(False)
        self.lst_link_events.setMinimumWidth(360)
        self.lst_link_events.setMaximumHeight(110)
        self.lst_link_events.setToolTip(
            "The latest Link log lines, newest first. The full record is in the link-log "
            "folder. " + HELP_HINT)
        f.addRow(self.lst_link_events)
        self.btn_open_link_log = QPushButton("Open Link log")
        self.btn_open_link_log.setToolTip("Open the folder holding the Link log files.")
        self.btn_open_link_log.clicked.connect(self.open_link_log_clicked)
        f.addRow(self.btn_open_link_log)

        grid.setColumnStretch(6, 1)

    def show_connection(self, summary: str, lines: list[str]) -> None:
        """Draw the Connection frame: called only from MainWindow after a Link log record."""
        self.lbl_link_summary.setText(summary)
        self.lst_link_events.clear()
        self.lst_link_events.addItems(lines)

    # -- settings <-> widgets -----------------------------------------------------
    def load(self, s: Settings) -> None:
        self.cmb_conn.setCurrentText(s.connection)
        self.txt_ident.setText(s.identifier)
        self.spn_res.setValue(int(s.resolution_index))
        self.spn_hz.setValue(float(s.sample_hz))
        self.spn_fault.setValue(float(s.fault_volts))
        self.spn_late.setValue(int(s.late_after_samples))
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
        self.update_previews(s)

    def harvest(self, s: Settings) -> Settings:
        """Write this panel's controls into `s` and return it."""
        s.connection = self.cmb_conn.currentText()
        s.identifier = self.txt_ident.text().strip() or "ANY"
        s.resolution_index = self.spn_res.value()
        s.sample_hz = self.spn_hz.value()
        s.fault_volts = self.spn_fault.value()
        s.late_after_samples = self.spn_late.value()
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
        return s

    def update_previews(self, s: Settings) -> None:
        self.lbl_late_preview.setText(late_preview(s.late_after_samples, s.sample_hz))
        rows = math.ceil(86400 / s.csv_interval_s)
        self.lbl_csv_size.setText(format_size_preview(
            estimate_bytes_per_day(s.csv_interval_s, s.csv_include_voltages), rows))

    def _browse_csv_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose the CSV log folder",
                                             self.txt_csvdir.text())
        if d:
            self.txt_csvdir.setText(d)
            self.changed.emit()
