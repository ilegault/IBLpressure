"""The live table: 14 gauges in 7 rows, plot checkboxes and the Plot all/none buttons."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..channels import CHANNELS, PAIRS, pair_index
from ..config import Settings
from ..model import GaugeStatus, Sample
from ..theme import CHANNEL_COLORS, LIGHT_THEME

COL_IG_PLOT, COL_CG_PLOT, COL_LOC = 0, 1, 2
COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS = 3, 4, 5
COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS = 6, 7, 8
NUM_PAIRS = len(PAIRS)
DATA_COLS = (COL_LOC, COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS,
             COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS)


def _cols(is_ion: bool) -> tuple[int, int, int]:
    """(pressure, volts, status) columns of an Ion Gauge or a Convectron."""
    if is_ion:
        return COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS
    return COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS


class TablePanel(QWidget):
    plotted_changed = Signal()      # a plot checkbox changed (once per bulk change)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme: dict = LIGHT_THEME
        self._quiet = False         # True while the panel itself edits its cells
        lay = QVBoxLayout(self)
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
        self._fill_table()
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)

        row = QHBoxLayout()
        for text, fn in (
            ("Plot all", lambda: self.set_plotted(lambda c: True)),
            ("Plot none", lambda: self.set_plotted(lambda c: False)),
            ("Ion only", lambda: self.set_plotted(lambda c: c.is_ion)),
            ("Convectron only", lambda: self.set_plotted(lambda c: not c.is_ion)),
        ):
            b = QPushButton(text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

    def _fill_table(self) -> None:
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.Monospace)
        mono_big_bold = QFont("Consolas", 12)
        mono_big_bold.setStyleHint(QFont.Monospace)
        mono_big_bold.setBold(True)

        for pair in range(NUM_PAIRS):
            ig_ch, cg_ch = PAIRS[pair]
            for col, ch in ((COL_IG_PLOT, ig_ch), (COL_CG_PLOT, cg_ch)):
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Unchecked)
                chk.setBackground(QColor(CHANNEL_COLORS[ch.ain]))
                self.table.setItem(pair, col, chk)

            self.table.setItem(pair, COL_LOC, QTableWidgetItem(ig_ch.location))

            for col, font in ((COL_IG_VOLTS, mono), (COL_CG_VOLTS, mono),
                              (COL_IG_PRESS, mono_big_bold), (COL_CG_PRESS, mono_big_bold)):
                item = QTableWidgetItem("---")
                item.setFont(font)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(pair, col, item)

            self.table.setItem(pair, COL_IG_STATUS, QTableWidgetItem(""))
            self.table.setItem(pair, COL_CG_STATUS, QTableWidgetItem(""))

        hh = self.table.horizontalHeader()
        for col in (COL_IG_PLOT, COL_CG_PLOT):
            hh.setSectionResizeMode(col, QHeaderView.Fixed)
            self.table.setColumnWidth(col, 42)
        for col in DATA_COLS:
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)

    # -- theme and appearance ------------------------------------------------
    def apply_theme(self, theme: dict) -> None:
        self._theme = theme

    def apply_appearance(self, settings: Settings) -> None:
        size = settings.table_font_size
        font = QFont("Consolas", size)
        font.setStyleHint(QFont.Monospace)
        font.setBold(True)
        loc_font = QFont("Consolas", settings.loc_font_size)
        loc_font.setStyleHint(QFont.Monospace)
        for pair in range(NUM_PAIRS):
            for col in (COL_IG_PRESS, COL_CG_PRESS):
                self.table.item(pair, col).setFont(font)
            self.table.item(pair, COL_LOC).setFont(loc_font)
        row_h = max(22, int(size * 2.4))
        self.table.verticalHeader().setDefaultSectionSize(row_h)
        for col in (COL_IG_PLOT, COL_CG_PLOT):
            self.table.setColumnWidth(col, max(22, row_h))
        visible = set(settings.table_visible_cols)
        for col in DATA_COLS:
            self.table.setColumnHidden(col, col not in visible)

    # -- which channels are plotted -------------------------------------------
    def plotted_ains(self) -> list[int]:
        return [
            ain
            for pair in range(NUM_PAIRS)
            for col, ain in ((COL_IG_PLOT, PAIRS[pair][0].ain), (COL_CG_PLOT, PAIRS[pair][1].ain))
            if self.table.item(pair, col).checkState() == Qt.Checked
        ]

    def load_plotted(self, ains) -> None:
        """Tick the boxes for `ains` without announcing a change."""
        wanted = set(ains)
        self._quiet = True
        for pair in range(NUM_PAIRS):
            for col, ch in ((COL_IG_PLOT, PAIRS[pair][0]), (COL_CG_PLOT, PAIRS[pair][1])):
                self.table.item(pair, col).setCheckState(
                    Qt.Checked if ch.ain in wanted else Qt.Unchecked)
        self._quiet = False

    def set_plotted(self, predicate) -> None:
        """Plot exactly the channels for which `predicate(channel)` is true."""
        self.load_plotted(c.ain for c in CHANNELS if predicate(c))
        self.plotted_changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._quiet or item.column() not in (COL_IG_PLOT, COL_CG_PLOT):
            return
        self.plotted_changed.emit()

    # -- showing readings -----------------------------------------------------
    def show_sample(self, sample: Sample) -> None:
        theme = self._theme
        self._quiet = True
        by_ain = sample.by_ain()
        for ch in CHANNELS:
            r = by_ain.get(ch.ain)
            if r is None:
                continue
            pair = pair_index(ch.ain)
            press_col, volts_col, status_col = _cols(ch.is_ion)

            self.table.item(pair, volts_col).setText(f"{r.voltage:8.4f}")
            self.table.item(pair, press_col).setText(r.display_text())
            self.table.item(pair, status_col).setText("" if r.ok else r.status.value)

            if r.status in (GaugeStatus.FAULT, GaugeStatus.NEGATIVE):
                bg = QColor(theme["fault_bg"])
            elif r.status in (GaugeStatus.UNDER, GaugeStatus.OVER):
                bg = QColor(theme["range_bg"])
            elif r.status is GaugeStatus.APPROX:
                bg = QColor(theme["approx_bg"])
            else:
                bg = QColor(Qt.transparent)
            for col in (press_col, volts_col, status_col):
                self.table.item(pair, col).setBackground(bg)
        self._quiet = False

    def show_stale(self, sample: Sample, age_s: float) -> None:
        """Replace every pressure number with STALE; the last value and its age
        go in that gauge's Status cell."""
        stale_bg = QColor(self._theme["stale_bg"])
        by_ain = sample.by_ain()
        self._quiet = True
        for ch in CHANNELS:
            r = by_ain.get(ch.ain)
            if r is None:
                continue
            pair = pair_index(ch.ain)
            press_col, volts_col, status_col = _cols(ch.is_ion)
            self.table.item(pair, press_col).setText("STALE")
            self.table.item(pair, status_col).setText(
                f"last {r.display_text()}, {age_s:.0f} s ago")
            for col in (press_col, volts_col, status_col):
                self.table.item(pair, col).setBackground(stale_bg)
        self._quiet = False
