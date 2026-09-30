"""The panels work on their own, with no MainWindow, worker or LinkMonitor."""
from ibl.channels import CHANNELS, PAIRS
from ibl.config import Settings
from ibl.conversion import convert
from ibl.model import Sample
from ibl.theme import LIGHT_THEME
from ibl.ui.settings_panel import SettingsPanel
from ibl.ui.table_panel import (
    COL_CG_PRESS,
    COL_CG_STATUS,
    COL_CG_VOLTS,
    COL_IG_PRESS,
    COL_IG_STATUS,
    COL_IG_VOLTS,
    TablePanel,
)


def test_settings_panel_round_trip(qtbot):
    panel = SettingsPanel()
    qtbot.addWidget(panel)
    s = Settings(
        connection="ETHERNET", identifier="192.168.1.5", resolution_index=5,
        sample_hz=2.5, fault_volts=9.5, late_after_samples=5, history_s=12 * 3600,
        csv_enabled=False, csv_interval_s=30.0, csv_dir="/somewhere/else",
        csv_include_voltages=True, show_legend=True, table_font_size=14,
        loc_font_size=9, table_visible_cols=[2, 3, 5], curve_alpha=50,
        curve_width=2.5, show_grid=False, grid_alpha=60,
    )

    panel.load(s)

    assert panel.harvest(Settings()) == s


def test_fault_sample_colours_only_its_own_row(qtbot):
    panel = TablePanel()
    qtbot.addWidget(panel)
    readings = [
        convert(ch.ain, 10.9 if ch.ain == 0 else (7.0 if ch.is_ion else 0.435),
                ch.is_ion, 10.0)
        for ch in CHANNELS
    ]

    panel.show_sample(Sample(1.0, readings))

    table = panel.table
    fault = LIGHT_THEME["fault_bg"]
    for col in (COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS):
        assert table.item(0, col).background().color().name() == fault
    assert table.item(0, COL_IG_PRESS).text() == "Gauge Fault"
    for pair in range(len(PAIRS)):
        for col in (COL_CG_PRESS, COL_CG_VOLTS, COL_CG_STATUS):
            assert table.item(pair, col).background().color().name() != fault
        if pair:
            for col in (COL_IG_PRESS, COL_IG_VOLTS, COL_IG_STATUS):
                assert table.item(pair, col).background().color().name() != fault


def test_table_panel_reports_plotted_channels(qtbot):
    panel = TablePanel()
    qtbot.addWidget(panel)
    seen = []
    panel.plotted_changed.connect(lambda: seen.append(panel.plotted_ains()))

    panel.set_plotted(lambda c: c.is_ion)

    assert seen == [[c.ain for c in CHANNELS if c.is_ion]]

