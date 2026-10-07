# 18: LinkMonitor names the Escalation step

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 14

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001

## What to build

`LinkMonitor` (`src/ibl/link.py`) learns about Escalation so the status line
reads exactly as the table in spec §2 *Status texts*: the step and attempt while
reconnecting and after a failure, the Hand-off message, and the step that worked
in the Recovery text. `LinkView` gains `detail` (latest LabJack error while not
Live) and the top bar shows it as the status line's tooltip. The window still
runs on `DaqWorker` until ticket 20, so this ticket also adapts
`MainWindow._on_reconnecting` and `_on_link_down` to the new signatures.

## Acceptance criteria

Tests in `tests/test_link.py` drive a real `LinkMonitor` with explicit `now` and
hand-built `Attempt`s from `ibl.escalation`; window tests in
`tests/test_window_link.py` use the existing `window` fixture and fake clock.

- [x] Signatures: `reconnecting(now, attempt: Attempt)`,
  `link_down(now, reason, attempt: Attempt | None = None)`,
  `link_up(now, description, recovered_by: Step | None = None)`, and
  `sample(now) -> Recovery | None` where frozen `Recovery(gap_s, step)` is returned
  only on the Sample that ends a Gap. Rewrite `test_reconnecting_text` and the test
  asserting `T7 not found: no device. Retrying every 5 s.` in place to the new texts.
- [x] Tests assert every row of the spec's status-text table verbatim, one test per
  row (`Reconnecting — Library reset (attempt 2 of 3)…`,
  `T7 not found: 1298. Acquisition restart (attempt 2) failed; next try in 30 s.`,
  `T7 not found: no device. Next try in 5 s.`, the Hand-off text with
  `attempt 9` and dot `#d62728` both while in flight and after failure, and
  `Live · Recovered at {stamp} after a 42 s gap (Library reset)`), plus that a
  Recovery with no Escalation keeps the old text with no parentheses.
- [x] `LinkView.detail` is the latest `link_down` reason or read error while the
  state is not Live, and `""` when Live or Idle. Test in `tests/test_window_link.py`:
  after `window._on_link_down("1298 LJME_ATTR_LOAD_COMM_FAILURE")` and a render,
  `window.topbar.lbl_status.toolTip()` contains that text; after a Live Sample it
  does not.
- [x] Until ticket 20, `MainWindow._on_reconnecting(attempt: int)` passes
  `Attempt(Step.REOPEN, attempt, TRIES_PER_STEP, attempt, False)` and
  `_on_link_down(reason)` passes no Attempt, each with a comment `# replaced in
  ticket 20`. Existing tests in `tests/test_window_link.py` and
  `tests/test_window_smoke.py` still pass unchanged.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — `LinkMonitor` now takes `Attempt`s and `recovered_by`, returns `Recovery` from
`sample`, and `LinkView.detail` carries the latest LabJack error while Late/Down. The top bar's
`show_link` adds it to the status line's tooltip. Texts are asserted verbatim, one test per row of
the spec table, in `tests/test_link.py`; window tests in `tests/test_window_link.py`.
`MainWindow._on_reconnecting` / `_on_link_down` adapted with `# replaced in ticket 20`.
Note for ticket 19: the Hand-off text needs `Attempt.hand_off` True on the *failed* first
Acquisition restart, so the Supervisor passes `dataclasses.replace(attempt, hand_off=esc.hand_off)`
to `Down` after calling `Escalation.failed`.
