"""History (two tiers) and minmax_decimate: pure numpy cores, explicit timestamps."""
from __future__ import annotations

import time

import numpy as np

from ibl.history import RAW_SPAN_S, SUMMARY_BUCKET_S, History, minmax_decimate


def fill(h: History, seconds: int, n_channels: int = 1, value=1e-7, spikes=None):
    """Append one sample per second, t = 0..seconds-1. spikes: {t: value} on channel 0."""
    spikes = spikes or {}
    for t in range(seconds):
        row = np.full(n_channels, value)
        if t in spikes:
            row[0] = spikes[t]
        h.append(float(t), row)


def test_api_constants():
    assert RAW_SPAN_S == 3600
    assert SUMMARY_BUCKET_S == 10


def test_recent_hour_is_full_resolution():
    h = History(1)
    fill(h, 3600)
    t, lo, hi = h.window(0, 0.0, 3600.0)
    assert len(t) == 3600
    assert np.array_equal(lo, hi)
    assert np.all(np.diff(t) > 0)


def test_older_data_is_summarised_with_minmax():
    h = History(1)
    fill(h, 7200, spikes={1800: 5e-5})
    t, lo, hi = h.window(0, 0.0, 3600.0)
    assert len(t) == 360
    assert np.all(np.diff(t) > 0)
    spiked = hi == 5e-5
    assert spiked.sum() == 1
    assert lo[spiked][0] == 1e-7


def test_all_nan_bucket_stays_nan():
    h = History(1)
    for t in range(7200):
        h.append(float(t), np.array([np.nan if 100 <= t < 110 else 1e-7]))
    t, lo, hi = h.window(0, 0.0, 3600.0)
    bucket = np.flatnonzero(t == 100.0)
    assert len(bucket) == 1
    assert np.isnan(lo[bucket[0]]) and np.isnan(hi[bucket[0]])
    assert np.isfinite(lo[t != 100.0]).all()


def test_partial_nan_bucket_uses_finite_values():
    h = History(1)
    for t in range(7200):
        v = np.nan if t == 205 else (3e-7 if t == 207 else 1e-7)
        h.append(float(t), np.array([v]))
    t, lo, hi = h.window(0, 0.0, 3600.0)
    i = np.flatnonzero(t == 200.0)[0]
    assert lo[i] == 1e-7 and hi[i] == 3e-7


def test_channels_are_independent():
    h = History(2)
    for t in range(7200):
        h.append(float(t), np.array([1e-7, 9e-7 if t == 50 else 2e-7]))
    _, _lo0, hi0 = h.window(0, 0.0, 3600.0)
    _, lo1, hi1 = h.window(1, 0.0, 3600.0)
    assert hi0.max() == 1e-7
    assert hi1.max() == 9e-7 and lo1.min() == 2e-7


def test_window_is_time_ordered_across_tiers():
    h = History(1)
    fill(h, 5000)
    t, _, _ = h.window(0, 0.0, 5000.0)
    assert np.all(np.diff(t) > 0)


def test_clear_empties_history():
    h = History(2)
    fill(h, 100, n_channels=2)
    h.clear()
    t, lo, hi = h.window(0, 0.0, 1e9)
    assert len(t) == len(lo) == len(hi) == 0


def test_drops_data_older_than_max_span():
    h = History(1)
    fill(h, 25 * 3600)
    t_last = 25 * 3600 - 1
    t, _, _ = h.window(0, -1e9, 1e9)
    assert len(t) > 0
    assert t.min() >= t_last - 24 * 3600


def test_memory_is_bounded_at_max_rate():
    # Sized for 10 Hz: the raw tier holds one hour of samples at that rate.
    assert History(14).memory_bytes() < 25 * 1024 * 1024


def test_raw_tier_cannot_overflow_above_max_rate():
    # Faster than max_rate_hz must fold the oldest samples, never grow or crash.
    h = History(1, raw_span_s=10, max_rate_hz=1.0)
    for i in range(1000):
        h.append(i * 0.1, np.array([1e-7]))
    t, _, _ = h.window(0, 0.0, 1e9)
    assert len(t) > 0
    assert np.all(np.diff(t) >= 0)


def test_decimate_caps_points():
    t = np.arange(86400, dtype=float)
    p = np.abs(np.sin(t / 500.0)) * 1e-6 + 1e-9
    t_out, p_out = minmax_decimate(t, p, p, 0.0, 86400.0, 1000, gap_s=1e9)
    assert len(t_out) == len(p_out)
    assert len(t_out) <= 2000 + int(np.isnan(p_out).sum())


def test_decimate_keeps_spike():
    t = np.arange(86400, dtype=float)
    p = np.full(86400, 1e-7)
    p[40000] = 5e-5
    _, p_out = minmax_decimate(t, p, p, 0.0, 86400.0, 1000, gap_s=1e9)
    assert np.nanmax(p_out) == 5e-5


def test_decimate_emits_min_and_max_in_time_order():
    t = np.arange(10, dtype=float)
    p = np.array([3.0, 5.0, 1.0, 4.0, 2.0, 9.0, 8.0, 7.0, 6.0, 5.0])
    t_out, p_out = minmax_decimate(t, p, p, 0.0, 10.0, 1, gap_s=1e9)
    assert list(p_out) == [1.0, 9.0]
    assert list(t_out) == [2.0, 5.0]


def test_decimate_uses_lo_and_hi_of_summary_points():
    t = np.array([1.0, 2.0])
    lo = np.array([1e-8, 5e-8])
    hi = np.array([3e-8, 9e-8])
    _, p_out = minmax_decimate(t, lo, hi, 0.0, 4.0, 1, gap_s=1e9)
    assert np.nanmin(p_out) == 1e-8 and np.nanmax(p_out) == 9e-8


def test_decimate_empty_bucket_is_a_break():
    # Two data points 9 s apart.  effective_gap = max(gap_s=2, width=1+1) = 2 s.
    # 9 s > 2 s → exactly one NaN break is inserted between them.
    # (The old behaviour — one NaN per empty bucket — was removed because it
    # caused every dense trace to render as isolated dots.)
    t = np.array([0.5, 9.5])
    p = np.array([1.0, 2.0])
    _t_out, p_out = minmax_decimate(t, p, p, 0.0, 10.0, 10, gap_s=2.0)
    assert len(p_out) == 3
    assert p_out[0] == 1.0
    assert np.isnan(p_out[1])
    assert p_out[2] == 2.0


def test_decimate_ignores_nan_points_and_empty_input():
    # All-NaN data: every point is filtered out by the finite check → empty output.
    t = np.arange(5, dtype=float)
    p = np.full(5, np.nan)
    t_out, _p_out = minmax_decimate(t, p, p, 0.0, 5.0, 2, gap_s=1e9)
    assert len(t_out) == 0
    # Completely empty input → also empty output (no per-bucket NaN any more).
    t_out, _p_out = minmax_decimate(np.array([]), np.array([]), np.array([]), 0.0, 5.0, 2, 1e9)
    assert len(t_out) == 0


def test_gap_becomes_a_break():
    t = np.concatenate([np.arange(0, 101), np.arange(200, 301)]).astype(float)
    p = np.full(len(t), 1e-7)
    t_out, p_out = minmax_decimate(t, p, p, 0.0, 300.0, 300, gap_s=3.0)
    between = (t_out > 100.0) & (t_out < 200.0)
    assert np.isnan(p_out[between]).any()
    # and the break sits between the finite points on either side
    i = np.flatnonzero(t_out == 100.0)[-1]
    assert np.isnan(p_out[i + 1])


def test_gap_break_inserted_between_finite_neighbours():
    t = np.array([0.0, 1.0, 20.0, 21.0])
    p = np.full(4, 1e-7)
    t_out, p_out = minmax_decimate(t, p, p, 0.0, 22.0, 22, gap_s=3.0)
    i = np.flatnonzero(t_out == 1.0)[0]
    assert np.isnan(p_out[i + 1])


def test_24h_window_decimates_fast():
    h = History(7)
    for t in range(24 * 3600):
        h.append(float(t), np.full(7, 1e-7))
    t_last = 24 * 3600 - 1
    start = time.perf_counter()
    for ch in range(7):
        t, lo, hi = h.window(ch, 0.0, float(t_last))
        minmax_decimate(t, lo, hi, 0.0, float(t_last), 1000, gap_s=120.0)
    elapsed = time.perf_counter() - start
    # The plot redraws on the GUI thread; anything near a second is the freeze
    # this effort fixes, so 0.25 s for all seven curves is the budget.
    assert elapsed < 0.25


def test_redraw_interval():
    from ibl.history import redraw_interval_s

    assert redraw_interval_s(300, 1000, 1.0) == 1.0
    assert redraw_interval_s(86_400, 1000, 1.0) == 86.4
    # a fast sample rate never asks for redraws faster than the samples arrive
    assert redraw_interval_s(60, 1000, 2.0) == 0.5
