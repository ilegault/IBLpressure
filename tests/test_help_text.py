"""The Help text is built from the real constants, so it cannot drift from the app."""
import re

from ibl import config, help_text
from ibl.config import MAX_HISTORY_S, MAX_SAMPLE_HZ, Settings
from ibl.help_text import help_html

SECTIONS = [
    "Status light",
    "When data is late",
    "When the connection drops",
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


def test_connection_drops_section_explains_escalation():
    text = _plain(help_html(Settings()))
    for phrase in ("When the connection drops", "Reopen", "Library reset",
                   "Acquisition restart", "unplug and replug the T7", "link-log",
                   "Connection", "Open Link log"):
        assert phrase in text, phrase


def test_connection_drops_numbers_come_from_config(monkeypatch):
    monkeypatch.setattr(config, "ACQUISITION_RESTART_INTERVAL_S", 45.0)
    monkeypatch.setattr(config, "WATCHDOG_TIMEOUT_S", 90)
    monkeypatch.setattr(config, "RETRY_INTERVAL_S", 7.0)
    monkeypatch.setattr(config, "TRIES_PER_STEP", 4)
    monkeypatch.setattr(config, "HUNG_AFTER_S", 21.0)
    text = _plain(help_html(Settings()))
    assert "45 s" in text and "90 s" in text and "7 s" in text and "21 s" in text
    assert "4 tries" in text
    assert "30 s" not in text and "60 s" not in text        # no hard-coded defaults


def test_default_numbers_are_the_real_defaults():
    text = _plain(help_html(Settings()))
    assert "30 s" in text and "60 s" in text and "5 s" in text and "15 s" in text
    assert "3 tries" in text


def test_down_bullet_no_longer_promises_a_fixed_retry():
    assert "retries every 5 s" not in _plain(help_html(Settings()))


def test_hand_off_text_in_help_matches_the_status_line():
    # The status line and the Help give the same three by-hand actions, in the same order.
    text = _plain(help_html(Settings()))
    assert text.index("check the USB cable") < text.index("unplug and replug the T7")
    assert text.index("unplug and replug the T7") < text.index("reboot this PC")
