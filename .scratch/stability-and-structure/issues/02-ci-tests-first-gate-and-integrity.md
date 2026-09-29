# 02: CI workflow, tests-first gate and ticket-engine integrity check

**What to build:** GitHub Actions CI that runs the three gates on every push and PR,
the tests-first gate script, and a caller workflow for the ticket-engine integrity
gate, so every later ticket is checked for honest tests. No Jules dispatch.
Spec: `.scratch/stability-and-structure/spec.md` §3; ADR 0001.

This ticket changes `.github/` and `scripts/`, so it is always held for the
developer's own merge. Expected, not a bug.

**Blocked by:** 01

**Status:** in-progress

**Runner:** any

**Auto-merge:** no

## Acceptance criteria

- [x] **`scripts/check_tests_first.py`.** Copy `scripts/check_tests_first.py` from
  `ilegault/ticket-engine` at tag `v1` (`git show v1:scripts/check_tests_first.py`
  in a clone, or the raw GitHub file). Change only `categorize_files` so a path
  counts as application code when it starts with `src/` **or equals `main.py`**,
  and update its docstring's first paragraph to say so. Add
  `tests/test_check_tests_first.py` with: `test_main_py_counts_as_source`
  (`categorize_files(["main.py"])` puts it in the first list),
  `test_src_change_without_tests_fails` and `test_src_change_with_tests_passes`
  (via `evaluate_tests_first`, asserting the returned bool), and
  `test_docs_only_change_passes`. Import the script with
  `importlib.util.spec_from_file_location`.
- [x] **`.github/workflows/ci.yml`**, exactly:
  ```yaml
  name: CI

  on:
    push:
      branches: [master, main]
    pull_request:
      branches: [master, main]

  jobs:
    lint-and-test:
      runs-on: ubuntu-latest
      env:
        QT_QPA_PLATFORM: offscreen
      steps:
        - uses: actions/checkout@v4
          with:
            fetch-depth: 0
        - uses: actions/setup-python@v5
          with:
            python-version: "3.14"
        - name: System libraries for headless Qt
          run: sudo apt-get update && sudo apt-get install -y libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3
        - name: Install
          run: |
            python -m pip install --upgrade pip
            pip install -r requirements-dev.txt
        - name: Lint with ruff
          run: ruff check .
        - name: Check tests-first gate
          run: python scripts/check_tests_first.py
        - name: Run tests with pytest
          run: pytest -q
  ```
- [x] **`.github/workflows/integrity.yml`** — the engine's caller, with no secrets
  required (the engine falls back to `GITHUB_TOKEN`):
  ```yaml
  name: Integrity Gate

  on:
    pull_request:
      branches: [master, main]

  jobs:
    integrity:
      uses: ilegault/ticket-engine/.github/workflows/integrity.yml@v1
      with:
        python-version: "3.14"
  ```
- [x] **`.ticket-engine.toml`** at the repo root, exactly:
  ```toml
  # ticket-engine configuration for IBL Pressure.
  # Integrity gate only; no Jules dispatch yet (the developer adds it later).
  default_branch = "master"
  gate_commands = ["ruff check .", "python scripts/check_tests_first.py", "pytest -q"]
  source_paths = ["src", "main.py"]
  test_paths = ["tests"]

  [test_env]
  QT_QPA_PLATFORM = "offscreen"
  ```
- [x] **A Qt smoke test proves headless Qt works in CI.** Add
  `tests/test_window_smoke.py::test_window_opens_in_simulation` using `qtbot`:
  build `MainWindow(Settings(simulate=True, csv_enabled=False))` (settings saved to
  a `tmp_path` file by monkeypatching `ibl.config.SETTINGS_PATH`), `qtbot.addWidget`
  it, and assert `window.lbl_status.text() == "Not connected - press Connect"`.
  Close the window at the end of the test.
- [x] **All three gates pass locally in CI order**, and the PR's CI run is green.
  The PR body notes that the integrity run on this PR itself is expected to hold
  (check 4: `.github/`, `scripts/`).

Gates, in CI order: `ruff check .`, `python scripts/check_tests_first.py`, `pytest -q`.

## Comments

- 2026-09-29: Implemented; awaiting review and the developer's own merge (held: changes `.github/` and `scripts/`),
  so Status stays `in-progress` until it lands. Ticket 01 had landed (PR 1) but still read `in-progress`; set it to `done`.
- `test_window_opens_in_simulation` does not call `window.close()` itself: `qtbot.addWidget` already closes the
  window at teardown, and a second close hangs (`MainWindow.closeEvent` blocks on a worker thread the first close
  stopped). Worth a look in a later ticket. `Settings.save/load` bind `SETTINGS_PATH` as a default argument, so the
  test also patches their defaults.
- Local gate (Python 3.11 here, CI uses 3.14): `ruff check .` clean, tests-first gate OK, `pytest -q` 60 passed.
  The integrity run on the PR is expected to hold (check 4: `.github/`, `scripts/`).
