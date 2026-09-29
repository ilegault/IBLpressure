"""Where the project root is, and that the build files point at src/."""
import os
import pathlib
import subprocess
import sys

from ibl import config, driver

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_app_dir_is_repo_root():
    assert (pathlib.Path(config.app_dir()) / "pyproject.toml").exists()
    assert pathlib.Path(config.SETTINGS_PATH) == REPO / "settings.json"


def test_driver_searches_repo_root_and_vendor():
    dirs = [pathlib.Path(d) for d in driver._candidate_dirs()]
    root = pathlib.Path(config.app_dir())
    assert dirs[:2] == [root, root / "vendor"]


def test_main_puts_src_on_path():
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    code = "import main, sys; main._ensure_src_on_path(); import ibl; print(ibl.__file__)"
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO, env=env,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert pathlib.Path(out).as_posix().endswith("src/ibl/__init__.py")


def test_build_files_point_at_src():
    assert "pathex=['src']" in (REPO / "IBLpressure.spec").read_text()
    assert "PYTHONPATH=%~dp0src" in (REPO / "build.bat").read_text()
