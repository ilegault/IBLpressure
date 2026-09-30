"""Small reusable widgets: the log-axis label style and the - / + spin box."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QWidget


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

