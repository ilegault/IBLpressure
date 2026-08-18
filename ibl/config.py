"""
Settings: defaults straight from Design.pdf, all editable in the GUI and
remembered between runs in settings.json next to the executable.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict, field, fields


def app_dir() -> str:
    """
    Folder the program 'lives in'.

    Frozen by PyInstaller  -> the folder holding IBLpressure.exe
    Running from source    -> the project folder
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


SETTINGS_PATH = os.path.join(app_dir(), "settings.json")


@dataclass
class Settings:
    # --- LabJack connection -------------------------------------------------
    connection: str = "USB"          # USB | ETHERNET | ANY
    identifier: str = "ANY"          # serial number, IP, or "ANY"
    simulate: bool = False           # run with fake data, no hardware needed

    # --- Acquisition --------------------------------------------------------
    sample_hz: float = 1.0           # how often the table and plot update
    resolution_index: int = 8        # T7 ADC resolution, 0 = default, 1..12
    fault_volts: float = 10.0        # above this the gauge reads "Gauge Fault"

    # --- CSV logging (Design.pdf: every 10 s, one file per day) -------------
    csv_enabled: bool = True
    csv_interval_s: float = 10.0
    csv_dir: str = field(default_factory=lambda: os.path.join(app_dir(), "data"))
    csv_include_voltages: bool = False

    # --- Appearance ---------------------------------------------------------
    dark_mode: bool = False          # False = light (default), True = dark
    show_legend: bool = False        # plot legend hidden by default

    # --- Plot ---------------------------------------------------------------
    plot_window_s: int = 300         # visible time span, default 5 minutes
    history_s: int = 6 * 3600        # how much data is kept in memory
    plotted_ains: list[int] = field(default_factory=lambda: [0, 2, 4, 6, 8, 10, 12])

    # -----------------------------------------------------------------------
    @classmethod
    def load(cls, path: str = SETTINGS_PATH) -> "Settings":
        s = cls()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return s
        valid = {f.name for f in fields(cls)}
        for key, value in raw.items():
            if key in valid:
                setattr(s, key, value)
        return s

    def save(self, path: str = SETTINGS_PATH) -> None:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2)
        except OSError:
            pass  # a read-only install folder should not crash the program
