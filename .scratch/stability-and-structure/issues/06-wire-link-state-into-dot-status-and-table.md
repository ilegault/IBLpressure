# 06: Drive the dot, status line and Stale table from LinkMonitor

**What to build:** Replace the window's scattered dot/status/watchdog logic with
`LinkMonitor` (ticket 05): the worker reports structured Link events, the window
refreshes one `LinkView` every 0.5 s and on every event, pressure cells never show a
number unless the Link is Live, and one bad gauge never affects anything but its own
cells. Spec §2 *Link state*, *Stale table*; AGENTS.md rules 3–5.

**Blocked by:** 04, 05

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

Qt tests in `tests/test_window_link.py` use a window built as in
`tests/test_window_smoke.py`, a fake clock (monkeypatch the window's
`self._now` callable, which production sets to `time.time`), and call the window's
slots directly with hand-built `Sample`s; they never wait on the real worker thread.

- [x] **Structured worker events.** `DaqWorker` replaces `status(str)` and
  `connection_changed(bool)` with signals `link_up(str)` (description
  `T7 #{serial} over {connection}` or `Simulation mode`), `link_down(str)` (reason),
  `reconnecting(int)` (attempt), `read_error(str)`, and keeps `sample(object)`.
  `_tick` emits `read_error` on each failed read and `reconnecting` before each
  reconnect attempt. Rewrite any existing test that used the old signals in place.
- [x] **One view, one place.** `MainWindow` owns `self.link = LinkMonitor(...)`,
  forwards each signal and `Connect`/`Disconnect` presses to it, configures it from
  `settings.late_after_samples` / `sample_hz` on every settings change, and has one
  method `_render_link()` that sets the dot colour from `view.dot_color` and
  `lbl_status` from `view.text`. A `QTimer` calls `_render_link` every 500 ms.
  `_check_stale`, the old watchdog and every other write to `lbl_link`'s style or
  `lbl_status`'s text for link purposes are removed (driver-missing messages from
  `_refresh_driver_state` stay, shown only while the state is DOWN).
  Test `test_dot_turns_green_again_after_late` (the reported bug): Live sample at
  t=0, render at t=5 → dot `#ff9f1a`; `_on_sample` at t=5.2 → dot `#2ca02c` and
  `lbl_status` starts `Live · Recovered at`.
- [x] **No number where a live one belongs.** Test `test_pressure_cells_go_stale`:
  after a good Sample at t=0 and a render at t=5 (3 missed samples at 1 Hz), every
  visible pressure cell's text is `STALE`, every status cell reads
  `last <value>, 5 s ago` where `<value>` is that Reading's `display_text()`, and the
  cells' background is the theme's `stale_bg`. Test `test_cells_live_again_on_recovery`:
  the next Sample restores numbers and clears the `last …` text.
- [x] **One bad gauge stays in its row.** Test `test_one_faulted_gauge_does_not_affect_link`:
  a Sample where only AIN0 reads 10.9 V (Gauge Fault) and the rest are normal →
  after render, dot is `#2ca02c`, `lbl_status` starts `Live`, the SNICS IG pressure
  cell reads `Gauge Fault` with the fault background, and all 13 other pressure cells
  show numbers.
- [x] **Read errors clear.** Test `test_read_error_clears_on_next_sample`: emit
  `read_error("timeout")` → status text ends `read error: timeout`; next Sample →
  it does not.
- [x] Rewrite `tests/test_window_smoke.py::test_window_opens_in_simulation` in place so
  it asserts the new Idle text `Not connected. Press Connect.` and a grey dot.
- [x] Update the module docstrings of `daq.py` and `mainwindow.py` to describe the
  new flow. Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments

- 2026-09-29: Implemented. Extras beyond the criteria: `tests/test_daq.py` (fake LJM) covers the new worker signals; a settings-save failure is now kept in `_settings_problem` and prefixed to the status line so the 500 ms redraw cannot erase it; on Disconnect/Down the last Sample stays in the table as STALE (rule 4). Driver-missing text only shows while DOWN, so at startup (Idle) only the Install button is visible.
