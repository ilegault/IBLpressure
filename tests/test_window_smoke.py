"""Headless Qt works: the main window builds in Simulation mode."""
import pytest
from test_supervisor import Spawner

from ibl import config
from ibl.acquisition import ApplySettings
from ibl.config import Settings
from ibl.mainwindow import MainWindow
from ibl.supervisor import Supervisor


@pytest.fixture
def spawn():
    return Spawner()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, spawn):
    # A fixture, not a local variable: pytest keeps the window alive until qtbot closes it
    # at teardown, so its timers never outlive it.
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    # Settings.save/load take SETTINGS_PATH as a default argument, bound when the
    # function was defined, so patching the module constant alone would not redirect them.
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))

    window = MainWindow(Settings(simulate=True, csv_enabled=False),
                        supervisor=Supervisor(spawn=spawn))
    qtbot.addWidget(window)
    return window


def test_window_opens_in_simulation(window):
    assert window.topbar.lbl_status.text() == "Not connected. Press Connect."
    assert "#999999" in window.topbar.lbl_link.styleSheet()
    # No explicit window.close(): qtbot.addWidget closes it at teardown.


def test_window_and_worker_do_not_share_settings(window, spawn):
    window._toggle_connection()                      # the acquisition child gets a copy
    assert spawn.settings[0] is not window.settings
    assert spawn.children[0].sent[0].settings is not window.settings


def test_settings_change_reaches_worker_as_a_copy(window, spawn):
    window._toggle_connection()
    window.topbar.chk_sim.setChecked(not window.settings.simulate)

    sent = [c for c in spawn.children[0].sent if isinstance(c, ApplySettings)]
    assert sent[-1].settings.simulate == window.settings.simulate
    assert sent[-1].settings is not window.settings


def test_spin_ranges_come_from_config(window):
    assert window.settings_panel.spn_hz.minimum() == config.MIN_SAMPLE_HZ
    assert window.settings_panel.spn_hz.maximum() == config.MAX_SAMPLE_HZ
    assert window.settings_panel.spn_hist.minimum() == config.MIN_HISTORY_S // 3600
    assert window.settings_panel.spn_hist.maximum() == config.MAX_HISTORY_S // 3600
    assert window.settings_panel.spn_csv.minimum() == config.MIN_CSV_INTERVAL_S
    assert window.settings_panel.spn_csv.maximum() == config.MAX_CSV_INTERVAL_S


def test_save_failure_is_shown_in_status_line(window, tmp_path, monkeypatch):
    blocker = tmp_path / "f.txt"
    blocker.write_text("a file")
    monkeypatch.setattr(Settings.save, "__defaults__", (str(blocker / "settings.json"),))

    window.settings_panel.spn_fault.setValue(window.settings_panel.spn_fault.value() + 0.5)

    assert window.topbar.lbl_status.text().startswith("Settings not saved:")
