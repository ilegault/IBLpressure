"""The window runs on the Supervisor: connect, escalate, quit, settings.

May fake: the child handle (FakeChild, from test_supervisor) and the clock.
Must be real: MainWindow, Supervisor, LinkMonitor.
"""
from __future__ import annotations

import pytest
from PySide6.QtCore import QThread
from test_supervisor import UP, Spawner

from ibl import config
from ibl.acquisition import ApplySettings, Lost, SampleReady, Start
from ibl.channels import CHANNELS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.mainwindow import MainWindow
from ibl.model import Sample
from ibl.supervisor import Supervisor
from ibl.ui.table_panel import COL_CG_PRESS, COL_IG_PRESS

GREEN = "#2ca02c"


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _sample(t):
    readings = [convert(ch.ain, 7.0 if ch.is_ion else 0.435, ch.is_ion, 10.0) for ch in CHANNELS]
    return Sample(t, readings)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def spawn():
    return Spawner()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, clock, spawn):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))
    w = MainWindow(Settings(simulate=True, csv_enabled=False, sample_hz=1.0,
                            late_after_samples=3),
                   supervisor=Supervisor(spawn=spawn))
    qtbot.addWidget(w)
    w._now = clock
    return w


def _numbers_shown(window):
    table = window.table_panel.table
    cells = [table.item(p, c).text() for p in range(7) for c in (COL_IG_PRESS, COL_CG_PRESS)]
    return all(text not in ("STALE", "") for text in cells)


def test_connect_goes_live_through_supervisor(window, spawn, clock):
    window._toggle_connection()
    child = spawn.children[0]
    assert isinstance(child.sent[0], Start)

    clock.t = 1.0
    child.incoming = [UP, SampleReady(_sample(1.0))]
    window._poll_supervisor()
    window._render_link()

    assert GREEN in window.topbar.lbl_link.styleSheet()
    assert window.topbar.lbl_status.text().startswith("Live ·")
    assert _numbers_shown(window)


def test_escalation_shows_on_status_line(window, spawn, clock):
    window._toggle_connection()
    child = spawn.children[0]
    clock.t = 1.0
    child.incoming = [UP, SampleReady(_sample(1.0))]
    window._poll_supervisor()

    clock.t = 5.0
    child.incoming = [Lost("timeout")]
    window._poll_supervisor()
    window._render_link()
    assert window.topbar.lbl_status.text() == "Reconnecting — Reopen (attempt 1 of 3)…"

    clock.t = 6.0
    child.incoming = [UP, SampleReady(_sample(6.0))]
    window._poll_supervisor()
    window._render_link()
    text = window.topbar.lbl_status.text()
    assert text.startswith("Live · Recovered at")
    assert text.endswith("(Reopen)")


def test_failed_attempt_shows_the_error_and_next_try(window, spawn, clock):
    from ibl.acquisition import LinkDown
    window._toggle_connection()
    child = spawn.children[0]
    clock.t = 1.0
    child.incoming = [LinkDown("1298 LJME_ATTR_LOAD_COMM_FAILURE")]
    window._poll_supervisor()
    window._render_link()
    assert window.topbar.lbl_status.text() == (
        "T7 not found: 1298 LJME_ATTR_LOAD_COMM_FAILURE. Next try in 5 s.")
    assert "1298 LJME_ATTR_LOAD_COMM_FAILURE" in window.topbar.lbl_status.toolTip()


def test_quit_never_waits_on_a_stuck_child(window, spawn):
    window._toggle_connection()
    child = spawn.children[0]            # its join() leaves it alive: a child stuck in LJM
    window.close()
    assert child.killed
    # QObject.thread() always exists as a method, so test for what was meant: no acquisition
    # QThread owned by the window and no worker object.
    assert window.findChildren(QThread) == []
    assert not hasattr(window, "worker")


def test_disconnect_stops_the_child_and_goes_idle(window, spawn, clock):
    window._toggle_connection()
    child = spawn.children[0]
    window._toggle_connection()
    assert child.killed
    assert window.topbar.lbl_status.text() == "Not connected. Press Connect."
    assert window.topbar.btn_connect.text() == "Connect"


def test_settings_change_reaches_child_as_copy(window, spawn):
    window._toggle_connection()
    child = spawn.children[0]
    window.settings_panel.spn_hz.setValue(2.0)
    sent = [c for c in child.sent if isinstance(c, ApplySettings)]
    assert sent
    s = sent[-1].settings
    assert s is not window.settings
    assert s.sample_hz == 2.0


def test_connect_hands_the_child_a_copy_of_settings(window, spawn):
    window._toggle_connection()
    start = spawn.children[0].sent[0]
    assert start.settings == window.settings
    assert start.settings is not window.settings
    assert spawn.settings[0] is not window.settings


def test_poll_timer_runs_every_100_ms(window):
    assert window._poll_timer.interval() == 100
    assert window._poll_timer.isActive()


def test_real_child_drives_the_real_window(qtbot, tmp_path, monkeypatch):
    """No fakes: a spawned acquisition process in Simulation mode makes the window Live."""
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))
    w = MainWindow(Settings(simulate=True, csv_enabled=False, sample_hz=10.0))
    qtbot.addWidget(w)
    w._toggle_connection()
    qtbot.waitUntil(lambda: w.topbar.lbl_status.text().startswith("Live ·"), timeout=20000)
    assert GREEN in w.topbar.lbl_link.styleSheet()
    assert _numbers_shown(w)
    child = w.supervisor.child
    w.close()
    assert not child.alive()
