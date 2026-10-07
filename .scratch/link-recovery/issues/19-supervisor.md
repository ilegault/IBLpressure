# 19: Supervisor: run, watch and restart the acquisition child

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 14, 16

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001, ADR 0003

## What to build

A module `src/ibl/supervisor.py` (no Qt) that runs in the window process. It
starts the acquisition child, drains its events, drives the `Escalation` (ticket 14)
from them, sends `Reopen` / `LibraryReset` or performs an Acquisition restart when
an Attempt is due, declares a silent child hung after `HUNG_AFTER_S`, and turns
everything into window events. It never blocks for longer than one stop
(`STOP_TIMEOUT_S`). The child is reached through a small handle interface so tests
can fake it; `spawn_child(settings)` is the real implementation using
`multiprocessing.get_context("spawn")`, two queues and `acquisition.run` as the
target (`daemon=True`). Nothing in the window uses it yet; ticket 20 does.

## Acceptance criteria

Unit tests in `tests/test_supervisor.py` use a `FakeChild` handle (`send`,
`receive` returning queued events, `alive`, `terminate`, `kill`, `join`) that
records every command and kill, and pass `now` explicitly. May fake: the child
handle. Must be real: `Supervisor` and `Escalation`. One test uses the real child.

- [ ] `config.py` gains `STOP_TIMEOUT_S = 2.0`. `Supervisor(spawn=spawn_child)` has
  `connect(now, settings)`, `disconnect(now)`, `update_settings(now, settings)`,
  `poll(now) -> list` and `shutdown() -> None`. Window events (frozen dataclasses in
  `supervisor.py`): `Up(description, ljm_version, firmware, warning, recovered_by)`,
  `Down(reason, attempt)`, `Reconnecting(attempt)`, `ReadError(message)`,
  `NewSample(sample)`. `connect` spawns a child and sends `Start(settings)`.
- [ ] Test `test_mid_run_loss_climbs_and_recovers`: child sends `LinkUp`, then
  `Lost("timeout")` at t=10 → `poll(10)` returns `Reconnecting(Attempt(Reopen, 1, …))`
  and the child received `Reopen()`; child answers `LinkDown("1298")` → `poll` returns
  `Down("1298", <that Attempt>)`; stepping time, the 4th Attempt sends
  `LibraryReset()`; the child answers `LinkUp` → `poll` returns
  `Up(…, recovered_by=Step.LIBRARY_RESET)`.
- [ ] Test `test_acquisition_restart_replaces_the_child`: driving failures until an
  Acquisition restart is due → the old `FakeChild` got `kill()` (after `Quit()` and
  `join`), `spawn` was called a second time, and the new child received
  `Start(settings)` with the same settings. Test `test_silent_child_is_hung`: a
  connected child that sends nothing for 15.1 s → `poll` returns
  `Down("acquisition not responding", …)`, then a `Reconnecting` for an Acquisition
  restart, and the old child was killed.
- [ ] Test `test_open_failure_at_connect_waits_five_seconds`: child answers `Start`
  with `LinkDown("no device")` → `poll(0)` returns `Down("no device", None)`, nothing
  is sent before t=5, and `Reopen()` is sent at `poll(5)`. Test
  `test_disconnect_kills_a_child_that_ignores_quit`: a `FakeChild` whose `join` leaves
  it alive → `disconnect` sends `Quit()`, then calls `terminate()` and `kill()`, and
  later `poll`s return nothing.
- [ ] Test `test_real_child_streams_simulated_samples` (real process, no fake): connect
  with `Settings(simulate=True, sample_hz=10)`, poll with the real clock for up to
  20 s until a `NewSample` arrives; then `shutdown()` returns in under 4 s and the
  child process is no longer alive.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments
