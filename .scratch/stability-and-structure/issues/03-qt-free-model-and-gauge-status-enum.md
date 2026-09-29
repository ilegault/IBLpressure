# 03: Qt-free model module, GaugeStatus enum, gauge pairs from CHANNELS

**What to build:** Move `Reading` and `Sample` into a Qt-free `model.py`, make the
status codes a `GaugeStatus` enum, and give `channels.py` the one definition of
each Location's gauge pair, so the CSV logger and every later core can be imported
without PySide6. Spec §2 *Structure*.

**Blocked by:** 02

**Status:** ready-for-agent

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

- [ ] **`src/ibl/model.py`** holds `Reading` (moved from `conversion.py`, same
  fields and methods) and `Sample` (moved from `daq.py`, same slots and `by_ain`).
  `conversion.py` imports `Reading` from `model`; `daq.py` and `csvlogger.py`
  import `Sample` from `model`. Test
  `tests/test_model.py::test_core_modules_do_not_import_qt` runs, in a subprocess
  with `src` on `PYTHONPATH`,
  `import sys, ibl.model, ibl.conversion, ibl.csvlogger, ibl.channels, ibl.config; print(any(m.startswith(("PySide6", "pyqtgraph")) for m in sys.modules))`
  and asserts the output is `False`.
- [ ] **`GaugeStatus`.** In `conversion.py`, replace the string constants with
  `class GaugeStatus(str, Enum)` members `OK = "OK"`, `FAULT = "Gauge Fault"`,
  `UNDER = "Under range"`, `OVER = "Over range"`, `NEGATIVE = "Neg Voltage"`,
  `APPROX = "Use IG"`. Keep module-level aliases `OK = GaugeStatus.OK` etc. only if
  something still imports them; `Reading.status` is typed `GaugeStatus`.
  `tests/test_conversion.py::test_convert_statuses` is rewritten in place to compare
  against `GaugeStatus` members.
- [ ] **CSV text unchanged.** `tests/test_csvlogger.py::test_fault_written_as_words`
  writes one `Sample` with a faulted IG on AIN0 through `DailyCsvLogger(tmp_path)`
  and asserts the row's `SNICS IG (Torr)` cell is exactly `Gauge Fault` (not
  `GaugeStatus.FAULT`) and a good CG cell is formatted `%.4E`. This test guards behaviour that must not
  change, so it also passes on the old code; integrity check 7 will hold the PR
  for the developer's merge because of it. Expected.
- [ ] **Pairs in one place.** `channels.py` gains
  `LOCATIONS: tuple[str, ...]` (the seven locations in wiring order) and
  `PAIRS: tuple[tuple[Channel, Channel], ...]` (IG first, CG second, one per
  Location), built from `CHANNELS`, plus `def pair_index(ain: int) -> int`.
  `tests/test_channels.py` asserts: 7 pairs; every pair shares a location; the first
  of each pair `is_ion` and the second is not; `pair_index(c.ain)` is the index of
  the pair containing `c` for all 14 channels. Replace every `pair * 2`,
  `pair * 2 + 1` and `ain // 2` in `mainwindow.py` with `PAIRS` / `pair_index`
  (grep must find none afterwards).
- [ ] Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
