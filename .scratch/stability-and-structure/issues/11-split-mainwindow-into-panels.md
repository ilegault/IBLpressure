# 11: Split MainWindow into panels; theme without globals

**What to build:** Break the ~1 000-line `mainwindow.py` into focused panel
widgets under `src/ibl/ui/`, with `MainWindow` only wiring them to the worker,
`LinkMonitor`, `History` and the logger; read theme colours from the current theme
instead of module globals. Behaviour does not change. Spec §2 *Structure*.

**Blocked by:** 06, 08, 09, 10

**Status:** done

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

This is a refactor: the existing Qt tests (`tests/test_window_*.py`) are the safety
net and must pass unchanged in what they assert. Where a test reached into a
widget attribute that moves (e.g. `window.lbl_status`), rewrite that test in place
to reach it through the panel (`window.topbar.lbl_status`) — same name, same
assertions.

- [x] **Panels.** New modules, each one `QWidget` subclass with the widgets and
  appearance logic it owns:
  `ui/widgets.py` (`CompactSpin`, `TorrAxis`), `ui/topbar.py` (`TopBar`: connect,
  simulation, dark mode, dot, status, install, CSV label, log folder),
  `ui/table_panel.py` (`TablePanel`: the table, plot checkboxes, *Plot all/none/IG/CG*,
  `show_sample`, `show_stale`, fonts/columns), `ui/plot_panel.py` (`PlotPanel`: span,
  Y range, curves, legend, grid, caption, `redraw`), `ui/settings_panel.py`
  (`SettingsPanel`: `load(settings)`, `harvest(settings) -> Settings`, previews).
  `mainwindow.py` ends under 350 lines.
- [x] **No theme globals.** `ROW_FAULT_BG` & co. and the `global` statement are
  removed; panels take a `theme: dict` in `apply_theme(theme)`. Test
  `test_dark_mode_changes_stale_colour`: toggle dark mode, force stale, assert a
  pressure cell's background equals `DARK_THEME["stale_bg"]`.
- [x] **Panels are testable alone.** `tests/test_panels.py`:
  `SettingsPanel` round-trip (`load(s)` then `harvest(Settings())` equals `s` for a
  non-default `s`), and `TablePanel.show_sample` on a fault Sample colours only that
  row's IG cells.
- [x] **Nothing lost.** `grep -rn "except Exception:\s*$" src/ibl` followed by a
  bare `pass` finds none in `mainwindow.py` or `ui/`. README *Code layout* lists the
  new modules. Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
- 2026-09-29: Implemented. Panels under `src/ibl/ui/`; `mainwindow.py` is 349 lines; theme globals and the `global` statement are gone (panels take `apply_theme(theme)`). Tests that reached moved widgets were rewritten in place to go through the panels. Two test files (`test_window_smoke.py`, and the CSV-reload test in `test_window_plot.py`) now build the window in a fixture instead of a local variable: the old accidental reference cycle (button lambdas capturing the window) used to keep it alive until qtbot closed it; without it the window was garbage-collected with its worker thread still running, which aborts the process. Assertions are unchanged. Ticket stays in-progress until the PR merges.
- 2026-09-30: PR merged; set to done.
