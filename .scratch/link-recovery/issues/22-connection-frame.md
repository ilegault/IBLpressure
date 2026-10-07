# 22: Connection frame: today's recoveries and recent Link events

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

**Blocked by:** 21

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001

## What to build

A new **Connection** group inside the Settings box (`src/ibl/ui/settings_panel.py`,
added with the same `add(col, title)` helper as the other groups, so it collapses
with Settings and never takes over the screen). It shows `LinkLog.summary(now)`, the
last `CONNECTION_FRAME_EVENTS` lines from `LinkLog.recent()` newest first in a
read-only list, and an **Open Link log** button that opens the link-log folder via
`TopBar.open_folder`. The window refreshes it after every Link log record and at
startup.

## Acceptance criteria

Qt tests in `tests/test_panels.py` (new tests) use the window fixture with a fake
child and `csv_dir=tmp_path`. May fake: the child handle, the clock, `open_folder`.
Must be real: `LinkLog`, the panel widgets.

- [ ] The Settings box contains a group titled `Connection` with a summary label, a
  `QListWidget` that is not editable, and a button labelled `Open Link log`.
- [ ] Test `test_frame_shows_todays_summary`: after two recoveries (Reopen, gap 7 s;
  Library reset, gap 42 s) the label reads
  `Today: 2 recoveries — Reopen 1, Library reset 1 · longest gap 42 s`.
- [ ] Test `test_frame_lists_newest_twenty`: after 25 Link log records the list has 20
  rows and row 0 is the newest record's line.
- [ ] Test `test_open_link_log_button`: clicking it calls `open_folder` with
  `<csv_dir>/link-log`.
- [ ] Test `test_frame_survives_restart`: a new window on the same `csv_dir` shows
  the same summary and rows (read back from the month file).

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments
