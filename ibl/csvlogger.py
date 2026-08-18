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
import os

from .channels import CHANNELS
from .daq import Sample


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
        cols = ["timestamp", "epoch_s"]
        cols += [f"{c.name} (Torr)" for c in CHANNELS]
        if self.include_voltages:
            cols += [f"AIN{c.ain} (V)" for c in CHANNELS]
        return cols

    # -- file rotation -------------------------------------------------------
    def _ensure_file(self, when: _dt.datetime) -> bool:
        if self._fh is not None and self._date == when.date():
            return True
        self.close()
        try:
            os.makedirs(self.directory, exist_ok=True)
            path = os.path.join(self.directory, f"{when:%Y-%m-%d}.csv")
            is_new = not os.path.exists(path) or os.path.getsize(path) == 0
            self._fh = open(path, "a", newline="", encoding="utf-8")
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
        when = _dt.datetime.fromtimestamp(sample.timestamp)
        if not self._ensure_file(when):
            return False

        by_ain = sample.by_ain()
        row: list[object] = [when.isoformat(timespec="seconds"), f"{sample.timestamp:.3f}"]
        for ch in CHANNELS:
            r = by_ain.get(ch.ain)
            if r is None:
                row.append("")
            elif r.pressure is None:
                row.append(r.status)
            else:
                row.append(f"{r.pressure:.4E}")
        if self.include_voltages:
            for ch in CHANNELS:
                r = by_ain.get(ch.ain)
                row.append("" if r is None else f"{r.voltage:.5f}")

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
