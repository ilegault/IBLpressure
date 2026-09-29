"""
Settings: defaults straight from Design.pdf, all editable in the GUI and
remembered between runs in settings.json next to the executable.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields, replace


def app_dir() -> str:
    """
    Folder the program 'lives in'.

    Frozen by PyInstaller  -> the folder holding IBLpressure.exe
    Running from source    -> the project folder
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # src/ibl/config.py -> src/ibl -> src -> project root
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SETTINGS_PATH = os.path.join(app_dir(), "settings.json")

# --- Limits: every widget range and every clamp reads these, never a literal ---
MIN_SAMPLE_HZ = 0.1
MAX_SAMPLE_HZ = 10.0
MIN_HISTORY_S = 3600
MAX_HISTORY_S = 24 * 3600
MIN_LATE_AFTER_SAMPLES = 2
MAX_LATE_AFTER_SAMPLES = 20
MIN_CSV_INTERVAL_S = 1.0
MAX_CSV_INTERVAL_S = 3600.0


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
    late_after_samples: int = 3      # this many missed sample periods = data is late

    # --- CSV logging (Design.pdf: every 10 s, one file per day) -------------
    csv_enabled: bool = True
    csv_interval_s: float = 10.0
    csv_dir: str = field(default_factory=lambda: os.path.join(app_dir(), "data"))
    csv_include_voltages: bool = False

    # --- Appearance ---------------------------------------------------------
    dark_mode: bool = False          # False = light (default), True = dark
    show_legend: bool = False        # plot legend hidden by default
    table_font_size: int = 12        # pressure cell font size (pt)
    loc_font_size: int = 10          # location cell font size (pt)
    table_visible_cols: list = field(default_factory=lambda: list(range(2, 9)))
    curve_alpha: int = 31            # plot line opacity 0-100 %
    curve_width: float = 1.0         # plot line width, pixels
    show_grid: bool = True           # show background grid lines on plot
    grid_alpha: int = 30             # grid line opacity 0-100 %

    # --- Plot ---------------------------------------------------------------
    plot_window_s: int = 300         # visible time span, default 5 minutes
    history_s: int = 24 * 3600       # how much data is kept in memory
    plotted_ains: list[int] = field(default_factory=lambda: [0, 2, 4, 6, 8, 10, 12])

    # -----------------------------------------------------------------------
    def clamped(self) -> Settings:
        """A copy with every limited field forced into its allowed range."""
        return replace(
            self,
            sample_hz=min(MAX_SAMPLE_HZ, max(MIN_SAMPLE_HZ, float(self.sample_hz))),
            history_s=min(MAX_HISTORY_S, max(MIN_HISTORY_S, int(self.history_s))),
            late_after_samples=min(
                MAX_LATE_AFTER_SAMPLES,
                max(MIN_LATE_AFTER_SAMPLES, int(self.late_after_samples))),
            csv_interval_s=min(
                MAX_CSV_INTERVAL_S, max(MIN_CSV_INTERVAL_S, float(self.csv_interval_s))),
        )

    @classmethod
    def load(cls, path: str = SETTINGS_PATH) -> Settings:
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
        return s.clamped()

    def save(self, path: str = SETTINGS_PATH) -> str:
        """Write the file. Returns "" on success, else a message for the operator."""
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(asdict(self), fh, indent=2)
        except OSError as exc:
            return f"Settings not saved: {exc}"  # a read-only folder must not crash the app
        return ""
