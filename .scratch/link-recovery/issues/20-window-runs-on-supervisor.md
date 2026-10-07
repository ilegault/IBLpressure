# 20: Window runs on the Supervisor; retire the QThread worker

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 17, 18, 19

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001, ADR 0003

## What to build

`MainWindow` (`src/ibl/mainwindow.py`) stops using `DaqWorker` and its `QThread`
and runs on the `Supervisor` (ticket 19). A 100 ms `QTimer` calls `poll(now)` and
hands each window event to the existing slots (`_on_link_up`, `_on_link_down`,
`_on_reconnecting`, `_on_read_error`, `_on_sample`), now with the Attempt and
`recovered_by` from ticket 18 (remove the `# replaced in ticket 20` shims).
Connect / Disconnect call `connect` / `disconnect`; `_on_widget_changed` calls
`update_settings` with a copy (`dataclasses.replace`, AGENTS.md rule 2);
`closeEvent` calls `shutdown()` instead of `BlockingQueuedConnection`. `main.py`
calls `multiprocessing.freeze_support()` first under `if __name__ == "__main__":`
so the PyInstaller exe can start the child. Delete `src/ibl/daq.py`. History,
plot, Daily CSV and LinkMonitor are not touched beyond these call sites.

## Acceptance criteria

Window tests use the `window` fixture pattern of `tests/test_window_link.py`, with
`MainWindow(settings, supervisor=Supervisor(spawn=<FakeChild factory>))` (new
optional argument; production passes nothing). May fake: the child handle and the
clock. Must be real: `MainWindow`, `Supervisor`, `LinkMonitor`.

- [x] Test `test_connect_goes_live_through_supervisor`: press Connect
  (`window._toggle_connection()`), the fake child sends `LinkUp` and a `SampleReady`,
  call `window._poll_supervisor()` → dot `#2ca02c`, status starts `Live ·`, and the
  table shows numbers.
- [x] Test `test_escalation_shows_on_status_line`: fake child sends `Lost("timeout")`
  → after a poll and render, status reads `Reconnecting — Reopen (attempt 1 of 3)…`;
  after `LinkUp` and a Sample, it starts `Live · Recovered at` and ends `(Reopen)`.
- [x] Test `test_quit_never_waits_on_a_stuck_child`: a fake child whose `join` leaves
  it alive → `window.close()` returns, the fake got `kill()`, and the window has no
  `thread` or `worker` attribute.
- [x] Test `test_settings_change_reaches_child_as_copy`: changing the sample rate in
  the settings panel sends `ApplySettings(s)` where `s is not window.settings` and
  `s.sample_hz` is the new value.
- [x] `grep -rn "DaqWorker\|QThread\|BlockingQueuedConnection" src main.py` finds
  nothing; `main.py` calls `multiprocessing.freeze_support()`; module docstrings of
  `mainwindow.py` and `supervisor.py` describe the new flow. Full gate green.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — `MainWindow(settings, supervisor=None)` now polls a `Supervisor` every
`WINDOW_POLL_MS` (new in `config.py`) and routes its events to the existing slots, with the
Attempt and `recovered_by`; the ticket-18 shims are gone. `closeEvent` calls `shutdown()`;
`src/ibl/daq.py` is deleted; `main.py` calls `multiprocessing.freeze_support()`.
Tests: `tests/test_window_supervisor.py` (new, covers each criterion plus one real spawned child
driving the real window); the two `test_window_smoke.py` tests that read `window.worker._settings`
were rewritten in place (same names) against the child's `Start`/`ApplySettings`; the
ticket-18 `test_reconnecting_signal_still_reads_as_a_reopen` now passes an `Attempt`.
Note: the ticket's "window has no `thread` attribute" cannot be asserted literally because
`QObject.thread()` always exists; the test asserts no `QThread` child and no `worker` instead.
Bench (ticket 25): the PyInstaller exe must start the child (`freeze_support`).
