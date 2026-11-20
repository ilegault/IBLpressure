"""The window writes the Link log. Real LinkLog and file under tmp_path; fake child and clock."""
from __future__ import annotations

import datetime as _dt
import glob
import os
import time

import pytest
from test_supervisor import UP, Spawner

from ibl import config
from ibl.acquisition import LibraryReset, LinkDown, Lost, Reopen, SampleReady, Start
from ibl.acquisition import ReadError as ChildReadError
from ibl.channels import CHANNELS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.linklog import local_day
from ibl.mainwindow import MainWindow
from ibl.model import Sample
from ibl.supervisor import Supervisor


class Clock:
    def __init__(self):
        self.t = time.time()        # APP_START is stamped with the real clock

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
def make_window(qtbot, tmp_path, monkeypatch, clock, spawn):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))

    def make(csv_dir=None):
        csv_dir = csv_dir or str(tmp_path / "data")
        w = MainWindow(
            Settings(simulate=True, csv_enabled=False, sample_hz=1.0, late_after_samples=3,
                     csv_dir=csv_dir, connection="USB", identifier="ANY"),
            supervisor=Supervisor(spawn=spawn))
        qtbot.addWidget(w)
        w._now = clock
        return w

    return make


@pytest.fixture
def window(make_window):
    return make_window()


def _log_lines(csv_dir) -> list[str]:
    lines: list[str] = []
    for path in sorted(glob.glob(os.path.join(str(csv_dir), "link-log", "*.log"))):
        with open(path, encoding="utf-8") as fh:
            lines.extend(fh.read().splitlines())
    return lines


def _kinds(lines) -> list[str]:
    return [line.split("  ")[1] for line in lines]


def _answer_open_requests(child, answered):
    """Fail every Start / Reopen / LibraryReset the child has not yet answered."""
    requests = [c for c in child.sent if isinstance(c, (Start, Reopen, LibraryReset))]
    for _ in requests[answered:]:
        child.incoming.append(LinkDown("1298"))
    return len(requests)


def test_session_is_logged(window, spawn, clock, tmp_path):
    window._toggle_connection()
    child = spawn.children[0]
    clock.t += 1
    child.incoming = [UP, SampleReady(_sample(clock.t))]
    window._poll_supervisor()
    window._toggle_connection()
    window.close()

    lines = _log_lines(tmp_path / "data")
    assert _kinds(lines) == ["APP_START", "CONNECT", "LINK_UP", "DISCONNECT", "APP_STOP"]
    link_up = lines[2]
    for expected in (UP.description, UP.ljm_version, UP.firmware, "USB", "ANY", "1 Hz"):
        assert expected in link_up


def test_closing_twice_writes_one_app_stop(window, tmp_path):
    window.close()
    window.close()
    assert _kinds(_log_lines(tmp_path / "data")).count("APP_STOP") == 1


def test_watchdog_warning_is_in_the_link_up_line(window, spawn, clock, tmp_path):
    from ibl.acquisition import LinkUp
    window._toggle_connection()
    spawn.children[0].incoming = [LinkUp("T7 #1 over USB", "1.2300", "1.0234",
                                         "Device watchdog not set: bad")]
    window._poll_supervisor()
    link_up = next(x for x in _log_lines(tmp_path / "data") if "  LINK_UP  " in x)
    assert "Device watchdog not set: bad" in link_up


def test_recovery_line_names_step_and_gap(window, spawn, clock, tmp_path):
    window._toggle_connection()
    child = spawn.children[0]
    t0 = clock.t
    child.incoming = [UP, SampleReady(_sample(t0))]
    window._poll_supervisor()

    clock.t = t0 + 1
    child.incoming = [ChildReadError("timeout")] * 3 + [Lost("timeout")]
    window._poll_supervisor()
    answered = 0
    while LibraryReset() not in child.sent:
        clock.t += 0.5
        answered = _answer_open_requests(child, answered)
        window._poll_supervisor()
    clock.t = t0 + 42
    child.incoming = [UP, SampleReady(_sample(clock.t))]
    window._poll_supervisor()

    lines = _log_lines(tmp_path / "data")
    assert lines[-1].endswith("  RECOVERED  Library reset · gap 42 s")
    kinds = _kinds(lines)
    assert "LOST" in kinds and "RECONNECTING" in kinds and "LINK_DOWN" in kinds
    assert "READ_ERROR" in kinds


def test_overnight_failure_stays_short(window, spawn, clock, tmp_path):
    window._toggle_connection()
    t0 = clock.t
    answered: dict[int, int] = {}
    while clock.t < t0 + 8 * 3600:
        for i, child in enumerate(spawn.children):
            answered[i] = _answer_open_requests(child, answered.get(i, 0))
        window._poll_supervisor()
        clock.t += 2.0
    lines = _log_lines(tmp_path / "data")
    kinds = _kinds(lines)
    assert len(lines) < 300
    assert kinds.count("HAND_OFF") == 1
    assert any("REPEATED" in line and "LINK_DOWN" in line for line in lines)
    assert len(spawn.children) > 100            # it really did keep restarting all night


def test_link_log_follows_csv_folder(make_window, tmp_path):
    window = make_window()
    new_dir = tmp_path / "elsewhere"
    window.settings_panel.txt_csvdir.setText(str(new_dir))
    window.settings_panel.txt_csvdir.editingFinished.emit()
    window._toggle_connection()
    assert "CONNECT" in _kinds(_log_lines(new_dir))
    assert "CONNECT" not in _kinds(_log_lines(tmp_path / "data"))


def test_link_log_failure_is_reported(make_window, spawn, clock, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "link-log").write_text("a file where the folder should be")
    window = make_window(str(data))
    window._toggle_connection()
    window._render_link()
    assert window.topbar.lbl_status.text().startswith("Link log not written:")
    # the app keeps running: a child was still started
    assert isinstance(spawn.children[0].sent[0], Start)


def test_summary_rolls_over_at_midnight_without_a_link_event(window, clock, qtbot):
    window._log("RECOVERED", step="Acquisition restart", gap_s=64)
    label = window.settings_panel.lbl_link_summary
    assert label.text() == "Today: 1 recovery — Acquisition restart 1 · longest gap 64 s"

    day_before = local_day(clock.t)
    clock.t = (
        _dt.datetime.fromtimestamp(clock.t, tz=_dt.UTC).astimezone()
        + _dt.timedelta(days=1)
    ).replace(hour=1, minute=0, second=0, microsecond=0).timestamp()
    assert local_day(clock.t) != day_before

    qtbot.waitUntil(lambda: label.text() == "Today: no recoveries", timeout=2000)

    lst = window.settings_panel.lst_link_events
    rows = [lst.item(i).text() for i in range(lst.count())]
    assert any("RECOVERED  Acquisition restart · gap 64 s" in row for row in rows)


def test_connection_frame_refreshes_only_when_day_changes(window, clock, monkeypatch):
    calls = 0
    orig = window._refresh_connection_frame

    def counted():
        nonlocal calls
        calls += 1
        orig()

    monkeypatch.setattr(window, "_refresh_connection_frame", counted)

    window._refresh_connection_frame_on_new_day()
    assert calls == 0

    clock.t = (
        _dt.datetime.fromtimestamp(clock.t, tz=_dt.UTC).astimezone()
        + _dt.timedelta(days=1)
    ).replace(hour=1, minute=0, second=0, microsecond=0).timestamp()
    window._refresh_connection_frame_on_new_day()
    assert calls == 1

    window._refresh_connection_frame_on_new_day()
    assert calls == 1
