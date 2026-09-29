# 07: Two-tier History and min/max decimation (pure core)

**What to build:** A Qt-free `src/ibl/history.py` holding at most 24 h of pressures
in two tiers (every Sample for the last hour, per-10-s min/max beyond that) and a
`minmax_decimate` function that turns any time window into at most two points per
Plot bucket, with Gaps as breaks. Not wired into the plot yet (ticket 08).
ADR 0002; spec §2 *History and plot*.

**Blocked by:** 03

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

Tests in `tests/test_history.py`, numpy only, explicit timestamps.

- [x] **API.** `RAW_SPAN_S = 3600`, `SUMMARY_BUCKET_S = 10`.
  `class History(n_channels: int, max_span_s: int = config.MAX_HISTORY_S, raw_span_s: int = RAW_SPAN_S, bucket_s: int = SUMMARY_BUCKET_S, max_rate_hz: float = config.MAX_SAMPLE_HZ)`
  with `append(t: float, values: np.ndarray)` (length `n_channels`, NaN = no valid
  pressure; timestamps non-decreasing), `window(channel, t0, t1) -> (t, lo, hi)`
  numpy arrays in time order (raw points have `lo == hi`), `clear()`, and
  `memory_bytes() -> int`. Storage is preallocated numpy arrays; no Python lists
  of samples.
- [x] **Tiers.** `test_recent_hour_is_full_resolution`: 3 600 samples at 1 Hz →
  `window` over the last hour returns 3 600 points with `lo == hi`.
  `test_older_data_is_summarised_with_minmax`: 2 h at 1 Hz where channel 0 is 1e-7
  except one spike of 5e-5 at t=1 800 → the window over the first hour returns
  360 buckets and exactly one bucket has `hi == 5e-5` and `lo == 1e-7`.
  `test_all_nan_bucket_stays_nan` and `test_partial_nan_bucket_uses_finite_values`.
- [x] **Bounded.** `test_drops_data_older_than_max_span`: 25 h at 1 Hz → nothing
  earlier than `t_last - 24 h` is returned. `test_memory_is_bounded_at_max_rate`:
  `History(14).memory_bytes() < 25 * 1024 * 1024` (sized for 10 Hz).
- [x] **`minmax_decimate(t, lo, hi, t0, t1, n_buckets, gap_s) -> (t_out, p_out)`.**
  At most `2 * n_buckets` finite points plus NaN breaks; each bucket emits its
  minimum and maximum in the order they occur; a bucket with no finite data emits
  one NaN; two consecutive output points further apart than `gap_s` get a NaN
  between them. Tests: `test_decimate_caps_points` (86 400 points, 1 000 buckets →
  `len(t_out) <= 2 000 + number of NaNs`), `test_decimate_keeps_spike`,
  `test_gap_becomes_a_break` (samples at 0–100 s and 200–300 s, `gap_s=3` → a NaN
  exists between t=100 and t=200 in `p_out`).
- [x] **Speed guard with a physical reason.** `test_24h_window_decimates_fast`:
  24 h at 1 Hz for 7 channels appended; decimating all 7 to 1 000 buckets takes
  < 0.25 s total (`time.perf_counter`), with a comment: the plot redraws on the GUI
  thread, and anything near a second is the freeze this effort fixes.
- [x] Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments

- 2026-09-29: Implemented `src/ibl/history.py` and `tests/test_history.py` (20 tests). Awaiting review
  and merge, so Status stays `in-progress` until it lands.
- Choices the ticket left open: `window` is half-open `[t0, t1)`; a Summary point is stamped with the
  start of its bucket (so it always sorts before the Raw points after it); a Raw sample folds into the
  Summary once it is `raw_span_s` old, and also if the Raw ring is full (faster than `max_rate_hz`).
  `minmax_decimate` of a window with no data returns one NaN per bucket, as the ticket says for an
  empty bucket.
- Local gate: `ruff check .`, `check_tests_first.py` and `pytest` pass, except `test_window_smoke.py`,
  which needs the system Qt libraries this sandbox lacks (CI runs it).
