# 08: Plot from History with per-pixel decimation and throttled redraw

**What to build:** Make the plot draw from `History` (ticket 07) through
`minmax_decimate`, redraw long spans only when a pixel's worth of time has passed,
and tell the operator on the plot when older data is summarised. This is the fix for
the 12 h / 24 h freeze. ADR 0002; spec §2 *History and plot*.

**Blocked by:** 06, 07

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

Qt tests in `tests/test_window_plot.py`, window built as in
`tests/test_window_smoke.py`, fake clock via `window._now`.

- [ ] **History replaces `Series`.** `MainWindow` holds one
  `History(len(CHANNELS))`; `_update_series` appends each Sample's pressures (NaN
  for `None` or ≤ 0); the `Series` class is removed; *Clear history* calls
  `History.clear()`. Curves no longer use pyqtgraph's own
  `setDownsampling`/`setClipToView`.
- [ ] **At most two points per pixel.** `_redraw_plot` asks each visible curve's
  data from `History.window` and `minmax_decimate` with
  `n_buckets = max(100, self.plot.width())` and `gap_s = self.link.late_threshold_s`.
  Test `test_24h_view_hands_bounded_points_to_curves`: fill History with 24 h at
  1 Hz for all channels, select `24 hours`, set the plot widget width to 1 000 px,
  call `_redraw_plot()`, and assert every visible curve's `getData()[0]` has at
  most 2 000 finite points.
- [ ] **Redraw throttle.** Pure function
  `redraw_interval_s(span_s, plot_width_px, sample_hz) = max(1 / sample_hz, span_s / plot_width_px)`
  in `history.py`, tested in `tests/test_history.py::test_redraw_interval`
  (300 s / 1 000 px / 1 Hz → 1.0; 86 400 s / 1 000 px / 1 Hz → 86.4).
  `_on_sample` redraws only when `now - last_redraw >= redraw_interval_s(...)`;
  changing the span, the plotted channels or *Clear history* redraws immediately.
  Test `test_long_span_skips_redundant_redraws`: at 24 h span, 10 Samples 1 s apart
  after one redraw → `curve.setData` (spy via monkeypatch) is not called again.
- [ ] **Gaps show as breaks.** Test `test_gap_is_not_bridged`: Samples 0–10 s,
  none for 30 s, then 40–50 s → the curve's y data contains a NaN between the
  two runs.
- [ ] **The operator is told.** A `QLabel` caption above the plot reads
  `Older than 1 h: min/max per 10 s` whenever the selected span is longer than
  `RAW_SPAN_S`, and is hidden otherwise (test both). Its tooltip explains why in
  one sentence.
- [ ] Full gate green.

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments
