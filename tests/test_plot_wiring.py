"""Plot-wiring integration tests.

These tests exercise the REAL sample path: data enters through _on_sample (the
same slot the DaqWorker signal feeds), accumulates in window.history, and is
drawn onto the plot by _redraw_plot / redraw_due.  They do NOT call
window.history.append() directly.

Assertions are on the curve objects that the operator sees: finite data present,
x values inside the current axis x-range, y values consistent with the data fed,
no unexpected NaN gaps between consecutively-fed samples, correct response to
Clear, and correct response to unchecking a gauge.

Two structural tests confirm wiring invariants:
  - History instance identity: the object _on_sample writes is the same object
    _redraw_plot hands to plot_panel.redraw.
  - Single clock: _redraw_plot passes self._now() to redraw; the same clock
    drives redraw_due so throttle and data window never diverge.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from ibl import config
from ibl.channels import CHANNELS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.mainwindow import MainWindow
from ibl.model import Sample
from ibl.theme import TIME_SPANS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def window(qtbot, tmp_path, monkeypatch, clock):
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))
    w = MainWindow(Settings(
        simulate=True, csv_enabled=False,
        sample_hz=1.0, late_after_samples=3,
    ))
    qtbot.addWidget(w)
    w._now = clock
    # Fix a pixel width so redraw_interval_s is predictable (not 0-px fallback).
    w.plot_panel.plot.setFixedWidth(1000)
    return w


def _sample(t: float) -> Sample:
    return Sample(t, [
        convert(ch.ain, 7.0 if ch.is_ion else 0.435, ch.is_ion, 10.0)
        for ch in CHANNELS
    ])


def _feed(window, clock, t: float) -> None:
    """Advance the fake clock and push one sample through the real _on_sample slot."""
    clock.t = t
    window._on_sample(_sample(t))


def _plot_all(window) -> None:
    window.table_panel.set_plotted(lambda c: True)


def _select_span(window, label: str) -> None:
    idx = window.plot_panel.cmb_span.findText(label)
    assert idx >= 0, f"span label not found: {label!r}"
    window.plot_panel.cmb_span.setCurrentIndex(idx)


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_history_instance_is_shared_between_sample_path_and_redraw(
        window, clock, monkeypatch):
    """The History that _on_sample writes to must be the SAME object that
    _redraw_plot hands to plot_panel.redraw.  A copy would cause the plot to
    read stale or empty data regardless of how many samples have arrived."""
    seen_ids: list[int] = []
    real_redraw = window.plot_panel.redraw

    def spy(history, *a, **kw):
        seen_ids.append(id(history))
        return real_redraw(history, *a, **kw)

    monkeypatch.setattr(window.plot_panel, "redraw", spy)

    _feed(window, clock, 1.0)
    window._redraw_plot()

    assert seen_ids, "redraw was never called"
    assert all(hid == id(window.history) for hid in seen_ids), (
        f"plot_panel.redraw received a different History instance "
        f"(window.history id={id(window.history)}, got {set(seen_ids)})"
    )


def test_redraw_throttle_uses_window_clock(window, clock, monkeypatch):
    """_redraw_plot must pass self._now() as `now` to plot_panel.redraw.
    If it used a different clock the throttle (_last_redraw) and the data
    window (since = now - span) would be based on different times and the
    plot would show data from the wrong window."""
    seen_nows: list[float] = []
    real_redraw = window.plot_panel.redraw

    def spy(history, now, *a, **kw):
        seen_nows.append(now)
        return real_redraw(history, now, *a, **kw)

    monkeypatch.setattr(window.plot_panel, "redraw", spy)

    clock.t = 42.0
    window._redraw_plot()
    clock.t = 99.0
    window._redraw_plot()

    assert seen_nows == [42.0, 99.0], (
        f"redraw received wrong 'now' values: {seen_nows}"
    )


# ---------------------------------------------------------------------------
# Curves contain data after feeding through _on_sample
# ---------------------------------------------------------------------------

# The IG at 7 V produces 1e-3 Torr; the CG at 0.435 V produces ~5e-3 Torr
# (status APPROX, but pressure > 0 so it is stored).  Use 1e-3 as the
# reference; the 3-order-of-magnitude band covers both gauges.
_IG_PRESSURE = 1e-3


def _assert_curves_have_data(window, clock, *, span_label: str,
                              n_samples: int, expected_pressure: float):
    _plot_all(window)
    _select_span(window, span_label)
    span_s = next(s for lbl, s in TIME_SPANS if lbl == span_label)

    for i in range(n_samples):
        _feed(window, clock, float(i))
    window._redraw_plot()

    now = clock.t
    since = now - span_s
    axis_xrange = window.plot_panel.plot.viewRange()[0]

    for ch in CHANNELS:
        curve = window.plot_panel.curves[ch.ain]
        assert curve.isVisible(), (
            f"Curve {ch.name} (AIN {ch.ain}) is not visible after {n_samples} "
            f"samples at span={span_label}"
        )

        x, y = curve.getData()
        assert x is not None, (
            f"curve.getData() returned None for {ch.name} (span={span_label})"
        )

        finite = np.isfinite(y)
        assert finite.sum() > 0, (
            f"{ch.name} (AIN {ch.ain}): no finite data after {n_samples} samples "
            f"at span={span_label}"
        )

        fx = x[finite]
        # Finite x must lie within [since, now]
        assert fx.min() >= since - 1e-6, (
            f"{ch.name}: finite x min {fx.min():.3f} < since={since:.3f}"
        )
        assert fx.max() <= now + 1e-6, (
            f"{ch.name}: finite x max {fx.max():.3f} > now={now:.3f}"
        )

        # Finite x must lie within the axis x-range that was set by redraw
        assert fx.min() >= axis_xrange[0] - 1e-6, (
            f"{ch.name}: finite data starts before the axis left edge "
            f"({fx.min():.3f} < {axis_xrange[0]:.3f})"
        )
        assert fx.max() <= axis_xrange[1] + 1e-6, (
            f"{ch.name}: finite data ends after the axis right edge "
            f"({fx.max():.3f} > {axis_xrange[1]:.3f})"
        )

        # pyqtgraph log-Y mode stores log10(pressure) in getData(), so y values
        # are negative exponents (e.g. log10(1e-3) = -3).  Check the ballpark
        # in log10 space: within ±3 decades of the expected log10 value.
        fy = y[finite]
        log_expected = math.log10(expected_pressure)
        assert fy.min() >= log_expected - 3, (
            f"{ch.name}: min log10-y {fy.min():.2f} far below expected "
            f"log10({expected_pressure:.1E}) = {log_expected:.1f}"
        )
        assert fy.max() <= log_expected + 3, (
            f"{ch.name}: max log10-y {fy.max():.2f} far above expected "
            f"log10({expected_pressure:.1E}) = {log_expected:.1f}"
        )


def test_curves_have_data_1min(window, clock):
    _assert_curves_have_data(window, clock,
                             span_label="1 minute", n_samples=60,
                             expected_pressure=_IG_PRESSURE)


def test_curves_have_data_5min(window, clock):
    _assert_curves_have_data(window, clock,
                             span_label="5 minutes", n_samples=300,
                             expected_pressure=_IG_PRESSURE)


def test_curves_have_data_1h(window, clock):
    _assert_curves_have_data(window, clock,
                             span_label="1 hour", n_samples=3600,
                             expected_pressure=_IG_PRESSURE)


def test_curves_have_data_24h(window, clock):
    # Feed 1 h of dense samples inside a 24 h window; data appears in the
    # rightmost 1/24 of the axis but must still be findable.
    _assert_curves_have_data(window, clock,
                             span_label="24 hours", n_samples=3600,
                             expected_pressure=_IG_PRESSURE)


# ---------------------------------------------------------------------------
# Curve continuity: no unexpected NaN gaps in densely-fed data
# ---------------------------------------------------------------------------

def _assert_no_unexpected_gaps(window, clock, span_label: str, n_samples: int):
    """With samples every 1 s and gap_s = 3 s, consecutive finite x values
    must never be more than (gap_s + 2*bucket_width) apart.  A wider gap
    means minmax_decimate inserted an unwarranted NaN break."""
    _plot_all(window)
    _select_span(window, span_label)
    span_s = next(s for lbl, s in TIME_SPANS if lbl == span_label)
    gap_s = window.link.late_threshold_s   # 3.0 s at fixture settings

    for i in range(n_samples):
        _feed(window, clock, float(i))
    window._redraw_plot()

    n_buckets = max(100, window.plot_panel.plot.width())   # 1000 at fixture
    bucket_width = span_s / n_buckets
    max_allowed_gap = gap_s + 2.0 * bucket_width

    for ch in CHANNELS:
        x, y = window.plot_panel.curves[ch.ain].getData()
        if x is None:
            continue
        fx = x[np.isfinite(y)]
        if len(fx) < 2:
            continue
        diffs = np.diff(fx)
        big = diffs[diffs > max_allowed_gap]
        assert len(big) == 0, (
            f"{ch.name} (span={span_label}): {len(big)} unexpected gap(s) "
            f"between consecutive finite x values: {big}"
        )


def test_curves_continuous_1min(window, clock):
    _assert_no_unexpected_gaps(window, clock, "1 minute", 60)


def test_curves_continuous_5min(window, clock):
    _assert_no_unexpected_gaps(window, clock, "5 minutes", 300)


def test_curves_continuous_1h(window, clock):
    _assert_no_unexpected_gaps(window, clock, "1 hour", 3600)


def test_curves_continuous_24h(window, clock):
    _assert_no_unexpected_gaps(window, clock, "24 hours", 3600)


# ---------------------------------------------------------------------------
# No NaN breaks inside a continuous dense stream
# ---------------------------------------------------------------------------

def _assert_no_nan_between_finite(window, clock, span_label: str, n_samples: int):
    """With dense 1 Hz samples the curve output must be one unbroken run of
    finite values: no NaN point should appear between the first and last finite
    point.  Stray NaN breaks cause the line to render as isolated dashes even
    though the data is continuous."""
    _plot_all(window)
    _select_span(window, span_label)
    for i in range(n_samples):
        _feed(window, clock, float(i))
    window._redraw_plot()

    for ch in CHANNELS:
        x, y = window.plot_panel.curves[ch.ain].getData()
        if x is None:
            continue
        finite_mask = np.isfinite(y)
        if not finite_mask.any():
            continue
        first = int(np.argmax(finite_mask))
        last = int(len(finite_mask) - np.argmax(finite_mask[::-1]) - 1)
        between = y[first : last + 1]
        nan_between = int(np.isnan(between).sum())
        assert nan_between == 0, (
            f"{ch.name} (span={span_label}): {nan_between} NaN value(s) found "
            f"between the first and last finite point — dense data should be "
            f"one continuous line, not broken dashes"
        )


def test_no_nan_breaks_1min(window, clock):
    _assert_no_nan_between_finite(window, clock, "1 minute", 60)


def test_no_nan_breaks_5min(window, clock):
    _assert_no_nan_between_finite(window, clock, "5 minutes", 300)


def test_no_nan_breaks_1h(window, clock):
    _assert_no_nan_between_finite(window, clock, "1 hour", 3600)


def test_no_nan_breaks_24h(window, clock):
    # 3600 dense samples inside a 24 h window: the occupied portion is continuous
    _assert_no_nan_between_finite(window, clock, "24 hours", 3600)


# ---------------------------------------------------------------------------
# Throttle must not block redraws when the plot widget has no pixel width
# ---------------------------------------------------------------------------

def test_redraw_due_fires_within_span_when_plot_has_zero_width(
        qtbot, tmp_path, monkeypatch, clock):
    """redraw_due must allow a redraw within one span_s even when plot.width()
    returns 0 (before the window has been painted).  The broken behaviour is
    that max(1.0, span/max(1.0, 0)) == span, so a 5-minute span blocks redraws
    for 300 seconds after the first one fires."""
    import time as _time
    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))

    w = MainWindow(Settings(
        simulate=True, csv_enabled=False,
        sample_hz=1.0, late_after_samples=3,
    ))
    qtbot.addWidget(w)
    w._now = clock
    # Deliberately do NOT call setFixedWidth — leave plot.width() == 0

    _plot_all(w)
    _select_span(w, "5 minutes")

    # Prime the throttle: a forced redraw at t=0 (simulates the widget-change
    # redraw that fires when the user changes any setting).
    clock.t = 0.0
    w._redraw_plot()

    # Feed one sample per second for 10 seconds.  The throttle must allow at
    # least one more redraw within that window; if plot.width()==0 inflates the
    # interval to 300 s none of these samples would trigger one.
    redraws = []
    real_redraw = w.plot_panel.redraw
    monkeypatch.setattr(w.plot_panel, "redraw",
                        lambda h, n, *a, **k: (redraws.append(n), real_redraw(h, n, *a, **k)))

    for i in range(1, 11):
        _feed(w, clock, float(i))

    assert redraws, (
        "No automatic redraw triggered in 10 s on a 5-min span with plot.width()==0; "
        "the throttle is treating zero-width as a 300-second interval"
    )


# ---------------------------------------------------------------------------
# Clear and refill via the real sample path
# ---------------------------------------------------------------------------

def test_clear_empties_curves_and_new_samples_refill_them(window, clock):
    """_clear_history must zero the curves immediately.  Samples arriving
    after the clear must refill them on the next redraw."""
    _plot_all(window)
    ain0 = CHANNELS[0].ain

    for i in range(30):
        _feed(window, clock, float(i))
    window._redraw_plot()

    x0, y0 = window.plot_panel.curves[ain0].getData()
    assert x0 is not None and np.isfinite(y0).sum() > 0, \
        "Test precondition: no data before Clear"

    # Clear through the real path (same as clicking the button)
    window._clear_history()

    x1, y1 = window.plot_panel.curves[ain0].getData()
    assert x1 is None or np.isfinite(y1).sum() == 0, \
        "Curve still has finite data immediately after _clear_history()"

    t_hist, _, _ = window.history.window(0, -1e12, 1e12)
    assert len(t_hist) == 0, "window.history not empty after _clear_history()"

    # Feed new samples after the clear
    for i in range(30, 60):
        _feed(window, clock, float(i))
    window._redraw_plot()

    x2, y2 = window.plot_panel.curves[ain0].getData()
    assert x2 is not None and np.isfinite(y2).sum() > 0, \
        "Curve still empty after feeding new samples following Clear"


# ---------------------------------------------------------------------------
# Checkbox wiring: uncheck hides curve, re-check restores it
# ---------------------------------------------------------------------------

def test_unchecking_gauge_hides_curve(window, clock):
    """Unchecking a gauge's plot checkbox must make its curve invisible and
    trigger a redraw that skips that channel — same as the operator sees."""
    from PySide6.QtCore import Qt
    from ibl.ui.table_panel import COL_IG_PLOT

    _plot_all(window)
    for i in range(30):
        _feed(window, clock, float(i))
    window._redraw_plot()

    ain0 = CHANNELS[0].ain
    x0, y0 = window.plot_panel.curves[ain0].getData()
    assert x0 is not None and np.isfinite(y0).sum() > 0, \
        "Test precondition: channel 0 must have data before uncheck"

    window.table_panel.table.item(0, COL_IG_PLOT).setCheckState(Qt.Unchecked)

    assert not window.plot_panel.curves[ain0].isVisible(), \
        "Curve for channel 0 is still visible after unchecking its checkbox"


def test_rechecking_gauge_shows_data_from_history(window, clock):
    """Re-checking a gauge must make its curve visible and show the history
    data that accumulated while the checkbox was unticked."""
    from PySide6.QtCore import Qt
    from ibl.ui.table_panel import COL_IG_PLOT

    _plot_all(window)
    for i in range(30):
        _feed(window, clock, float(i))

    ain0 = CHANNELS[0].ain
    window.table_panel.table.item(0, COL_IG_PLOT).setCheckState(Qt.Unchecked)
    window.table_panel.table.item(0, COL_IG_PLOT).setCheckState(Qt.Checked)
    window._redraw_plot()

    curve = window.plot_panel.curves[ain0]
    assert curve.isVisible(), "Curve invisible after re-checking"
    x, y = curve.getData()
    assert x is not None and np.isfinite(y).sum() > 0, \
        "No data after re-checking (history should still hold the samples)"


# ---------------------------------------------------------------------------
# Axis x-range tracks [now - span_s, now] after any redraw
# ---------------------------------------------------------------------------

def test_xrange_equals_span_window_after_redraw(window, clock):
    """After feeding data and calling _redraw_plot, the plot's x-axis must be
    [now - span_s, now].  If pyqtgraph auto-range is left active the displayed
    window would not match the chosen time span."""
    _plot_all(window)
    _select_span(window, "5 minutes")

    for i in range(60):
        _feed(window, clock, float(i))
    window._redraw_plot()

    now = clock.t        # 59.0
    span_s = 300
    since = now - span_s  # -241.0

    xrange = window.plot_panel.plot.viewRange()[0]
    assert math.isclose(xrange[0], since, abs_tol=1e-3), (
        f"x-axis left edge {xrange[0]:.3f} != since={since:.3f}"
    )
    assert math.isclose(xrange[1], now, abs_tol=1e-3), (
        f"x-axis right edge {xrange[1]:.3f} != now={now:.3f}"
    )
