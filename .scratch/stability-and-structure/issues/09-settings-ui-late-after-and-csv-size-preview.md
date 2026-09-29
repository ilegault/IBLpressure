# 09: Settings panel — "Late after" with preview, CSV size preview, new limits

**What to build:** Add the *Late after N missed samples* control with a live
seconds preview, a live *≈ size per day* preview next to *Write every*, and enforce
the 10 Hz / 24 h limits in the panel. Spec §2 *Settings*.

**Blocked by:** 04, 06

**Status:** done

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

- [x] **Pure preview helpers.** In `config.py`:
  `late_preview(late_after_samples: int, sample_hz: float) -> str` returning
  `= {seconds:.1f} s at {hz:g} Hz`. In `csvlogger.py`:
  `estimate_bytes_per_day(interval_s: float, include_voltages: bool) -> int` =
  header bytes + `ceil(86400 / interval_s)` × bytes of one row produced by the
  logger's own row formatter (factor the row-building out of `write` into
  `format_row(sample, include_voltages) -> list[str]` and measure a synthetic
  all-OK Sample written through `csv.writer` to an `io.StringIO`), and
  `format_size_preview(nbytes: int, rows: int) -> str` giving
  `≈ {x:.1f} KB per day ({rows:,} rows)` below 1 MB, else `≈ {x:.1f} MB per day (…)`
  (1 KB = 1024 B). Tests in `tests/test_config.py` / `tests/test_csvlogger.py`:
  `late_preview(3, 1.0) == "= 3.0 s at 1 Hz"`, `late_preview(2, 0.5) == "= 4.0 s at 0.5 Hz"`;
  `estimate_bytes_per_day(10, True) > estimate_bytes_per_day(10, False)`;
  **the estimate matches reality**: write 100 rows with `DailyCsvLogger` into
  `tmp_path`, and assert the file size is within 2 % of
  `header + 100 * row_bytes` from the same formula.
- [x] **Late after control.** In the *Acquisition* group, add
  `Late after:` → `CompactSpin(MIN_LATE_AFTER_SAMPLES, MAX_LATE_AFTER_SAMPLES, 3, suffix=" samples")`
  bound to `settings.late_after_samples`, with a `QLabel` beside it showing
  `late_preview(...)`, updated when either the spin or the update rate changes.
  Tooltip: `The status turns amber (Late) and the table shows STALE when this many samples in a row are missing.`
  Test: set rate 0.5 Hz and late-after 2 → label text `= 4.0 s at 0.5 Hz` and the
  window's `LinkMonitor.late_threshold_s == 4.0`.
- [x] **CSV size preview.** In the *CSV logging* group, a `QLabel` under *Write
  every* shows `format_size_preview(...)` for the current interval and raw-volts
  checkbox, updated live. Test: interval 10 s, no volts → text ends
  `(8,640 rows)`; ticking *Also record raw volts* makes the size larger.
- [x] **Limits in the UI.** The rate spin cannot exceed 10 Hz, the history spin
  cannot exceed 24 hr (both from `config.py`). Test: `spn_hz.setValue(20)` →
  `spn_hz.value() == 10.0` and `window.settings.sample_hz == 10.0`.
- [x] Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
- 2026-09-29: Implemented. `late_preview` in `config.py`; `header`, `format_row`, `estimate_bytes_per_day`, `format_size_preview` in `csvlogger.py`; Late-after spin, its preview and the CSV size label in the settings panel. The size estimate uses a realistic epoch timestamp so its row width matches real rows. Ticket stays in-progress until the PR merges.
- 2026-09-29: PR merged, ticket set to done.
