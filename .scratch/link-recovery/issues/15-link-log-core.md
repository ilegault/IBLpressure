# 15: Link log core: monthly files with folded repeats

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None (can start immediately)

**Spec:** `.scratch/link-recovery/spec.md`
**Binding:** ADR 0001

## What to build

A module `src/ibl/linklog.py` that writes the Link log exactly as spec §2 *Link
log* describes: one file per month, one line per event, repeats folded, plus the
two things the Connection frame (ticket 22) will show — the last N lines and
today's recovery summary. File I/O is its job (AGENTS.md rule 1), so it may touch
the filesystem, but it takes `now` on every call and never reads the clock.
Pattern to copy for the file handling and error reporting: `DailyCsvLogger` in
`src/ibl/csvlogger.py` (`_ensure_file`, `write`, `last_error`). Nothing calls it
yet; ticket 21 does.

## Acceptance criteria

Tests in `tests/test_linklog.py` write real files under `tmp_path`; nothing is
faked. Convert `now` with local time exactly as `link.py` does for the Recovery
stamp, and build expected strings the same way in the test.

- [x] `config.py` gains `LINK_LOG_FOLD_S = 600.0` and `CONNECTION_FRAME_EVENTS = 20`.
  `LinkLog(directory)` has `record(now, kind, detail="", fold_key=None, step=None,
  gap_s=None) -> bool`, `recent(n) -> list[str]` (newest first), `summary(now) -> str`,
  `reconfigure(directory)` and `last_error`.
- [x] Test `test_one_file_per_month`: records at local 2026-10-31 23:59 and
  2026-11-01 00:01 land in `link-log/2026-10.log` and `link-log/2026-11.log`
  (directory created on first write); each line is
  `YYYY-MM-DD HH:MM:SS  KIND  detail`. A new `LinkLog` on the same directory appends
  (the earlier lines are still there, no header).
- [x] Test `test_repeats_fold_into_one_line`: 120 `record(t, "LINK_DOWN", "1298 …",
  fold_key="1298")` calls 5 s apart starting at t0 write exactly one `LINK_DOWN`
  line for the first 600 s; the first record after the window, or an
  intervening `record(t, "RECOVERED", …)` (no `fold_key`), first writes
  `REPEATED  LINK_DOWN 1298 ×{n} since {HH:MM:SS of t0}` with the right count. A
  record with no `fold_key` is always written in full. Test
  `test_alternating_keys_fold_independently`: alternating `RECONNECTING`
  (`fold_key="Acquisition restart"`) and `LINK_DOWN` (`fold_key="1298"`) records
  every 30 s for 600 s write one line of each plus nothing else until the window
  ends.
- [x] Test `test_summary_counts_todays_recoveries`: after RECOVERED records
  (`step="Reopen", gap_s=7`), (`"Reopen", 12`), (`"Library reset", 42`) today and
  one yesterday, `summary(now)` is
  `Today: 3 recoveries — Reopen 2, Library reset 1 · longest gap 42 s`; with one it
  is `Today: 1 recovery — Reopen 1 · longest gap 7 s`; with none,
  `Today: no recoveries`. A new `LinkLog` opened on the same directory gives the
  same summary and `recent(20)` (it reads back the current month's file).
- [x] Test `test_write_failure_is_reported`: with `directory` pointing at a path
  that is a regular file, `record` returns `False`, `last_error` starts
  `Link log not written:` and no exception escapes.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `pytest -q`

## Comments

2026-10-07 — Implemented `src/ibl/linklog.py` (`LinkLog`) and `LINK_LOG_FOLD_S`,
`CONNECTION_FRAME_EVENTS` in `config.py`. `tests/test_linklog.py` covers each criterion on real
files under `tmp_path`: monthly files and append, folding with exact counts, independent keys,
summary and reload, write failure. `recent()` also reads back into earlier months.
