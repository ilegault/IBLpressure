# 10: Daily CSV append safety and reloading History on startup

**What to build:** Make appending to an existing Daily CSV safe when the columns
change (new rows go to a `_b`, `_c`, … file instead of under the wrong header), and
refill the plot's History from yesterday's and today's CSVs when the app starts.
Spec §2 *CSV*; CONTEXT.md *Daily CSV*.

**Blocked by:** 07

**Status:** done

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

Tests in `tests/test_csvlogger.py`, real files in `tmp_path`, no Qt.

- [x] **Appending keeps working.** `test_restart_appends_to_todays_file`: write 3
  rows with one logger, close it, write 2 rows with a new logger on the same folder
  and date → one file, one header line, 5 data rows. (This already works and must keep working, so the
  test passes on the old code too; integrity check 7 will hold the PR for the
  developer's merge. Expected.)
- [x] **Column change never mixes headers.** `test_header_change_starts_suffixed_file`:
  write rows without volts, then reconfigure with `include_voltages=True` and write
  → `2026-09-28.csv` still has only the no-volts header and its rows;
  `2026-09-28_b.csv` has the volts header and the new rows. A third header change
  back to no-volts appends to `2026-09-28.csv` again (first candidate with a
  matching header). Implement as a pure helper
  `choose_daily_path(directory, day: date, header: list[str]) -> str` used by
  `_ensure_file`, with its own test.
- [x] **Reader.** `read_daily_csv(path) -> Iterator[tuple[float, list[float]]]`
  yields `(epoch_s, pressures in CHANNELS order)`, mapping `Gauge Fault`, `Neg Voltage`,
  `Under range`, `Over range` and empty cells to NaN and `~`-prefixed values to
  their number; columns are matched by header name, so files with or without volts
  both load. Test round-trips a Sample through `write` → `read_daily_csv` and a
  fault cell comes back NaN.
- [x] **Startup reload.** `load_recent_history(directory, now, span_s, history)`
  reads every Daily CSV for `now`'s date and the day before (all suffixes), sorts by
  time, and appends rows with `epoch_s >= now - span_s` into `history`. The window
  calls it once in `__init__` before the worker starts, and shows
  `History reloaded: N rows from CSV` in the CSV label. Test with two days of files
  in `tmp_path` asserts only rows inside the span land in `History` and a malformed
  line is skipped and counted, not raised.
- [x] Update `csvlogger.py`'s module docstring (append, suffix rule, reload).
  Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
- 2026-09-29: Implemented. `choose_daily_path`, `read_daily_csv`, `load_recent_history` in `csvlogger.py`; `_ensure_file` uses the path chooser; the window reloads History once in `__init__` before the worker starts. If lines are unreadable the label adds `(N unreadable lines skipped)` after the required text. Ticket stays in-progress until the PR merges.
- 2026-09-29: PR merged, ticket set to done.
