"""The Help text is built from the real constants, so it cannot drift from the app."""
import re

from ibl import help_text
from ibl.config import MAX_HISTORY_S, MAX_SAMPLE_HZ, Settings
from ibl.help_text import help_html

SECTIONS = [
    "Status light",
    "When data is late",
    "Gauge status colours",
    "The plot at long time spans",
    "CSV log files",
    "Settings you can change",
]


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_sections_in_order():
    html = help_html(Settings())
    headings = re.findall(r"<h3>(.*?)</h3>", html)
    assert headings == SECTIONS


def test_names_all_four_link_states_with_colours():
    text = _plain(help_html(Settings()))
    for state, colour in [("Idle", "grey"), ("Live", "green"),
                          ("Late", "amber"), ("Down", "red")]:
        assert re.search(rf"{state}\W+(?:\w+\W+){{0,3}}{colour}|{colour}\W+(?:\w+\W+){{0,3}}{state}",
                         text), (state, colour)


def test_late_threshold_is_taken_from_settings():
    html = help_html(Settings(sample_hz=0.5, late_after_samples=2))
    assert "4.0 s" in _plain(html)


def test_long_span_summary_uses_history_constants(monkeypatch):
    text = _plain(help_html(Settings()))
    assert "min/max per 10 s" in text
    assert "1 h" in text
    monkeypatch.setattr(help_text, "SUMMARY_BUCKET_S", 30)
    assert "per 30 s" in _plain(help_html(Settings()))
    monkeypatch.setattr(help_text, "RAW_SPAN_S", 7200)
    assert "2 h" in _plain(help_html(Settings()))


def test_csv_files_explained():
    text = _plain(help_html(Settings()))
    assert "_b" in text
    assert "restart" in text.lower() and "append" in text.lower()


def test_one_faulted_gauge_does_not_change_the_status_light():
    text = _plain(help_html(Settings())).lower()
    assert "one faulted gauge" in text
    assert "status light" in text


def test_settings_limits_come_from_config():
    text = _plain(help_html(Settings()))
    assert f"{MAX_SAMPLE_HZ:g} Hz" in text
    assert f"{MAX_HISTORY_S // 3600} h" in text
