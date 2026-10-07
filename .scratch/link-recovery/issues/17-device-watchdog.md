# 17: Device watchdog set on open, written only when it differs

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 16

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001, ADR 0003

## What to build

On every successful open of the real T7, `Acquisition` (ticket 16) checks the
Device watchdog and sets it exactly as spec §2 *Device watchdog* says: read four
registers, write only if they differ, in the stated order, and never let a failure
block the Link. Simulation never touches it. Put the open-time step right after
the AIN `eWriteNames` call that `Acquisition` copied from `DaqWorker._open`.

## Acceptance criteria

Tests in `tests/test_daq.py` (new tests) use the `FakeLjm`, extended to record
every `eReadNames`/`eWriteNames` call and to hold register values. May fake: the
LJM module. Must be real: `Acquisition`.

- [x] `config.py` gains `WATCHDOG_TIMEOUT_S = 60`. Test
  `test_watchdog_written_when_off`: fake registers all 0 → after `Start`, exactly one
  `eWriteNames` call with names
  `["WATCHDOG_ENABLE_DEFAULT", "WATCHDOG_TIMEOUT_S_DEFAULT",
  "WATCHDOG_RESET_ENABLE_DEFAULT", "WATCHDOG_STRICT_ENABLE_DEFAULT",
  "WATCHDOG_ENABLE_DEFAULT"]` and values `[0, 60, 1, 0, 1]`, besides the AIN config
  write.
- [x] Test `test_watchdog_not_rewritten_when_already_set`: fake registers already
  `1, 60, 1, 0` → after `Start` and after a `Reopen`, no watchdog `eWriteNames`
  call was made (flash wear).
- [x] Test `test_watchdog_failure_does_not_block_link`: the watchdog read raises
  `OSError("bad")` → the events are `[LinkUp(<description>, …, warning=
  "Device watchdog not set: bad")]` and the next `tick` still returns a
  `SampleReady`.
- [x] Test `test_simulation_never_touches_watchdog`: `Start(Settings(simulate=True))`
  makes no LJM call at all.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — `Acquisition._set_device_watchdog` runs right after the AIN `eWriteNames` on every
real open: reads the four `_DEFAULT` registers, writes the five-name sequence only when they
differ from `1, 60, 1, 0`, and reports a failure on `LinkUp.warning`. `WATCHDOG_TIMEOUT_S = 60`
in `config.py`. Tests are in `tests/test_daq.py` (written when off, not rewritten when set,
each register differing, failure does not block, Simulation makes no LJM call).
Bench: confirm on the real T7 (ticket 25) that the registers read back `1, 60, 1, 0`.
