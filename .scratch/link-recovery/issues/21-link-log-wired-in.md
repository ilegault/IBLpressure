# 21: Link log records every Link event

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 15, 20

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001

## What to build

The window writes the Link log (ticket 15) for everything spec §2 *Link log*
lists: app start and stop, Connect, Disconnect, each `Up` (with LJM version,
firmware, connection, identifier, sample rate and any watchdog warning), `Down`,
`Reconnecting`, read errors, Hand-off (once, when it begins) and each Recovery
(from `LinkMonitor.sample`'s `Recovery`, with step and gap). Repeating failures are
folded with `fold_key`. The log lives in `<csv_dir>/link-log/` and follows a CSV
folder change. A write failure is reported, never silent (AGENTS.md rule 7): show
it the way `_settings_problem` is prefixed to the status line in `_render_link`.

## Acceptance criteria

Tests in `tests/test_window_linklog.py` use the window fixture with a fake child
(as in ticket 20) and `csv_dir=tmp_path`; they read the real log file. May fake:
the child handle, the clock. Must be real: `LinkLog` and its file.

- [x] Test `test_session_is_logged`: build the window, Connect, fake `LinkUp`, a
  Sample, Disconnect, close → the month file holds, in order, lines with kinds
  `APP_START`, `CONNECT`, `LINK_UP`, `DISCONNECT`, `APP_STOP`; the `LINK_UP` line
  contains the description, the LJM version and firmware strings from the fake,
  `USB`, `ANY` and `1 Hz`.
- [x] Test `test_recovery_line_names_step_and_gap`: a loss recovered by Library reset
  after a 42 s gap writes `RECOVERED  Library reset · gap 42 s`.
- [x] Test `test_overnight_failure_stays_short`: drive 8 h of failures with the fake
  clock (child answers every Attempt with `LinkDown("1298")`) → the file has fewer
  than 300 lines, exactly one `HAND_OFF` line, and at least one `REPEATED` line
  counting `LINK_DOWN`.
- [x] Test `test_link_log_follows_csv_folder`: changing the CSV folder in settings
  makes the next record land in `<new dir>/link-log/`.
- [x] Test `test_link_log_failure_is_reported`: with the link-log path blocked by a
  regular file, the status line starts `Link log not written:` and the app keeps
  running.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — `MainWindow` owns a `LinkLog` (follows the CSV folder) and records APP_START/APP_STOP,
CONNECT/DISCONNECT, LINK_UP (description, LJM version, firmware, connection, identifier, rate,
watchdog warning), LINK_DOWN and RECONNECTING (folded), READ_ERROR (folded), LOST (derived from the
first Attempt after read errors, because the Supervisor does not forward `Lost`), HAND_OFF (once per
loss) and RECOVERED (step and gap from `LinkMonitor.sample`'s `Recovery`; a Gap with no
Escalation step is written as `gap N s` and is not counted in the Connection summary).
A write failure is prefixed to the status line (`Link log not written: …`). `closeEvent` is guarded so
APP_STOP is written once. Tests: `tests/test_window_linklog.py`.
