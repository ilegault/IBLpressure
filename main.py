"""
IBL Pressure - beamline vacuum monitor.

Reads the analog outputs of the INFICON VGC083A gauge controllers through a
LabJack T7, converts them to pressures, shows them live, plots them, and
logs everything to a daily CSV.

Run from source:   python main.py
Build a Windows exe:  build.bat   (one folder, one window, no console)
"""
from __future__ import annotations

import multiprocessing
import os
import sys
import traceback


def _excepthook(exc_type, exc, tb) -> None:
    """A frozen, windowed exe has no console, so show crashes in a dialog."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    sys.stderr.write(text)
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        if QApplication.instance() is not None:
            QMessageBox.critical(None, "IBL Pressure - unexpected error", text)
    except Exception:  # noqa: BLE001, S110 - pre-existing best-effort cleanup, error ignored
        pass


def _ensure_src_on_path() -> None:
    """From source the package lives in src/; a frozen exe bundles it already."""
    if getattr(sys, "frozen", False):
        return
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
    if src not in sys.path:
        sys.path.insert(0, src)


def main() -> int:
    sys.excepthook = _excepthook
    _ensure_src_on_path()

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)

    app = QApplication(sys.argv)
    app.setApplicationName("IBL Pressure")
    app.setOrganizationName("IBL")

    from ibl.config import Settings
    from ibl.mainwindow import MainWindow

    settings = Settings.load()

    # --simulate on the command line forces demo mode for this run.
    if "--simulate" in sys.argv or "--sim" in sys.argv:
        settings.simulate = True

    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    # The acquisition child is a spawned process; a frozen exe needs this to start it.
    multiprocessing.freeze_support()
    sys.exit(main())
