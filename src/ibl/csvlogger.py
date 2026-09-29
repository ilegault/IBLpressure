"""
Daily CSV log.

Design.pdf: "Write all pressures to a csv file every 10 seconds.  Make a new
file for each day, filename = date."

So:  <csv_dir>/2026-08-18.csv  and a fresh file the moment the date rolls over.
Faulted channels are written as the text "Gauge Fault" rather than a number,
so a bad gauge never looks like a real pressure in the record.

Appending: restarting the app appends to the day's file. A file never mixes two
headers. If the columns change mid-day (e.g. "Also record raw volts" is ticked),
`choose_daily_path` picks the first of `YYYY-MM-DD.csv`, `YYYY-MM-DD_b.csv`,
`YYYY-MM-DD_c.csv`, ... whose header matches, or the first that does not exist yet.

Reload: `read_daily_csv` reads a file back as (epoch, pressures) with columns matched
by header name, and `load_recent_history` refills the plot's History from yesterday's
and today's files (all suffixes) when the app starts. A line that cannot be parsed
is skipped and counted, never raised and never silently lost.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import math
import os
from collections.abc import Iterator

import numpy as np

from .channels import CHANNELS
from .config import Settings
from .conversion import convert
from .model import GaugeStatus, Sample


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


def _read_header(path: str) -> list[str] | None:
    """The first line of `path` as columns, or None if the file is missing or empty."""
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return next(csv.reader(fh), None)
    except OSError:
        return None


def _candidate_paths(directory: str, day: _dt.date) -> Iterator[str]:
    yield os.path.join(directory, f"{day:%Y-%m-%d}.csv")
    for letter in "bcdefghijklmnopqrstuvwxyz":
        yield os.path.join(directory, f"{day:%Y-%m-%d}_{letter}.csv")


def choose_daily_path(directory: str, day: _dt.date, header: list[str]) -> str:
    """The file new rows with this `header` belong in: the first candidate that is
    missing or empty, or whose header already matches. Never a file with another header."""
    last = ""
    for path in _candidate_paths(directory, day):
        last = path
        existing = _read_header(path)
        if not existing or existing == header:
            return path
    raise OSError(f"too many differently-shaped CSV files for {day:%Y-%m-%d}: {last}")


_NAN_WORDS = {
    "",
    GaugeStatus.FAULT.value,
    GaugeStatus.NEGATIVE.value,
    GaugeStatus.UNDER.value,
    GaugeStatus.OVER.value,
    GaugeStatus.APPROX.value,
}


def _parse_pressure(cell: str) -> float:
    text = cell.strip()
    if text in _NAN_WORDS:
        return math.nan
    return float(text.lstrip("~"))


def _parse_daily(path: str) -> Iterator[tuple[float, list[float]] | None]:
    """One item per data line: (epoch_s, pressures in CHANNELS order), or None if the
    line is malformed."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        head = next(reader, None)
        if not head:
            return
        col = {name: i for i, name in enumerate(head)}
        if "epoch_s" not in col:
            return
        wanted = [col.get(f"{c.name} (Torr)") for c in CHANNELS]
        for cells in reader:
            try:
                if len(cells) != len(head):
                    raise ValueError("wrong number of cells")
                epoch = float(cells[col["epoch_s"]])
                if not math.isfinite(epoch):
                    raise ValueError("bad time")
                pressures = [math.nan if i is None else _parse_pressure(cells[i])
                             for i in wanted]
            except ValueError:
                yield None
                continue
            yield epoch, pressures


def read_daily_csv(path: str) -> Iterator[tuple[float, list[float]]]:
    """Yield (epoch_s, pressures in CHANNELS order) from one Daily CSV.

    Gauge Fault, Neg Voltage, Under range, Over range and empty cells come back as
    NaN; "~1.5E-03" comes back as 0.0015. Malformed lines are left out here;
    `load_recent_history` counts them.
    """
    for item in _parse_daily(path):
        if item is not None:
            yield item


def load_recent_history(directory: str, now: float, span_s: float, history) -> tuple[int, int]:
    """Refill `history` from every Daily CSV of `now`'s date and the day before.

    Rows with epoch_s >= now - span_s are appended in time order. Returns
    (rows loaded, malformed lines skipped).
    """
    today = _dt.datetime.fromtimestamp(now).date()  # noqa: DTZ006 - files use the PC's local calendar day
    rows: list[tuple[float, list[float]]] = []
    skipped = 0
    for day in (today - _dt.timedelta(days=1), today):
        for path in _candidate_paths(directory, day):
            if not os.path.exists(path):
                break
            try:
                items = list(_parse_daily(path))
            except OSError:
                skipped += 1
                continue
            for item in items:
                if item is None:
                    skipped += 1
                else:
                    rows.append(item)
    rows.sort(key=lambda r: r[0])
    loaded = 0
    for epoch, pressures in rows:
        if epoch >= now - span_s:
            history.append(epoch, np.array(pressures))
            loaded += 1
    return loaded, skipped


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
            path = choose_daily_path(self.directory, when.date(), self._header())
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
