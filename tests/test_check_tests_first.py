"""The tests-first gate script: what counts as source, and when it fails."""
import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "check_tests_first.py"
_spec = importlib.util.spec_from_file_location("check_tests_first", SCRIPT)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_main_py_counts_as_source():
    src, tests, other = gate.categorize_files(["main.py"])
    assert src == ["main.py"]
    assert tests == [] and other == []


def test_src_change_without_tests_fails():
    passed, _ = gate.evaluate_tests_first(["src/ibl/config.py"])
    assert passed is False


def test_src_change_with_tests_passes():
    passed, _ = gate.evaluate_tests_first(["src/ibl/config.py", "tests/test_config.py"])
    assert passed is True


def test_docs_only_change_passes():
    passed, _ = gate.evaluate_tests_first(["docs/adr/0001.md", "README.md"])
    assert passed is True
