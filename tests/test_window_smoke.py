"""Headless Qt works: the main window builds in Simulation mode."""
from ibl import config
from ibl.config import Settings
from ibl.mainwindow import MainWindow


def _make_window(qtbot, tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    # Settings.save/load take SETTINGS_PATH as a default argument, bound when the
    # function was defined, so patching the module constant alone would not redirect them.
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))

    window = MainWindow(Settings(simulate=True, csv_enabled=False))
    qtbot.addWidget(window)
    return window


def test_window_opens_in_simulation(qtbot, tmp_path, monkeypatch):
    window = _make_window(qtbot, tmp_path, monkeypatch)

    assert window.topbar.lbl_status.text() == "Not connected. Press Connect."
    assert "#999999" in window.topbar.lbl_link.styleSheet()
    # No explicit window.close(): qtbot.addWidget closes it at teardown. A second close
    # would hang, because closeEvent makes a blocking call into a worker thread that the
    # first close already stopped.


def test_window_and_worker_do_not_share_settings(qtbot, tmp_path, monkeypatch):
    window = _make_window(qtbot, tmp_path, monkeypatch)

    assert window.worker._settings is not window.settings


def test_settings_change_reaches_worker_as_a_copy(qtbot, tmp_path, monkeypatch):
    window = _make_window(qtbot, tmp_path, monkeypatch)

    window.topbar.chk_sim.setChecked(not window.settings.simulate)

    qtbot.waitUntil(lambda: window.worker._settings.simulate == window.settings.simulate)
    assert window.worker._settings is not window.settings


def test_spin_ranges_come_from_config(qtbot, tmp_path, monkeypatch):
    window = _make_window(qtbot, tmp_path, monkeypatch)

    assert window.settings_panel.spn_hz.minimum() == config.MIN_SAMPLE_HZ
    assert window.settings_panel.spn_hz.maximum() == config.MAX_SAMPLE_HZ
    assert window.settings_panel.spn_hist.minimum() == config.MIN_HISTORY_S // 3600
    assert window.settings_panel.spn_hist.maximum() == config.MAX_HISTORY_S // 3600
    assert window.settings_panel.spn_csv.minimum() == config.MIN_CSV_INTERVAL_S
    assert window.settings_panel.spn_csv.maximum() == config.MAX_CSV_INTERVAL_S


def test_save_failure_is_shown_in_status_line(qtbot, tmp_path, monkeypatch):
    window = _make_window(qtbot, tmp_path, monkeypatch)
    blocker = tmp_path / "f.txt"
    blocker.write_text("a file")
    monkeypatch.setattr(Settings.save, "__defaults__", (str(blocker / "settings.json"),))

    window.settings_panel.spn_fault.setValue(window.settings_panel.spn_fault.value() + 0.5)

    assert window.topbar.lbl_status.text().startswith("Settings not saved:")
