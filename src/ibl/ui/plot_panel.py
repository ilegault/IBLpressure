"""The plot: time span, Y range, one curve per channel, legend, grid and caption."""
from __future__ import annotations

import math

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..channels import CHANNELS
from ..config import Settings
from ..help_text import HELP_HINT
from ..history import (
    RAW_SPAN_S,
    SUMMARY_BUCKET_S,
    History,
    minmax_decimate,
    redraw_interval_s,
)
from ..theme import CHANNEL_COLORS, LIGHT_THEME, TIME_SPANS
from .widgets import CompactSpin, TorrAxis

pg.setConfigOptions(antialias=True)


class PlotPanel(QWidget):
    span_changed = Signal()
    clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chan_index = {c.ain: i for i, c in enumerate(CHANNELS)}
        self._last_redraw = -math.inf            # clock of the last redraw
        self.curves: dict[int, pg.PlotDataItem] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Time span:"))
        self.cmb_span = QComboBox()
        for label, secs in TIME_SPANS:
            self.cmb_span.addItem(label, secs)
        self.cmb_span.currentIndexChanged.connect(self.span_changed)
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
        btn_clear.clicked.connect(self.clear_requested)
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
        # pyqtgraph would otherwise "helpfully" rescale Torr to mTorr.
        for name in ("left", "right", "bottom"):
            self.plot.getAxis(name).enableAutoSIPrefix(False)
        self.plot.setLogMode(x=False, y=True)
        self.legend = self.plot.addLegend(offset=(8, 8), labelTextSize="8pt")
        self.lbl_plot_note = QLabel(
            f"Older than {RAW_SPAN_S // 3600} h: min/max per {SUMMARY_BUCKET_S} s")
        self.lbl_plot_note.setToolTip(
            f"Only the most recent {RAW_SPAN_S // 3600} h is kept sample by sample; older "
            f"data is summarised as the lowest and highest reading of each "
            f"{SUMMARY_BUCKET_S} s, so spikes still show. {HELP_HINT}")
        self.lbl_plot_note.setVisible(False)
        lay.addWidget(self.lbl_plot_note)
        lay.addWidget(self.plot, 1)

        for ch in CHANNELS:
            curve = self.plot.plot([], [], pen=pg.mkPen("w"), connect="finite")
            curve.setVisible(False)
            self.curves[ch.ain] = curve

        self.apply_theme(LIGHT_THEME)
        self._apply_y_mode()

    # -- span ------------------------------------------------------------------
    def span_s(self) -> int:
        return int(self.cmb_span.currentData() or 300)

    def set_span(self, window_s: int) -> None:
        idx = max(0, next((i for i, (_, sec) in enumerate(TIME_SPANS) if sec >= window_s), 1))
        self.cmb_span.setCurrentIndex(idx)

    # -- theme and appearance ---------------------------------------------------
    def apply_theme(self, theme: dict) -> None:
        self.plot.setBackground(theme["pg_bg"])
        for axis_name in ("left", "bottom", "right"):
            axis = self.plot.getAxis(axis_name)
            axis.setPen(theme["pg_fg"])
            axis.setTextPen(theme["pg_fg"])
        self.plot.getAxis("left").setLabel("Pressure [Torr]", color=theme["pg_fg"])

        self.legend.setBrush(pg.mkBrush(*theme["legend_brush"]))
        self.legend.setPen(pg.mkPen(theme["legend_pen"]))
        for item in self.legend.items:
            for single in item:
                if isinstance(single, pg.graphicsItems.LabelItem.LabelItem):
                    single.setText(single.text, color=theme["pg_fg"])

    def apply_appearance(self, settings: Settings) -> None:
        alpha = int(settings.curve_alpha / 100 * 255)
        for ch in CHANNELS:
            color = pg.mkColor(CHANNEL_COLORS[ch.ain])
            pen = pg.mkPen((color.red(), color.green(), color.blue(), alpha),
                           width=settings.curve_width)
            self.curves[ch.ain].setPen(pen)
        self.plot.showGrid(x=settings.show_grid, y=settings.show_grid,
                           alpha=settings.grid_alpha / 100)
        self.legend.setVisible(settings.show_legend)

    def set_plotted(self, ains) -> None:
        """Show the curves for `ains`, and list only those in the legend, so 14
        entries do not cover the graph when two channels are being watched."""
        wanted = set(ains)
        self.legend.clear()
        for ch in CHANNELS:
            self.curves[ch.ain].setVisible(ch.ain in wanted)
            if ch.ain in wanted:
                self.legend.addItem(self.curves[ch.ain], ch.name)

    def _apply_y_mode(self, *_args) -> None:
        if self.chk_autoy.isChecked():
            self.plot.enableAutoRange(axis="y")
        else:
            lo = min(self.spn_ymin.value(), self.spn_ymax.value() - 1)
            hi = max(self.spn_ymax.value(), lo + 1)
            self.plot.disableAutoRange(axis="y")
            self.plot.setYRange(lo, hi, padding=0)   # log mode: these are exponents

    # -- drawing ------------------------------------------------------------------
    def redraw_due(self, now: float, sample_hz: float) -> bool:
        return now - self._last_redraw >= redraw_interval_s(
            self.span_s(), self.plot.width(), sample_hz)

    def redraw(self, history: History, now: float, gap_s: float) -> None:
        span = self.span_s()
        self._last_redraw = now
        since = now - span
        self.lbl_plot_note.setVisible(span > RAW_SPAN_S)
        n_buckets = max(100, self.plot.width())
        t1 = math.nextafter(now, math.inf)   # History.window excludes t1; keep a Sample at `now`
        any_data = False
        for ch in CHANNELS:
            curve = self.curves[ch.ain]
            if not curve.isVisible():
                continue
            t, lo, hi = history.window(self._chan_index[ch.ain], since, t1)
            t, p = minmax_decimate(t, lo, hi, since, now, n_buckets, gap_s)
            if np.isfinite(p).any():
                any_data = True
            curve.setData(t, p)
        if any_data:
            self.plot.setXRange(since, now, padding=0)
