"""The Link log is the permanent record of Link events. Real files under tmp_path, no fakes."""
from __future__ import annotations

import datetime as _dt
import os

from ibl import config
from ibl.linklog import LinkLog


def _ts(year, month, day, hour=0, minute=0, second=0) -> float:
    """Epoch seconds for a LOCAL wall-clock time, as the operator reads it."""
    return _dt.datetime(year, month, day, hour, minute, second).timestamp()  # noqa: DTZ001


def _stamp(now: float) -> str:
    # Same conversion link.py uses for the Recovery stamp.
    local = _dt.datetime.fromtimestamp(now, tz=_dt.UTC).astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _clock(now: float) -> str:
    return _stamp(now)[11:]


def _lines(path) -> list[str]:
    with open(path, encoding="utf-8") as fh:
        return fh.read().splitlines()


def test_constants_live_in_config():
    assert config.LINK_LOG_FOLD_S == 600.0
    assert config.CONNECTION_FRAME_EVENTS == 20


def test_one_file_per_month(tmp_path):
    log = LinkLog(str(tmp_path))
    a = _ts(2026, 10, 31, 23, 59)
    b = _ts(2026, 11, 1, 0, 1)
    assert log.record(a, "CONNECT", "USB ANY")
    assert log.record(b, "LINK_UP", "T7 #1 over USB")
    folder = tmp_path / "link-log"
    assert _lines(folder / "2026-10.log") == [f"{_stamp(a)}  CONNECT  USB ANY"]
    assert _lines(folder / "2026-11.log") == [f"{_stamp(b)}  LINK_UP  T7 #1 over USB"]

    again = LinkLog(str(tmp_path))
    c = _ts(2026, 11, 1, 0, 2)
    again.record(c, "DISCONNECT")
    assert _lines(folder / "2026-11.log") == [
        f"{_stamp(b)}  LINK_UP  T7 #1 over USB",
        f"{_stamp(c)}  DISCONNECT",
    ]


def test_repeats_fold_into_one_line(tmp_path):
    log = LinkLog(str(tmp_path))
    t0 = _ts(2026, 10, 7, 3, 0, 0)
    for i in range(120):
        assert log.record(t0 + 5 * i, "LINK_DOWN", "1298 comm failure", fold_key="1298")
    path = tmp_path / "link-log" / "2026-10.log"
    assert _lines(path) == [f"{_stamp(t0)}  LINK_DOWN  1298 comm failure"]

    after = t0 + config.LINK_LOG_FOLD_S
    log.record(after, "LINK_DOWN", "1298 comm failure", fold_key="1298")
    assert _lines(path) == [
        f"{_stamp(t0)}  LINK_DOWN  1298 comm failure",
        f"{_stamp(after)}  REPEATED  LINK_DOWN 1298 ×119 since {_clock(t0)}",
        f"{_stamp(after)}  LINK_DOWN  1298 comm failure",
    ]


def test_record_without_fold_key_flushes_counts_and_is_written_in_full(tmp_path):
    log = LinkLog(str(tmp_path))
    t0 = _ts(2026, 10, 7, 3, 0, 0)
    for i in range(4):
        log.record(t0 + 5 * i, "LINK_DOWN", "1298", fold_key="1298")
    log.record(t0 + 30, "RECOVERED", "Reopen · gap 30 s", step="Reopen", gap_s=30)
    log.record(t0 + 31, "RECOVERED", "Reopen · gap 1 s", step="Reopen", gap_s=1)
    lines = _lines(tmp_path / "link-log" / "2026-10.log")
    assert lines == [
        f"{_stamp(t0)}  LINK_DOWN  1298",
        f"{_stamp(t0 + 30)}  REPEATED  LINK_DOWN 1298 ×3 since {_clock(t0)}",
        f"{_stamp(t0 + 30)}  RECOVERED  Reopen · gap 30 s",
        f"{_stamp(t0 + 31)}  RECOVERED  Reopen · gap 1 s",
    ]
    # A new loss after the flush starts a fresh window and is written in full.
    log.record(t0 + 40, "LINK_DOWN", "1298", fold_key="1298")
    assert _lines(tmp_path / "link-log" / "2026-10.log")[-1] == f"{_stamp(t0 + 40)}  LINK_DOWN  1298"


def test_alternating_keys_fold_independently(tmp_path):
    log = LinkLog(str(tmp_path))
    t0 = _ts(2026, 10, 7, 3, 0, 0)
    for i in range(20):                         # every 30 s for 600 s
        t = t0 + 30 * i
        log.record(t, "RECONNECTING", "Acquisition restart", fold_key="Acquisition restart")
        log.record(t, "LINK_DOWN", "1298", fold_key="1298")
    path = tmp_path / "link-log" / "2026-10.log"
    assert _lines(path) == [
        f"{_stamp(t0)}  RECONNECTING  Acquisition restart",
        f"{_stamp(t0)}  LINK_DOWN  1298",
    ]
    end = t0 + config.LINK_LOG_FOLD_S
    log.record(end, "LINK_UP", "T7")
    assert _lines(path)[2:] == [
        f"{_stamp(end)}  REPEATED  RECONNECTING Acquisition restart ×19 since {_clock(t0)}",
        f"{_stamp(end)}  REPEATED  LINK_DOWN 1298 ×19 since {_clock(t0)}",
        f"{_stamp(end)}  LINK_UP  T7",
    ]


def test_summary_counts_todays_recoveries(tmp_path):
    log = LinkLog(str(tmp_path))
    now = _ts(2026, 10, 7, 15, 0, 0)
    assert log.summary(now) == "Today: no recoveries"
    log.record(_ts(2026, 10, 6, 23, 0), "RECOVERED", step="Reopen", gap_s=99)   # yesterday
    assert log.summary(now) == "Today: no recoveries"
    log.record(_ts(2026, 10, 7, 9, 0), "RECOVERED", step="Reopen", gap_s=7)
    assert log.summary(now) == "Today: 1 recovery — Reopen 1 · longest gap 7 s"
    log.record(_ts(2026, 10, 7, 10, 0), "RECOVERED", step="Reopen", gap_s=12)
    log.record(_ts(2026, 10, 7, 11, 0), "RECOVERED", step="Library reset", gap_s=42)
    expected = "Today: 3 recoveries — Reopen 2, Library reset 1 · longest gap 42 s"
    assert log.summary(now) == expected

    reopened = LinkLog(str(tmp_path))
    assert reopened.summary(now) == expected
    assert reopened.recent(20) == log.recent(20)
    assert len(log.recent(20)) == 4


def test_recent_is_newest_first_and_limited(tmp_path):
    log = LinkLog(str(tmp_path))
    t0 = _ts(2026, 10, 7, 9, 0)
    for i in range(30):
        log.record(t0 + i, "CONNECT", f"n{i}")
    recent = log.recent(20)
    assert len(recent) == 20
    assert recent[0].endswith("CONNECT  n29")
    assert recent[-1].endswith("CONNECT  n10")
    assert LinkLog(str(tmp_path / "empty")).recent(20) == []


def test_recent_reads_back_into_previous_month(tmp_path):
    log = LinkLog(str(tmp_path))
    log.record(_ts(2026, 10, 31, 23, 59), "CONNECT", "old")
    log.record(_ts(2026, 11, 1, 0, 1), "CONNECT", "new")
    recent = LinkLog(str(tmp_path)).recent(20)
    assert [line.split("  ")[-1] for line in recent] == ["new", "old"]


def test_reconfigure_moves_the_log(tmp_path):
    log = LinkLog(str(tmp_path / "a"))
    t = _ts(2026, 10, 7, 9, 0)
    log.record(t, "CONNECT")
    log.reconfigure(str(tmp_path / "b"))
    log.record(t + 1, "DISCONNECT")
    assert os.path.exists(tmp_path / "a" / "link-log" / "2026-10.log")
    assert _lines(tmp_path / "b" / "link-log" / "2026-10.log") == [f"{_stamp(t + 1)}  DISCONNECT"]


def test_write_failure_is_reported(tmp_path):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x")
    log = LinkLog(str(blocker))
    assert log.last_error == ""
    assert log.record(_ts(2026, 10, 7, 9, 0), "CONNECT") is False
    assert log.last_error.startswith("Link log not written:")
    # and the log recovers once the folder is fine again
    log.reconfigure(str(tmp_path / "good"))
    assert log.record(_ts(2026, 10, 7, 9, 1), "CONNECT") is True
    assert log.last_error == ""
