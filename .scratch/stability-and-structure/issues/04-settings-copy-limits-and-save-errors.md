# 04: Worker gets its own Settings copy; limits and save errors

**What to build:** Stop the window and the acquisition thread sharing one mutable
`Settings` object (which silently breaks reconnect-on-change), put every settings
limit in `config.py` with clamping on load, add `late_after_samples`, and report
save failures instead of swallowing them. Spec §1.4, §2 *Settings*.

**Blocked by:** 03

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

- [ ] **Limits.** `config.py` defines `MIN_SAMPLE_HZ = 0.1`, `MAX_SAMPLE_HZ = 10.0`,
  `MIN_HISTORY_S = 3600`, `MAX_HISTORY_S = 24 * 3600`, `MIN_LATE_AFTER_SAMPLES = 2`,
  `MAX_LATE_AFTER_SAMPLES = 20`, `MIN_CSV_INTERVAL_S = 1.0`,
  `MAX_CSV_INTERVAL_S = 3600.0`, and a field `late_after_samples: int = 3`. Add
  `def clamped(self) -> "Settings"` returning a copy with `sample_hz`, `history_s`,
  `late_after_samples`, `csv_interval_s` clamped into range; `Settings.load` returns
  `clamped()`. `tests/test_config.py::test_load_clamps_out_of_range_values` writes a
  JSON file with `sample_hz: 20`, `history_s: 172800`, `late_after_samples: 1`,
  `csv_interval_s: 0.2` and asserts the loaded values are 10.0, 86400, 2, 1.0.
  `test_load_keeps_defaults_for_missing_keys` asserts `late_after_samples == 3`
  when the key is absent.
- [ ] **Widgets read their ranges from `config.py`.** In `mainwindow.py`,
  `spn_hz` uses `MIN_SAMPLE_HZ`/`MAX_SAMPLE_HZ`, `spn_hist` uses
  `MIN_HISTORY_S // 3600`/`MAX_HISTORY_S // 3600`, `spn_csv` uses the CSV limits;
  each spin's constructor default equals the `Settings()` default (1.0 Hz, 24 hr,
  10.0 s; curve opacity 31 %, grid opacity 30 %). `DaqWorker._apply_interval`
  clamps with the config constants instead of `0.05` / `20.0`.
- [ ] **The worker never holds the window's object.** `MainWindow` passes
  `dataclasses.replace(self.settings)` to `DaqWorker(...)` and emits
  `settings_changed` with `dataclasses.replace(s)`. Tests in
  `tests/test_window_smoke.py` (window built as in `test_window_opens_in_simulation`):
  `test_window_and_worker_do_not_share_settings` asserts
  `window.worker._settings is not window.settings` right after construction;
  `test_settings_change_reaches_worker_as_a_copy` toggles
  `window.chk_sim.setChecked(not window.settings.simulate)`, then
  `qtbot.waitUntil(lambda: window.worker._settings.simulate == window.settings.simulate)`
  and asserts `window.worker._settings is not window.settings`. (On the old code the
  two are the same object, so the first test fails there — that is the bug that made
  `DaqWorker.update_settings`'s `relink` always false.)
- [ ] **Save errors are reported.** `Settings.save` returns `""` on success and
  `"Settings not saved: <reason>"` on `OSError`. `MainWindow._on_widget_changed`
  shows a non-empty result in `lbl_csv`'s neighbour status (`lbl_status`) and in the
  log. Test `test_save_reports_unwritable_path` saves to a path inside a file
  (e.g. `tmp_path/"f.txt"/"settings.json"` where `f.txt` is a file) and asserts the
  return starts with `Settings not saved:`. Replace `closeEvent`'s bare
  `except Exception: pass` around saving with the same reporting (print to stderr is
  acceptable there since the window is closing).
- [ ] Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
