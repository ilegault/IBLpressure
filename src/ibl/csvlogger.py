"""
Daily CSV log.

Design.pdf: "Write all pressures to a csv file every 10 seconds.  Make a new
file for each day, filename = date."

So:  <csv_dir>/2026-08-18.csv  and a fresh file the moment the date rolls over.
Faulted channels are written as the text "Gauge Fault" rather than a number,
so a bad gauge never looks like a real pressure in the record.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import math
import os

from .channels import CHANNELS
from .config import Settings
from .conversion import convert
from .model import Sample


def header(include_voltages: bool) -> list[str]:
    cols = ["timestamp", "epoch_s"]
    cols += [f"{c.name} (Torr)" for c in CHANNELS]
    if include_voltages:
        cols += [f"AIN{c.ain} (V)" for c in CHANNELS]
    return cols


def format_row(sample: Sample, include_voltages: bool) -> list[str]:
    """One CSV row, as text, for one Sample."""
    when = _dt.datetime.fromtimestamp(sample.timestamp)  # noqa: DTZ006 - file names use the PC's local calendar day
    by_ain = sample.by_ain()
    row = [when.isoformat(timespec="seconds"), f"{sample.timestamp:.3f}"]
    for ch in CHANNELS:
        r = by_ain.get(ch.ain)
        if r is None:
            row.append("")
        elif r.pressure is None:
            row.append(r.status.value)
        else:
            row.append(f"{r.pressure:.4E}")
    if include_voltages:
        for ch in CHANNELS:
            r = by_ain.get(ch.ain)
            row.append("" if r is None else f"{r.voltage:.5f}")
    return row


def _csv_bytes(row: list[str]) -> int:
    buf = io.StringIO()
    csv.writer(buf).writerow(row)
    return len(buf.getvalue().encode("utf-8"))


# Any present-day instant: the epoch column has the same width until the year 2286.
_TYPICAL_TIMESTAMP = 1_800_000_000.0


def estimate_bytes_per_day(interval_s: float, include_voltages: bool) -> int:
    """Header plus one day of rows, each measured on a typical all-OK Sample."""
    typical = Sample(_TYPICAL_TIMESTAMP, [
        convert(c.ain, 7.0 if c.is_ion else 0.435, c.is_ion, Settings().fault_volts)
        for c in CHANNELS
    ])
    row_bytes = _csv_bytes(format_row(typical, include_voltages))
    return _csv_bytes(header(include_voltages)) + math.ceil(86400 / interval_s) * row_bytes


def format_size_preview(nbytes: int, rows: int) -> str:
    if nbytes < 1024 * 1024:
        return f"≈ {nbytes / 1024:.1f} KB per day ({rows:,} rows)"
    return f"≈ {nbytes / (1024 * 1024):.1f} MB per day ({rows:,} rows)"


class DailyCsvLogger:
    def __init__(self, directory: str, include_voltages: bool = False):
        self.directory = directory
        self.include_voltages = include_voltages
        self._date: _dt.date | None = None
        self._fh = None
        self._writer: csv.writer | None = None
        self.last_error: str = ""
        self.current_path: str = ""

    # -- header --------------------------------------------------------------
    def _header(self) -> list[str]:
        return header(self.include_voltages)

    # -- file rotation -------------------------------------------------------
    def _ensure_file(self, when: _dt.datetime) -> bool:
        if self._fh is not None and self._date == when.date():
            return True
        self.close()
        try:
            os.makedirs(self.directory, exist_ok=True)
            path = os.path.join(self.directory, f"{when:%Y-%m-%d}.csv")
            is_new = not os.path.exists(path) or os.path.getsize(path) == 0
            self._fh = open(path, "a", newline="", encoding="utf-8")  # noqa: SIM115 - held open for the day, closed in close()
            self._writer = csv.writer(self._fh)
            if is_new:
                self._writer.writerow(self._header())
                self._fh.flush()
            self._date = when.date()
            self.current_path = path
            self.last_error = ""
            return True
        except OSError as exc:
            self.last_error = f"CSV: {exc}"
            self._fh = None
            self._writer = None
            return False

    # -- writing -------------------------------------------------------------
    def write(self, sample: Sample) -> bool:
        when = _dt.datetime.fromtimestamp(sample.timestamp)  # noqa: DTZ006 - file names use the PC's local calendar day
        if not self._ensure_file(when):
            return False

        row = format_row(sample, self.include_voltages)

        try:
            self._writer.writerow(row)   # type: ignore[union-attr]
            self._fh.flush()             # type: ignore[union-attr]
            os.fsync(self._fh.fileno())  # type: ignore[union-attr]
            self.last_error = ""
            return True
        except OSError as exc:
            self.last_error = f"CSV: {exc}"
            self.close()
            return False

    def reconfigure(self, directory: str, include_voltages: bool) -> None:
        if directory != self.directory or include_voltages != self.include_voltages:
            self.close()
            self.directory = directory
            self.include_voltages = include_voltages

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
        self._fh = None
        self._writer = None
        self._date = None
