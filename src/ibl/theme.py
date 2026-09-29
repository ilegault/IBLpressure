"""Colour palettes, channel colours, and time-span choices.

Single source of truth — import from here rather than duplicating constants.
"""
from __future__ import annotations

LIGHT_THEME: dict = {
    "pg_bg": "w", "pg_fg": "k",
    "legend_brush": (255, 255, 255, 240), "legend_pen": "#888888",
    "fault_bg": "#ffd6d6", "range_bg": "#fff3cd", "approx_bg": "#ffe0b2", "stale_bg": "#f0f0f0",
    "stylesheet": """
        QMainWindow, QWidget { background-color: #f0f0f0; color: #1a1a1a; }
        QGroupBox { border: 1px solid #bbb; border-radius: 4px;
                    margin-top: 6px; padding-top: 10px; color: #1a1a1a;
                    background-color: #f5f5f5; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        QTableWidget { background-color: #ffffff; alternate-background-color: #f5f5f5;
                       color: #1a1a1a; gridline-color: #d0d0d0; }
        QHeaderView::section { background-color: #e8e8e8; color: #1a1a1a;
                               border: 1px solid #ccc; padding: 3px; }
        QPushButton { background-color: #e0e0e0; color: #1a1a1a;
                      border: 1px solid #aaa; border-radius: 3px; padding: 4px 8px; }
        QPushButton:hover { background-color: #d0d0d0; }
        QPushButton:pressed { background-color: #c0c0c0; }
        QComboBox { background-color: #ffffff; color: #1a1a1a; border: 1px solid #aaa; }
        QComboBox QAbstractItemView { background-color: #ffffff; color: #1a1a1a; }
        QLineEdit { background-color: #ffffff; color: #1a1a1a; border: 1px solid #aaa; }
        QCheckBox { color: #1a1a1a; }
        QCheckBox::indicator, QGroupBox::indicator { border: 2px solid #888;
                               border-radius: 2px; width: 14px; height: 14px;
                               background-color: #ffffff; }
        QCheckBox::indicator:checked, QGroupBox::indicator:checked {
                               background-color: #3078c6; border-color: #3078c6; }
        QLabel { color: #1a1a1a; }
        QSplitter::handle { background-color: #ccc; }
    """,
}

DARK_THEME: dict = {
    "pg_bg": "#1e1e1e", "pg_fg": "#d4d4d4",
    "legend_brush": (40, 40, 40, 240), "legend_pen": "#999999",
    "fault_bg": "#6b2020", "range_bg": "#5c4a1a", "approx_bg": "#5c3a0a", "stale_bg": "#333333",
    "stylesheet": """
        QMainWindow, QWidget { background-color: #2b2b2b; color: #d4d4d4; }
        QGroupBox { border: 1px solid #555; border-radius: 4px;
                    margin-top: 6px; padding-top: 10px; color: #d4d4d4; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; }
        QTableWidget { background-color: #1e1e1e; alternate-background-color: #2a2a2a;
                       color: #d4d4d4; gridline-color: #444; }
        QHeaderView::section { background-color: #333; color: #d4d4d4;
                               border: 1px solid #444; padding: 3px; }
        QPushButton { background-color: #3c3c3c; color: #d4d4d4;
                      border: 1px solid #555; border-radius: 3px; padding: 4px 8px; }
        QPushButton:hover { background-color: #505050; }
        QPushButton:pressed { background-color: #606060; }
        QComboBox { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; }
        QComboBox QAbstractItemView { background-color: #2b2b2b; color: #d4d4d4; }
        QLineEdit { background-color: #3c3c3c; color: #d4d4d4; border: 1px solid #555; }
        QCheckBox { color: #d4d4d4; }
        QCheckBox::indicator, QGroupBox::indicator { border: 2px solid #888;
                               border-radius: 2px; width: 14px; height: 14px;
                               background-color: #3c3c3c; }
        QCheckBox::indicator:checked, QGroupBox::indicator:checked {
                               background-color: #4a9eff; border-color: #4a9eff; }
        QLabel { color: #d4d4d4; }
        QSplitter::handle { background-color: #444; }
    """,
}

# One colour per AIN.  Ion gauges get the saturated colours, Convectrons the
# lighter partner of the same hue, so a location's pair reads as a pair.
CHANNEL_COLORS: list[str] = [
    "#1f77b4", "#8fbfe0",   # SNICS
    "#d62728", "#f0a3a3",   # Injector
    "#2ca02c", "#98d798",   # Post-accel
    "#9467bd", "#c9b3de",   # Switching Magnet
    "#ff7f0e", "#ffc38a",   # Left Chamber
    "#17becf", "#96e2ea",   # Middle Chamber
    "#8c564b", "#c4a09b",   # Right Chamber
]

TIME_SPANS: list[tuple[str, int]] = [
    ("1 minute", 60), ("5 minutes", 300), ("15 minutes", 900),
    ("30 minutes", 1800), ("1 hour", 3600), ("3 hours", 10800),
    ("6 hours", 21600), ("12 hours", 43200), ("24 hours", 86400),
]
