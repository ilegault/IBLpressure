"""Acquisition turns commands and ticks into events; the fake LJM stands in for the T7.

May fake: the LJM module and the clock (explicit `now`). Must be real: Acquisition.
"""
from __future__ import annotations

import dataclasses
import os
import pickle
import queue
import subprocess
import sys

import pytest

from ibl import acquisition, config
from ibl.acquisition import (
    Acquisition,
    Alive,
    ApplySettings,
    LibraryReset,
    LinkDown,
    LinkUp,
    Lost,
    Quit,
    ReadError,
    Reopen,
    SampleReady,
    Start,
    run,
)
from ibl.config import Settings


class FakeLjm:
    def __init__(self, fail_reads=0, fail_opens=0):
        self.fail_reads = fail_reads
        self.fail_opens = fail_opens
        self.opens = 0
        self.closes = 0
        self.close_alls = 0
        self.calls = []

    def openS(self, *_args):
        self.opens += 1
        self.calls.append("openS")
        if self.fail_opens:
            self.fail_opens -= 1
            raise OSError("no device")
        return 1

    def getHandleInfo(self, _h):
        return (7, 3, 470012345, 0, 0, 0)

    def readLibraryConfigS(self, _name):
        return 1.23

    def eReadName(self, _h, _name):
        return 1.0234

    def eWriteNames(self, *_args):
        self.calls.append("eWriteNames")

    def eReadNames(self, _h, n, _names):
        if self.fail_reads:
            self.fail_reads -= 1
            raise OSError("timeout")
        return [7.0 if i % 2 == 0 else 0.435 for i in range(n)]

    def close(self, _h):
        self.closes += 1
        self.calls.append("close")

    def closeAll(self):
        self.close_alls += 1
        self.calls.append("closeAll")


def _acq(monkeypatch, ljm):
    monkeypatch.setattr(acquisition, "ljm", ljm)
    monkeypatch.setattr(acquisition, "LJM_AVAILABLE", True)
    return Acquisition()


def _real(**kw):
    return Settings(simulate=False, connection="USB", identifier="ANY", **kw)


def test_simulation_reports_link_up(monkeypatch):
    fake = FakeLjm()
    acq = _acq(monkeypatch, fake)
    events = acq.handle(Start(Settings(simulate=True)), 0.0)
    assert events == [LinkUp("Simulation mode", "", "", "")]
    assert fake.calls == []


def test_open_reports_serial_and_connection(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    events = acq.handle(Start(_real()), 0.0)
    assert events == [LinkUp("T7 #470012345 over USB", "1.2300", "1.0234", "")]


def test_failed_open_reports_link_down(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm(fail_opens=1))
    assert acq.handle(Start(_real()), 0.0) == [LinkDown("no device")]


def test_reopen_closes_then_opens(monkeypatch):
    fake = FakeLjm()
    acq = _acq(monkeypatch, fake)
    acq.handle(Start(_real()), 0.0)
    fake.calls.clear()
    events = acq.handle(Reopen(), 1.0)
    assert fake.calls[:2] == ["close", "openS"]
    assert events == [LinkUp("T7 #470012345 over USB", "1.2300", "1.0234", "")]


def test_library_reset_calls_close_all_then_opens(monkeypatch):
    fake = FakeLjm()
    acq = _acq(monkeypatch, fake)
    acq.handle(Start(_real()), 0.0)
    fake.calls.clear()
    events = acq.handle(LibraryReset(), 1.0)
    assert fake.close_alls == 1
    assert fake.calls.index("closeAll") < fake.calls.index("openS")
    assert [type(e) for e in events] == [LinkUp]


def test_library_reset_failing_open_reports_link_down(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    acq.handle(Start(_real()), 0.0)
    monkeypatch.setattr(acquisition.ljm, "fail_opens", 1)
    assert acq.handle(LibraryReset(), 1.0) == [LinkDown("no device")]


def test_missing_ljm_library_reports_link_down(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    monkeypatch.setattr(acquisition, "LJM_AVAILABLE", False)
    monkeypatch.setattr(acquisition, "LJM_IMPORT_ERROR", "no dll")
    assert acq.handle(Start(_real()), 0.0) == [
        LinkDown("LabJack LJM library not found (no dll)")
    ]


def test_failed_read_emits_read_error_then_reconnects_after_three(monkeypatch):
    fake = FakeLjm(fail_reads=3)
    acq = _acq(monkeypatch, fake)
    acq.handle(Start(_real()), 0.0)
    opens = fake.opens

    assert acq.tick(1.0) == [ReadError("timeout")]
    assert acq.tick(2.0) == [ReadError("timeout")]
    assert acq.tick(3.0) == [ReadError("timeout"), Lost("timeout")]

    assert fake.closes == 1
    for t in (4.0, 5.0, 6.0, 40.0):
        assert not any(isinstance(e, SampleReady) for e in acq.tick(t))
    assert fake.opens == opens          # the child never retries on its own


def test_good_read_emits_sample(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    acq.handle(Start(_real()), 0.0)
    events = acq.tick(1.0)
    assert [type(e) for e in events] == [SampleReady]
    sample = events[0].sample
    assert sample.timestamp == 1.0
    assert len(sample.readings) == 14


def test_sample_waits_for_the_interval(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    acq.handle(Start(_real(sample_hz=1.0)), 0.0)
    assert [type(e) for e in acq.tick(0.0)] == [SampleReady]
    assert acq.tick(0.5) == []
    assert [type(e) for e in acq.tick(1.0)] == [SampleReady]


def test_retry_when_not_connected_announces_attempt(monkeypatch):
    fake = FakeLjm(fail_opens=1)
    acq = _acq(monkeypatch, fake)
    assert acq.handle(Start(_real()), 0.0) == [LinkDown("no device")]
    for t in (1.0, 6.0, 60.0, 600.0):
        acq.tick(t)
    assert fake.opens == 1               # a closed Acquisition never opens from tick


def test_alive_heartbeat_when_nothing_else_to_say(monkeypatch):
    fake = FakeLjm(fail_opens=1)
    acq = _acq(monkeypatch, fake)
    acq.handle(Start(_real()), 10.0)       # LinkDown at t=10, not connected
    assert acq.tick(10.5) == []
    assert acq.tick(11.0) == [Alive()]
    assert acq.tick(11.5) == []
    assert acq.tick(12.0) == [Alive()]


def test_alive_heartbeat_between_slow_samples(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    acq.handle(Start(_real(sample_hz=0.1)), 0.0)
    assert [type(e) for e in acq.tick(0.0)] == [SampleReady]
    assert acq.tick(0.5) == []
    assert acq.tick(1.0) == [Alive()]
    assert acq.tick(9.0) == [Alive()]
    assert [type(e) for e in acq.tick(10.0)] == [SampleReady]


def test_heartbeat_constant():
    assert config.HEARTBEAT_S == 1.0


def test_apply_settings_reopens_when_connection_changes(monkeypatch):
    fake = FakeLjm()
    acq = _acq(monkeypatch, fake)
    start = _real()
    acq.handle(Start(start), 0.0)
    for change in (
        {"connection": "ETHERNET"},
        {"identifier": "470012345"},
        {"resolution_index": 4},
    ):
        before = fake.opens
        events = acq.handle(ApplySettings(dataclasses.replace(start, **change)), 1.0)
        assert fake.opens == before + 1, change
        assert [type(e) for e in events] == [LinkUp]
        start = dataclasses.replace(start, **change)


def test_apply_settings_simulate_toggle_reopens(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    start = _real()
    acq.handle(Start(start), 0.0)
    events = acq.handle(ApplySettings(dataclasses.replace(start, simulate=True)), 1.0)
    assert events == [LinkUp("Simulation mode", "", "", "")]


def test_apply_settings_sample_rate_only_changes_interval(monkeypatch):
    fake = FakeLjm()
    acq = _acq(monkeypatch, fake)
    start = _real(sample_hz=1.0)
    acq.handle(Start(start), 0.0)
    acq.tick(0.0)
    opens = fake.opens
    assert acq.handle(ApplySettings(dataclasses.replace(start, sample_hz=2.0)), 0.1) == []
    assert fake.opens == opens
    assert [type(e) for e in acq.tick(0.5)] == [SampleReady]       # now every 0.5 s


def test_quit_closes_and_calls_close_all(monkeypatch):
    fake = FakeLjm()
    acq = _acq(monkeypatch, fake)
    acq.handle(Start(_real()), 0.0)
    assert acq.handle(Quit(), 1.0) == []
    assert fake.closes == 1
    assert fake.close_alls == 1
    assert acq.finished


def test_run_loop_exits_on_quit():
    commands: queue.Queue = queue.Queue()
    events: queue.Queue = queue.Queue()
    commands.put(Start(Settings(simulate=True)))
    commands.put(Quit())
    run(commands, events)
    got = []
    while not events.empty():
        got.append(events.get())
    assert any(isinstance(e, LinkUp) for e in got)
    assert any(isinstance(e, SampleReady) for e in got)


def test_acquisition_imports_no_qt():
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    env = dict(os.environ, PYTHONPATH=os.path.abspath(src))
    out = subprocess.run(
        [sys.executable, "-c", "import sys, ibl.acquisition; print('PySide6' in sys.modules)"],
        capture_output=True, text=True, env=env, check=True,
    )
    # labjack prints a notice to stdout when the LJM library is absent; the answer is the last line.
    assert out.stdout.strip().splitlines()[-1] == "False"


def test_messages_round_trip_through_pickle(monkeypatch):
    acq = _acq(monkeypatch, FakeLjm())
    messages = [
        Start(Settings(simulate=True)), ApplySettings(Settings()), Reopen(),
        LibraryReset(), Quit(), Alive(), LinkUp("d", "v", "f", "w"), LinkDown("r"),
        Lost("r"), ReadError("m"),
    ]
    acq.handle(Start(_real()), 0.0)
    messages += acq.tick(1.0)
    for message in messages:
        assert pickle.loads(pickle.dumps(message)) == message or isinstance(message, SampleReady)
    sample = next(m for m in messages if isinstance(m, SampleReady))
    back = pickle.loads(pickle.dumps(sample))
    assert back.sample.timestamp == sample.sample.timestamp
    assert [r.pressure for r in back.sample.readings] == [r.pressure for r in sample.sample.readings]


@pytest.mark.parametrize("cls", [Alive, Reopen, LibraryReset, Quit])
def test_parameterless_messages_compare_equal(cls):
    assert cls() == cls()
