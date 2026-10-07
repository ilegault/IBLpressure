# 16: Acquisition core: the T7 conversation, Qt-free

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001, ADR 0003

## What to build

Move the T7 conversation out of `DaqWorker` into `src/ibl/acquisition.py`, which
imports neither PySide6 nor pyqtgraph, so it can run in a child process (ticket 19).
It defines the command and event dataclasses of spec §2 *Process split*, an
`Acquisition` class that turns each command and each `tick(now)` into a list of
events, and `run(commands, events)`, a thin loop over two queues. Copy the logic
from `src/ibl/daq.py`: `_Simulator` (move it), `DaqWorker._open` (AIN config via
`eWriteNames`), `_close`, the read in `_tick`, and the relink rule of
`update_settings`. Unlike `DaqWorker`, it never retries on its own: after 3 failed
reads it closes the handle and reports `Lost`. `DaqWorker` stays in use until
ticket 20; it may import `_Simulator` from `acquisition`.

## Acceptance criteria

Rewrite the tests in `tests/test_daq.py` in place (same test names) so they
drive `Acquisition` directly with the `FakeLjm` already in that file (extend it with
`readLibraryConfigS` and `eReadName`) and an explicit `now`. May fake: the LJM
module. Must be real: `Acquisition`.

- [ ] Events per command: `Start(Settings(simulate=True))` → `[LinkUp("Simulation mode",
  "", "", "")]`; `Start` on the fake T7 → `[LinkUp("T7 #470012345 over USB",
  <LJM version string>, <firmware string>, "")]`; a failing `openS` →
  `[LinkDown("no device")]`. `Reopen()` closes then opens; `LibraryReset()` calls
  `closeAll` (assert the fake counted it) then opens. Rewritten
  `test_failed_open_reports_link_down` etc. assert these lists exactly.
- [ ] `tick(now)` at the sample interval returns `[SampleReady(sample)]` with 14
  Readings; rewritten `test_failed_read_emits_read_error_then_reconnects_after_three`
  asserts two ticks give `[ReadError("timeout")]` each and the third gives
  `[ReadError("timeout"), Lost("timeout")]`, after which the fake's `close` was
  called and further ticks return no `SampleReady` and no `openS` call (no
  self-retry). `test_retry_when_not_connected_announces_attempt` is rewritten in
  place to assert that a closed `Acquisition` never calls `openS` from `tick`.
- [ ] `tick` returns `Alive()` whenever `HEARTBEAT_S = 1.0` (new constant in
  `config.py`) has passed since the last event it returned, connected or not.
- [ ] `ApplySettings` with a changed `connection`, `identifier`, `resolution_index`
  or `simulate` closes and reopens (events as for `Reopen`); a changed `sample_hz`
  only changes the read interval (no `openS` call). `Quit()` closes and calls
  `closeAll`, and `run` returns. Test `test_run_loop_exits_on_quit` feeds
  `queue.Queue`s in-process: `Start(simulate)`, then `Quit()`; `run` returns and the
  event queue held a `LinkUp` and at least one `SampleReady`.
- [ ] Test `test_acquisition_imports_no_qt` runs
  `python -c "import sys, ibl.acquisition; print('PySide6' in sys.modules)"` in a
  subprocess with `src` on `PYTHONPATH` and asserts it prints `False`. All events
  and commands round-trip through `pickle`.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments
