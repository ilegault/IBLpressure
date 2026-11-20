# 26: Connection frame summary rolls over at midnight

**Status:** done

**Runner:** any

**Auto-merge:** yes

**Blocked by:** None

**Spec:** `.scratch/link-recovery/spec.md` (follow-up to ticket 22)
**Binding:** ADR 0001

## What was seen

On the lab PC on 2026-11-20 the Connection frame still read
`Today: 1 recovery — Acquisition restart 1 · longest gap 64 s`. That one recovery
happened on 2026-10-30, and the Link has stayed up ever since. The Link log file and
the event list are correct. Only the summary line is stale.

## Cause

`MainWindow._refresh_connection_frame` (`src/ibl/mainwindow.py`) is called only from
`MainWindow._log`, so the summary is recomputed only when a Link log line is written.
`LinkLog.summary(now)` (`src/ibl/linklog.py`) gives the right answer for any `now`,
but nobody asks it again after midnight. A quiet Link therefore leaves an old day's
summary on screen under the word "Today".

## What to build

1. `src/ibl/linklog.py`: add a module-level pure function directly under `_local`:
   ```python
   def local_day(now: float) -> str:
       """The operator's calendar day for `now`, as `YYYY-MM-DD` (the prefix of every log line)."""
       return f"{_local(now):%Y-%m-%d}"
   ```
   In `LinkLog.summary`, replace `today = f"{local:%Y-%m-%d} "` with
   `today = f"{local_day(now)} "`. `local_day` must be pure (no Qt, takes `now`, no
   file access). The window must not do its own date arithmetic (AGENTS.md rule 1),
   and the window's day check and `summary` must agree on what "today" is.
2. `src/ibl/mainwindow.py`: change the import to `from .linklog import LinkLog, local_day`.
   In `MainWindow.__init__`, add `self._connection_frame_day = ""` with the other
   state fields (after `self._link_wanted = False`, before `_build_ui()` and before the
   `_log("APP_START", …)` call).
3. `MainWindow._refresh_connection_frame`: read the clock once into `now`, set
   `self._connection_frame_day = local_day(now)`, and pass that same `now` to
   `self.linklog.summary(now)`.
4. Add `MainWindow._refresh_connection_frame_on_new_day()` directly below it:
   ```python
   def _refresh_connection_frame_on_new_day(self) -> None:
       """The summary says "Today"; redraw it when the local day changes even if the Link is quiet."""
       if local_day(self._now()) != self._connection_frame_day:
           self._refresh_connection_frame()
   ```
   It must re-read the Link log **only** when the day has changed. The timer fires
   every 500 ms for weeks, and the month file grows forever.
5. In `__init__`, right after `self._link_timer.timeout.connect(self._render_link)`,
   add `self._link_timer.timeout.connect(self._refresh_connection_frame_on_new_day)`.
   Do not put the check inside `_render_link`, which is reserved for the dot and
   status line (AGENTS.md rule 3). Do not add a new QTimer.

## Acceptance criteria

The tests come first and must be seen failing. May fake: the clock (`window._now`, the
`clock` fixture in `tests/test_window_linklog.py`). Must be real: `LinkLog`, the
month file under `tmp_path`, and the window's own `_link_timer`.

- [x] `tests/test_linklog.py::test_local_day_is_the_operators_calendar_day` asserts
  `local_day(_ts(2026, 10, 30, 23, 59, 59)) == "2026-10-30"`,
  `local_day(_ts(2026, 10, 31, 0, 0, 0)) == "2026-10-31"` and
  `local_day(_ts(2026, 11, 1, 0, 0, 0)) == "2026-11-01"`.
- [x] `tests/test_window_linklog.py::test_summary_rolls_over_at_midnight_without_a_link_event(window, clock, qtbot)`
  logs `window._log("RECOVERED", step="Acquisition restart", gap_s=64)`, asserts
  `settings_panel.lbl_link_summary.text() == "Today: 1 recovery — Acquisition restart 1 · longest gap 64 s"`,
  then moves `clock.t` to 01:00 local time on the next day:
  `(_dt.datetime.fromtimestamp(clock.t, tz=_dt.UTC).astimezone() + _dt.timedelta(days=1)).replace(hour=1, minute=0, second=0, microsecond=0).timestamp()`.
  Using 01:00 keeps the time on the next day even across an overnight DST change.
  The test asserts `local_day` really changed, then
  `qtbot.waitUntil(lambda: label.text() == "Today: no recoveries", timeout=2000)`.
  After moving the clock, no window method may be called by hand: the real
  `_link_timer` must cause the change.
- [x] The same test asserts that one row of `settings_panel.lst_link_events` still
  contains `RECOVERED  Acquisition restart · gap 64 s` (the event list is history and
  is not cleared at midnight).
- [x] `LinkLog.summary` uses `local_day`. `_refresh_connection_frame_on_new_day` calls
  `_refresh_connection_frame` only when `local_day(now)` differs from
  `self._connection_frame_day`.
- [x] Existing Connection frame and Link log tests still pass, including
  `tests/test_panels.py::test_frame_shows_todays_summary` and
  `::test_frame_survives_restart` (no test: CI's full suite).

## Out of scope

The summary wording (no date added to "Today:"), Help text and tooltips (they
already say "today's recoveries"), `LinkLog.recent`, folding, the log file format,
the Daily CSV day rollover, History, the plot, Supervisor, Escalation, `_render_link`.

## Gate

Run in CI's order (`.github/workflows/ci.yml`):

1. `ruff check .`
2. `python scripts/check_tests_first.py`
3. `QT_QPA_PLATFORM=offscreen pytest -q tests/test_linklog.py tests/test_window_linklog.py`

pytest runs on the touched test files only; CI runs the full suite on the PR.

## Comments

2026-11-20: Filed after a photo of the lab PC showed the 2026-10-30 recovery still
counted under "Today" three weeks later.

2026-11-20: Added pure `local_day(now)` in `src/ibl/linklog.py` (used by
`LinkLog.summary`) and wired `MainWindow._refresh_connection_frame_on_new_day` to
`_link_timer.timeout` in `src/ibl/mainwindow.py` so the Connection frame summary
refreshes only when `local_day(self._now())` changes from
`self._connection_frame_day`. Covered by
`test_local_day_is_the_operators_calendar_day`,
`test_summary_rolls_over_at_midnight_without_a_link_event`, and
`test_connection_frame_refreshes_only_when_day_changes`.

CI red from master, not this ticket: ruff RUF100 on `src/ibl/csvlogger.py`, `tests/test_csvlogger.py`, and `tests/test_linklog.py:13` (5 errors). First red at `7a38a83` (direct push, no PR). Re-run CI once master is green: `gh run rerun 44820814627`.
