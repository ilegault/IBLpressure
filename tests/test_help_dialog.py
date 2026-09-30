"""The Help button, the dialog it opens, and the tooltips that point to it."""
import pytest
from PySide6.QtWidgets import QApplication, QTextBrowser

from ibl import config
from ibl.config import Settings
from ibl.mainwindow import MainWindow
from ibl.ui.help_dialog import HelpDialog

HINT = "(Help explains more.)"


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))
    w = MainWindow(Settings(simulate=True, csv_enabled=False))
    qtbot.addWidget(w)
    return w


def test_help_button_opens_dialog_with_status_light_section(window, qtbot):
    assert window.topbar.btn_help.text() == "Help"
    window.topbar.btn_help.click()
    dialogs = [w for w in QApplication.topLevelWidgets()
               if isinstance(w, HelpDialog) and w.isVisible()]
    assert len(dialogs) == 1
    dlg = dialogs[0]
    assert dlg.windowTitle() == "How IBL Pressure works"
    browser = dlg.findChild(QTextBrowser)
    assert browser.isReadOnly()
    assert "Status light" in browser.toPlainText()
    dlg.close()


def test_help_text_reflects_current_settings(window, qtbot):
    window.settings.sample_hz = 0.5
    window.settings.late_after_samples = 2
    dlg = window.show_help()
    qtbot.addWidget(dlg)
    assert "4.0 s" in dlg.findChild(QTextBrowser).toPlainText()


def test_tooltips_point_to_help(window):
    widgets = [
        window.topbar.lbl_link,
        window.topbar.lbl_status,
        window.plot_panel.lbl_plot_note,
        window.settings_panel.spn_late,
        window.settings_panel.lbl_csv_size,
    ]
    for w in widgets:
        assert w.toolTip().endswith(HINT), w
