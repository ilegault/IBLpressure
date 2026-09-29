"""LinkMonitor: the one pure core that decides the Link state. No Qt, no clock."""
from __future__ import annotations

import pathlib
from datetime import UTC, datetime

from ibl.link import DOT_COLORS, RECOVERY_NOTICE_S, LinkMonitor, LinkState, LinkView

DESC = "T7 #470012345 over USB"


def live_monitor(n=3, hz=1.0) -> LinkMonitor:
    m = LinkMonitor(n, hz)
    m.connect_requested(0)
    m.link_up(0, DESC)
    return m


def test_api_constants():
    assert DOT_COLORS == {
        LinkState.IDLE: "#999999",
        LinkState.LIVE: "#2ca02c",
        LinkState.LATE: "#ff9f1a",
        LinkState.DOWN: "#d62728",
    }
    assert RECOVERY_NOTICE_S == 10.0
    v = LinkView(LinkState.IDLE, "#999999", "x")
    assert (v.state, v.dot_color, v.text) == (LinkState.IDLE, "#999999", "x")


def test_link_module_imports_no_qt_or_time():
    from ibl import link
    src = pathlib.Path(link.__file__).read_text()
    for banned in ("import time", "from time", "PySide6", "pyqtgraph"):
        assert banned not in src


def test_idle_until_connect_requested():
    v = LinkMonitor(3, 1.0).view(0)
    assert v.state is LinkState.IDLE
    assert v.dot_color == "#999999"
    assert v.text == "Not connected. Press Connect."


def test_live_after_link_up_and_sample():
    m = live_monitor()
    m.sample(1.0)
    v = m.view(1.4)
    assert v.state is LinkState.LIVE
    assert v.dot_color == "#2ca02c"
    assert v.text == "Live · T7 #470012345 over USB · last sample 0.4 s ago"


def test_late_when_no_sample_within_threshold():
    m = live_monitor()
    m.sample(10.0)
    v = m.view(13.5)
    assert v.state is LinkState.LATE
    assert v.dot_color == "#ff9f1a"
    assert v.text == "Late · no sample for 4 s"
    assert m.view(12.9).state is LinkState.LIVE


def test_down_when_open_fails():
    m = LinkMonitor(3, 1.0)
    m.connect_requested(0)
    m.link_down(0, "no device")
    v = m.view(1)
    assert v.state is LinkState.DOWN
    assert v.dot_color == "#d62728"
    assert v.text == "T7 not found: no device. Retrying every 5 s."


def test_waiting_for_first_sample():
    m = live_monitor()
    v = m.view(1.0)
    assert v.state is LinkState.LATE
    assert v.text == "Connected · waiting for first sample"


def test_reconnecting_text():
    m = live_monitor()
    m.sample(1.0)
    m.reconnecting(5.0, 2)
    v = m.view(5.1)
    assert v.state is LinkState.LATE
    assert v.text == "Reconnecting (attempt 2)…"


def test_recovers_to_live_after_gap():
    m = live_monitor()
    m.sample(0)
    assert m.view(10).state is LinkState.LATE
    m.sample(10.2)
    v = m.view(10.5)
    assert v.state is LinkState.LIVE
    stamp = datetime.fromtimestamp(10.2, tz=UTC).astimezone().strftime("%H:%M:%S")
    assert v.text == f"Live · Recovered at {stamp} after a 10 s gap"
    for t in range(11, 21):  # samples keep arriving once a second
        m.sample(float(t))
    assert m.view(10.2 + 10.1).text.startswith("Live · T7 #470012345 over USB · last sample")


def test_recovers_after_down():
    m = LinkMonitor(3, 1.0)
    m.connect_requested(0)
    m.link_down(0, "no device")
    m.link_up(6.0, DESC)
    m.sample(6.5)
    v = m.view(7.0)
    assert v.state is LinkState.LIVE
    assert "Recovered at" in v.text


def test_read_error_shown_until_next_sample():
    m = live_monitor()
    m.sample(5.0)
    m.read_error(5.1, "timeout")
    v = m.view(5.2)
    assert v.state is LinkState.LIVE
    assert v.text.endswith("· read error: timeout")
    m.sample(6.0)
    assert "read error" not in m.view(6.1).text


def test_threshold_follows_sample_rate():
    m = LinkMonitor(3, 0.2)
    assert m.late_threshold_s == 15.0
    m.configure(2, 1.0)
    assert m.late_threshold_s == 2.0
    m.configure(3, 0.2)
    m.connect_requested(0)
    m.link_up(0, DESC)
    m.sample(0)
    assert m.view(12).state is LinkState.LIVE


def test_disconnect_returns_to_idle():
    m = live_monitor()
    m.sample(1.0)
    m.disconnect_requested(2.0)
    v = m.view(2.1)
    assert v.state is LinkState.IDLE
    assert v.text == "Not connected. Press Connect."
