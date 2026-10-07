# 14: Escalation core: which recovery step comes next

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001 (tests first), ADR 0003

## What to build

A pure module `src/ibl/escalation.py` (no PySide6, no `time.time()`, every method
takes `now`) that decides Escalation as spec §2 *Escalation* describes: Reopen ×3 →
Library reset ×3 → Acquisition restart forever, Hand-off after the first
Acquisition restart fails, and the step that worked on Recovery. Nothing calls it
yet; ticket 19 does. Pattern to copy: `src/ibl/link.py` (`LinkMonitor`), a frozen
dataclass for the answer and a class that takes `now` on every event.

## Acceptance criteria

Tests in `tests/test_escalation.py` drive a real `Escalation` with explicit `now`
values; nothing is faked.

- [ ] `config.py` gains `RETRY_INTERVAL_S = 5.0`, `TRIES_PER_STEP = 3`,
  `ACQUISITION_RESTART_INTERVAL_S = 30.0`, `HUNG_AFTER_S = 15.0`. `escalation.py`
  defines `Step` (values `"Reopen"`, `"Library reset"`, `"Acquisition restart"`),
  frozen `Attempt(step, number, of, total, hand_off)` (`of` is `TRIES_PER_STEP` for
  Reopen/Library reset and `None` for Acquisition restart) and `Escalation` with
  `lost(now, retry_now)`, `due(now) -> Attempt | None`, `failed(now, reason)`,
  `hung(now)`, `recovered(now) -> Step | None`, `reset()`, and properties
  `climbing`, `hand_off`, `in_flight`.
- [ ] Test `test_full_climb_order_and_timing`: `lost(0, retry_now=True)`, then
  repeatedly call `due(t)` and, whenever it returns an Attempt, `failed(t, "1298")`,
  stepping `t` by 1 s up to 130 s. The Attempts returned, as `(t, step.value, number,
  total)`, are exactly: (0, Reopen, 1, 1), (5, Reopen, 2, 2), (10, Reopen, 3, 3),
  (15, Library reset, 1, 4), (20, Library reset, 2, 5), (25, Library reset, 3, 6),
  (30, Acquisition restart, 1, 7), (60, Acquisition restart, 2, 8),
  (90, Acquisition restart, 3, 9), (120, Acquisition restart, 4, 10). `due` returns
  `None` while an Attempt is in flight (before `failed`) and at every other second.
- [ ] Test `test_hand_off_starts_after_first_restart_fails`: in the climb above,
  `hand_off` is `False` up to and including the Attempt at t=30, `True` from the
  `failed` call at t=30 onward, and every later Attempt has `hand_off=True`.
- [ ] Test `test_connect_failure_waits_five_seconds`: `lost(0, retry_now=False)` →
  `due(4.9)` is `None`, `due(5.0)` is `Attempt(Reopen, 1, 3, 1, False)`.
  Test `test_hung_jumps_to_restart`: after `lost(0, True)` and Reopen #1 in flight,
  `hung(3)` → `due(3)` is an Acquisition restart Attempt with `number=1`, `total=2`.
- [ ] Test `test_recovery_reports_step_and_resets`: climb to Library reset #2 in
  flight, `recovered(22)` returns `Step.LIBRARY_RESET`; afterwards `climbing` and
  `hand_off` are `False`, `due(100)` is `None`, and a new `lost(200, True)` makes
  `due(200)` return `Attempt(Reopen, 1, 3, 1, False)`. `recovered` when not
  climbing returns `None`. `reset()` mid-climb behaves like recovery but returns
  nothing.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments
