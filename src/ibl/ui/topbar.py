"""The top bar: Connect, Simulation, Dark mode, the link dot, the status line, CSV label."""
from __future__ import annotations

import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from .. import driver
from ..link import DOT_COLORS, LinkState

DOT = "●"


def _dot_style(color: str) -> str:
    return f"color: {color}; font-size: 18px;"


class TopBar(QWidget):
    connect_clicked = Signal()
    install_clicked = Signal()
    open_log_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        bar = QHBoxLayout(self)
        bar.setContentsMargins(0, 0, 0, 0)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setFixedWidth(110)
        self.btn_connect.clicked.connect(self.connect_clicked)
        bar.addWidget(self.btn_connect)

        self.chk_sim = QCheckBox("Simulation mode")
        self.chk_sim.setToolTip("Generate fake gauge data so the program can be "
                                "used with no LabJack attached.")
        bar.addWidget(self.chk_sim)

        self.chk_dark = QCheckBox("Dark mode")
        bar.addWidget(self.chk_dark)

        self.lbl_link = QLabel(DOT)
        self.lbl_link.setStyleSheet(_dot_style(DOT_COLORS[LinkState.IDLE]))
        self.lbl_link.setFixedWidth(16)
        bar.addWidget(self.lbl_link)

        self.lbl_status = QLabel("")
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(self.lbl_status, 1)

        self.btn_install = QPushButton("Install driver")
        self.btn_install.setToolTip("Install the LabJack LJM driver that "
                                    "ships in this folder.")
        self.btn_install.clicked.connect(self.install_clicked)
        self.btn_install.hide()
        bar.addWidget(self.btn_install)

        self.lbl_csv = QLabel("CSV: off")
        bar.addWidget(self.lbl_csv)

        btn_open = QPushButton("Open log folder")
        btn_open.clicked.connect(self.open_log_clicked)
        bar.addWidget(btn_open)

    def show_link(self, dot_color: str, text: str) -> None:
        """Draw the dot and the status line; called only from MainWindow._render_link."""
        self.lbl_link.setStyleSheet(_dot_style(dot_color))
        self.lbl_link.setText(DOT)
        self.lbl_status.setText(text)

    def run_installer(self) -> bool:
        """Offer the bundled LabJack installer.  True if it was launched."""
        path = driver.find_installer()
        if not path:
            QMessageBox.information(
                self, "Install driver",
                "No LabJack installer was bundled with this program.\n\n"
                "Download and run the LJM software installer from labjack.com.")
            return False
        if QMessageBox.question(
                self, "Install LabJack driver",
                "This will launch the LabJack LJM installer.\n\n"
                "Windows will ask for administrator permission.  When it "
                "finishes, close and reopen IBL Pressure so it can find the "
                "driver.\n\nContinue?") != QMessageBox.Yes:
            return False
        if driver.launch_installer(path):
            return True
        QMessageBox.warning(self, "Install driver",
                            "Could not launch the installer:\n" + path)
        return False

    def open_folder(self, path: str) -> None:
        try:
            os.makedirs(path, exist_ok=True)
            os.startfile(path)  # type: ignore[attr-defined]  (Windows)
        except Exception:  # noqa: BLE001 - any failure is reported or handled here
            QMessageBox.information(self, "Log folder", path)
