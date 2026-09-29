# 05: LinkMonitor — the one pure core that decides the Link state

**What to build:** A Qt-free `src/ibl/link.py` whose `LinkMonitor` takes Link
events with an explicit `now` and returns the one `LinkView` (state, dot colour,
status text) that both the dot and the status line will show. No wiring into the
window yet (ticket 06). Spec §2 *Link state*; CONTEXT.md *Link state*.

**Blocked by:** 03

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

All tests in `tests/test_link.py`, pure (no Qt, no `time.time()`), driving the
monitor with explicit `now` values. Status strings are the exact texts in spec §2.

- [x] **API.** `class LinkState(Enum)`: `IDLE`, `LIVE`, `LATE`, `DOWN`.
  `@dataclass(frozen=True) class LinkView: state: LinkState; dot_color: str; text: str`.
  `DOT_COLORS = {IDLE: "#999999", LIVE: "#2ca02c", LATE: "#ff9f1a", DOWN: "#d62728"}`.
  `RECOVERY_NOTICE_S = 10.0`. `class LinkMonitor(late_after_samples: int, sample_hz: float)`
  with methods `configure(late_after_samples, sample_hz)`, `connect_requested(now)`,
  `disconnect_requested(now)`, `link_up(now, description)`, `link_down(now, reason)`,
  `reconnecting(now, attempt)`, `sample(now)`, `read_error(now, message)`,
  `view(now) -> LinkView`, and property `late_threshold_s`
  (`late_after_samples / sample_hz`). `link.py` must not import `time`, `PySide6`
  or `pyqtgraph`.
- [x] **The four states.** `test_idle_until_connect_requested` (IDLE, grey,
  `Not connected. Press Connect.`); `test_live_after_link_up_and_sample`
  (`link_up(0, "T7 #470012345 over USB")`, `sample(1.0)`, `view(1.4)` → LIVE,
  green, `Live · T7 #470012345 over USB · last sample 0.4 s ago`);
  `test_late_when_no_sample_within_threshold` (3 samples at 1 Hz: sample at 10.0,
  `view(13.5)` → LATE, amber, `Late · no sample for 4 s`; `view(12.9)` still LIVE);
  `test_down_when_open_fails` (`connect_requested`, `link_down(0, "no device")` →
  DOWN, red, `T7 not found: no device. Retrying every 5 s.`);
  `test_waiting_for_first_sample` (`link_up` with no sample → LATE,
  `Connected · waiting for first sample`); `test_reconnecting_text`.
- [x] **It never gets stuck (the old bug).** `test_recovers_to_live_after_gap`:
  sample at 0, `view(10)` is LATE, `sample(10.2)`, `view(10.5)` is LIVE and its text
  is `Live · Recovered at {hh:mm:ss} after a 10 s gap` where the time is
  `datetime.fromtimestamp(10.2).strftime("%H:%M:%S")`; `view(10.2 + 10.1)` shows the
  normal Live text again. `test_recovers_after_down`: DOWN, then `link_up` +
  `sample` → LIVE with the Recovered text.
- [x] **Read errors clear themselves.** `test_read_error_shown_until_next_sample`:
  LIVE, `read_error(5.1, "timeout")`, `view(5.2)` text ends
  `· read error: timeout` and the state is still LIVE; after `sample(6.0)`,
  `view(6.1)` has no `read error`.
- [x] **Threshold follows the rate.** `test_threshold_follows_sample_rate`:
  `LinkMonitor(3, 0.2).late_threshold_s == 15.0`; after `configure(2, 1.0)` it is
  `2.0`; a gap of 12 s at 0.2 Hz is still LIVE. `test_disconnect_returns_to_idle`.
- [x] Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments

- 2026-09-29: Implemented `src/ibl/link.py` and `tests/test_link.py` (13 tests). Awaiting review and
  merge, so Status stays `in-progress` until it lands.
- Choices the ticket left open: after `connect_requested` and before `link_up`/`link_down` the view is
  Late with the text `Connecting…`. A Gap starts at the last Sample (or the failure time if none) and
  ends at the next Sample. A read error outranks the Recovery text while it is current.
- Local gate: `ruff check .`, `check_tests_first.py` and `pytest` (all but `test_window_smoke.py`, which
  needs the system Qt libraries this sandbox lacks) pass; CI runs that one.
