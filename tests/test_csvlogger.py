"""The CSV file's text is a contract with anyone reading the logs."""
import csv

from ibl.conversion import convert
from ibl.csvlogger import DailyCsvLogger
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
