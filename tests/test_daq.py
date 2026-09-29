"""DaqWorker reports structured Link events; the fake LJM stands in for the T7."""

from ibl import daq
from ibl.config import Settings


class FakeLjm:
    def __init__(self, fail_reads=0, fail_opens=0):
        self.fail_reads = fail_reads
        self.fail_opens = fail_opens
        self.opens = 0

    def openS(self, *_args):
        self.opens += 1
        if self.fail_opens:
            self.fail_opens -= 1
            raise OSError("no device")
        return 1

    def getHandleInfo(self, _h):
        return (7, 3, 470012345, 0, 0, 0)

    def eWriteNames(self, *_args):
        pass

    def eReadNames(self, _h, n, _names):
        if self.fail_reads:
            self.fail_reads -= 1
            raise OSError("timeout")
        return [7.0 if i % 2 == 0 else 0.435 for i in range(n)]

    def close(self, _h):
        pass

    def closeAll(self):
        pass


def _worker(monkeypatch, ljm, simulate=False):
    monkeypatch.setattr(daq, "ljm", ljm)
    monkeypatch.setattr(daq, "LJM_AVAILABLE", True)
    monkeypatch.setattr(daq.time, "sleep", lambda _s: None)
    w = daq.DaqWorker(Settings(simulate=simulate, connection="USB", identifier="ANY"))
    events = []
    w.link_up.connect(lambda d: events.append(("up", d)))
    w.link_down.connect(lambda r: events.append(("down", r)))
    w.reconnecting.connect(lambda a: events.append(("reconnecting", a)))
    w.read_error.connect(lambda m: events.append(("read_error", m)))
    w.sample.connect(lambda s: events.append(("sample", s)))
    return w, events


def test_simulation_reports_link_up(qtbot, monkeypatch):
    w, events = _worker(monkeypatch, FakeLjm(), simulate=True)
    w._running = True
    w._open()
    assert events == [("up", "Simulation mode")]


def test_open_reports_serial_and_connection(qtbot, monkeypatch):
    w, events = _worker(monkeypatch, FakeLjm())
    w._open()
    assert events == [("up", "T7 #470012345 over USB")]


def test_failed_open_reports_link_down(qtbot, monkeypatch):
    w, events = _worker(monkeypatch, FakeLjm(fail_opens=1))
    w._open()
    assert events == [("down", "no device")]


def test_failed_read_emits_read_error_then_reconnects_after_three(qtbot, monkeypatch):
    w, events = _worker(monkeypatch, FakeLjm(fail_reads=3))
    w._running = True
    w._open()
    events.clear()

    w._tick()
    w._tick()
    assert events == [("read_error", "timeout")] * 2

    events.clear()
    w._tick()
    assert events == [
        ("read_error", "timeout"),
        ("reconnecting", 1),
        ("up", "T7 #470012345 over USB"),
    ]


def test_good_read_emits_sample(qtbot, monkeypatch):
    w, events = _worker(monkeypatch, FakeLjm())
    w._open()
    events.clear()
    w._tick()
    assert [e[0] for e in events] == ["sample"]


def test_retry_when_not_connected_announces_attempt(qtbot, monkeypatch):
    w, events = _worker(monkeypatch, FakeLjm(fail_opens=1))
    w._running = True
    w._open()
    events.clear()
    monkeypatch.setattr(daq.time, "time", lambda: w._reconnect_at + 6.0)

    w._tick()

    assert events == [("reconnecting", 1), ("up", "T7 #470012345 over USB")]
