"""The plot draws from History through minmax_decimate and redraws at a throttled pace.

The window's clock is faked (`window._now`) and slots are called directly with
hand-built Samples, so nothing waits on the real worker thread.
"""
import numpy as np
import pytest

from ibl import config
from ibl.channels import CHANNELS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.history import RAW_SPAN_S
from ibl.mainwindow import MainWindow
from ibl.model import Sample


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
    w = MainWindow(Settings(simulate=True, csv_enabled=False, sample_hz=1.0,
                            late_after_samples=3))
    qtbot.addWidget(w)
    w._now = clock
    return w


def _sample(t):
    readings = [
        convert(ch.ain, 7.0 if ch.is_ion else 0.435, ch.is_ion, 10.0) for ch in CHANNELS
    ]
    return Sample(t, readings)


def _feed(window, clock, t):
    clock.t = t
    window._on_sample(_sample(t))


def _select_span(window, label):
    idx = window.cmb_span.findText(label)
    assert idx >= 0, label
    window.cmb_span.setCurrentIndex(idx)


def _plot_all(window):
    window._set_plotted(lambda c: True)


def test_series_class_is_gone():
    import ibl.mainwindow as mw

    assert not hasattr(mw, "Series")


def test_24h_view_hands_bounded_points_to_curves(window, clock):
    _plot_all(window)
    n = len(CHANNELS)
    for t in range(24 * 3600):
        window.history.append(float(t), np.full(n, 1e-7))
    clock.t = 24 * 3600 - 1.0
    window.plot.setFixedWidth(1000)
    _select_span(window, "24 hours")
    window._redraw_plot()
    for ch in CHANNELS:
        curve = window.curves[ch.ain]
        assert curve.isVisible()
        _x, y = curve.getData()
        assert 0 < np.isfinite(y).sum() <= 2000


def test_gap_is_not_bridged(window, clock):
    _plot_all(window)
    for t in list(range(11)) + list(range(40, 51)):
        _feed(window, clock, float(t))
    window._redraw_plot()
    _x, y = window.curves[CHANNELS[0].ain].getData()
    finite = np.flatnonzero(np.isfinite(y))
    # the 30 s silence is a break in the line: a NaN sits between two finite points
    between = y[finite[0]:finite[-1] + 1]
    assert np.isnan(between).any()


def test_long_span_skips_redundant_redraws(window, clock, monkeypatch):
    _plot_all(window)
    _select_span(window, "24 hours")
    _feed(window, clock, 0.0)
    window._redraw_plot()
    calls = []
    for ch in CHANNELS:
        curve = window.curves[ch.ain]
        real = curve.setData
        monkeypatch.setattr(curve, "setData",
                            lambda *a, _real=real, **k: (calls.append(1), _real(*a, **k)))
    for t in range(1, 11):
        _feed(window, clock, float(t))
    assert calls == []


def test_span_change_redraws_immediately(window, clock, monkeypatch):
    _plot_all(window)
    _select_span(window, "24 hours")
    _feed(window, clock, 0.0)
    window._redraw_plot()
    calls = []
    curve = window.curves[CHANNELS[0].ain]
    real = curve.setData
    monkeypatch.setattr(curve, "setData",
                        lambda *a, **k: (calls.append(1), real(*a, **k)))
    _select_span(window, "5 minutes")
    assert calls


def test_clear_history_empties_history_and_curves(window, clock):
    _plot_all(window)
    for t in range(5):
        _feed(window, clock, float(t))
    window._redraw_plot()
    window._clear_history()
    t, _lo, _hi = window.history.window(0, -1e12, 1e12)
    assert len(t) == 0
    x, y = window.curves[CHANNELS[0].ain].getData()
    assert x is None or np.isfinite(y).sum() == 0


def test_caption_shown_only_for_long_spans(window, clock):
    _select_span(window, "5 minutes")
    assert window.lbl_plot_note.isHidden()
    _select_span(window, "24 hours")
    assert not window.lbl_plot_note.isHidden()
    assert window.lbl_plot_note.text() == "Older than 1 h: min/max per 10 s"
    assert window.lbl_plot_note.toolTip()
    assert RAW_SPAN_S == 3600
    _select_span(window, "5 minutes")
    assert window.lbl_plot_note.isHidden()


def test_window_reloads_history_from_csv_at_startup(qtbot, tmp_path, monkeypatch):
    import time as _time

    from ibl.csvlogger import DailyCsvLogger

    path = str(tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", path)
    monkeypatch.setattr(Settings.save, "__defaults__", (path,))
    monkeypatch.setattr(Settings.load.__func__, "__defaults__", (path,))
    now = _time.time()
    logs = tmp_path / "logs"
    logger = DailyCsvLogger(str(logs))
    for i in range(5):
        assert logger.write(_sample(now - 50 + i))
    logger.close()

    w = MainWindow(Settings(simulate=True, csv_enabled=True, csv_dir=str(logs),
                            sample_hz=1.0, history_s=3600))
    qtbot.addWidget(w)
    assert w.lbl_csv.text() == "History reloaded: 5 rows from CSV"
    t, _lo, _hi = w.history.window(0, now - 3600, now + 1)
    assert len(t) == 5
