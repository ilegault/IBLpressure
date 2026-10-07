"""The window's dot, status line and table are all drawn from one LinkView.

The window's clock is faked (`window._now`) and the slots are called directly with
hand-built Samples, so nothing here waits on the real worker thread.
"""
import pytest

from ibl import config
from ibl.channels import CHANNELS, PAIRS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.escalation import Attempt, Step
from ibl.mainwindow import MainWindow
from ibl.model import Sample
from ibl.theme import DARK_THEME, LIGHT_THEME
from ibl.ui.table_panel import COL_CG_PRESS, COL_CG_STATUS, COL_IG_PRESS, COL_IG_STATUS

GREEN, AMBER = "#2ca02c", "#ff9f1a"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, clock):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))
    w = MainWindow(Settings(simulate=True, csv_enabled=False, sample_hz=1.0,
                            late_after_samples=3))
    qtbot.addWidget(w)
    w._now = clock
    return w


def _sample(t, volts=None):
    volts = volts or {}
    readings = [
        convert(ch.ain, volts.get(ch.ain, 7.0 if ch.is_ion else 0.435), ch.is_ion, 10.0)
        for ch in CHANNELS
    ]
    return Sample(t, readings)


def _connect(window, clock):
    """Press Connect without starting the real worker, and let the T7 report in."""
    window.link.connect_requested(clock.t)
    window._on_link_up("Simulation mode")


def _dot(window):
    return window.topbar.lbl_link.styleSheet()


def _pressure_cells(window):
    return [window.table_panel.table.item(p, c) for p in range(len(PAIRS))
            for c in (COL_IG_PRESS, COL_CG_PRESS)]


def _status_cells(window):
    return [window.table_panel.table.item(p, c) for p in range(len(PAIRS))
            for c in (COL_IG_STATUS, COL_CG_STATUS)]


def test_dot_turns_green_again_after_late(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))

    clock.t = 5.0
    window._render_link()
    assert AMBER in _dot(window)

    clock.t = 5.2
    window._on_sample(_sample(5.2))
    assert GREEN in _dot(window)
    assert window.topbar.lbl_status.text().startswith("Live · Recovered at")


def test_pressure_cells_go_stale(window, clock):
    _connect(window, clock)
    sample = _sample(0.0)
    window._on_sample(sample)

    clock.t = 5.0
    window._render_link()

    by_ain = sample.by_ain()
    for pair, (ig, cg) in enumerate(PAIRS):
        for col, status_col, ch in ((COL_IG_PRESS, COL_IG_STATUS, ig),
                                    (COL_CG_PRESS, COL_CG_STATUS, cg)):
            press = window.table_panel.table.item(pair, col)
            status = window.table_panel.table.item(pair, status_col)
            assert press.text() == "STALE"
            assert status.text() == f"last {by_ain[ch.ain].display_text()}, 5 s ago"
            assert press.background().color().name() == LIGHT_THEME["stale_bg"]


def test_cells_live_again_on_recovery(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))
    clock.t = 5.0
    window._render_link()

    clock.t = 5.2
    window._on_sample(_sample(5.2))

    assert all(c.text() != "STALE" for c in _pressure_cells(window))
    assert all(c.text() == "" for c in _status_cells(window))


def test_one_faulted_gauge_does_not_affect_link(window, clock):
    _connect(window, clock)
    clock.t = 1.0
    window._on_sample(_sample(1.0, {0: 10.9}))
    window._render_link()

    assert GREEN in _dot(window)
    assert window.topbar.lbl_status.text().startswith("Live")
    cells = _pressure_cells(window)
    assert cells[0].text() == "Gauge Fault"
    assert cells[0].background().color().name() == LIGHT_THEME["fault_bg"]
    assert all(c.text() not in ("STALE", "Gauge Fault", "---") for c in cells[1:])
    assert len(cells) == 14


def test_read_error_clears_on_next_sample(window, clock):
    _connect(window, clock)
    clock.t = 1.0
    window._on_sample(_sample(1.0))

    window._on_read_error("timeout")
    assert window.topbar.lbl_status.text().endswith("read error: timeout")

    clock.t = 2.0
    window._on_sample(_sample(2.0))
    assert "read error" not in window.topbar.lbl_status.text()


def test_disconnect_does_not_leave_numbers_on_screen(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))

    window.link.disconnect_requested(1.0)
    clock.t = 1.0
    window._render_link()

    assert window.topbar.lbl_status.text() == "Not connected. Press Connect."
    assert all(c.text() == "STALE" for c in _pressure_cells(window))


def test_link_down_shows_reason_and_stales_table(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))

    clock.t = 2.0
    window._on_link_down("no device")

    assert "#d62728" in _dot(window)
    assert "no device" in window.topbar.lbl_status.text()
    assert all(c.text() == "STALE" for c in _pressure_cells(window))


def test_settings_change_reconfigures_link(window):
    window.settings.sample_hz = 2.0
    window.settings.late_after_samples = 4
    window._on_widget_changed()

    assert window.link.late_threshold_s == pytest.approx(
        window.settings.late_after_samples / window.settings.sample_hz)


def test_settings_problem_is_not_overwritten_by_the_timer(window, clock):
    window._settings_problem = "Settings not saved: disk full"
    window._render_link()

    assert window.topbar.lbl_status.text().startswith("Settings not saved:")


def test_render_timer_runs_every_500_ms(window):
    assert window._link_timer.isActive()
    assert window._link_timer.interval() == 500


def test_late_after_control_shows_seconds_and_drives_the_monitor(window):
    window.settings_panel.spn_hz.setValue(0.5)
    window.settings_panel.spn_late.setValue(2)
    assert window.settings_panel.lbl_late_preview.text() == "= 4.0 s at 0.5 Hz"
    assert window.link.late_threshold_s == 4.0
    assert window.settings.late_after_samples == 2


def test_csv_size_preview_follows_interval_and_volts(window):
    window.settings_panel.spn_csv.setValue(10)
    window.settings_panel.chk_csvv.setChecked(False)
    text = window.settings_panel.lbl_csv_size.text()
    assert text.endswith("(8,640 rows)")
    window.settings_panel.chk_csvv.setChecked(True)
    assert window.settings_panel.lbl_csv_size.text() != text


def test_rate_cannot_exceed_ten_hz(window):
    window.settings_panel.spn_hz.setValue(20)
    assert window.settings_panel.spn_hz.value() == 10.0
    assert window.settings.sample_hz == 10.0


def test_dark_mode_changes_stale_colour(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))

    window.topbar.chk_dark.setChecked(True)
    clock.t = 5.0
    window._render_link()

    cell = window.table_panel.table.item(0, COL_IG_PRESS)
    assert cell.text() == "STALE"
    assert cell.background().color().name() == DARK_THEME["stale_bg"]


def test_status_tooltip_carries_the_latest_labjack_error(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))

    clock.t = 2.0
    window._on_link_down("1298 LJME_ATTR_LOAD_COMM_FAILURE")
    assert "1298 LJME_ATTR_LOAD_COMM_FAILURE" in window.topbar.lbl_status.toolTip()

    clock.t = 3.0
    window._on_link_up("Simulation mode")
    window._on_sample(_sample(3.0))
    assert "1298 LJME_ATTR_LOAD_COMM_FAILURE" not in window.topbar.lbl_status.toolTip()
    assert "fresh data" in window.topbar.lbl_status.toolTip()      # the normal tooltip is back


def test_reconnecting_signal_still_reads_as_a_reopen(window, clock):
    _connect(window, clock)
    window._on_sample(_sample(0.0))
    clock.t = 2.0
    window._on_reconnecting(Attempt(Step.REOPEN, 2, 3, 2, False))
    assert window.topbar.lbl_status.text() == "Reconnecting — Reopen (attempt 2 of 3)…"
