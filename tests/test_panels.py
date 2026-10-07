"""The panels work on their own, with no MainWindow, worker or LinkMonitor."""
import os
import time

import pytest
from PySide6.QtWidgets import QAbstractItemView, QGroupBox, QListWidget, QPushButton
from test_supervisor import Spawner

from ibl import __version__, config
from ibl.channels import CHANNELS, PAIRS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.mainwindow import MainWindow
from ibl.model import Sample
from ibl.supervisor import Supervisor
from ibl.theme import LIGHT_THEME
from ibl.ui.settings_panel import SettingsPanel
from ibl.ui.table_panel import (
    COL_CG_PRESS,
    COL_CG_STATUS,
    COL_CG_VOLTS,
    COL_IG_PRESS,
    COL_IG_STATUS,
    COL_IG_VOLTS,
    TablePanel,
)


def test_settings_panel_round_trip(qtbot):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    s = Settings(
        connection="ETHERNET", identifier="192.168.1.5", resolution_index=5,
        sample_hz=2.5, fault_volts=9.5, late_after_samples=5, history_s=12 * 3600,
        csv_enabled=False, csv_interval_s=30.0, csv_dir="/somewhere/else",
        csv_include_voltages=True, show_legend=True, table_font_size=14,
        loc_font_size=9, table_visible_cols=[2, 3, 5], curve_alpha=50,
        curve_width=2.5, show_grid=False, grid_alpha=60,
    )

    panel.load(s)

    assert panel.harvest(Settings()) == s


def test_fault_sample_colours_only_its_own_row(qtbot):
    panel = TablePanel()
    qtbot.addWidget(panel)
    readings = [
        convert(ch.ain, 10.9 if ch.ain == 0 else (7.0 if ch.is_ion else 0.435),
                ch.is_ion, 10.0)
        for ch in CHANNELS
    ]

    panel.show_sample(Sample(1.0, readings))

    table = panel.table
    fault = LIGHT_THEME["fault_bg"]
    for col in (COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS):
        assert table.item(0, col).background().color().name() == fault
    assert table.item(0, COL_IG_PRESS).text() == "Gauge Fault"
    for pair in range(len(PAIRS)):
        for col in (COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS):
            assert table.item(pair, col).background().color().name() != fault
        if pair:
            for col in (COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS):
                assert table.item(pair, col).background().color().name() != fault


def test_table_panel_reports_plotted_channels(qtbot):
    panel = TablePanel()
    qtbot.addWidget(panel)
    seen = []
    panel.plotted_changed.connect(lambda: seen.append(panel.plotted_ains()))

    panel.set_plotted(lambda c: c.is_ion)

    assert seen == [[c.ain for c in CHANNELS if c.is_ion]]



# --- Connection frame (inside the Settings box) -----------------------------------
@pytest.fixture
def make_window(qtbot, tmp_path, monkeypatch):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))

    def make():
        w = MainWindow(Settings(simulate=True, csv_enabled=False, csv_dir=str(tmp_path / "data")),
                       supervisor=Supervisor(spawn=Spawner()))
        qtbot.addWidget(w)
        w._now = lambda: time.time()
        return w

    return make


def _frame_rows(window):
    lst = window.settings_panel.lst_link_events
    return [lst.item(i).text() for i in range(lst.count())]


def test_settings_box_has_a_connection_group(make_window):
    panel = make_window().settings_panel
    titles = [g.title() for g in panel.findChildren(QGroupBox)]
    assert "Connection" in titles
    assert isinstance(panel.lst_link_events, QListWidget)
    assert panel.lst_link_events.editTriggers() == QAbstractItemView.NoEditTriggers
    buttons = [b.text() for b in panel.findChildren(QPushButton)]
    assert "Open Link log" in buttons
    assert panel.lbl_link_summary.text() == "Today: no recoveries"


def test_frame_shows_todays_summary(make_window):
    window = make_window()
    window._log("RECOVERED", step="Reopen", gap_s=7)
    window._log("RECOVERED", step="Library reset", gap_s=42)
    assert window.settings_panel.lbl_link_summary.text() == (
        "Today: 2 recoveries — Reopen 1, Library reset 1 · longest gap 42 s")


def test_frame_lists_newest_twenty(make_window):
    window = make_window()
    for i in range(25):
        window._log("CONNECT", f"record {i}")
    rows = _frame_rows(window)
    assert len(rows) == config.CONNECTION_FRAME_EVENTS == 20
    assert rows[0].endswith("CONNECT  record 24")
    assert rows[-1].endswith("CONNECT  record 5")


def test_open_link_log_button(make_window, tmp_path, monkeypatch):
    window = make_window()
    opened = []
    monkeypatch.setattr(window.topbar, "open_folder", opened.append)
    window.settings_panel.setChecked(True)          # expand Settings, as the operator would
    window.settings_panel.btn_open_link_log.click()
    assert opened == [os.path.join(str(tmp_path / "data"), "link-log")]


def test_frame_survives_restart(make_window):
    first = make_window()
    first._log("RECOVERED", step="Reopen", gap_s=7)
    first._log("CONNECT", "again")
    before_rows = _frame_rows(first)
    second = make_window()                     # same csv_dir: it reads the month file back
    assert second.settings_panel.lbl_link_summary.text() == (
        "Today: 1 recovery — Reopen 1 · longest gap 7 s")
    assert _frame_rows(second)[1:] == before_rows          # row 0 is the new window's APP_START
    assert _frame_rows(second)[0].endswith(f"APP_START  IBL Pressure v{__version__}")
