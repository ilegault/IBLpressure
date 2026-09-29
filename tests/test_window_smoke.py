"""Headless Qt works: the main window builds in Simulation mode."""
from ibl import config
from ibl.config import Settings
from ibl.mainwindow import MainWindow


def test_window_opens_in_simulation(qtbot, tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    # Settings.save/load take SETTINGS_PATH as a default argument, bound when the
    # function was defined, so patching the module constant alone would not redirect them.
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))

    window = MainWindow(Settings(simulate=True, csv_enabled=False))
    qtbot.addWidget(window)

    assert window.lbl_status.text() == "Not connected - press Connect"
    # No explicit window.close(): qtbot.addWidget closes it at teardown. A second close
    # would hang, because closeEvent makes a blocking call into a worker thread that the
    # first close already stopped.
