"""The CSV file's text is a contract with anyone reading the logs."""
import csv
import datetime as _dt
import math

import numpy as np
import pytest

from ibl.channels import CHANNELS
from ibl.conversion import convert
from ibl.csvlogger import (
    DailyCsvLogger,
    choose_daily_path,
    header,
    load_recent_history,
    read_daily_csv,
)
from ibl.history import History
from ibl.model import Sample


def test_fault_written_as_words(tmp_path):
    readings = [convert(0, 10.9, True, 10.0)]          # SNICS IG faulted
    readings.append(convert(1, 1.1552, False, 10.0))   # SNICS CG good
    stamp = 1_767_323_045.0  # any fixed instant; the file name uses the PC's local day
    logger = DailyCsvLogger(str(tmp_path))
    assert logger.write(Sample(stamp, readings))
    logger.close()

    with open(logger.current_path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["SNICS IG (Torr)"] == "Gauge Fault"
    assert rows[0]["SNICS CG (Torr)"] == f"{readings[1].pressure:.4E}"


def _ok_sample(t=1_767_323_045.0):
    from ibl.channels import CHANNELS
    return Sample(t, [convert(c.ain, 7.0 if c.is_ion else 0.435, c.is_ion, 10.0)
                      for c in CHANNELS])


def test_estimate_grows_when_volts_are_recorded():
    from ibl.csvlogger import estimate_bytes_per_day
    assert estimate_bytes_per_day(10, True) > estimate_bytes_per_day(10, False)


def test_estimate_matches_the_file_actually_written(tmp_path):
    import os

    from ibl.csvlogger import estimate_bytes_per_day
    for volts in (False, True):
        folder = tmp_path / str(volts)
        logger = DailyCsvLogger(str(folder), include_voltages=volts)
        for i in range(100):
            assert logger.write(_ok_sample(1_767_323_045.0 + i))
        logger.close()
        actual = os.path.getsize(logger.current_path)
        # One row a second for 100 s: the per-day formula, scaled to 100 rows.
        per_row_and_header = estimate_bytes_per_day(86400 / 100, volts)
        assert abs(actual - per_row_and_header) <= 0.02 * actual


def test_size_preview_text():
    from ibl.csvlogger import format_size_preview
    assert format_size_preview(2048, 8640) == "≈ 2.0 KB per day (8,640 rows)"
    assert format_size_preview(3 * 1024 * 1024, 86400) == "≈ 3.0 MB per day (86,400 rows)"


# -- append safety and reload (ticket 10) --------------------------------------
_NOON = _dt.datetime(2026, 9, 28, 12, 0, 0).timestamp()  # noqa: DTZ001 - the PC's local calendar day


def _data_rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.reader(fh))[1:]


def test_restart_appends_to_todays_file(tmp_path):
    first = DailyCsvLogger(str(tmp_path))
    for i in range(3):
        assert first.write(_ok_sample(_NOON + i))
    first.close()
    second = DailyCsvLogger(str(tmp_path))
    for i in range(2):
        assert second.write(_ok_sample(_NOON + 10 + i))
    second.close()

    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["2026-09-28.csv"]
    with open(tmp_path / files[0], newline="", encoding="utf-8") as fh:
        lines = list(csv.reader(fh))
    assert lines[0] == header(False)
    assert sum(1 for r in lines if r[0] == "timestamp") == 1
    assert len(lines) - 1 == 5


def test_header_change_starts_suffixed_file(tmp_path):
    logger = DailyCsvLogger(str(tmp_path))
    logger.write(_ok_sample(_NOON))
    logger.write(_ok_sample(_NOON + 1))
    logger.reconfigure(str(tmp_path), True)
    logger.write(_ok_sample(_NOON + 2))
    logger.reconfigure(str(tmp_path), False)
    logger.write(_ok_sample(_NOON + 3))
    logger.close()

    a = tmp_path / "2026-09-28.csv"
    b = tmp_path / "2026-09-28_b.csv"
    with open(a, newline="", encoding="utf-8") as fh:
        rows_a = list(csv.reader(fh))
    with open(b, newline="", encoding="utf-8") as fh:
        rows_b = list(csv.reader(fh))
    assert rows_a[0] == header(False)
    assert len(rows_a) - 1 == 3            # two, then the third change back appends here
    assert rows_b[0] == header(True)
    assert len(rows_b) - 1 == 1
    assert not (tmp_path / "2026-09-28_c.csv").exists()


def test_choose_daily_path_first_candidate_with_matching_header(tmp_path):
    day = _dt.date(2026, 9, 28)
    plain, volts = header(False), header(True)
    assert choose_daily_path(str(tmp_path), day, plain) == str(tmp_path / "2026-09-28.csv")

    (tmp_path / "2026-09-28.csv").write_text(",".join(plain) + "\n", encoding="utf-8")
    assert choose_daily_path(str(tmp_path), day, plain) == str(tmp_path / "2026-09-28.csv")
    assert choose_daily_path(str(tmp_path), day, volts) == str(tmp_path / "2026-09-28_b.csv")

    (tmp_path / "2026-09-28_b.csv").write_text(",".join(volts) + "\n", encoding="utf-8")
    assert choose_daily_path(str(tmp_path), day, volts) == str(tmp_path / "2026-09-28_b.csv")
    other = plain[:-1] + ["something else"]
    assert choose_daily_path(str(tmp_path), day, other) == str(tmp_path / "2026-09-28_c.csv")


def test_reader_round_trips_a_sample_and_maps_faults_to_nan(tmp_path):
    readings = [convert(c.ain, 7.0 if c.is_ion else 0.435, c.is_ion, 10.0) for c in CHANNELS]
    readings[0] = convert(0, 10.9, True, 10.0)   # SNICS IG faulted
    sample = Sample(_NOON, readings)
    for volts in (False, True):
        folder = tmp_path / str(volts)
        logger = DailyCsvLogger(str(folder), include_voltages=volts)
        assert logger.write(sample)
        logger.close()
        rows = list(read_daily_csv(logger.current_path))
        assert len(rows) == 1
        epoch, pressures = rows[0]
        assert epoch == pytest.approx(_NOON, abs=0.001)
        assert len(pressures) == len(CHANNELS)
        assert math.isnan(pressures[0])
        assert pressures[1] == pytest.approx(readings[1].pressure, rel=1e-3)


def test_reader_maps_words_empty_cells_and_tilde(tmp_path):
    cols = header(False)
    cells = ["2026-09-28T12:00:00", f"{_NOON:.3f}"] + [""] * len(CHANNELS)
    cells[2 + 0] = "Neg Voltage"
    cells[2 + 1] = "Over range"
    cells[2 + 2] = "Under range"
    cells[2 + 3] = "~1.5E-03"
    cells[2 + 4] = "2.0000E-07"
    path = tmp_path / "x.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        w.writerow(cells)
    (_, p), = read_daily_csv(str(path))
    nan_columns = [0, 1, 2] + list(range(5, len(CHANNELS)))
    assert all(math.isnan(p[i]) for i in nan_columns)
    assert p[3] == pytest.approx(1.5e-3)
    assert p[4] == pytest.approx(2.0e-7)


def test_load_recent_history_keeps_only_rows_in_span_and_counts_bad_lines(tmp_path):
    now = _NOON
    day = 86400.0
    logger = DailyCsvLogger(str(tmp_path))
    # yesterday: one row inside the span (now - 1000 s is today, so use 25 h ago span)
    old_out = now - day - 7200          # yesterday, outside a 24 h span
    old_in = now - day + 3600           # yesterday, inside a 24 h span
    for t in (old_out, old_in, now - 60, now - 30):
        assert logger.write(_ok_sample(t))
    logger.close()
    # a second file for today with another header, plus a malformed line
    logger.reconfigure(str(tmp_path), True)
    assert logger.write(_ok_sample(now - 10))
    logger.close()
    with open(tmp_path / "2026-09-28.csv", "a", encoding="utf-8") as fh:
        fh.write("this,is,not,a,row\n")
    # two days back is never read
    stale = tmp_path / "2026-09-26.csv"
    stale.write_text(",".join(header(False)) + "\n", encoding="utf-8")

    hist = History(len(CHANNELS))
    loaded, skipped = load_recent_history(str(tmp_path), now, day, hist)
    assert loaded == 4
    assert skipped == 1
    t, lo, _hi = hist.window(1, 0.0, now + 1)
    assert len(t) == 4
    assert list(t) == sorted(t)
    assert t[0] == pytest.approx(old_in, abs=0.001)
    assert np.isfinite(lo).all()
