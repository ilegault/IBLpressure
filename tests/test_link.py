"""LinkMonitor: the one pure core that decides the Link state. No Qt, no clock."""
from __future__ import annotations

import pathlib
from datetime import UTC, datetime

from ibl.escalation import Attempt, Step
from ibl.link import DOT_COLORS, RECOVERY_NOTICE_S, LinkMonitor, LinkState, LinkView, Recovery

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
    assert v.text == "T7 not found: no device. Next try in 5 s."


def test_waiting_for_first_sample():
    m = live_monitor()
    v = m.view(1.0)
    assert v.state is LinkState.LATE
    assert v.text == "Connected · waiting for first sample"


def test_reconnecting_text():
    m = live_monitor()
    m.sample(1.0)
    m.reconnecting(5.0, Attempt(Step.REOPEN, 2, 3, 2, False))
    v = m.view(5.1)
    assert v.state is LinkState.LATE
    assert v.text == "Reconnecting — Reopen (attempt 2 of 3)…"


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


# --- Escalation status texts (spec §2 Status texts), one test per row ---------
RED, AMBER, GREEN = "#d62728", "#ff9f1a", "#2ca02c"


def lost_monitor() -> LinkMonitor:
    m = live_monitor()
    m.sample(1.0)
    return m


def test_text_attempt_in_flight_reopen_and_library_reset():
    m = lost_monitor()
    m.reconnecting(5.0, Attempt(Step.LIBRARY_RESET, 2, 3, 5, False))
    v = m.view(5.1)
    assert (v.state, v.dot_color) == (LinkState.LATE, AMBER)
    assert v.text == "Reconnecting — Library reset (attempt 2 of 3)…"


def test_text_attempt_in_flight_acquisition_restart():
    m = lost_monitor()
    m.reconnecting(5.0, Attempt(Step.ACQUISITION_RESTART, 1, None, 7, False))
    v = m.view(5.1)
    assert (v.state, v.dot_color) == (LinkState.LATE, AMBER)
    assert v.text == "Reconnecting — Acquisition restart (attempt 1)…"


def test_text_attempt_failed_reopen():
    m = lost_monitor()
    m.link_down(5.0, "1298", Attempt(Step.REOPEN, 3, 3, 3, False))
    v = m.view(5.1)
    assert (v.state, v.dot_color) == (LinkState.DOWN, RED)
    assert v.text == "T7 not found: 1298. Reopen (attempt 3 of 3) failed; next try in 5 s."


def test_text_attempt_failed_library_reset():
    m = lost_monitor()
    m.link_down(5.0, "1298", Attempt(Step.LIBRARY_RESET, 1, 3, 4, False))
    assert m.view(5.1).text == (
        "T7 not found: 1298. Library reset (attempt 1 of 3) failed; next try in 5 s.")


def test_text_attempt_failed_acquisition_restart_waits_thirty_seconds():
    m = lost_monitor()
    m.link_down(5.0, "1298", Attempt(Step.ACQUISITION_RESTART, 2, None, 8, False))
    v = m.view(5.1)
    assert (v.state, v.dot_color) == (LinkState.DOWN, RED)
    assert v.text == "T7 not found: 1298. Acquisition restart (attempt 2) failed; next try in 30 s."


def test_text_open_failed_at_connect_has_no_attempt_yet():
    m = LinkMonitor(3, 1.0)
    m.connect_requested(0)
    m.link_down(0, "no device")
    assert m.view(1).text == "T7 not found: no device. Next try in 5 s."


HAND_OFF = (
    "T7 not responding — automatic recovery still trying (attempt 9). If this persists: "
    "check the USB cable to the T7, unplug and replug the T7, then reboot this PC. "
    "Details in the Link log."
)


def test_text_hand_off_in_flight_is_red():
    m = lost_monitor()
    m.reconnecting(5.0, Attempt(Step.ACQUISITION_RESTART, 3, None, 9, True))
    v = m.view(5.1)
    assert (v.state, v.dot_color) == (LinkState.DOWN, RED)
    assert v.text == HAND_OFF


def test_text_hand_off_after_failure_is_red():
    m = lost_monitor()
    m.link_down(5.0, "1298", Attempt(Step.ACQUISITION_RESTART, 3, None, 9, True))
    v = m.view(5.1)
    assert (v.state, v.dot_color) == (LinkState.DOWN, RED)
    assert v.text == HAND_OFF


def test_text_recovery_after_escalation_names_the_step():
    m = lost_monitor()
    m.link_down(5.0, "1298", Attempt(Step.LIBRARY_RESET, 1, 3, 4, False))
    m.link_up(47.5, DESC, Step.LIBRARY_RESET)
    recovery = m.sample(48.0)
    assert recovery == Recovery(47.0, Step.LIBRARY_RESET)
    stamp = datetime.fromtimestamp(48.0, tz=UTC).astimezone().strftime("%H:%M:%S")
    v = m.view(48.5)
    assert (v.state, v.dot_color) == (LinkState.LIVE, GREEN)
    assert v.text == f"Live · Recovered at {stamp} after a 47 s gap (Library reset)"
    for t in range(49, 60):
        m.sample(float(t))
    after = m.view(48.0 + RECOVERY_NOTICE_S + 1)
    assert after.text.startswith("Live · T7 #470012345")
    assert "Library reset" not in after.text


def test_text_recovery_without_escalation_is_unchanged():
    m = live_monitor()
    m.sample(0)
    recovery = m.sample(10.2)
    assert recovery == Recovery(10.2, None)
    stamp = datetime.fromtimestamp(10.2, tz=UTC).astimezone().strftime("%H:%M:%S")
    assert m.view(10.5).text == f"Live · Recovered at {stamp} after a 10 s gap"


def test_sample_returns_recovery_only_on_the_sample_that_ends_a_gap():
    m = live_monitor()
    assert m.sample(1.0) is None
    assert m.sample(2.0) is None
    m.link_down(3.0, "x")
    m.link_up(4.0, DESC, Step.REOPEN)
    assert m.sample(5.0) == Recovery(3.0, Step.REOPEN)   # the Gap began at the last Sample, t=2
    assert m.sample(6.0) is None


def test_detail_is_latest_error_while_not_live():
    m = live_monitor()
    assert m.view(0.5).detail == ""
    m.sample(1.0)
    assert m.view(1.5).detail == ""
    m.link_down(5.0, "1298 LJME_ATTR_LOAD_COMM_FAILURE")
    assert m.view(5.1).detail == "1298 LJME_ATTR_LOAD_COMM_FAILURE"
    m.link_down(6.0, "1239 other", Attempt(Step.REOPEN, 2, 3, 2, False))
    assert m.view(6.1).detail == "1239 other"
    m.link_up(7.0, DESC, Step.REOPEN)
    m.sample(7.5)
    assert m.view(7.6).detail == ""
    m.sample(20.0)
    assert m.view(20.1).detail == ""             # an old error never comes back


def test_detail_is_empty_when_idle():
    m = LinkMonitor(3, 1.0)
    assert m.view(0).detail == ""
    m.connect_requested(0)
    m.link_down(0, "no device")
    m.disconnect_requested(1)
    assert m.view(2).detail == ""
