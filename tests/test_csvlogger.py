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
