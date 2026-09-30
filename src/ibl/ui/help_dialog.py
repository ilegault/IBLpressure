"""The read-only Help dialog. The text itself lives in ibl.help_text."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

from ..config import Settings
from ..help_text import help_html


class HelpDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("How IBL Pressure works")
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.setReadOnly(True)
        self.browser.setHtml(help_html(settings))
        lay.addWidget(self.browser)
