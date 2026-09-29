# 01: Move the package to src/ibl, add pyproject.toml, turn the conversion self-test into pytest

**What to build:** Move `ibl/` to `src/ibl/` with the build, entry point and path
helpers updated so the app, the exe build and pytest all still work, and replace
`conversion.self_test()`'s printed checks with real pytest tests. Spec:
`.scratch/stability-and-structure/spec.md` §2 *Structure*.

This ticket runs before CI exists (ticket 02), so its gate is local only.

**Blocked by:** None

**Status:** in-progress

**Runner:** any

**Auto-merge:** yes

## Acceptance criteria

Write `tests/test_paths.py` and `tests/test_conversion.py` first. The paths tests
must fail before the move; the conversion tests describe existing behaviour, so
prove each one can fail by breaking `ion_gauge_pressure` / a `CG_SEGMENTS`
coefficient locally, watching it go red, and restoring it.

- [x] **Move.** `git mv ibl src/ibl` (keep history). No `ibl/` folder remains at
  the root. Delete the stale root `__pycache__/`. Add `pyproject.toml` with exactly:
  ```toml
  [build-system]
  requires = ["setuptools>=69"]
  build-backend = "setuptools.build_meta"

  [project]
  name = "ibl-pressure"
  dynamic = ["version"]
  requires-python = ">=3.12"
  dependencies = ["PySide6>=6.8", "pyqtgraph>=0.13.7", "numpy>=1.26", "labjack-ljm>=1.23"]

  [project.optional-dependencies]
  dev = ["pytest>=8", "pytest-qt>=4.4", "ruff>=0.6"]

  [tool.setuptools.dynamic]
  version = {attr = "ibl.__version__"}

  [tool.setuptools.packages.find]
  where = ["src"]

  [tool.pytest.ini_options]
  pythonpath = ["src"]
  testpaths = ["tests"]
  qt_api = "pyside6"

  [tool.ruff]
  line-length = 100
  target-version = "py312"
  extend-exclude = ["build", "dist", "vendor", ".scratch"]
  ```
  Add `requirements-dev.txt` containing the single line `-e .[dev]` (the
  ticket-engine integrity workflow installs it). Keep `requirements.txt` unchanged.
- [x] **`app_dir()` still means the project root.** In `src/ibl/config.py`,
  `app_dir()` (not frozen) returns the folder three levels above `config.py`
  (the repo root). In `src/ibl/driver.py`, `_candidate_dirs()` calls
  `config.app_dir()` instead of repeating the logic. Test
  `tests/test_paths.py::test_app_dir_is_repo_root` asserts
  `pathlib.Path(config.app_dir()) / "pyproject.toml"` exists and
  `config.SETTINGS_PATH` is `<repo root>/settings.json`;
  `test_driver_searches_repo_root_and_vendor` asserts the first two entries of
  `driver._candidate_dirs()` are `app_dir()` and `app_dir()/vendor`.
- [x] **`main.py` runs from source without an install.** Add
  `def _ensure_src_on_path() -> None` to `main.py`: when not frozen, insert
  `<folder of main.py>/src` at `sys.path[0]` if absent; `main()` calls it before
  importing `ibl`. Test `test_main_puts_src_on_path` runs
  `[sys.executable, "-c", "import main, sys; main._ensure_src_on_path(); import ibl; print(ibl.__file__)"]`
  in a subprocess with `cwd` = repo root and `PYTHONPATH` removed from its env,
  and asserts the printed path ends with `src/ibl/__init__.py` (compare with
  `pathlib.Path(...).as_posix()`).
- [x] **Build files point at `src`.** `IBLpressure.spec`: `pathex=['src']`.
  `build.bat`: before the conversion check add `set "PYTHONPATH=%~dp0src"` so
  `"%PY%" -m ibl.conversion` still runs. `README.md` *Code layout* shows `src/ibl/…`,
  adds `tests/`, `pyproject.toml`, and drops the `smoke_test.py` line.
  `tests/test_paths.py::test_build_files_point_at_src` asserts the spec text
  contains `pathex=['src']` and `build.bat` contains `PYTHONPATH=%~dp0src`.
  (The real exe build is verified on the bench in ticket 13.)
- [x] **Conversion tests.** `tests/test_conversion.py`, using only the public
  functions `ion_gauge_pressure`, `convectron_pressure`, `convert` and the tables
  in `conversion.py`:
  - `test_ion_gauge_matches_manual` — parametrized over the ten `(p, v)` pairs
    currently in `self_test()`'s `ig_table`; relative error < 1 %.
  - `test_convectron_matches_manual_table` — parametrized over `CG_TABLE` rows with
    `p > 0`; tolerance 10 % when `p < 5e-3`, else 2 %, with the comment from
    `self_test()` explaining why (manual coefficients vs. flat S-curve bottom).
  - `test_convectron_segments_are_continuous` — at each segment boundary the two
    segments agree within 2 %.
  - `test_convert_statuses` — parametrized: IG 7.0 V → `OK`, pressure 1e-3 (±1 %);
    IG 10.4 V → `Gauge Fault`, pressure `None`; IG 9.5 V → `Over range`;
    CG 1.1552 V → `OK`, pressure 0.2 (±2 %); CG 10.9 V → `Gauge Fault`;
    CG 0.2 V → `Under range`; CG 5.9 V → `Over range`; CG 0.3759 V → `Use IG` with
    `display_text()` starting `~`; any gauge −0.1 V → `Neg Voltage`. Threshold 10.0.

  `python -m ibl.conversion` (with `src` on the path) still prints its report and
  exits 0.
- [x] **Gate.** `ruff check .` and `pytest -q` both pass locally; fix any existing
  ruff findings in the moved files without changing behaviour.

Gates: `ruff check .`, `pytest -q` (CI arrives in ticket 02).

## Comments

- Implemented; awaiting review and merge, so Status stays `in-progress` until it lands.
- ruff 0.16 enables more default rules than 0.6 did. Safe ones were auto-fixed (import order, unused
  imports, f-string prefixes, `int(round())`). Existing broad `except Exception` handlers, the open
  CSV handle and the local-time file name carry a `# noqa` with a reason instead of a behaviour change.
- The conversion tests were proven able to fail by breaking `ion_gauge_pressure` (11 red) and two
  `CG_SEGMENTS` coefficients (22 red), then restoring.
