"""Settings limits, clamping on load, and honest save errors."""
import json

from ibl import config
from ibl.config import Settings


def test_load_clamps_out_of_range_values(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "sample_hz": 20,
        "history_s": 172800,
        "late_after_samples": 1,
        "csv_interval_s": 0.2,
    }))

    s = Settings.load(str(path))

    assert s.sample_hz == 10.0
    assert s.history_s == 86400
    assert s.late_after_samples == 2
    assert s.csv_interval_s == 1.0


def test_load_keeps_defaults_for_missing_keys(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"sample_hz": 2.0}))

    s = Settings.load(str(path))

    assert s.late_after_samples == 3
    assert s.sample_hz == 2.0


def test_save_reports_unwritable_path(tmp_path):
    blocker = tmp_path / "f.txt"
    blocker.write_text("i am a file, not a folder")

    result = Settings().save(str(blocker / "settings.json"))

    assert result.startswith("Settings not saved:")


def test_save_returns_empty_string_on_success(tmp_path):
    assert Settings().save(str(tmp_path / "settings.json")) == ""


def test_late_preview_states_seconds_and_rate():
    assert config.late_preview(3, 1.0) == "= 3.0 s at 1 Hz"
    assert config.late_preview(2, 0.5) == "= 4.0 s at 0.5 Hz"
